import csv
import io
import math
import os
import subprocess
import sys
import pandas as pd
import json
import numpy as np
from django.db import transaction
from django.conf import settings
import glob


from pathlib import Path
import logging # <-- Add logging

from django.db.models import Avg

# Get an instance of a logger
logger = logging.getLogger(__name__)

from datetime import datetime
from django.utils import timezone
from django.contrib.auth import authenticate, login, logout
from django.views.decorators.csrf import ensure_csrf_cookie
from django.http import FileResponse, JsonResponse
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from rest_framework import status, generics, viewsets
from rest_framework.decorators import action
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
from .models import Stock, StockData, CSVUploadRecord, UserProfile, AnalysisResult, ForecastResult, BacktestResult, BetaForecastResult, MeanReversionResult, FactorSharedStats, StockFactorResult
from datetime import date, datetime
from django.contrib.auth import update_session_auth_hash
from rest_framework.decorators import parser_classes
from .model_runner import run_analysis_from_web


def _model_field_names(model_cls):
    # concrete, non-relational field names
    return {f.name for f in model_cls._meta.get_fields() if hasattr(f, "attname") and not f.many_to_many and not f.one_to_many}

def _safe_create(model_cls, payload: dict):
    fields = _model_field_names(model_cls)
    clean = {k: v for k, v in payload.items() if k in fields}
    return model_cls.objects.create(**clean)

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
    """
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # --- Required parameters ---
        csv_upload_id = request.data.get('csv_upload_id')
        if not csv_upload_id:
            return Response({'success': False, 'error': 'csv_upload_id required'}, status=400)

        mode = request.data.get('mode', 'forecast')  # forecast or backtest
        parameters = request.data.get('parameters', {}) or {}

        # --- Get uploaded file record ---
        try:
            upload = CSVUploadRecord.objects.get(id=csv_upload_id, user=request.user)
        except CSVUploadRecord.DoesNotExist:
            return Response({'success': False, 'error': 'Upload not found'}, status=404)

        # --- Create analysis record ---
        analysis = AnalysisResult.objects.create(
            user=request.user,
            csv_upload=upload,
            analysis_type='b_forecast_pipeline_extended',
            parameters=parameters,
            status='running',
            started_at=timezone.now()
        )

        # --- Resolve model file path ---
        project_root = Path(settings.BASE_DIR).parent

        # ✅ NEW MODEL FILE (Active)
        script_path = project_root / 'data-analysis' / 'b_forecast_pipeline_extended.py'


        # --- LEGACY MODEL FILES (Preserved for rollback) ---
        # candidates = [
        #     'data-analysis/main_model_file_merged_bcoef_strategy1_stats_legacy (1).py',
        #     'data-analysis/main_model_file_stable_2_extended_future_prediciton_bhat.py',
        #     'data-analysis/main_model_file_stable_2_extended_future_prediciton.py'
        # ]
        # for candidate in candidates:
        #     potential = project_root / candidate
        #     if potential.exists():
        #         script_path = potential
        #         break

        if not script_path.exists():
            analysis.status = 'failed'
            analysis.error_message = f'Model script not found: {script_path}'
            analysis.completed_at = timezone.now()
            analysis.save()
            return Response({'success': False, 'error': 'Model script not found'}, status=500)

        # --- Prepare output directory ---
        output_dir = Path(settings.MEDIA_ROOT) / 'analysis_results' / str(analysis.id)
        output_dir.mkdir(parents=True, exist_ok=True)

        # --- Build command (NEW MODEL) ---
        cmd = [
            sys.executable,
            str(script_path),
            '--mode', mode,
            '--file', upload.filename.path,  # Input file path
            '--out', str(output_dir)
        ]

        # --- Optional additional parameters ---
        for prm, flag in [
            ('train_years', '--train_years'),
            ('min_coverage', '--min_coverage'),
            ('threshold_fixed', '--threshold_fixed')
        ]:
            if prm in parameters:
                cmd += [flag, str(parameters[prm])]

        logger.info(f"[RunAnalysisView] Running b_forecast_pipeline_extendedl.py for analysis {analysis.id}:\n{' '.join(cmd)}")

        # --- LEGACY COMMAND STRUCTURE (Preserved) ---
        # cmd = [sys.executable, str(script_path), '--mode', mode, '--excel', upload.filename.path, '--out', str(output_dir)]
        # if analysis_type == 'beta':
        #     cmd += ['--bcoef', 'on', '--strategy', parameters.get('strategy', '1')]
        # elif analysis_type == 'mr':
        #     cmd += ['--bcoef', 'off']
        # else:
        #     cmd += ['--bcoef', 'on', '--combined', '1']

        # --- Execute the model script ---
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, cwd=str(project_root), timeout=900
            )

            if len(proc.stderr) > 50000:
                proc.stderr = proc.stderr[-50000:]

        except subprocess.TimeoutExpired:
            analysis.status = 'failed'
            analysis.error_message = 'Timeout after 15 minutes'
            analysis.completed_at = timezone.now()
            analysis.save()
            return Response({'success': False, 'error': 'Analysis timed out'}, status=500)
        except Exception as e:
            analysis.status = 'failed'
            analysis.error_message = f'Execution failed: {e}'
            analysis.completed_at = timezone.now()
            analysis.save()
            return Response({'success': False, 'error': str(e)}, status=500)

        # --- Handle script exit ---
        if proc.returncode != 0:
            analysis.status = 'failed'
            analysis.error_message = proc.stderr[-2000:]
            analysis.completed_at = timezone.now()
            analysis.save()
            logger.error(f"[RunAnalysisView] Josh_model.py failed for analysis {analysis.id}: {proc.stderr}")
            return Response({
                'success': False,
                'error': 'Model script failed',
                'stderr': proc.stderr[-2000:]
            }, status=500)

        # --- Postprocess model outputs ---
        try:
            self._postprocess(analysis, output_dir, mode)
            analysis.status = 'completed'
            analysis.completed_at = timezone.now()
            analysis.save()
        except Exception as e:
            analysis.status = 'failed'
            analysis.error_message = f'Post-processing failed: {e}'
            analysis.completed_at = timezone.now()
            analysis.save()
            logger.error(f"[RunAnalysisView] Post-processing error for analysis {analysis.id}: {e}")
            return Response({'success': False, 'error': str(e)}, status=500)

        return Response({'success': True, 'analysis_id': analysis.id})

    # ================= Helper methods ================= #

    def _postprocess(self, analysis, output_dir: Path, mode: str):
        """Handles output files generated by b_forecast_pipeline_extended.py"""

        summary_path = output_dir / 'Outputs' / 'all_model_metrics_summary.csv'
        coeff_plot = list(output_dir.rglob('enet_coefficients.png'))
        learning_table = list(output_dir.rglob('learning_table.csv'))

        if summary_path.exists():
            self._store_b_forecast_summary(analysis, summary_path, coeff_plot, learning_table)
        else:
            raise ValueError('No output summary found for b_forecast_pipeline_extended')

    def _store_b_forecast_summary(self, analysis, summary_csv, coeff_plot_files, learning_tables):
        df = pd.read_csv(summary_csv)

        # ---- Key outputs ----
        b_coef = float(df['Pred_b_ENET'].iloc[0]) if 'Pred_b_ENET' in df else float('nan')
        oos_r2 = float(df.get('OOS_R2_global', np.nan))
        oos_mae = float(df.get('OOS_MAE', np.nan))

        # ---- Load coefficients from ENET model ----
        coef_file = None
        for p in coeff_plot_files:
            if 'enet_coefficients' in str(p):
                coef_file = p
                break

        factors = []
        if coef_file:
            coef_csv = coef_file.with_suffix('.csv')
            if coef_csv.exists():
                coef_df = pd.read_csv(coef_csv)
                top_factors = coef_df.sort_values(by='coefficient', key=abs, ascending=False).head(10)
                factors = top_factors.to_dict(orient='records')

        # ---- Load learning table for averages ----
        avg_factors = {}
        if learning_tables:
            lt = pd.read_csv(learning_tables[0])
            feature_cols = [c for c in lt.columns if any(
                pref in c for pref in ['ar1_corr', 'vol_', 'sign_persist_', 'ret_', 'Z_ma_', 'cs_rank_'])]
            avg_factors = lt[feature_cols].mean().to_dict()

        analysis.summary_stats = {
            'b_coefficient': b_coef,
            'oos_r2': oos_r2,
            'oos_mae': oos_mae,
            'top_factors': factors,
            'avg_factor_values': avg_factors
        }

        analysis.status = 'completed'
        analysis.completed_at = timezone.now()
        analysis.save()

    def _store_backtests(self, analysis, csv_paths):
        BacktestResult.objects.filter(analysis_result=analysis).delete()
        all_frames, objs = [], []

        for p in csv_paths:
            horizon = p.stem.replace('predictions_', '')
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
                'horizons': sorted(set(p.stem.replace('predictions_', '') for p in csv_paths)),
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
    FactorSharedStatsSerializer,
    StockFactorResultSerializer, StockFactorTimeSeriesSerializer,
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
                # Fetch all key fields: stock_id, date, data_type, and the PK (id)
                existing_records = StockData.objects.filter(**existing_records_filter).values('stock_id', 'date',
                                                                                              'data_type', 'id')

                # Create a map for fast lookup: (stock_id, date, data_type) -> id
                existing_records_map = {
                    (rec['stock_id'], rec['date'], rec['data_type']): rec['id']
                    for rec in existing_records
                }

                # 2. Separate into lists for creation and update
                records_to_create = []
                records_to_update = []

                for data_point in data_to_process:
                    stock_id = data_point['stock'].id
                    date_val = data_point['date']
                    data_type_val = data_point['data_type']  # Get the data_type

                    # Check for existence using the full unique key
                    key = (stock_id, date_val, data_type_val)

                    if key in existing_records_map:
                        record_id = existing_records_map[key]
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
    permission_classes = [IsAuthenticated]  # ensure user is logged in

    def post(self, request, *args, **kwargs):
        file_obj = request.data.get('file')
        if not file_obj:
            return Response({'error': 'No file was provided.'}, status=status.HTTP_400_BAD_REQUEST)

        # Associate upload with the current logged-in user
        serializer = CSVUploadSerializer(data={'filename': file_obj})
        if serializer.is_valid():
            upload_record = None
            try:
                upload_record = serializer.save(user=request.user)  # <-- FIX: set the user
                file_path = upload_record.filename.path

                if file_path.endswith('.xlsx'):
                    # Use model-style reading logic for Excel
                    with pd.ExcelFile(file_path) as xls:
                        if "Returns" not in xls.sheet_names:
                            raise ValueError("No 'Returns' sheet found in Excel file.")

                        df = pd.read_excel(xls, sheet_name="Returns", header=None)

                        # --- Detect header row containing "Date" ---
                        header_row = None
                        for i in range(min(50, len(df))):
                            if df.iloc[i].astype(str).str.lower().eq("date").any():
                                header_row = i
                                break
                        if header_row is None:
                            raise ValueError("No header row containing 'Date' found in sheet.")

                        # --- Assign columns and clean data ---
                        cols = df.iloc[header_row].astype(str).str.strip().tolist()
                        data_df = df.iloc[header_row + 1:].copy()
                        data_df.columns = cols
                        data_df = data_df.loc[:, ~(data_df.isna().all())]

                        # Ensure 'Date' column is properly parsed
                        date_col = next((c for c in data_df.columns if str(c).strip().lower() == "date"), None)
                        if not date_col:
                            raise ValueError("No 'Date' column found in sheet.")
                        if date_col != "Date":
                            data_df = data_df.rename(columns={date_col: "Date"})

                        data_df["Date"] = pd.to_datetime(data_df["Date"], errors="coerce")
                        data_df = data_df.dropna(subset=["Date"])

                        data_to_process = []
                        data_type = "return"

                        # --- Create Stock and StockData entries ---
                        stock_names = [c for c in data_df.columns if c != "Date"]
                        if not stock_names:
                            raise ValueError("No stock columns found in sheet.")

                        # Bulk get_or_create for stocks
                        stocks_map = {name.strip(): Stock.objects.get_or_create(name=name.strip())[0] for name in
                                      stock_names}

                        # Collect data points (similar structure to what process_data uses)
                        for stock_name in stock_names:
                            stock_obj = stocks_map[stock_name]
                            for _, row in data_df.iterrows():
                                val = row[stock_name]
                                if pd.isna(val):
                                    continue

                                data_to_process.append({
                                    'stock': stock_obj,
                                    'date': row["Date"].date(),
                                    'data_type': data_type,
                                    'value': float(val),
                                })

                        # --- Start Upsert Logic ---

                        # 1. Get existing records in a single query (Only query for the relevant stock/date/data_type)
                        existing_records_filter = {
                            'stock__in': [d['stock'] for d in data_to_process],
                            'data_type': data_type,
                            'date__in': [d['date'] for d in data_to_process]
                        }
                        existing_records = StockData.objects.filter(**existing_records_filter).values('stock_id',
                                                                                                      'date',
                                                                                                      'data_type', 'id')

                        # Create a map for fast lookup: (stock_id, date, data_type) -> id
                        existing_records_map = {
                            (rec['stock_id'], rec['date'], rec['data_type']): rec['id']
                            for rec in existing_records
                        }

                        # 2. Separate into lists for creation and update
                        records_to_create = []
                        records_to_update = []

                        for data_point in data_to_process:
                            stock_id = data_point['stock'].id
                            date_val = data_point['date']
                            data_type_val = data_point['data_type']

                            key = (stock_id, date_val, data_type_val)

                            if key in existing_records_map:
                                record_id = existing_records_map[key]
                                records_to_update.append(
                                    StockData(
                                        id=record_id,
                                        **data_point  # Pass all fields including stock, date, data_type, and value
                                    )
                                )
                            else:
                                records_to_create.append(StockData(**data_point))

                        # 3. Perform bulk operations
                        if records_to_create:
                            StockData.objects.bulk_create(records_to_create, batch_size=5000)

                        if records_to_update:
                            # Only update the 'value' field
                            StockData.objects.bulk_update(records_to_update, ['value'], batch_size=5000)

                        print(
                            f"Successfully imported {len(records_to_create)} new and updated {len(records_to_update)} stock return records from XLSX.")

                elif file_path.endswith('.csv'):
                    df = pd.read_csv(file_path, header=None)
                    # Determine data_type based on filename
                    if 'prices' in file_obj.name.lower():
                        data_type = 'price'
                    elif 'returns' or 'mxus_data' in file_obj.name.lower():
                        data_type = 'return'
                    elif 'bql_query' or 'equity' in file_obj.name.lower():
                        data_type = 'equity'
                    else:
                        raise ValueError("Could not determine data type from CSV filename.")

                    process_data(df, file_obj, data_type, upload_record)

                else:
                    raise ValueError("Unsupported file format.")

                return Response({'message': 'File uploaded and processed successfully.'},
                                status=status.HTTP_201_CREATED)

            except Exception as e:
                # Cleanup if processing fails
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

    # Check if file exists before trying to open it
    try:
        if not upload.filename:
            return Response({"error": "File path not found"}, status=404)
        return FileResponse(upload.filename.open("rb"), as_attachment=True, filename=os.path.basename(upload.filename.name))
    except FileNotFoundError:
        return Response({"error": "File not found on disk"}, status=404)


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


@api_view(["GET"])
def factor_shared(request):
    """Returns the latest FactorSharedStats summary (averages, coefs, etc)
    plus average Y-Intercept from per-stock results."""
    try:
        latest_shared = FactorSharedStats.objects.latest("created_at")
        serializer = FactorSharedStatsSerializer(latest_shared)
        data = serializer.data

        avg_y_intercept = (
            StockFactorResult.objects
            .filter(shared_stats=latest_shared)
            .aggregate(Avg("y_intercept"))
            ["y_intercept__avg"]
        )

        data["y_intercept"] = avg_y_intercept  # append to JSON output

        return Response(data)

    except FactorSharedStats.DoesNotExist:
        return Response({}, status=status.HTTP_404_NOT_FOUND)



@api_view(["GET"])
def factor_summary(request):
    """Returns latest per-ticker results for the most recent FactorSharedStats record."""
    import math

    def safe_json(obj):
        if isinstance(obj, float):
            if math.isnan(obj) or math.isinf(obj):
                return None
            return obj
        elif isinstance(obj, list):
            return [safe_json(x) for x in obj]
        elif isinstance(obj, dict):
            return {k: safe_json(v) for k, v in obj.items()}
        return obj

    try:
        latest_shared = FactorSharedStats.objects.latest("created_at")
        stock_results = (
            StockFactorResult.objects
            .filter(shared_stats=latest_shared)
            .order_by("ticker", "-created_at")
            .distinct("ticker")
        )
        serializer = StockFactorResultSerializer(stock_results, many=True)
        cleaned_data = safe_json(serializer.data)
        return Response({"summary": cleaned_data})
    except FactorSharedStats.DoesNotExist:
        return Response({"summary": []})


@api_view(['GET'])
def beta_timeseries(request, ticker):
    ticker = ticker.strip().upper()
    qs = StockFactorResult.objects.filter(ticker__iexact=ticker).order_by("created_at")

    if not qs.exists():
        return Response({"detail": f"No time series found for ticker {ticker}."}, status=status.HTTP_404_NOT_FOUND)

    serializer = StockFactorTimeSeriesSerializer(qs, many=True)
    data = serializer.data

    # Adapt to chart structure
    response = {
        "ticker": ticker,
        "dates": [row["created_at"] for row in data],
        "beta_pred": [row["b_coefficient"] for row in data],
        "beta_true": [None for _ in data],  # placeholder until actual betas available
        "confidence_bands": [{"lower": row["b_coefficient"] - 0.02, "upper": row["b_coefficient"] + 0.02} for row in data]
    }

    return Response(response, status=status.HTTP_200_OK)

@api_view(["GET"])
def latest_summary(request):
    """Return latest per-stock results for the most recent shared model run."""
    latest_shared = FactorSharedStats.objects.order_by("-created_at").first()
    if not latest_shared:
        return Response({"detail": "No shared stats found"}, status=404)

    latest_results = (
        StockFactorResult.objects
        .filter(shared_stats=latest_shared)
        .order_by("ticker", "-created_at")
        .distinct("ticker")
    )

    serializer = StockFactorResultSerializer(latest_results, many=True)
    return Response(serializer.data, status=200)
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
    try:
        result = run_analysis_from_web(upload_pk=pk, model_for_pred="enet")
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "Unknown error"))
        return Response(result, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"ok": False, "error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


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

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def analyze_csv(request, pk):
    """
    """
    try:
        upload_record = CSVUploadRecord.objects.get(pk=pk, user=request.user)
    except CSVUploadRecord.DoesNotExist:
        return Response({"error": "CSV upload not found"}, status=status.HTTP_404_NOT_FOUND)

    # --- Path setup ---
    project_root = Path(settings.BASE_DIR).parent
    analysis_dir = project_root / "data-analysis"

    # ✅ NEW MODEL (Active)
    script_path = analysis_dir / 'b_forecast_pipeline_extended.py'

    # --- LEGACY MODEL (Preserved) ---
    # script_path = analysis_dir / "main_model_file_stable_2_extended_future_prediciton.py"

    if not script_path.exists():
        logger.error(f"Model script not found at {script_path}")
        return Response({"error": "Model script not found on server."}, status=500)

    out_dir = Path(settings.MEDIA_ROOT) / "analysis_results" / str(pk)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Change to analysis directory
        original_cwd = os.getcwd()
        os.chdir(analysis_dir)

        # ✅ Run Josh_model.py
        cmd = [
            sys.executable,
            str(script_path),
            "--mode", "forecast",
            "--file", upload_record.filename.path,
            "--out", str(out_dir),
        ]

        logger.info(f"Running model command: {' '.join(cmd)}")

        # --- LEGACY COMMAND (Preserved) ---
        # cmd = [
        #     "python", "main_model_file_stable_2_extended_future_prediciton.py",
        #     "--mode", "forecast",
        #     "--excel", "MXUS_Data.xlsx",
        #     "--out", f"results_{pk}",
        #     "--model", "logit"
        # ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        os.chdir(original_cwd)

        if result.returncode != 0:
            logger.error(f"Josh_model failed for pk={pk}. Stderr: {result.stderr}")
            return Response(
                {"error": "Analysis failed", "details": result.stderr[-2000:]},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # ✅ Create AnalysisResult record
        analysis_result = AnalysisResult.objects.create(
            csv_upload=upload_record,
            status="completed",
            parameters={"mode": "forecast", "model": "model"},
        )

        # --- Locate and process forecast results ---
        forecast_files = list(out_dir.glob("forecast_*.csv"))
        if forecast_files:
            latest_forecast = max(forecast_files, key=os.path.getctime)
            analysis_result.result_file = str(latest_forecast.relative_to(project_root))
            analysis_result.save()

            df = pd.read_csv(latest_forecast)
            forecast_records = []
            for _, row in df.iterrows():
                forecast_records.append(
                    ForecastResult(
                        analysis_result=analysis_result,
                        ticker=row.get("Ticker", ""),
                        forecast_date=pd.to_datetime(row.get("Forecast Date")).date()
                        if row.get("Forecast Date") else None,
                        forecast_horizon=row.get("Forecast Horizon", ""),
                        raw_probability=float(row.get("Raw Probability", 0)),
                        calibrated_probability=float(row.get("Calibrated Probability", 0)),
                        expected_move=float(row.get("Expected Move", 0)),
                        prediction=int(row.get("Prediction", 0)),
                        confidence=float(row.get("Confidence", 0)),
                        prediction_interval_low=float(row.get("Prediction Interval (Low)", 0)),
                        prediction_interval_high=float(row.get("Prediction Interval (High)", 0)),
                        abstained=bool(row.get("Abstained", False)),
                    )
                )

            ForecastResult.objects.bulk_create(forecast_records, batch_size=1000)
            return Response(
                {
                    "message": "Analysis completed successfully.",
                    "analysis_id": analysis_result.id,
                    "forecast_count": len(forecast_records),
                }
            )
        else:
            return Response({"error": "No forecast results generated."}, status=500)

    except Exception as e:
        os.chdir(original_cwd)
        logger.error(f"Analysis failed for pk={pk}: {e}")
        return Response({"error": f"Analysis failed: {e}"}, status=500)


# # ================= Dual-Model Architecture Views ================= #
#
# class UnifiedAnalysisView(APIView):
#     """Unified analysis endpoint supporting both Mean-Reversion and Beta-Forecasting models"""
#     permission_classes = [IsAuthenticated]
#
#     def post(self, request):
#         """Start analysis with model selection"""
#         serializer = AnalysisRequestSerializer(data=request.data)
#         if not serializer.is_valid():
#             return Response({'success': False, 'error': serializer.errors}, status=400)
#
#         data = serializer.validated_data
#         upload_id = data['upload_id']
#         model_type = data['model_type']
#         tickers = data.get('tickers', [])
#
#         try:
#             upload = CSVUploadRecord.objects.get(id=upload_id, user=request.user)
#         except CSVUploadRecord.DoesNotExist:
#             return Response({'success': False, 'error': 'Upload not found'}, status=404)
#
#         # Create analysis record
#         analysis = AnalysisResult.objects.create(
#             user=request.user,
#             csv_upload=upload,
#             analysis_type=model_type,
#             parameters={'tickers': tickers} if tickers else {},
#             status='running',
#             started_at=timezone.now()
#         )
#
#         try:
#             # Route to appropriate model execution
#             if model_type == 'mean-reversion':
#                 self._run_mean_reversion_analysis(analysis, upload, tickers)
#             elif model_type == 'beta-forecasting':
#                 self._run_beta_forecasting_analysis(analysis, upload, tickers)
#             elif model_type == 'both':
#                 self._run_both_models_analysis(analysis, upload, tickers)
#
#             analysis.status = 'completed'
#             analysis.completed_at = timezone.now()
#             analysis.save()
#
#             return Response({
#                 'success': True,
#                 'analysis_id': str(analysis.id),
#                 'model_type': model_type,
#                 'status': 'completed',
#                 'tickers': tickers or self._extract_tickers_from_upload(upload),
#                 'summary': {
#                     'total': len(tickers) if tickers else self._count_tickers_in_upload(upload),
#                     'completed': len(tickers) if tickers else self._count_tickers_in_upload(upload),
#                     'failed': 0
#                 }
#             })
#
#         except Exception as e:
#             analysis.status = 'failed'
#             analysis.error_message = str(e)
#             analysis.completed_at = timezone.now()
#             analysis.save()
#             logger.error(f"Analysis {analysis.id} failed: {str(e)}")
#             return Response({'success': False, 'error': str(e)}, status=500)
#
#     def _run_mean_reversion_analysis(self, analysis, upload, tickers=None):
#         """Execute Mean-Reversion model"""
#         project_root = Path(settings.BASE_DIR).parent
#         script_path = project_root / 'data-analysis' / 'main_model_file_stable_2_extended_future_prediciton.py'
#
#         if not script_path.exists():
#             raise FileNotFoundError(f"Mean-Reversion script not found: {script_path}")
#
#         output_dir = Path(settings.MEDIA_ROOT) / 'analysis_results' / str(analysis.id)
#         output_dir.mkdir(parents=True, exist_ok=True)
#
#         cmd = [sys.executable, str(script_path), '--excel', upload.filename.path, '--out', str(output_dir)]
#         if tickers:
#             cmd += ['--tickers', ','.join(tickers)]
#
#         logger.info(f"Running Mean-Reversion analysis {analysis.id}: {' '.join(cmd)}")
#         proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(project_root), timeout=900)
#
#         if proc.returncode != 0:
#             raise RuntimeError(f"Mean-Reversion script failed: {proc.stderr}")
#
#         # Process results and store in MeanReversionResult model
#         self._store_mean_reversion_results(analysis, output_dir)
#
#     def _run_beta_forecasting_analysis(self, analysis, upload, tickers=None):
#         """Execute Beta-Forecasting model"""
#         project_root = Path(settings.BASE_DIR).parent
#         script_path = project_root / 'data-analysis' / 'bcoef_forecast_v_4_no_market.py'
#
#         if not script_path.exists():
#             raise FileNotFoundError(f"Beta-Forecasting script not found: {script_path}")
#
#         output_dir = Path(settings.MEDIA_ROOT) / 'analysis_results' / str(analysis.id)
#         output_dir.mkdir(parents=True, exist_ok=True)
#
#         cmd = [sys.executable, str(script_path), '--excel', upload.filename.path, '--out', str(output_dir)]
#         if tickers:
#             cmd += ['--tickers', ','.join(tickers)]
#
#         logger.info(f"Running Beta-Forecasting analysis {analysis.id}: {' '.join(cmd)}")
#         proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(project_root), timeout=900)
#
#         if proc.returncode != 0:
#             raise RuntimeError(f"Beta-Forecasting script failed: {proc.stderr}")
#
#         # Process results and store in BetaForecastResult model
#         self._store_beta_forecast_results(analysis, output_dir)
#
#     def _run_both_models_analysis(self, analysis, upload, tickers=None):
#         """Execute both models"""
#         self._run_mean_reversion_analysis(analysis, upload, tickers)
#         self._run_beta_forecasting_analysis(analysis, upload, tickers)
#
#     def _store_mean_reversion_results(self, analysis, output_dir):
#         """Store Mean-Reversion results in database"""
#         # Look for mean-reversion output files
#         result_files = list(output_dir.glob('*mean_reversion*.csv'))
#         if not result_files:
#             result_files = list(output_dir.glob('*mr_results*.csv'))
#
#         if not result_files:
#             logger.warning(f"No mean-reversion results found in {output_dir}")
#             return
#
#         latest_file = max(result_files, key=lambda p: p.stat().st_mtime)
#         df = pd.read_csv(latest_file)
#
#         # Store results (mock implementation - adapt based on actual output format)
#         for _, row in df.iterrows():
#             MeanReversionResult.objects.create(
#                 analysis_result=analysis,
#                 analysis_date=timezone.now().date(),
#                 ticker=row.get('ticker', ''),
#                 z_score_current=float(row.get('z_score_current', 0)),
#                 z_score_trend=float(row.get('z_score_trend', 0)),
#                 mean_reversion_probability=float(row.get('mean_reversion_probability', 0)),
#                 reversion_strength=row.get('reversion_strength', 'Moderate'),
#                 magnitude_prediction=float(row.get('magnitude_prediction', 0)),
#                 magnitude_lower_bound=float(row.get('magnitude_lower_bound', 0)),
#                 magnitude_upper_bound=float(row.get('magnitude_upper_bound', 0)),
#                 calibration_score=float(row.get('calibration_score', 0)),
#                 confidence_interval_90=[
#                     float(row.get('ci_90_lower', 0)),
#                     float(row.get('ci_90_upper', 0))
#                 ],
#                 confidence_interval_95=[
#                     float(row.get('ci_95_lower', 0)),
#                     float(row.get('ci_95_upper', 0))
#                 ],
#                 historical_accuracy=float(row.get('historical_accuracy', 0)),
#                 lookback_period_days=int(row.get('lookback_period_days', 252)),
#                 recommendation=row.get('recommendation', 'HOLD'),
#                 recommendation_confidence=float(row.get('recommendation_confidence', 0))
#             )
#
#     def _store_beta_forecast_results(self, analysis, output_dir):
#         """Store Beta-Forecast results in database"""
#         # Look for beta forecast output files
#         result_files = list(output_dir.glob('*beta_forecast*.csv'))
#         if not result_files:
#             result_files = list(output_dir.glob('*forecast*.csv'))
#
#         if not result_files:
#             logger.warning(f"No beta forecast results found in {output_dir}")
#             return
#
#         latest_file = max(result_files, key=lambda p: p.stat().st_mtime)
#         df = pd.read_csv(latest_file)
#
#         # Store results (adapt based on actual output format)
#         for _, row in df.iterrows():
#             BetaForecastResult.objects.create(
#                 analysis_result=analysis,
#                 forecast_date=pd.to_datetime(row.get('forecast_date', timezone.now().date())).date(),
#                 ticker=row.get('ticker', ''),
#                 beta_pred=float(row.get('beta_pred', 0)),
#                 beta_pred_ema=float(row.get('beta_pred_ema', 0)),
#                 lo=float(row.get('lo', 0)),
#                 hi=float(row.get('hi', 0)),
#                 r2_ols=float(row.get('r2_ols', 0)),
#                 p_value=float(row.get('p_value', 0)),
#                 confidence_level=row.get('confidence_level', 'Medium (p≤5%)'),
#                 confidence_tier=row.get('confidence_tier', 'Tier-2'),
#                 delta_beta_20d=float(row.get('delta_beta_20d', 0)),
#                 conf_20d=float(row.get('conf_20d', 0)),
#                 agree_adjacent=bool(row.get('agree_adjacent', False)),
#                 term_unstable=bool(row.get('term_unstable', False)),
#                 action=row.get('action', 'hold'),
#                 hold_reason=row.get('hold_reason', '')
#             )
#
#     def _extract_tickers_from_upload(self, upload):
#         """Extract ticker list from uploaded file"""
#         # Mock implementation - adapt based on actual file structure
#         return ['AAPL', 'MSFT', 'GOOGL']
#
#     def _count_tickers_in_upload(self, upload):
#         """Count tickers in uploaded file"""
#         return len(self._extract_tickers_from_upload(upload))
#
#
# class UnifiedAnalysisResultView(APIView):
#     """Get unified analysis results for a specific ticker and model"""
#     permission_classes = [IsAuthenticated]
#
#     def get(self, request, ticker, model_type):
#         """Get analysis result for specific ticker and model type"""
#         try:
#             if model_type == 'mean-reversion':
#                 results = MeanReversionResult.objects.filter(
#                     analysis_result__user=request.user,
#                     ticker=ticker.upper()
#                 ).order_by('-analysis_date').first()
#
#                 if not results:
#                     return Response({'error': 'No mean-reversion results found'}, status=404)
#
#                 serializer = MeanReversionResultSerializer(results)
#                 return Response({
#                     'analysis_id': str(results.analysis_result.id),
#                     'model_type': 'mean-reversion',
#                     'ticker': ticker.upper(),
#                     'name': f"{ticker.upper()} Inc.",  # Mock - could be enhanced with company name lookup
#                     'analysis_date': results.analysis_date,
#                     'recommendation': results.recommendation,
#                     'confidence': results.recommendation_confidence,
#                     'model_data': serializer.data
#                 })
#
#             elif model_type == 'beta-forecasting':
#                 results = BetaForecastResult.objects.filter(
#                     analysis_result__user=request.user,
#                     ticker=ticker.upper()
#                 ).order_by('-forecast_date').first()
#
#                 if not results:
#                     return Response({'error': 'No beta forecast results found'}, status=404)
#
#                 serializer = BetaForecastResultSerializer(results)
#
#                 # Map action to recommendation
#                 action_to_recommendation = {
#                     'chase': 'BUY',
#                     'fade': 'SELL',
#                     'hold': 'HOLD'
#                 }
#
#                 return Response({
#                     'analysis_id': str(results.analysis_result.id),
#                     'model_type': 'beta-forecasting',
#                     'ticker': ticker.upper(),
#                     'name': f"{ticker.upper()} Inc.",  # Mock - could be enhanced
#                     'analysis_date': results.forecast_date,
#                     'recommendation': action_to_recommendation.get(results.action, 'HOLD'),
#                     'confidence': results.conf_20d,
#                     'model_data': serializer.data
#                 })
#
#             else:
#                 return Response({'error': 'Invalid model type'}, status=400)
#
#         except Exception as e:
#             logger.error(f"Error retrieving unified analysis result: {str(e)}")
#             return Response({'error': str(e)}, status=500)
#
#
# class ModelComparisonView(APIView):
#     """Compare both models for a specific ticker"""
#     permission_classes = [IsAuthenticated]
#
#     def get(self, request, ticker):
#         """Compare both Mean-Reversion and Beta-Forecasting for a ticker"""
#         try:
#             # Get both results
#             mr_view = UnifiedAnalysisResultView()
#             mr_request = request._request if hasattr(request, '_request') else request
#             mr_response = mr_view.get(mr_request, ticker, 'mean-reversion')
#
#             beta_response = mr_view.get(mr_request, ticker, 'beta-forecasting')
#
#             if mr_response.status_code != 200 or beta_response.status_code != 200:
#                 return Response({'error': 'Results not found for both models'}, status=404)
#
#             mr_data = mr_response.data
#             beta_data = beta_response.data
#
#             # Compare recommendations
#             mr_recommendation = mr_data['recommendation']
#             beta_recommendation = beta_data['recommendation']
#
#             if mr_recommendation == beta_recommendation:
#                 agreement = "Strong"
#                 primary_recommendation = mr_recommendation
#                 confidence_score = max(mr_data['confidence'], beta_data['confidence'])
#             else:
#                 agreement = "Conflicting"
#                 # Use beta model as primary when conflicting (higher confidence generally)
#                 if beta_data['confidence'] > mr_data['confidence']:
#                     primary_recommendation = beta_recommendation
#                     confidence_score = beta_data['confidence']
#                 else:
#                     primary_recommendation = mr_recommendation
#                     confidence_score = mr_data['confidence']
#
#             return Response({
#                 'mean_reversion': mr_data,
#                 'beta_forecasting': beta_data,
#                 'comparison': {
#                     'agreement': agreement,
#                     'primary_recommendation': primary_recommendation,
#                     'confidence_score': confidence_score
#                 }
#             })
#
#         except Exception as e:
#             logger.error(f"Error in model comparison: {str(e)}")
#             return Response({'error': str(e)}, status=500)
#
#
# # ================= Beta Coefficient Model Output API Views ================= #
#
# class BetaRealizedListView(APIView):
#     """API endpoint for beta realized data from betas_20d.csv"""
#
#     def get(self, request):
#         from .models import BetaRealized
#         from .serializers import BetaRealizedSerializer
#
#         ticker = request.query_params.get('ticker')
#         start_date = request.query_params.get('start_date')
#         end_date = request.query_params.get('end_date')
#
#         queryset = BetaRealized.objects.all()
#
#         if ticker:
#             queryset = queryset.filter(ticker=ticker)
#         if start_date:
#             queryset = queryset.filter(date__gte=start_date)
#         if end_date:
#             queryset = queryset.filter(date__lte=end_date)
#
#         queryset = queryset.order_by('-date', 'ticker')[:1000]  # Limit results
#
#         serializer = BetaRealizedSerializer(queryset, many=True)
#         return Response({
#             'count': queryset.count(),
#             'results': serializer.data
#         })
#
#
# class ForecastEvaluationListView(APIView):
#     """API endpoint for forecast evaluation data from forecast_eval_20d.csv"""
#
#     def get(self, request):
#         from .models import ForecastEvaluation
#         from .serializers import ForecastEvaluationSerializer
#
#         ticker = request.query_params.get('ticker')
#         start_date = request.query_params.get('start_date')
#         end_date = request.query_params.get('end_date')
#         min_significance = request.query_params.get('min_significance', 0.7)
#
#         queryset = ForecastEvaluation.objects.all()
#
#         if ticker:
#             queryset = queryset.filter(ticker=ticker)
#         if start_date:
#             queryset = queryset.filter(date__gte=start_date)
#         if end_date:
#             queryset = queryset.filter(date__lte=end_date)
#
#         queryset = queryset.filter(significance_score__gte=float(min_significance))
#         queryset = queryset.order_by('-date', 'ticker')[:1000]
#
#         serializer = ForecastEvaluationSerializer(queryset, many=True)
#         return Response({
#             'count': queryset.count(),
#             'results': serializer.data
#         })
#
#
# class BetaCoefficientSummaryView(APIView):
#     """Summary statistics for beta coefficient predictions"""
#
#     def get(self, request):
#         from .models import ForecastEvaluation
#         from django.db.models import Avg, Count, Max
#
#         # Get summary by ticker
#         summary_data = []
#
#         for ticker_data in ForecastEvaluation.objects.values('ticker').annotate(
#             forecast_count=Count('id'),
#             avg_r2=Avg('r2_ols'),
#             latest_date=Max('date')
#         ).order_by('-forecast_count'):
#
#             ticker = ticker_data['ticker']
#             latest_record = ForecastEvaluation.objects.filter(
#                 ticker=ticker,
#                 date=ticker_data['latest_date']
#             ).first()
#
#             if latest_record:
#                 # Calculate prediction accuracy (simplified)
#                 prediction_error = abs(latest_record.beta_pred - latest_record.beta_true) if latest_record.beta_true else None
#                 accuracy = 1 - min(prediction_error, 1.0) if prediction_error is not None else None
#
#                 confidence_level = 'High' if latest_record.significance_score > 0.8 else 'Medium' if latest_record.significance_score > 0.6 else 'Low'
#
#                 summary_data.append({
#                     'ticker': ticker,
#                     'latest_date': latest_record.date,
#                     'latest_beta_pred': latest_record.beta_pred,
#                     'latest_beta_true': latest_record.beta_true,
#                     'avg_r2_ols': ticker_data['avg_r2'],
#                     'prediction_accuracy': accuracy,
#                     'forecast_count': ticker_data['forecast_count'],
#                     'confidence_level': confidence_level
#                 })
#
#         return Response({
#             'summary': summary_data[:50]  # Top 50 tickers
#         })
#
#
# class BetaCoefficientTimeSeriesView(APIView):
#     """Time series data for a specific ticker's beta coefficient predictions"""
#
#     def get(self, request, ticker):
#         from .models import ForecastEvaluation
#
#         queryset = ForecastEvaluation.objects.filter(
#             ticker=ticker
#         ).order_by('date')
#
#         dates = []
#         beta_pred = []
#         beta_true = []
#         confidence_bands = []
#
#         for record in queryset:
#             dates.append(record.date)
#             beta_pred.append(record.beta_pred)
#             beta_true.append(record.beta_true)
#
#             # Calculate confidence bands using the band value
#             confidence_bands.append({
#                 'lower': record.beta_pred - record.band,
#                 'upper': record.beta_pred + record.band
#             })
#
#         return Response({
#             'ticker': ticker,
#             'dates': dates,
#             'beta_pred': beta_pred,
#             'beta_true': beta_true,
#             'confidence_bands': confidence_bands
#         })
#
#
# class ImportBetaDataView(APIView):
#     """Import beta coefficient data from CSV files"""
#     permission_classes = [IsAuthenticated]
#
#     def post(self, request):
#         from .models import BetaRealized, ForecastEvaluation
#         import csv
#         from django.conf import settings
#
#         try:
#             # Import betas_20d.csv
#             betas_file = os.path.join(settings.BASE_DIR.parent, 'outputs', 'betas_20d.csv')
#             if os.path.exists(betas_file):
#                 with open(betas_file, 'r') as f:
#                     reader = csv.DictReader(f)
#                     beta_objects = []
#
#                     for row in reader:
#                         if row['Date'] and row['ticker']:  # Skip empty rows
#                             try:
#                                 beta_obj = BetaRealized(
#                                     date=datetime.strptime(row['Date'], '%m/%d/%Y').date(),
#                                     ticker=row['ticker'],
#                                     beta_realised=float(row['beta_realised']) if row['beta_realised'] else None,
#                                     r2_ols_x=float(row['r2_ols_x']) if row['r2_ols_x'] else None,
#                                     r2_ols_y=float(row['r2_ols_y']) if row['r2_ols_y'] else None,
#                                     p_value=float(row['p_value']) if row['p_value'] else None,
#                                     significance_score=float(row['significance_score']) if row['significance_score'] else None,
#                                     beta_pred=float(row['beta_pred']) if row['beta_pred'] else None,
#                                     beta_true=float(row['beta_true']) if row['beta_true'] else None,
#                                     band=float(row['band']) if row['band'] else None,
#                                     lo=float(row['lo']) if row['lo'] else None,
#                                     hi=float(row['hi']) if row['hi'] else None,
#                                 )
#                                 beta_objects.append(beta_obj)
#                             except (ValueError, KeyError) as e:
#                                 continue  # Skip invalid rows
#
#                     # Bulk create with ignore conflicts
#                     BetaRealized.objects.bulk_create(beta_objects, ignore_conflicts=True, batch_size=1000)
#
#             # Import forecast_eval_20d.csv
#             forecast_file = os.path.join(settings.BASE_DIR.parent, 'outputs', 'forecast_eval_20d.csv')
#             if os.path.exists(forecast_file):
#                 with open(forecast_file, 'r') as f:
#                     reader = csv.DictReader(f)
#                     forecast_objects = []
#
#                     for row in reader:
#                         try:
#                             forecast_obj = ForecastEvaluation(
#                                 date=datetime.strptime(row['Date'], '%m/%d/%Y').date(),
#                                 ticker=row['ticker'],
#                                 r2_ols=float(row['r2_ols']),
#                                 p_value=float(row['p_value']),
#                                 significance_score=float(row['significance_score']),
#                                 beta_pred=float(row['beta_pred']),
#                                 beta_true=float(row['beta_true']),
#                                 band=float(row['band']),
#                             )
#                             forecast_objects.append(forecast_obj)
#                         except (ValueError, KeyError) as e:
#                             continue
#
#                     ForecastEvaluation.objects.bulk_create(forecast_objects, ignore_conflicts=True, batch_size=1000)
#
#             return Response({
#                 'message': 'Beta coefficient data imported successfully',
#                 'beta_records': BetaRealized.objects.count(),
#                 'forecast_records': ForecastEvaluation.objects.count()
#             })
#
#         except Exception as e:
#             logger.error(f"Error importing beta data: {str(e)}")
#             return Response({'error': str(e)}, status=500)


# Pooled Model Output API Views
from .serializers import (
    AnalysisRunSerializer, AnalysisRunDetailSerializer, DashboardSummarySerializer,
    StockPredictionSerializer, StockPerformanceMetricsSerializer, OutOfSamplePredictionSerializer,
    ModelCoefficientSerializer, FoldStatisticsSerializer, StockAnalysisSerializer,
    TimeSeriesAnalysisSerializer, PredictionDistributionSerializer
)
from .models import AnalysisRun, ModelCoefficient, StockPrediction, StockPerformanceMetrics, OutOfSamplePrediction, FoldStatistics
from django.db.models import Q, Count, Avg, Max, Min
from rest_framework import generics, viewsets
from rest_framework.decorators import action
from django.utils.dateparse import parse_date


class AnalysisRunViewSet(viewsets.ModelViewSet):
    """ViewSet for managing analysis runs"""
    serializer_class = AnalysisRunSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        return AnalysisRun.objects.filter(user=self.request.user).order_by('-created_at')
    
    def get_serializer_class(self):
        if self.action == 'retrieve':
            return AnalysisRunDetailSerializer
        return AnalysisRunSerializer
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
    
    @action(detail=True, methods=['get'])
    def predictions(self, request, pk=None):
        """Get all predictions for this analysis run"""
        analysis_run = self.get_object()
        predictions = analysis_run.predictions.all()
        
        # Filter by ticker if provided
        ticker = request.query_params.get('ticker')
        if ticker:
            predictions = predictions.filter(ticker__icontains=ticker)
        
        # Pagination
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 50))
        start = (page - 1) * page_size
        end = start + page_size
        
        paginated_predictions = predictions[start:end]
        serializer = StockPredictionSerializer(paginated_predictions, many=True)
        
        return Response({
            'results': serializer.data,
            'total': predictions.count(),
            'page': page,
            'page_size': page_size
        })
    
    @action(detail=True, methods=['get'])
    def performance(self, request, pk=None):
        """Get performance metrics for this analysis run"""
        analysis_run = self.get_object()
        metrics = analysis_run.stock_metrics.all()
        
        # Filter by ticker if provided
        ticker = request.query_params.get('ticker')
        if ticker:
            metrics = metrics.filter(ticker__icontains=ticker)
        
        serializer = StockPerformanceMetricsSerializer(metrics, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def coefficients(self, request, pk=None):
        """Get model coefficients for this analysis run"""
        analysis_run = self.get_object()
        coefficients = analysis_run.coefficients.all().order_by('-coefficient_value')
        serializer = ModelCoefficientSerializer(coefficients, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def summary(self, request, pk=None):
        """Get comprehensive summary for this analysis run"""
        analysis_run = self.get_object()
        
        # Basic stats
        predictions_count = analysis_run.predictions.count()
        stocks_count = analysis_run.predictions.values('ticker').distinct().count()
        
        # Performance aggregates
        avg_metrics = analysis_run.stock_metrics.aggregate(
            avg_r2=Avg('r2_oos'),
            avg_mae=Avg('mae_oos'),
            avg_dir_acc=Avg('dir_acc_oos')
        )
        
        # Top and bottom performers
        top_stocks = analysis_run.stock_metrics.order_by('-dir_acc_oos')[:5]
        bottom_stocks = analysis_run.stock_metrics.order_by('dir_acc_oos')[:5]
        
        return Response({
            'run_info': AnalysisRunSerializer(analysis_run).data,
            'statistics': {
                'total_predictions': predictions_count,
                'unique_stocks': stocks_count,
                'avg_r2_oos': avg_metrics['avg_r2'],
                'avg_mae_oos': avg_metrics['avg_mae'],
                'avg_directional_accuracy': avg_metrics['avg_dir_acc']
            },
            'top_performers': StockPerformanceMetricsSerializer(top_stocks, many=True).data,
            'worst_performers': StockPerformanceMetricsSerializer(bottom_stocks, many=True).data
        })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_summary(request):
    """Get dashboard summary data for the authenticated user"""
    user_runs = AnalysisRun.objects.filter(user=request.user)
    
    # Basic counts
    total_runs = user_runs.count()
    latest_run = user_runs.order_by('-created_at').first()
    
    if total_runs == 0:
        return Response({
            'total_runs': 0,
            'latest_run': None,
            'avg_directional_accuracy': 0,
            'avg_r2': 0,
            'total_predictions': 0,
            'unique_stocks': 0,
            'recent_activity': []
        })
    
    # Aggregate metrics across all user runs
    completed_runs = user_runs.filter(status='completed')
    if completed_runs.exists():
        avg_metrics = completed_runs.aggregate(
            avg_dir_acc=Avg('directional_accuracy'),
            avg_r2=Avg('r2_global')
        )
    else:
        avg_metrics = {'avg_dir_acc': 0, 'avg_r2': 0}
    
    # Total predictions and stocks
    total_predictions = sum(run.predictions.count() for run in user_runs)
    unique_stocks = StockPrediction.objects.filter(
        analysis_run__user=request.user
    ).values('ticker').distinct().count()
    
    # Recent activity
    recent_runs = user_runs.order_by('-created_at')[:5]
    
    serializer = DashboardSummarySerializer({
        'total_runs': total_runs,
        'latest_run': latest_run,
        'avg_directional_accuracy': avg_metrics['avg_dir_acc'] or 0,
        'avg_r2': avg_metrics['avg_r2'] or 0,
        'total_predictions': total_predictions,
        'unique_stocks': unique_stocks,
        'recent_activity': recent_runs
    })
    
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def stock_analysis(request, ticker):
    """Get comprehensive analysis for a specific stock across all user's runs"""
    user_runs = AnalysisRun.objects.filter(user=request.user)
    
    # Get all predictions for this ticker
    predictions = StockPrediction.objects.filter(
        analysis_run__in=user_runs,
        ticker__iexact=ticker
    ).order_by('-prediction_date')
    
    if not predictions.exists():
        return Response({'error': 'No data found for this ticker'}, status=404)
    
    # Get performance metrics
    performance_metrics = StockPerformanceMetrics.objects.filter(
        analysis_run__in=user_runs,
        ticker__iexact=ticker
    )
    
    # Calculate aggregates
    total_predictions = predictions.count()
    avg_prediction = predictions.aggregate(avg=Avg('final_prediction'))['avg']
    
    best_performance = performance_metrics.aggregate(best_r2=Max('r2_oos'))['best_r2'] or 0
    avg_performance = performance_metrics.aggregate(avg_acc=Avg('dir_acc_oos'))['avg_acc'] or 0
    
    latest_prediction = predictions.first()
    recent_predictions = predictions[:10]
    
    response_data = {
        'ticker': ticker.upper(),
        'total_predictions': total_predictions,
        'avg_prediction': avg_prediction,
        'avg_performance': avg_performance,
        'best_r2': best_performance,
        'latest_prediction': latest_prediction.final_prediction if latest_prediction else None,
        'latest_date': latest_prediction.prediction_date if latest_prediction else None,
        'recent_predictions': recent_predictions
    }
    
    serializer = StockAnalysisSerializer(response_data)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def time_series_analysis(request, run_id, ticker):
    """Get time series data for a specific stock in a specific run"""
    try:
        analysis_run = AnalysisRun.objects.get(id=run_id, user=request.user)
    except AnalysisRun.DoesNotExist:
        return Response({'error': 'Analysis run not found'}, status=404)
    
    # Get out-of-sample predictions
    oos_predictions = OutOfSamplePrediction.objects.filter(
        analysis_run=analysis_run,
        ticker__iexact=ticker
    ).order_by('date')
    
    if not oos_predictions.exists():
        return Response({'error': 'No time series data found for this stock'}, status=404)
    
    # Prepare time series data
    dates = [pred.date for pred in oos_predictions]
    predictions = [pred.y_pred for pred in oos_predictions]
    actuals = [pred.y_actual for pred in oos_predictions]
    errors = [pred.prediction_error for pred in oos_predictions]
    
    # Calculate cumulative R²
    cumulative_r2 = []
    for i in range(1, len(predictions) + 1):
        subset_preds = predictions[:i]
        subset_actuals = [a for a in actuals[:i] if a is not None]
        if len(subset_actuals) >= 2:
            # Calculate R² for this subset
            actual_vals = np.array(subset_actuals)
            pred_vals = np.array(subset_preds[:len(subset_actuals)])
            
            ss_tot = np.sum((actual_vals - np.mean(actual_vals)) ** 2)
            ss_res = np.sum((actual_vals - pred_vals) ** 2)
            r2 = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
            cumulative_r2.append(r2)
        else:
            cumulative_r2.append(0)
    
    response_data = {
        'dates': dates,
        'predictions': predictions,
        'actuals': actuals,
        'errors': errors,
        'cumulative_r2': cumulative_r2
    }
    
    serializer = TimeSeriesAnalysisSerializer(response_data)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def prediction_distribution(request, run_id):
    """Get distribution analysis of predictions for a specific run"""
    try:
        analysis_run = AnalysisRun.objects.get(id=run_id, user=request.user)
    except AnalysisRun.DoesNotExist:
        return Response({'error': 'Analysis run not found'}, status=404)
    
    predictions = analysis_run.predictions.values_list('final_prediction', flat=True)
    
    if not predictions:
        return Response({'error': 'No predictions found'}, status=404)
    
    pred_array = np.array(list(predictions))
    
    # Create histogram
    hist, bin_edges = np.histogram(pred_array, bins=30)
    bins = bin_edges[:-1].tolist()  # Use left edges of bins
    counts = hist.tolist()
    
    # Calculate percentiles
    percentiles = {
        '5th': np.percentile(pred_array, 5),
        '25th': np.percentile(pred_array, 25),
        '50th': np.percentile(pred_array, 50),
        '75th': np.percentile(pred_array, 75),
        '95th': np.percentile(pred_array, 95)
    }
    
    # Calculate statistics
    statistics = {
        'mean': np.mean(pred_array),
        'std': np.std(pred_array),
        'min': np.min(pred_array),
        'max': np.max(pred_array),
        'skewness': float(pd.Series(pred_array).skew()),
        'kurtosis': float(pd.Series(pred_array).kurtosis())
    }
    
    response_data = {
        'bins': bins,
        'counts': counts,
        'percentiles': percentiles,
        'statistics': statistics
    }
    
    serializer = PredictionDistributionSerializer(response_data)
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def save_analysis_results(request):
    """Save pooled model analysis results to database"""
    try:
        data = request.data
        
        # Create analysis run record
        analysis_run = AnalysisRun.objects.create(
            user=request.user,
            run_name=data.get('run_name', f"Analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}"),
            model_type=data.get('model_type', 'pooled_enet'),
            horizon_days=data.get('horizon_days', 10),
            status='completed',
            completed_at=timezone.now(),
            # Overall metrics from oos_metrics.csv
            mae=data.get('mae'),
            rmse=data.get('rmse'),
            directional_accuracy=data.get('directional_accuracy'),
            sample_size=data.get('sample_size'),
            r2_global=data.get('r2_global'),
            r2_fold_mean=data.get('r2_fold_mean'),
            r2_fold_weighted=data.get('r2_fold_weighted'),
            mae_ratio_global=data.get('mae_ratio_global'),
            mae_ratio_fold_mean=data.get('mae_ratio_fold_mean'),
            mae_ratio_fold_weighted=data.get('mae_ratio_fold_weighted')
        )
        
        # Save model coefficients
        if 'coefficients' in data:
            coefficient_objects = []
            for coef_data in data['coefficients']:
                coefficient_objects.append(ModelCoefficient(
                    analysis_run=analysis_run,
                    feature_name=coef_data['feature_name'],
                    coefficient_value=coef_data['coefficient_value']
                ))
            ModelCoefficient.objects.bulk_create(coefficient_objects)
        
        # Save predictions
        if 'predictions' in data:
            prediction_objects = []
            for pred_data in data['predictions']:
                prediction_objects.append(StockPrediction(
                    analysis_run=analysis_run,
                    ticker=pred_data['ticker'],
                    prediction_date=parse_date(pred_data['prediction_date']),
                    final_prediction=pred_data['final_prediction'],
                    **{k: v for k, v in pred_data.items() if k not in ['ticker', 'prediction_date', 'final_prediction']}
                ))
            StockPrediction.objects.bulk_create(prediction_objects, batch_size=1000)
        
        # Save performance metrics
        if 'performance_metrics' in data:
            metric_objects = []
            for metric_data in data['performance_metrics']:
                metric_objects.append(StockPerformanceMetrics(
                    analysis_run=analysis_run,
                    ticker=metric_data['ticker'],
                    r2_oos=metric_data['r2_oos'],
                    rmse_oos=metric_data['rmse_oos'],
                    mae_oos=metric_data['mae_oos'],
                    mase_oos=metric_data['mase_oos'],
                    dir_acc_oos=metric_data['dir_acc_oos'],
                    pred_std_oos=metric_data['pred_std_oos'],
                    n_obs_oos=metric_data['n_obs_oos']
                ))
            StockPerformanceMetrics.objects.bulk_create(metric_objects, batch_size=1000)
        
        # Save out-of-sample predictions
        if 'oos_predictions' in data:
            oos_objects = []
            for oos_data in data['oos_predictions']:
                oos_objects.append(OutOfSamplePrediction(
                    analysis_run=analysis_run,
                    ticker=oos_data['ticker'],
                    date=parse_date(oos_data['date']),
                    y_pred=oos_data['y_pred'],
                    y_actual=oos_data.get('y_actual'),
                    prediction_error=oos_data.get('prediction_error'),
                    abs_error=oos_data.get('abs_error'),
                    squared_error=oos_data.get('squared_error'),
                    fold_id=oos_data.get('fold_id')
                ))
            OutOfSamplePrediction.objects.bulk_create(oos_objects, batch_size=1000)
        
        # Save fold statistics
        if 'fold_statistics' in data:
            fold_objects = []
            for fold_data in data['fold_statistics']:
                fold_objects.append(FoldStatistics(
                    analysis_run=analysis_run,
                    fold_id=fold_data['fold_id'],
                    fold_r2=fold_data.get('fold_r2'),
                    fold_mae=fold_data.get('fold_mae'),
                    fold_rmse=fold_data.get('fold_rmse'),
                    fold_directional_acc=fold_data.get('fold_directional_acc'),
                    fold_n_obs=fold_data.get('fold_n_obs'),
                    train_start_date=parse_date(fold_data['train_start_date']) if fold_data.get('train_start_date') else None,
                    train_end_date=parse_date(fold_data['train_end_date']) if fold_data.get('train_end_date') else None,
                    val_start_date=parse_date(fold_data['val_start_date']) if fold_data.get('val_start_date') else None,
                    val_end_date=parse_date(fold_data['val_end_date']) if fold_data.get('val_end_date') else None
                ))
            FoldStatistics.objects.bulk_create(fold_objects, batch_size=1000)
        
        return Response({
            'message': 'Analysis results saved successfully',
            'analysis_run_id': analysis_run.id,
            'run_name': analysis_run.run_name
        }, status=201)
        
    except Exception as e:
        logger.error(f"Error saving analysis results: {str(e)}")
        return Response({'error': str(e)}, status=500)