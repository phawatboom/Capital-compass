import csv
import io
import os
import subprocess
import sys
import pandas as pd
from django.conf import settings
import glob


from pathlib import Path
import logging # <-- Add logging

# Get an instance of a logger
logger = logging.getLogger(__name__)

from datetime import datetime
from django.contrib.auth import authenticate, login, logout
from django.views.decorators.csrf import ensure_csrf_cookie
from django.http import FileResponse
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from rest_framework import status, viewsets
from rest_framework.decorators import api_view, permission_classes, authentication_classes, parser_classes
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
from .models import Stock, StockData, CSVUploadRecord, UserProfile
from datetime import date, datetime
from django.http import FileResponse
from django.contrib.auth import update_session_auth_hash

from .serializers import (
    CSVUploadSerializer,
    StockSerializer,
    StockDetailSerializer,
    StockDataSerializer,
    CSVUploadRecordSerializer,
    UserProfileSerializer,
    PasswordChangeSerializer,
)

def _parse_date(date_str: str) -> date:
    date_str = date_str.strip()
    for fmt in ("%d-%b-%Y", "%d-%b-%y", "%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"time data '{date_str}' does not match expected formats")


# Helper function to process a single DataFrame (from CSV or Excel sheet)
def process_data(df, file, data_type, upload_record):
    try:
        data_to_process = []
        date_col_index = None
        stock_names_start_index = None
        data_start_row_index = None

        # ---- Determine sheet structure based on data_type ----
        if data_type == 'price' and 'line#' in df.iloc[3].astype(str).str.lower().values:
            header_row_index = 3
            date_col_index = 1
            stock_names_start_index = 2
            data_start_row_index = header_row_index + 1
        elif data_type == 'return' and 'date' in df.iloc[5].astype(str).str.lower().values:
            header_row_index = 5
            date_col_index = 0
            stock_names_start_index = 1
            data_start_row_index = header_row_index + 1
        elif data_type == 'equity' and 'dates' in df.iloc[1].astype(str).str.lower().values:
            header_row_index = 0
            date_col_index = 0
            stock_names_start_index = 1
            data_start_row_index = 2
        else:
            raise ValueError(f"Could not determine format for data type: {data_type}")

        # ---- Find and prepare stock objects ----
        header_series = df.iloc[header_row_index, stock_names_start_index:].astype(str)

        exchange_codes = [' UN', ' UW', ' UQ', ' UF', '/B UN']

        if data_type == 'equity':
            stock_names = [
                name.strip() for name in header_series.dropna().tolist()
                if 'equity' in name.lower() and any(code.lower() in name.lower() for code in exchange_codes)
            ]
            cleaned_stock_names = [name.replace(' Equity', '').strip() for name in stock_names]
        else:
            stock_names = [
                name.strip() for name in header_series.dropna().tolist()
                if any(code.lower() in name.lower() for code in exchange_codes)
            ]
            cleaned_stock_names = stock_names

        if not cleaned_stock_names:
            raise ValueError("No valid stock names found in header.")

        # Bulk get_or_create for stocks
        stocks_map = {name: Stock.objects.get_or_create(name=name)[0] for name in cleaned_stock_names}

        # ---- Process data points and collect them into a list ----
        data_df = df.iloc[data_start_row_index:].reset_index(drop=True)
        for _, row in data_df.iterrows():
            try:
                date_str = str(row.iloc[date_col_index]).strip()
                if not date_str:
                    continue
                date_object = _parse_date(date_str)
            except (IndexError, ValueError):
                continue

            for i, stock_name in enumerate(cleaned_stock_names):
                value_raw = row.iloc[stock_names_start_index + i]
                value = None

                # Value parsing logic
                if isinstance(value_raw, (int, float)):
                    value = value_raw
                elif isinstance(value_raw, str):
                    value_str = value_raw.strip()
                    if value_str not in ["#N/A", ""]:
                        if data_type == 'return' and '%' in value_str:
                            try:
                                value = float(value_str.strip('%')) / 100.0
                            except ValueError:
                                continue
                        else:
                            try:
                                value = float(value_str)
                            except ValueError:
                                continue

                data_to_process.append({
                    'stock': stocks_map[stock_name],
                    'date': date_object,
                    'data_type': data_type,
                    'value': value,
                })

        # ---- Bulk operations ----
        # 1. Get existing records in a single query
        existing_records_filter = {
            'stock__in': [d['stock'] for d in data_to_process],
            'data_type': data_type,
            'date__in': [d['date'] for d in data_to_process]
        }
        existing_records = StockData.objects.filter(**existing_records_filter).values('stock_id', 'date', 'id')

        # Create a map for fast lookup
        existing_records_map = {
            (rec['stock_id'], rec['date']): rec['id']
            for rec in existing_records
        }

        # 2. Separate into lists for creation and update
        records_to_create = []
        records_to_update = []

        for data_point in data_to_process:
            stock_id = data_point['stock'].id
            date_val = data_point['date']

            if (stock_id, date_val) in existing_records_map:
                record_id = existing_records_map[(stock_id, date_val)]
                records_to_update.append(
                    StockData(
                        id=record_id,
                        stock=data_point['stock'],
                        date=date_val,
                        data_type=data_point['data_type'],
                        value=data_point['value']
                    )
                )
            else:
                records_to_create.append(StockData(**data_point))

        # 3. Perform bulk operations
        if records_to_create:
            StockData.objects.bulk_create(records_to_create, batch_size=5000)

        if records_to_update:
            StockData.objects.bulk_update(records_to_update, ['value'], batch_size=5000)

    except Exception as e:
        raise Exception(f"Failed to process {file.name}, data type: {data_type}. Error: {e}")


# View to handle file uploads
# --------------------------------------------------------------------------------------
class FileUploadView(APIView):
    parser_classes = (MultiPartParser, FormParser)
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        file_obj = request.data.get('file')

        if not file_obj:
            return Response({'error': 'No file was provided.'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = CSVUploadSerializer(data={'filename': file_obj})
        if serializer.is_valid():
            try:
                upload_record = serializer.save(user=request.user)
                file_path = upload_record.filename.path
                # Handle XLSX files with multiple sheets
                if file_path.endswith('.xlsx'):
                    sheets_to_process = {
                        'Prices': 'price',
                        'Returns': 'return',
                    }
                    with pd.ExcelFile(file_path) as xls:
                        print(f"Available sheets: {xls.sheet_names}")  # Add this debug line
                        for sheet_name, data_type in sheets_to_process.items():
                            if sheet_name in xls.sheet_names:
                                print(f"Processing sheet: {sheet_name}")  # Add this debug line
                                df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
                                process_data(df, file_obj, data_type, upload_record)

                # Handle CSV files
                elif file_path.endswith('.csv'):
                    df = pd.read_csv(file_path, header=None)

                    # Determine data_type based on filename
                    if 'prices' in file_obj.name.lower():
                        data_type = 'price'
                    elif 'returns' in file_obj.name.lower() or 'mxus_data' in file_obj.name.lower():
                        data_type = 'return'
                    elif 'bql_query' in file_obj.name.lower() or 'equity' in file_obj.name.lower():
                        data_type = 'equity'
                    else:
                        raise ValueError("Could not determine data type from CSV filename.")

                    process_data(df, file_obj, data_type, upload_record)

                else:
                    raise ValueError("Unsupported file format.")

                return Response({'message': 'File uploaded and processed successfully.'},
                                status=status.HTTP_201_CREATED)

            except Exception as e:
                if upload_record:
                    if os.path.exists(upload_record.filename.path):
                        os.remove(upload_record.filename.path)
                    upload_record.delete()

                return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class StockViewSet(viewsets.ModelViewSet):
    queryset = Stock.objects.all()

    def get_serializer_class(self):
        # The 'retrieve' action handles GET /api/stocks/{id}/
        if self.action == 'retrieve':
            return StockDetailSerializer

        # All other actions (list, create, update, etc.) use the basic serializer
        return StockSerializer

    def get_queryset(self):
        queryset = super().get_queryset()

        filter_type = self.request.query_params.get("filter", None)
        if filter_type == "trending":
            queryset = queryset.filter(
                b_coefficient__gt=0,
                p_value__lt=0.05
            )
        elif filter_type == "meanreverting":
            queryset = queryset.filter(
                b_coefficient__lt=0,
                p_value__lt=0.05
            )

        return queryset

# List all stocks.
@api_view(['GET'])
def stock_list(request):

    filter_type = request.query_params.get("filter", None)

    if not filter_type or filter_type == 'all':
        stocks_data = list(Stock.objects.all().values('id', 'name'))
        return Response(stocks_data, status=status.HTTP_200_OK)

    queryset = Stock.objects.all()

    if filter_type == "trending":
        queryset = queryset.filter(
            b_coefficient__gt=0,
            p_value__lt=0.05
        )
    elif filter_type == "meanreverting":
        queryset = queryset.filter(
            b_coefficient__lt=0,
            p_value__lt=0.05
        )

    stocks_data = [
        {"id": stock.id, "name": stock.name}
        for stock in queryset
    ]

    return Response(stocks_data, status=status.HTTP_200_OK)


@api_view(['GET'])
def stock_details(request, pk):
    try:
        stock = Stock.objects.get(pk=pk)
    except Stock.DoesNotExist:
        return Response({"error": "Stock not found"}, status=status.HTTP_404_NOT_FOUND)

    data = {}
    for entry in StockData.objects.filter(stock=stock).order_by("date"):
        if entry.date not in data:
            data[entry.date] = {"date": entry.date, "price": None, "return": None, "equity": None}

        # Replace NaN with None
        value = entry.value
        if value != value:  # NaN check
            value = None

        data[entry.date][entry.data_type] = value

    rows = sorted(data.values(), key=lambda x: x["date"])

    return Response({
        "id": stock.id,
        "name": stock.name,
        "b_coefficient": stock.b_coefficient,
        "p_value": stock.p_value,
        "data": rows
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
# @permission_classes([IsAuthenticated])
def list_csv_uploads(request):
    records = CSVUploadRecord.objects.all().order_by('-uploaded_at')
    serializer = CSVUploadRecordSerializer(records, many=True)
    return Response(serializer.data)


@api_view(["DELETE"])
def delete_csv_upload(request, pk: int):
    try:
        record = CSVUploadRecord.objects.get(pk=pk)
    except CSVUploadRecord.DoesNotExist:
        return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

    try:
        if record.filename:
            record.filename.delete(save=False)
    except Exception:
        # ignore file removal errors; proceed to delete db record
        pass

    record.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
# @permission_classes([IsAuthenticated])
def download_csv(request, pk):
    try:
        upload = CSVUploadRecord.objects.get(pk=pk)
    except CSVUploadRecord.DoesNotExist:
        return Response({"error": "File not found"}, status=404)

    return FileResponse(upload.filename.open("rb"), as_attachment=True, filename=os.path.basename(upload.filename.name))


@api_view(["GET"])
def information_file(request, pk):
    try:
        upload = CSVUploadRecord.objects.get(pk=pk)
    except CSVUploadRecord.DoesNotExist:
        return Response({"error": "File not found"}, status=404)
    info = {
        "id": upload.id,
        "filename": os.path.basename(upload.filename.name),
        "uploaded_at": upload.uploaded_at,
        "file_size": upload.file_size,
    }
    return Response(info)



# 2. Authentication and Permissions
#
#
#
# --- CSRF bootstrap ---
@api_view(["GET"])
@ensure_csrf_cookie
@permission_classes([AllowAny])
def csrf(request):
    return Response({"detail": "CSRF cookie set"})


# --- Login (creates server-side session + sets sessionid cookie) ---
@api_view(["POST"])
@permission_classes([AllowAny])
def login_user(request):
    username = request.data.get("username")
    password = request.data.get("password")
    if not username or not password:
        return Response({"error": "Username and password are required"}, status=400)

    user = authenticate(request, username=username, password=password)
    if user is None:
        return Response({"error": "Invalid credentials"}, status=401)

    login(request, user)  # sets session
    return Response({"detail": "ok"})

@api_view(["POST"])
@permission_classes([AllowAny])
def register_user(request):
    username = request.data.get("username")
    password = request.data.get("password")
    if not username or not password:
        return Response({"error": "Username and password are required"}, status=400)

    if User.objects.filter(username=username).exists():
        return Response({"error": "Username already taken"}, status=400)

    try:
        validate_password(password)
    except ValidationError as e:
        return Response({"errors": e.messages}, status=400)

    User.objects.create_user(username=username, password=password)
    return Response({"detail": "User created"}, status=201)


# --- Logout (clears session) ---
@api_view(["POST"])
def logout_user(request):
    logout(request)
    return Response({"detail": "logged out"})


# --- Who am I (for frontend to read role or user state) ---

@api_view(["GET"])
def me(request):
    u = request.user
    if not u.is_authenticated:
        return Response({
            "authenticated": False,
            "username": None,
            "is_staff": False,
            "is_superuser": False,
            "is_moderator": False,
            "avatar_url": None,
            "email": None,
        })

    # ensure a profile exists
    profile, _ = UserProfile.objects.get_or_create(user=u)
    avatar_url = profile.avatar.url if profile.avatar else None
    if avatar_url:
        avatar_url = request.build_absolute_uri(avatar_url)

    return Response({
        "authenticated": True,
        "username": u.username,
        "email": u.email,
        "is_staff": u.is_staff,
        "is_superuser": u.is_superuser,
        "is_moderator": (
            u.groups.filter(name="mods").exists() or
            u.has_perm("webapp.can_moderate")
        ),
        "avatar_url": avatar_url,
    })


# ------- New: profile read/update -------
@api_view(["GET", "PUT", "PATCH"])
@permission_classes([IsAuthenticated])
def profile_view(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if request.method in ("PUT", "PATCH"):
        serializer = UserProfileSerializer(
            profile, data=request.data, partial=(request.method == "PATCH"), context={"request": request}
        )
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        print("PROFILE ERRORS:", serializer.errors)
        return Response(serializer.errors, status=400)

    serializer = UserProfileSerializer(profile, context={"request": request})
    return Response(serializer.data)


# ------- New: avatar upload/replace & delete -------
@api_view(["POST", "DELETE"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def profile_avatar(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    if request.method == "DELETE":
        try:
            if profile.avatar:
                profile.avatar.delete(save=False)
            profile.avatar = None
            profile.save(update_fields=["avatar"])
        except Exception:
            pass
        return Response({"avatar_url": None})

    # POST: upload/replace
    file_obj = request.data.get("avatar")
    if not file_obj:
        return Response({"error": "No file provided (field name 'avatar')."}, status=400)

    # Optional validation (size/type)
    if file_obj.size > 5 * 1024 * 1024:
        return Response({"error": "Max avatar size is 5MB."}, status=400)
    if not (file_obj.content_type or "").startswith("image/"):
        return Response({"error": "Avatar must be an image."}, status=400)

    # Replace existing file cleanly
    if profile.avatar:
        try:
            profile.avatar.delete(save=False)
        except Exception:
            pass

    profile.avatar = file_obj
    profile.save(update_fields=["avatar"])

    avatar_url = request.build_absolute_uri(profile.avatar.url) if profile.avatar else None
    return Response({"avatar_url": avatar_url})


# ------- New: change password -------
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def change_password(request):
    serializer = PasswordChangeSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=400)

    current_password = serializer.validated_data["current_password"]
    new_password = serializer.validated_data["new_password"]

    user = request.user
    if not user.check_password(current_password):
        return Response({"error": "Current password is incorrect."}, status=400)

    try:
        validate_password(new_password, user=user)
    except ValidationError as e:
        return Response({"errors": e.messages}, status=400)

    user.set_password(new_password)
    user.save()
    # keep session valid after password change
    update_session_auth_hash(request, user)

    return Response({"detail": "Password changed successfully."})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def analyze_upload(request, pk: int):
    logger.info(f"Starting analysis for upload pk={pk}, user={request.user.username}")

    # 1. Find the uploaded file record
    try:
        rec = CSVUploadRecord.objects.get(pk=pk, user=request.user)
    except CSVUploadRecord.DoesNotExist:
        logger.warning(f"Analysis failed: Upload pk={pk} not found for user={request.user.username}")
        return Response({"error": "Upload not found"}, status=status.HTTP_404_NOT_FOUND)

    # 2. Define paths robustly
    project_root = Path(settings.BASE_DIR).parent
    script_path = project_root / "Data Analysis" / "main_model_file_stable_2_extended_future_prediciton.py"

    if not script_path.exists():
        logger.error(f"Model script not found at {script_path}")
        return Response({"error": "Model script not found on server."}, status=500)

    out_dir = Path(settings.MEDIA_ROOT) / "analysis_results" / str(pk)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 3. Run the model script SAFELY
    cmd = [
        sys.executable,
        str(script_path),
        "--mode", "forecast",
        "--excel", rec.filename.path,
        "--out", str(out_dir),
    ]
    logger.info(f"Running command: {' '.join(cmd)}")

    try:
        # Using check=True will automatically raise CalledProcessError on failure
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=600)

    except subprocess.CalledProcessError as e:
        # This block runs if the script executes but returns a non-zero (error) exit code
        logger.error(f"Model script failed for pk={pk}. Stderr: {e.stderr}")
        return Response(
            {
                "error": "Model script failed to execute.",
                "details": "The analysis script encountered an error.",
                "stdout": e.stdout[-2000:], # Last 2000 characters of standard output
                "stderr": e.stderr[-2000:], # Last 2000 characters of standard error
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    except FileNotFoundError:
        logger.error("Could not run model script. Is the python interpreter or script path correct?")
        return Response({"error": "Failed to find the model script or python executable."}, status=500)
    except subprocess.TimeoutExpired:
        logger.warning(f"Analysis for pk={pk} timed out.")
        return Response({"error": "Analysis timed out after 10 minutes."}, status=500)
    except Exception as e:
        # Catch any other unexpected errors during the subprocess call
        logger.exception(f"An unexpected error occurred while running the model for pk={pk}")
        return Response({"error": "An unexpected error occurred during analysis.", "detail": str(e)}, status=500)

    # 4. Find the generated output file
    logger.info(f"Model run successful for pk={pk}. Searching for output file in {out_dir}")
    try:
        latest_file = sorted(out_dir.glob("forecast_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)[0]
    except IndexError:
        logger.error(f"Model ran, but no output file was found in {out_dir}")
        return Response({"error": "Model ran, but no output file was generated."}, status=500)

    # 5. Return the file for download
    logger.info(f"Returning file {latest_file.name} for download.")
    return FileResponse(open(latest_file, "rb"), as_attachment=True, filename=latest_file.name)