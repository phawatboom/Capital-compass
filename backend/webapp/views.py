# file: backend/webapp/views.py
import csv
import io
import os
from datetime import datetime
import pandas as pd
from django.contrib.auth import authenticate, login, logout
from django.views.decorators.csrf import ensure_csrf_cookie
from django.http import FileResponse
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
from .models import Stock, StockData, CSVUploadRecord
from datetime import date, datetime
from django.http import FileResponse

from .serializers import (
    CSVUploadSerializer,
    StockSerializer,
    StockDataSerializer,
    CSVUploadRecordSerializer,
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
    # Common processing logic for different data types
    try:
        # ---- Logic for Prices sheet ----
        if 'line#' in df.iloc[3].astype(str).str.lower().values and data_type == 'price':
            header_row_index = 3
            date_col_index = 1
            stock_names_start_index = 2

            header_series = df.iloc[header_row_index, stock_names_start_index:].astype(str)
            stock_names = [name.strip() for name in header_series.dropna().tolist() if
                           name.strip() and 'un' in name.lower()]

            if not stock_names:
                raise ValueError("No stock names found in header.")

            stocks = {name: Stock.objects.get_or_create(name=name)[0] for name in stock_names}

            data_df = df.iloc[header_row_index + 1:].reset_index(drop=True)
            for _, row in data_df.iterrows():
                try:
                    date_str = str(row.iloc[date_col_index]).strip()
                    if not date_str:
                        continue
                    try:
                        date_object = datetime.strptime(date_str, '%Y-%m-%d').date()
                    except ValueError:
                        date_object = datetime.strptime(date_str, '%d-%b-%Y').date()
                except (IndexError, ValueError):
                    continue

                for i, stock_name in enumerate(stock_names):
                    value_raw = row.iloc[stock_names_start_index + i]
                    value = None

                    if isinstance(value_raw, (int, float)):
                        value = value_raw
                    elif isinstance(value_raw, str):
                        value_str = value_raw.strip()
                        if value_str not in ["#N/A", ""]:
                            try:
                                value = float(value_str)
                            except ValueError:
                                continue

                    stock_obj = stocks[stock_name]
                    StockData.objects.update_or_create(
                        stock=stock_obj,
                        date=date_object,
                        data_type=data_type,
                        defaults={'value': value}
                    )

        # ---- Logic for Returns sheet ----
        if 'date' in df.iloc[5].astype(str).str.lower().values and data_type == 'return':
            header_row_index = 5
            date_col_index = 0
            stock_names_start_index = 1

            header_series = df.iloc[header_row_index, stock_names_start_index:].astype(str)
            stock_names = [name.strip() for name in header_series.dropna().tolist() if
                           name.strip() and 'un' in name.lower()]

            if not stock_names:
                raise ValueError("No stock names found in header.")

            stocks = {name: Stock.objects.get_or_create(name=name)[0] for name in stock_names}

            data_df = df.iloc[header_row_index + 1:].reset_index(drop=True)
            for _, row in data_df.iterrows():
                try:
                    date_str = str(row.iloc[date_col_index]).strip()
                    if not date_str:
                        continue
                    try:
                        date_object = datetime.strptime(date_str, '%Y-%m-%d').date()
                    except ValueError:
                        date_object = datetime.strptime(date_str, '%d-%b-%Y').date()
                except (IndexError, ValueError):
                    continue

                for i, stock_name in enumerate(stock_names):
                    value_raw = row.iloc[stock_names_start_index + i]
                    value = None

                    if isinstance(value_raw, str):
                        value_str = value_raw.strip()
                        if value_str not in ["#N/A", ""]:
                            if '%' in value_str:
                                value = float(value_str.strip('%')) / 100.0
                            else:
                                try:
                                    value = float(value_str)
                                except ValueError:
                                    continue

                    stock_obj = stocks[stock_name]
                    StockData.objects.update_or_create(
                        stock=stock_obj,
                        date=date_object,
                        data_type=data_type,
                        defaults={'value': value}
                    )

        # ---- Logic for BQL Query sheet ----
        if 'dates' in df.iloc[1].astype(str).str.lower().values and data_type == 'equity':
            header_row_index = 0
            date_col_index = 0
            stock_names_start_index = 1
            data_start_row_index = 2
            # Look for 'un equity' in stock names
            header_series = df.iloc[header_row_index, stock_names_start_index:].astype(str)
            stock_names = [name.strip() for name in header_series.dropna().tolist() if
                           name.strip() and 'un equity' in name.lower()]

            if not stock_names:
                raise ValueError("No stock names found in header.")
            # Remove ' Equity' suffix if present
            cleaned_stock_names = [name.replace(' Equity', '') for name in stock_names]
            stocks = {name: Stock.objects.get_or_create(name=name)[0] for name in cleaned_stock_names}

            data_df = df.iloc[data_start_row_index:].reset_index(drop=True)
            for _, row in data_df.iterrows():
                try:
                    date_str = str(row.iloc[date_col_index]).strip()
                    if not date_str:
                        continue
                    try:
                        date_object = datetime.strptime(date_str, '%d/%m/%Y').date()
                    except ValueError:
                        date_object = datetime.strptime(date_str, '%Y-%m-%d').date()
                except (IndexError, ValueError):
                    continue

                for i, stock_name in enumerate(cleaned_stock_names):
                    value_raw = row.iloc[stock_names_start_index + i]
                    value = None

                    if isinstance(value_raw, (int, float)):
                        value = value_raw
                    elif isinstance(value_raw, str):
                        value_str = value_raw.strip()
                        if value_str not in ["#N/A", ""]:
                            try:
                                value = float(value_str)
                            except ValueError:
                                continue

                    stock_obj = stocks[stock_name]
                    StockData.objects.update_or_create(
                        stock=stock_obj,
                        date=date_object,
                        data_type=data_type,
                        defaults={'value': value}
                    )

    except Exception as e:
        raise Exception(f"Failed to process {file.name}, data type: {data_type}. Error: {e}")

# View to handle file uploads
# --------------------------------------------------------------------------------------
class FileUploadView(APIView):
    parser_classes = (MultiPartParser, FormParser)
    # permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        file_obj = request.data.get('file')

        if not file_obj:
            return Response({'error': 'No file was provided.'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = CSVUploadSerializer(data={'filename': file_obj})
        if serializer.is_valid():
            upload_record = None
            try:
                upload_record = serializer.save()
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
                    elif 'returns' in file_obj.name.lower():
                        data_type = 'return'
                    elif 'bql_query' in file_obj.name.lower():
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


# List all stocks.
@api_view(['GET'])
# @permission_classes([AllowAny])
def stock_list(request):
    stocks = Stock.objects.all()
    serializer = StockSerializer(stocks, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


# Retrieve details and all data points for a specific stock.
@api_view(['GET'])
# @permission_classes([AllowAny])
def stock_details(request, pk):
    try:
        stock = Stock.objects.get(pk=pk)
    except Stock.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    stock_serializer = StockSerializer(stock)
    stock_data_list = StockData.objects.filter(stock=stock).order_by('date')
    stock_data_serializer = StockDataSerializer(stock_data_list, many=True)

    return Response({
        "stock_info": stock_serializer.data,
        "data_points": stock_data_serializer.data
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
        if record.filename and hasattr(record.filename, "path") and os.path.exists(record.filename.path):
            os.remove(record.filename.path)
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
    return Response({
        "authenticated": u.is_authenticated,
        "username": u.username if u.is_authenticated else None,
        "is_staff": u.is_staff if u.is_authenticated else False,
        "is_superuser": u.is_superuser if u.is_authenticated else False,
        "is_moderator": (
            u.groups.filter(name="mods").exists() or
            u.has_perm("webapp.can_moderate")
        ) if u.is_authenticated else False,
    })
