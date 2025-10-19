import csv
import io
import os
import subprocess
import sys
import pandas as pd
import numpy as np
from django.db import transaction
from django.conf import settings
import glob


from pathlib import Path
import logging # <-- Add logging

# Get an instance of a logger
logger = logging.getLogger(__name__)

from datetime import datetime
from django.utils import timezone
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
from .models import Stock, StockData, CSVUploadRecord, UserProfile, AnalysisResult, ForecastResult, BacktestResult, BetaForecastResult, MeanReversionResult
from datetime import date, datetime
from django.http import FileResponse
from django.contrib.auth import update_session_auth_hash
from rest_framework.decorators import parser_classes

# ================= New / Refactored Analysis Views (synchronous execution) ================= #

class AnalysisResultListView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        qs = AnalysisResult.objects.filter(user=request.user).order_by('-created_at')[:50]
        return Response({'results': [
            {
                'id': a.id,
                'analysis_type': a.analysis_type,
                'status': a.status,
                'created_at': a.created_at.isoformat(),
                'completed_at': a.completed_at.isoformat() if a.completed_at else None,
                'summary_stats': a.summary_stats,
                'error': a.error_message,
            } for a in qs
        ]})

class DownloadAnalysisResultView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request, analysis_id):
        try:
            analysis = AnalysisResult.objects.get(id=analysis_id, user=request.user)
        except AnalysisResult.DoesNotExist:
            return Response({'error': 'Not found'}, status=404)
        out_dir = Path(settings.MEDIA_ROOT) / 'analysis_results' / str(analysis.id)
        files = sorted(out_dir.glob('forecast_*.csv'), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            return Response({'error': 'No forecast CSV available'}, status=404)
        f = files[0]
        return FileResponse(open(f, 'rb'), as_attachment=True, filename=f.name)

class RunAnalysisView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        csv_upload_id = request.data.get('csv_upload_id')
        if not csv_upload_id:
            return Response({'success': False, 'error': 'csv_upload_id required'}, status=400)
        analysis_type = request.data.get('analysis_type', 'beta')  # mr|beta|combined
        mode = request.data.get('mode', 'forecast')  # forecast|backtest
        parameters = request.data.get('parameters', {}) or {}
        try:
            upload = CSVUploadRecord.objects.get(id=csv_upload_id, user=request.user)
        except CSVUploadRecord.DoesNotExist:
            return Response({'success': False, 'error': 'Upload not found'}, status=404)

        analysis = AnalysisResult.objects.create(
            user=request.user,
            csv_upload=upload,
            analysis_type=analysis_type,
            parameters=parameters,
            status='running',
            started_at=timezone.now()
        )

        project_root = Path(settings.BASE_DIR).parent
        candidates = [
            'Data Analysis/main_model_file_merged_bcoef_strategy1_stats_legacy (1).py',
            'Data Analysis/main_model_file_stable_2_extended_future_prediciton_bhat.py',
            'Data Analysis/main_model_file_stable_2_extended_future_prediciton.py'
        ]
        script_path = None
        for rel in candidates:
            p = project_root / rel
            if p.exists():
                script_path = p
                break
        if not script_path:
            analysis.status = 'failed'
            analysis.error_message = 'No analysis script found'
            analysis.completed_at = timezone.now()
            analysis.save()
            return Response({'success': False, 'error': 'Script not found'}, status=500)

        output_dir = Path(settings.MEDIA_ROOT) / 'analysis_results' / str(analysis.id)
        output_dir.mkdir(parents=True, exist_ok=True)

        cmd = [sys.executable, str(script_path), '--mode', mode, '--excel', upload.filename.path, '--out', str(output_dir)]
        if analysis_type == 'beta':
            cmd += ['--bcoef', 'on', '--strategy', parameters.get('strategy', '1')]
        elif analysis_type == 'mr':
            cmd += ['--bcoef', 'off']
        else:
            cmd += ['--bcoef', 'on', '--combined', '1']
        for prm, flag in [('train_years','--train_years'), ('min_coverage','--min_coverage'), ('threshold_fixed','--threshold_fixed')]:
            if prm in parameters:
                cmd += [flag, str(parameters[prm])]

        logger.info(f"Executing analysis {analysis.id}: {' '.join(cmd)}")
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(project_root), timeout=900)
        except subprocess.TimeoutExpired:
            analysis.status = 'failed'; analysis.error_message = 'timeout'; analysis.completed_at = timezone.now(); analysis.save()
            return Response({'success': False, 'error': 'Timeout'}, status=500)
        except Exception as e:
            analysis.status = 'failed'; analysis.error_message = str(e); analysis.completed_at = timezone.now(); analysis.save()
            return Response({'success': False, 'error': str(e)}, status=500)

        if proc.returncode != 0:
            analysis.status = 'failed'; analysis.error_message = proc.stderr[-4000:]; analysis.completed_at = timezone.now(); analysis.save()
            return Response({'success': False, 'error': 'Script failed', 'stderr_tail': proc.stderr[-1000:]}, status=500)

        try:
            self._postprocess(analysis, output_dir, mode)
            analysis.status = 'completed'
            analysis.completed_at = timezone.now()
            analysis.save()
        except Exception as e:
            analysis.status = 'failed'; analysis.error_message = f'Post-processing: {e}'; analysis.completed_at = timezone.now(); analysis.save()
            return Response({'success': False, 'error': str(e)}, status=500)

        return Response({'success': True, 'analysis_id': analysis.id})

    def _postprocess(self, analysis, output_dir: Path, mode: str):
        forecast_files = sorted(output_dir.glob('forecast_*.csv'))
        backtest_files = sorted(output_dir.glob('predictions_*.csv'))
        if mode == 'forecast' and forecast_files:
            latest = max(forecast_files, key=lambda p: p.stat().st_mtime)
            self._store_forecasts(analysis, latest)
        elif mode == 'backtest' and backtest_files:
            self._store_backtests(analysis, backtest_files)
        else:
            raise ValueError('No output files generated')

    def _store_forecasts(self, analysis, csv_path: Path):
        df = pd.read_csv(csv_path)
        required = ['Forecast Date','Ticker','Forecast Horizon','Raw Probability','Calibrated Probability','Confidence','Expected Move','Prediction Interval (Low)','Prediction Interval (High)','Momentum Sign','Prediction','Abstained']
        miss = [c for c in required if c not in df.columns]
        if miss:
            raise ValueError(f'Missing forecast columns: {miss}')
        df['Forecast Date'] = pd.to_datetime(df['Forecast Date']).dt.date
        ForecastResult.objects.filter(analysis_result=analysis).delete()
        objs = []
        for row in df.itertuples():
            dct = row._asdict()
            objs.append(ForecastResult(
                analysis_result=analysis,
                forecast_date=dct['Forecast Date'],
                ticker=dct['Ticker'],
                forecast_horizon=dct['Forecast Horizon'],
                raw_probability=dct['Raw Probability'],
                calibrated_probability=dct['Calibrated Probability'],
                confidence=dct['Confidence'],
                expected_move=dct['Expected Move'],
                prediction_interval_low=dct['Prediction Interval (Low)'],
                prediction_interval_high=dct['Prediction Interval (High)'],
                momentum_sign=dct['Momentum Sign'],
                decision_threshold=dct.get('Decision Threshold'),
                prediction=int(dct['Prediction']),
                abstained=bool(dct['Abstained'])
            ))
        if objs:
            ForecastResult.objects.bulk_create(objs, batch_size=1000)
        analysis.summary_stats = {
            'total_forecasts': len(df),
            'unique_tickers': int(df['Ticker'].nunique()),
            'horizons': sorted(df['Forecast Horizon'].unique().tolist()),
            'mean_confidence': float(df['Confidence'].mean())
        }
        analysis.save(update_fields=['summary_stats'])

    def _store_backtests(self, analysis, csv_paths):
        BacktestResult.objects.filter(analysis_result=analysis).delete()
        all_frames = []
        objs = []
        for p in csv_paths:
            horizon = p.stem.replace('predictions_','')
            df = pd.read_csv(p)
            req = ['Date','ticker','y_true','y_prob_cal','y_pred','fwd_ret','mr_score','confidence','abstained']
            miss = [c for c in req if c not in df.columns]
            if miss:
                continue
            all_frames.append(df)
            for row in df.itertuples():
                dct = row._asdict()
                objs.append(BacktestResult(
                    analysis_result=analysis,
                    date=pd.to_datetime(dct['Date']).date(),
                    ticker=dct['ticker'],
                    horizon=horizon,
                    y_true=int(dct['y_true']),
                    y_prob_cal=float(dct['y_prob_cal']),
                    y_pred=int(dct['y_pred']),
                    fwd_ret=float(dct['fwd_ret']),
                    mr_score=float(dct['mr_score']),
                    confidence=float(dct['confidence']),
                    abstained=bool(dct['abstained'])
                ))
        if objs:
            BacktestResult.objects.bulk_create(objs, batch_size=1000)
        if all_frames:
            all_df = pd.concat(all_frames, ignore_index=True)
            accuracy = (all_df['y_true'] == all_df['y_pred']).mean()
            analysis.summary_stats = {
                'total_predictions': int(len(all_df)),
                'unique_tickers': int(all_df['ticker'].nunique()),
                'horizons': sorted(set(p.stem.replace('predictions_','') for p in csv_paths)),
                'overall_accuracy': float(accuracy),
                'mean_confidence': float(all_df['confidence'].mean())
            }
            analysis.save(update_fields=['summary_stats'])

from .serializers import (
    CSVUploadSerializer,
    StockSerializer,
    StockDataSerializer,
    CSVUploadRecordSerializer,
    UserProfileSerializer,
    PasswordChangeSerializer,
    # Dual-model architecture serializers
    BetaForecastResultSerializer,
    MeanReversionResultSerializer,
    UnifiedAnalysisResultSerializer,
    ModelComparisonSerializer,
    AnalysisRequestSerializer,
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
def stock_list(request):
    """
    Returns a list of all stocks (id and name only)
    """
    stocks = Stock.objects.all().values("id", "name")
    return Response(list(stocks), status=status.HTTP_200_OK)


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


class DashboardDataView(APIView):
    """Get real dashboard data from database"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        try:
            # Get latest completed analysis
            latest_analysis = AnalysisResult.objects.filter(
                user=request.user,
                status='completed'
            ).order_by('-completed_at').first()
            
            if not latest_analysis:
                return Response({
                    'message': 'No completed analysis found',
                    'has_data': False
                })
            
            # Get forecast data
            forecasts = ForecastResult.objects.filter(
                analysis_result=latest_analysis
            ).select_related('analysis_result')
            
            # Calculate dashboard metrics
            dashboard_data = self.calculate_dashboard_metrics(latest_analysis, forecasts)
            dashboard_data['has_data'] = True
            dashboard_data['last_updated'] = latest_analysis.completed_at.isoformat()
            dashboard_data['analysis_id'] = latest_analysis.id
            
            return Response(dashboard_data)
            
        except Exception as e:
            return Response({'error': str(e)}, status=500)
    
    def calculate_dashboard_metrics(self, analysis_result, forecasts):
        """Calculate key metrics for dashboard"""
        
        if not forecasts.exists():
            return {'message': 'No forecast data available'}
        
        # Convert to DataFrame for easier analysis
        forecast_data = []
        for f in forecasts:
            forecast_data.append({
                'ticker': f.ticker,
                'horizon': f.forecast_horizon,
                'calibrated_probability': f.calibrated_probability,
                'confidence': f.confidence,
                'expected_move': f.expected_move,
                'prediction': f.prediction,
                'abstained': f.abstained,
                'signal_strength': f.signal_strength
            })
        
        df = pd.DataFrame(forecast_data)
        
        # Key metrics
        total_stocks = df['ticker'].nunique()
        total_signals = len(df[df['prediction'] != -1])
        mean_reverting_signals = len(df[df['prediction'] == 1])
        momentum_signals = len(df[df['prediction'] == 0])
        abstained_count = len(df[df['abstained'] == True])
        
        # Confidence distribution
        high_confidence = len(df[df['confidence'] >= 0.8])
        medium_confidence = len(df[(df['confidence'] >= 0.6) & (df['confidence'] < 0.8)])
        low_confidence = len(df[df['confidence'] < 0.6])
        
        # Top opportunities
        top_mean_reverting = df[df['prediction'] == 1].nlargest(10, 'signal_strength')
        top_momentum = df[df['prediction'] == 0].nlargest(10, 'signal_strength')
        
        # Risk metrics
        high_risk_moves = len(df[df['expected_move'].abs() >= 0.05])  # 5%+ expected moves
        
        return {
            'overview': {
                'total_stocks_analyzed': total_stocks,
                'total_signals_generated': total_signals,
                'mean_reverting_signals': mean_reverting_signals,
                'momentum_signals': momentum_signals,
                'abstained_count': abstained_count,
                'signal_rate': round((total_signals / len(df)) * 100, 1) if len(df) > 0 else 0
            },
            'confidence_distribution': {
                'high_confidence': high_confidence,
                'medium_confidence': medium_confidence,
                'low_confidence': low_confidence
            },
            'risk_metrics': {
                'high_risk_moves': high_risk_moves,
                'avg_expected_move': round(df['expected_move'].abs().mean(), 4),
                'max_expected_move': round(df['expected_move'].abs().max(), 4)
            },
            'top_opportunities': {
                'mean_reverting': [
                    {
                        'ticker': row['ticker'],
                        'horizon': row['horizon'],
                        'confidence': round(row['confidence'], 3),
                        'expected_move': round(row['expected_move'], 4),
                        'signal_strength': round(row['signal_strength'], 4)
                    }
                    for _, row in top_mean_reverting.iterrows()
                ],
                'momentum': [
                    {
                        'ticker': row['ticker'],
                        'horizon': row['horizon'],
                        'confidence': round(row['confidence'], 3),
                        'expected_move': round(row['expected_move'], 4),
                        'signal_strength': round(row['signal_strength'], 4)
                    }
                    for _, row in top_momentum.iterrows()
                ]
            },
            'horizon_breakdown': df.groupby('horizon').agg({
                'prediction': lambda x: (x != -1).sum(),
                'confidence': 'mean',
                'expected_move': lambda x: x.abs().mean()
            }).round(4).to_dict()
        }

class StockForecastView(APIView):
    """Get forecast data for specific stock or all stocks"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request, ticker=None):
        try:
            # Get latest analysis
            latest_analysis = AnalysisResult.objects.filter(
                user=request.user,
                status='completed'
            ).order_by('-completed_at').first()
            
            if not latest_analysis:
                return Response({'error': 'No completed analysis found'}, status=404)
            
            # Filter forecasts
            forecasts_query = ForecastResult.objects.filter(
                analysis_result=latest_analysis
            )
            
            if ticker:
                forecasts_query = forecasts_query.filter(ticker=ticker.upper())
            
            forecasts = forecasts_query.order_by('ticker', 'forecast_horizon')
            
            # Serialize forecast data
            forecast_data = []
            for f in forecasts:
                forecast_data.append({
                    'ticker': f.ticker,
                    'forecast_date': f.forecast_date.isoformat(),
                    'horizon': f.forecast_horizon,
                    'raw_probability': round(f.raw_probability, 4),
                    'calibrated_probability': round(f.calibrated_probability, 4),
                    'confidence': round(f.confidence, 4),
                    'expected_move': round(f.expected_move, 4),
                    'prediction_interval': {
                        'low': round(f.prediction_interval_low, 4),
                        'high': round(f.prediction_interval_high, 4)
                    },
                    'prediction': f.prediction,
                    'abstained': f.abstained,
                    'signal_strength': round(f.signal_strength, 4),
                    'is_mean_reverting': f.is_mean_reverting
                })
            
            return Response({
                'success': True,
                'data': forecast_data,
                'analysis_date': latest_analysis.completed_at.isoformat(),
                'total_records': len(forecast_data)
            })
            
        except Exception as e:
            return Response({'error': str(e)}, status=500)

class BacktestPerformanceView(APIView):
    """Get backtest performance data"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        try:
            # Get latest backtest analysis
            latest_analysis = AnalysisResult.objects.filter(
                user=request.user,
                status='completed'
            ).order_by('-completed_at').first()
            
            if not latest_analysis:
                return Response({'error': 'No completed analysis found'}, status=404)
            
            # Get backtest results
            backtests = BacktestResult.objects.filter(
                analysis_result=latest_analysis
            ).order_by('-date')
            
            if not backtests.exists():
                return Response({'message': 'No backtest data available'})
            
            # Calculate performance metrics
            performance_data = self.calculate_backtest_performance(backtests)
            performance_data['analysis_date'] = latest_analysis.completed_at.isoformat()
            
            return Response(performance_data)
            
        except Exception as e:
            return Response({'error': str(e)}, status=500)
    
    def calculate_backtest_performance(self, backtests):
        """Calculate backtest performance metrics"""
        
        # Convert to DataFrame
        backtest_data = []
        for b in backtests:
            backtest_data.append({
                'date': b.date,
                'ticker': b.ticker,
                'horizon': b.horizon,
                'y_true': b.y_true,
                'y_pred': b.y_pred,
                'y_prob_cal': b.y_prob_cal,
                'fwd_ret': b.fwd_ret,
                'confidence': b.confidence,
                'abstained': b.abstained
            })
        
        df = pd.DataFrame(backtest_data)
        
        # Overall performance
        total_predictions = len(df[~df['abstained']])
        correct_predictions = len(df[(~df['abstained']) & (df['y_true'] == df['y_pred'])])
        accuracy = correct_predictions / total_predictions if total_predictions > 0 else 0
        
        # Performance by horizon
        horizon_performance = {}
        for horizon in df['horizon'].unique():
            h_df = df[df['horizon'] == horizon]
            h_total = len(h_df[~h_df['abstained']])
            h_correct = len(h_df[(~h_df['abstained']) & (h_df['y_true'] == h_df['y_pred'])])
            h_accuracy = h_correct / h_total if h_total > 0 else 0
            
            horizon_performance[horizon] = {
                'total_predictions': h_total,
                'correct_predictions': h_correct,
                'accuracy': round(h_accuracy, 4),
                'avg_confidence': round(h_df['confidence'].mean(), 4),
                'coverage': round((h_total / len(h_df)), 4)
            }
        
        # Time series performance (monthly)
        df['month'] = pd.to_datetime(df['date']).dt.to_period('M')
        monthly_performance = df.groupby('month').apply(
            lambda x: pd.Series({
                'accuracy': (x['y_true'] == x['y_pred']).mean(),
                'coverage': (~x['abstained']).mean(),
                'avg_confidence': x['confidence'].mean()
            })
        ).round(4).to_dict()
        
        return {
            'overall': {
                'total_predictions': total_predictions,
                'correct_predictions': correct_predictions,
                'accuracy': round(accuracy, 4),
                'coverage': round((total_predictions / len(df)), 4)
            },
            'by_horizon': horizon_performance,
            'time_series': monthly_performance,
            'summary_stats': {
                'date_range': [str(df['date'].min()), str(df['date'].max())],
                'unique_tickers': df['ticker'].nunique(),
                'total_records': len(df)
            }
        }

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def analyze_csv(request, pk):
    try:
        upload_record = CSVUploadRecord.objects.get(pk=pk, user=request.user)
    except CSVUploadRecord.DoesNotExist:
        return Response({'error': 'CSV upload not found'}, status=status.HTTP_404_NOT_FOUND)
    
    # Set up paths
    analysis_dir = os.path.join(settings.BASE_DIR, '..', 'Data Analysis')
    analysis_script_path = os.path.join(analysis_dir, 'main_model_file_stable_2_extended_future_prediciton.py')
    
    try:
        # Change to analysis directory
        original_cwd = os.getcwd()
        os.chdir(analysis_dir)
        
        # Run analysis
        cmd = [
            'python', 'main_model_file_stable_2_extended_future_prediciton.py',
            '--mode', 'forecast',
            '--excel', 'MXUS_Data.xlsx',
            '--out', f'results_{pk}',
            '--model', 'logit'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        os.chdir(original_cwd)
        
        if result.returncode != 0:
            logger.error(f"Analysis failed for pk={pk}. Stderr: {result.stderr}")
            return Response({
                'error': 'Analysis failed',
                'details': result.stderr
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        # Create AnalysisResult record
        analysis_result = AnalysisResult.objects.create(
            csv_upload=upload_record,
            status='completed',
            parameters={'mode': 'forecast', 'model': 'logit'}
        )
        
        # Parse and save forecast results
        results_dir = Path(analysis_dir) / f'results_{pk}'
        forecast_files = list(results_dir.glob('forecast_*.csv'))
        
        if forecast_files:
            latest_forecast = max(forecast_files, key=os.path.getctime)
            analysis_result.result_file = str(latest_forecast.relative_to(Path(settings.BASE_DIR).parent))
            analysis_result.save()
            
            # Parse CSV and create ForecastResult records
            df = pd.read_csv(latest_forecast)
            forecast_records = []
            
            for _, row in df.iterrows():
                forecast_records.append(ForecastResult(
                    analysis=analysis_result,
                    ticker=row.get('ticker', ''),
                    date=pd.to_datetime(row.get('date')).date(),
                    horizon=row.get('horizon', ''),
                    raw_probability=float(row.get('raw_probability', 0)),
                    calibrated_probability=float(row.get('calibrated_probability', 0)),
                    expected_move=float(row.get('expected_move', 0)),
                    prediction=int(row.get('prediction', 0)),
                    confidence=float(row.get('confidence', 0)),
                    prediction_interval_low=float(row.get('prediction_interval_low', 0)),
                    prediction_interval_high=float(row.get('prediction_interval_high', 0)),
                    abstained=bool(row.get('abstained', False))
                ))
            
            # Bulk create for efficiency
            ForecastResult.objects.bulk_create(forecast_records, batch_size=1000)
            
            return Response({
                'message': 'Analysis completed successfully',
                'analysis_id': analysis_result.id,
                'forecast_count': len(forecast_records)
            })
        else:
            return Response({'error': 'No forecast results generated'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
    except Exception as e:
        os.chdir(original_cwd)
        logger.error(f"Analysis failed for pk={pk}: {str(e)}")
        return Response({'error': f'Analysis failed: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ================= Dual-Model Architecture Views ================= #

class UnifiedAnalysisView(APIView):
    """Unified analysis endpoint supporting both Mean-Reversion and Beta-Forecasting models"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        """Start analysis with model selection"""
        serializer = AnalysisRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({'success': False, 'error': serializer.errors}, status=400)
        
        data = serializer.validated_data
        upload_id = data['upload_id']
        model_type = data['model_type']
        tickers = data.get('tickers', [])
        
        try:
            upload = CSVUploadRecord.objects.get(id=upload_id, user=request.user)
        except CSVUploadRecord.DoesNotExist:
            return Response({'success': False, 'error': 'Upload not found'}, status=404)
        
        # Create analysis record
        analysis = AnalysisResult.objects.create(
            user=request.user,
            csv_upload=upload,
            analysis_type=model_type,
            parameters={'tickers': tickers} if tickers else {},
            status='running',
            started_at=timezone.now()
        )
        
        try:
            # Route to appropriate model execution
            if model_type == 'mean-reversion':
                self._run_mean_reversion_analysis(analysis, upload, tickers)
            elif model_type == 'beta-forecasting':
                self._run_beta_forecasting_analysis(analysis, upload, tickers)
            elif model_type == 'both':
                self._run_both_models_analysis(analysis, upload, tickers)
            
            analysis.status = 'completed'
            analysis.completed_at = timezone.now()
            analysis.save()
            
            return Response({
                'success': True,
                'analysis_id': str(analysis.id),
                'model_type': model_type,
                'status': 'completed',
                'tickers': tickers or self._extract_tickers_from_upload(upload),
                'summary': {
                    'total': len(tickers) if tickers else self._count_tickers_in_upload(upload),
                    'completed': len(tickers) if tickers else self._count_tickers_in_upload(upload),
                    'failed': 0
                }
            })
            
        except Exception as e:
            analysis.status = 'failed'
            analysis.error_message = str(e)
            analysis.completed_at = timezone.now()
            analysis.save()
            logger.error(f"Analysis {analysis.id} failed: {str(e)}")
            return Response({'success': False, 'error': str(e)}, status=500)
    
    def _run_mean_reversion_analysis(self, analysis, upload, tickers=None):
        """Execute Mean-Reversion model"""
        project_root = Path(settings.BASE_DIR).parent
        script_path = project_root / 'Data Analysis' / 'main_model_file_stable_2_extended_future_prediciton.py'
        
        if not script_path.exists():
            raise FileNotFoundError(f"Mean-Reversion script not found: {script_path}")
        
        output_dir = Path(settings.MEDIA_ROOT) / 'analysis_results' / str(analysis.id)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        cmd = [sys.executable, str(script_path), '--excel', upload.filename.path, '--out', str(output_dir)]
        if tickers:
            cmd += ['--tickers', ','.join(tickers)]
        
        logger.info(f"Running Mean-Reversion analysis {analysis.id}: {' '.join(cmd)}")
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(project_root), timeout=900)
        
        if proc.returncode != 0:
            raise RuntimeError(f"Mean-Reversion script failed: {proc.stderr}")
        
        # Process results and store in MeanReversionResult model
        self._store_mean_reversion_results(analysis, output_dir)
    
    def _run_beta_forecasting_analysis(self, analysis, upload, tickers=None):
        """Execute Beta-Forecasting model"""
        project_root = Path(settings.BASE_DIR).parent
        script_path = project_root / 'Data Analysis' / 'bcoef_forecast_v_4_no_market.py'
        
        if not script_path.exists():
            raise FileNotFoundError(f"Beta-Forecasting script not found: {script_path}")
        
        output_dir = Path(settings.MEDIA_ROOT) / 'analysis_results' / str(analysis.id)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        cmd = [sys.executable, str(script_path), '--excel', upload.filename.path, '--out', str(output_dir)]
        if tickers:
            cmd += ['--tickers', ','.join(tickers)]
        
        logger.info(f"Running Beta-Forecasting analysis {analysis.id}: {' '.join(cmd)}")
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(project_root), timeout=900)
        
        if proc.returncode != 0:
            raise RuntimeError(f"Beta-Forecasting script failed: {proc.stderr}")
        
        # Process results and store in BetaForecastResult model
        self._store_beta_forecast_results(analysis, output_dir)
    
    def _run_both_models_analysis(self, analysis, upload, tickers=None):
        """Execute both models"""
        self._run_mean_reversion_analysis(analysis, upload, tickers)
        self._run_beta_forecasting_analysis(analysis, upload, tickers)
    
    def _store_mean_reversion_results(self, analysis, output_dir):
        """Store Mean-Reversion results in database"""
        # Look for mean-reversion output files
        result_files = list(output_dir.glob('*mean_reversion*.csv'))
        if not result_files:
            result_files = list(output_dir.glob('*mr_results*.csv'))
        
        if not result_files:
            logger.warning(f"No mean-reversion results found in {output_dir}")
            return
        
        latest_file = max(result_files, key=lambda p: p.stat().st_mtime)
        df = pd.read_csv(latest_file)
        
        # Store results (mock implementation - adapt based on actual output format)
        for _, row in df.iterrows():
            MeanReversionResult.objects.create(
                analysis_result=analysis,
                analysis_date=timezone.now().date(),
                ticker=row.get('ticker', ''),
                z_score_current=float(row.get('z_score_current', 0)),
                z_score_trend=float(row.get('z_score_trend', 0)),
                mean_reversion_probability=float(row.get('mean_reversion_probability', 0)),
                reversion_strength=row.get('reversion_strength', 'Moderate'),
                magnitude_prediction=float(row.get('magnitude_prediction', 0)),
                magnitude_lower_bound=float(row.get('magnitude_lower_bound', 0)),
                magnitude_upper_bound=float(row.get('magnitude_upper_bound', 0)),
                calibration_score=float(row.get('calibration_score', 0)),
                confidence_interval_90=[
                    float(row.get('ci_90_lower', 0)),
                    float(row.get('ci_90_upper', 0))
                ],
                confidence_interval_95=[
                    float(row.get('ci_95_lower', 0)),
                    float(row.get('ci_95_upper', 0))
                ],
                historical_accuracy=float(row.get('historical_accuracy', 0)),
                lookback_period_days=int(row.get('lookback_period_days', 252)),
                recommendation=row.get('recommendation', 'HOLD'),
                recommendation_confidence=float(row.get('recommendation_confidence', 0))
            )
    
    def _store_beta_forecast_results(self, analysis, output_dir):
        """Store Beta-Forecast results in database"""
        # Look for beta forecast output files
        result_files = list(output_dir.glob('*beta_forecast*.csv'))
        if not result_files:
            result_files = list(output_dir.glob('*forecast*.csv'))
        
        if not result_files:
            logger.warning(f"No beta forecast results found in {output_dir}")
            return
        
        latest_file = max(result_files, key=lambda p: p.stat().st_mtime)
        df = pd.read_csv(latest_file)
        
        # Store results (adapt based on actual output format)
        for _, row in df.iterrows():
            BetaForecastResult.objects.create(
                analysis_result=analysis,
                forecast_date=pd.to_datetime(row.get('forecast_date', timezone.now().date())).date(),
                ticker=row.get('ticker', ''),
                beta_pred=float(row.get('beta_pred', 0)),
                beta_pred_ema=float(row.get('beta_pred_ema', 0)),
                lo=float(row.get('lo', 0)),
                hi=float(row.get('hi', 0)),
                r2_ols=float(row.get('r2_ols', 0)),
                p_value=float(row.get('p_value', 0)),
                confidence_level=row.get('confidence_level', 'Medium (p≤5%)'),
                confidence_tier=row.get('confidence_tier', 'Tier-2'),
                delta_beta_20d=float(row.get('delta_beta_20d', 0)),
                conf_20d=float(row.get('conf_20d', 0)),
                agree_adjacent=bool(row.get('agree_adjacent', False)),
                term_unstable=bool(row.get('term_unstable', False)),
                action=row.get('action', 'hold'),
                hold_reason=row.get('hold_reason', '')
            )
    
    def _extract_tickers_from_upload(self, upload):
        """Extract ticker list from uploaded file"""
        # Mock implementation - adapt based on actual file structure
        return ['AAPL', 'MSFT', 'GOOGL']
    
    def _count_tickers_in_upload(self, upload):
        """Count tickers in uploaded file"""
        return len(self._extract_tickers_from_upload(upload))


class UnifiedAnalysisResultView(APIView):
    """Get unified analysis results for a specific ticker and model"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request, ticker, model_type):
        """Get analysis result for specific ticker and model type"""
        try:
            if model_type == 'mean-reversion':
                results = MeanReversionResult.objects.filter(
                    analysis_result__user=request.user,
                    ticker=ticker.upper()
                ).order_by('-analysis_date').first()
                
                if not results:
                    return Response({'error': 'No mean-reversion results found'}, status=404)
                
                serializer = MeanReversionResultSerializer(results)
                return Response({
                    'analysis_id': str(results.analysis_result.id),
                    'model_type': 'mean-reversion',
                    'ticker': ticker.upper(),
                    'name': f"{ticker.upper()} Inc.",  # Mock - could be enhanced with company name lookup
                    'analysis_date': results.analysis_date,
                    'recommendation': results.recommendation,
                    'confidence': results.recommendation_confidence,
                    'model_data': serializer.data
                })
                
            elif model_type == 'beta-forecasting':
                results = BetaForecastResult.objects.filter(
                    analysis_result__user=request.user,
                    ticker=ticker.upper()
                ).order_by('-forecast_date').first()
                
                if not results:
                    return Response({'error': 'No beta forecast results found'}, status=404)
                
                serializer = BetaForecastResultSerializer(results)
                
                # Map action to recommendation
                action_to_recommendation = {
                    'chase': 'BUY',
                    'fade': 'SELL',
                    'hold': 'HOLD'
                }
                
                return Response({
                    'analysis_id': str(results.analysis_result.id),
                    'model_type': 'beta-forecasting',
                    'ticker': ticker.upper(),
                    'name': f"{ticker.upper()} Inc.",  # Mock - could be enhanced
                    'analysis_date': results.forecast_date,
                    'recommendation': action_to_recommendation.get(results.action, 'HOLD'),
                    'confidence': results.conf_20d,
                    'model_data': serializer.data
                })
            
            else:
                return Response({'error': 'Invalid model type'}, status=400)
                
        except Exception as e:
            logger.error(f"Error retrieving unified analysis result: {str(e)}")
            return Response({'error': str(e)}, status=500)


class ModelComparisonView(APIView):
    """Compare both models for a specific ticker"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request, ticker):
        """Compare both Mean-Reversion and Beta-Forecasting for a ticker"""
        try:
            # Get both results
            mr_view = UnifiedAnalysisResultView()
            mr_request = request._request if hasattr(request, '_request') else request
            mr_response = mr_view.get(mr_request, ticker, 'mean-reversion')
            
            beta_response = mr_view.get(mr_request, ticker, 'beta-forecasting')
            
            if mr_response.status_code != 200 or beta_response.status_code != 200:
                return Response({'error': 'Results not found for both models'}, status=404)
            
            mr_data = mr_response.data
            beta_data = beta_response.data
            
            # Compare recommendations
            mr_recommendation = mr_data['recommendation']
            beta_recommendation = beta_data['recommendation']
            
            if mr_recommendation == beta_recommendation:
                agreement = "Strong"
                primary_recommendation = mr_recommendation
                confidence_score = max(mr_data['confidence'], beta_data['confidence'])
            else:
                agreement = "Conflicting"
                # Use beta model as primary when conflicting (higher confidence generally)
                if beta_data['confidence'] > mr_data['confidence']:
                    primary_recommendation = beta_recommendation
                    confidence_score = beta_data['confidence']
                else:
                    primary_recommendation = mr_recommendation
                    confidence_score = mr_data['confidence']
            
            return Response({
                'mean_reversion': mr_data,
                'beta_forecasting': beta_data,
                'comparison': {
                    'agreement': agreement,
                    'primary_recommendation': primary_recommendation,
                    'confidence_score': confidence_score
                }
            })
            
        except Exception as e:
            logger.error(f"Error in model comparison: {str(e)}")
            return Response({'error': str(e)}, status=500)


# ================= Beta Coefficient Model Output API Views ================= #

class BetaRealizedListView(APIView):
    """API endpoint for beta realized data from betas_20d.csv"""
    
    def get(self, request):
        from .models import BetaRealized
        from .serializers import BetaRealizedSerializer
        
        ticker = request.query_params.get('ticker')
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        
        queryset = BetaRealized.objects.all()
        
        if ticker:
            queryset = queryset.filter(ticker=ticker)
        if start_date:
            queryset = queryset.filter(date__gte=start_date)
        if end_date:
            queryset = queryset.filter(date__lte=end_date)
        
        queryset = queryset.order_by('-date', 'ticker')[:1000]  # Limit results
        
        serializer = BetaRealizedSerializer(queryset, many=True)
        return Response({
            'count': queryset.count(),
            'results': serializer.data
        })


class ForecastEvaluationListView(APIView):
    """API endpoint for forecast evaluation data from forecast_eval_20d.csv"""
    
    def get(self, request):
        from .models import ForecastEvaluation
        from .serializers import ForecastEvaluationSerializer
        
        ticker = request.query_params.get('ticker')
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        min_significance = request.query_params.get('min_significance', 0.7)
        
        queryset = ForecastEvaluation.objects.all()
        
        if ticker:
            queryset = queryset.filter(ticker=ticker)
        if start_date:
            queryset = queryset.filter(date__gte=start_date)
        if end_date:
            queryset = queryset.filter(date__lte=end_date)
        
        queryset = queryset.filter(significance_score__gte=float(min_significance))
        queryset = queryset.order_by('-date', 'ticker')[:1000]
        
        serializer = ForecastEvaluationSerializer(queryset, many=True)
        return Response({
            'count': queryset.count(),
            'results': serializer.data
        })


class BetaCoefficientSummaryView(APIView):
    """Summary statistics for beta coefficient predictions"""
    
    def get(self, request):
        from .models import ForecastEvaluation
        from django.db.models import Avg, Count, Max
        
        # Get summary by ticker
        summary_data = []
        
        for ticker_data in ForecastEvaluation.objects.values('ticker').annotate(
            forecast_count=Count('id'),
            avg_r2=Avg('r2_ols'),
            latest_date=Max('date')
        ).order_by('-forecast_count'):
            
            ticker = ticker_data['ticker']
            latest_record = ForecastEvaluation.objects.filter(
                ticker=ticker,
                date=ticker_data['latest_date']
            ).first()
            
            if latest_record:
                # Calculate prediction accuracy (simplified)
                prediction_error = abs(latest_record.beta_pred - latest_record.beta_true) if latest_record.beta_true else None
                accuracy = 1 - min(prediction_error, 1.0) if prediction_error is not None else None
                
                confidence_level = 'High' if latest_record.significance_score > 0.8 else 'Medium' if latest_record.significance_score > 0.6 else 'Low'
                
                summary_data.append({
                    'ticker': ticker,
                    'latest_date': latest_record.date,
                    'latest_beta_pred': latest_record.beta_pred,
                    'latest_beta_true': latest_record.beta_true,
                    'avg_r2_ols': ticker_data['avg_r2'],
                    'prediction_accuracy': accuracy,
                    'forecast_count': ticker_data['forecast_count'],
                    'confidence_level': confidence_level
                })
        
        return Response({
            'summary': summary_data[:50]  # Top 50 tickers
        })


class BetaCoefficientTimeSeriesView(APIView):
    """Time series data for a specific ticker's beta coefficient predictions"""
    
    def get(self, request, ticker):
        from .models import ForecastEvaluation
        
        queryset = ForecastEvaluation.objects.filter(
            ticker=ticker
        ).order_by('date')
        
        dates = []
        beta_pred = []
        beta_true = []
        confidence_bands = []
        
        for record in queryset:
            dates.append(record.date)
            beta_pred.append(record.beta_pred)
            beta_true.append(record.beta_true)
            
            # Calculate confidence bands using the band value
            confidence_bands.append({
                'lower': record.beta_pred - record.band,
                'upper': record.beta_pred + record.band
            })
        
        return Response({
            'ticker': ticker,
            'dates': dates,
            'beta_pred': beta_pred,
            'beta_true': beta_true,
            'confidence_bands': confidence_bands
        })


class ImportBetaDataView(APIView):
    """Import beta coefficient data from CSV files"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        from .models import BetaRealized, ForecastEvaluation
        import csv
        from django.conf import settings
        
        try:
            # Import betas_20d.csv
            betas_file = os.path.join(settings.BASE_DIR.parent, 'outputs', 'betas_20d.csv')
            if os.path.exists(betas_file):
                with open(betas_file, 'r') as f:
                    reader = csv.DictReader(f)
                    beta_objects = []
                    
                    for row in reader:
                        if row['Date'] and row['ticker']:  # Skip empty rows
                            try:
                                beta_obj = BetaRealized(
                                    date=datetime.strptime(row['Date'], '%m/%d/%Y').date(),
                                    ticker=row['ticker'],
                                    beta_realised=float(row['beta_realised']) if row['beta_realised'] else None,
                                    r2_ols_x=float(row['r2_ols_x']) if row['r2_ols_x'] else None,
                                    r2_ols_y=float(row['r2_ols_y']) if row['r2_ols_y'] else None,
                                    p_value=float(row['p_value']) if row['p_value'] else None,
                                    significance_score=float(row['significance_score']) if row['significance_score'] else None,
                                    beta_pred=float(row['beta_pred']) if row['beta_pred'] else None,
                                    beta_true=float(row['beta_true']) if row['beta_true'] else None,
                                    band=float(row['band']) if row['band'] else None,
                                    lo=float(row['lo']) if row['lo'] else None,
                                    hi=float(row['hi']) if row['hi'] else None,
                                )
                                beta_objects.append(beta_obj)
                            except (ValueError, KeyError) as e:
                                continue  # Skip invalid rows
                    
                    # Bulk create with ignore conflicts
                    BetaRealized.objects.bulk_create(beta_objects, ignore_conflicts=True, batch_size=1000)
            
            # Import forecast_eval_20d.csv
            forecast_file = os.path.join(settings.BASE_DIR.parent, 'outputs', 'forecast_eval_20d.csv')
            if os.path.exists(forecast_file):
                with open(forecast_file, 'r') as f:
                    reader = csv.DictReader(f)
                    forecast_objects = []
                    
                    for row in reader:
                        try:
                            forecast_obj = ForecastEvaluation(
                                date=datetime.strptime(row['Date'], '%m/%d/%Y').date(),
                                ticker=row['ticker'],
                                r2_ols=float(row['r2_ols']),
                                p_value=float(row['p_value']),
                                significance_score=float(row['significance_score']),
                                beta_pred=float(row['beta_pred']),
                                beta_true=float(row['beta_true']),
                                band=float(row['band']),
                            )
                            forecast_objects.append(forecast_obj)
                        except (ValueError, KeyError) as e:
                            continue
                    
                    ForecastEvaluation.objects.bulk_create(forecast_objects, ignore_conflicts=True, batch_size=1000)
            
            return Response({
                'message': 'Beta coefficient data imported successfully',
                'beta_records': BetaRealized.objects.count(),
                'forecast_records': ForecastEvaluation.objects.count()
            })
            
        except Exception as e:
            logger.error(f"Error importing beta data: {str(e)}")
            return Response({'error': str(e)}, status=500)