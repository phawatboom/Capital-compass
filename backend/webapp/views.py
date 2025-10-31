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
import threading



from pathlib import Path
import logging # <-- Add logging

from django.db.models import Avg
from django.shortcuts import get_object_or_404

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
from .models import Stock, StockData, CSVUploadRecord, UserProfile, FactorSharedStats, StockFactorResult, StockPerformanceMetrics
from datetime import date, datetime
from django.contrib.auth import update_session_auth_hash
from django.shortcuts import get_object_or_404
from rest_framework.decorators import parser_classes
from .model_runner import run_analysis_from_web


def _model_field_names(model_cls):
    # concrete, non-relational field names
    return {f.name for f in model_cls._meta.get_fields() if hasattr(f, "attname") and not f.many_to_many and not f.one_to_many}

# ---- Minimal progress tracking on disk ----
PROGRESS_DIR = Path(settings.MEDIA_ROOT) / "upload_progress"
PROGRESS_DIR.mkdir(parents=True, exist_ok=True)

def _progress_path(upload_id: int) -> Path:
    return PROGRESS_DIR / f"{upload_id}.json"

def _write_progress(upload_id: int, payload: dict) -> None:
    p = _progress_path(upload_id)
    tmp = p.with_suffix(".tmp")
    payload = {**payload, "updated_at": timezone.now().isoformat()}
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, p)

def _read_progress(upload_id: int) -> dict | None:
    p = _progress_path(upload_id)
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

@api_view(["GET"])
def factor_stats_summary(request, pk: int):
    obj = get_object_or_404(FactorSharedStats, pk=pk)
    return Response(FactorSharedStatsSerializer(obj).data)

@api_view(["GET"])
def factor_stats_latest_summary(request):
    horizon = int(request.GET.get("horizon", 5))
    obj = FactorSharedStats.objects.filter(horizon_days=horizon).order_by("-created_at").first()
    if not obj:
        return Response({"detail": "No run found for this horizon"}, status=404)
    return Response(FactorSharedStatsSerializer(obj).data)

@api_view(["GET"])
def factor_stats_oos_table(request, pk: int):
    order = request.GET.get("order", "-r2_oos")
    # min_n = int(request.GET.get("min_n", 1))
    allowed = {"r2_oos","rmse_oos","mae_oos","mase_oos","diracc_oos","predstd_oos","n_oos"}

    qs = StockOOSMetric.objects
    if order.lstrip("-") in allowed:
        qs = qs.order_by(order)
    return Response(list(qs.values(
        "ticker","r2_oos","rmse_oos","mae_oos","mase_oos",
        "diracc_oos","predstd_oos","n_oos"
    )))

from .serializers import (
    CSVUploadSerializer,
    StockSerializer,
    StockDataSerializer,
    CSVUploadRecordSerializer,
    UserProfileSerializer,
    PasswordChangeSerializer,
    # Dual-model architecture serializers
    UnifiedAnalysisResultSerializer,
    ModelComparisonSerializer,
    AnalysisRequestSerializer,
    FactorSharedStatsSerializer,
    StockFactorResultSerializer, StockFactorTimeSeriesSerializer,
    StockPerformanceMetricsSerializer,
    StockOOSMetricSerializer
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
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        file_obj = request.data.get('file')
        if not file_obj:
            return Response({'error': 'No file was provided.'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = CSVUploadSerializer(data={'filename': file_obj})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        upload_record = serializer.save(user=request.user)
        upload_id = upload_record.id

        # Seed progress as queued so frontend can poll immediately
        try:
            _write_progress(upload_id, {
                "status": "processing",
                "stage": "Queued",
                "progress": 1,
                "filename": os.path.basename(upload_record.filename.name),
                "file_size": getattr(upload_record, "file_size", file_obj.size if hasattr(file_obj, "size") else None)
            })
        except Exception:
            pass

        # Kick off background processing (was previously inline here)
        threading.Thread(
            target=_process_upload_background,
            args=(upload_id,),
            daemon=True
        ).start()

        # Return fast with the id + status URL for polling
        return Response({
            'message': 'File received; processing has started.',
            'upload_id': upload_id,
            'status_url': f'/uploads/{upload_id}/status/'
        }, status=status.HTTP_201_CREATED)




def _process_upload_background(upload_id: int):
    """
    Minimal background processor:
      - Reuses existing Excel/CSV logic from FileUploadView
      - Updates a small JSON progress file for polling
    """
    try:
        upload_record = CSVUploadRecord.objects.get(pk=upload_id)
        file_path = upload_record.filename.path
        filename = os.path.basename(upload_record.filename.name)
        file_size = getattr(upload_record, "file_size", None)

        _write_progress(upload_id, {
            "status": "processing",
            "stage": "Validating file",
            "progress": 3,
            "filename": filename,
            "file_size": file_size,
        })

        # ---- Excel branch (copied from your FileUploadView with tiny tweaks) ----
        if file_path.endswith(".xlsx"):
            _write_progress(upload_id, {
                "status": "processing", "stage": "Reading Excel", "progress": 8
            })

            with pd.ExcelFile(file_path) as xls:
                if "Returns" not in xls.sheet_names:
                    raise ValueError("No 'Returns' sheet found in Excel file.")

                df = pd.read_excel(xls, sheet_name="Returns", header=None)

                # Detect header row containing "Date"
                header_row = None
                for i in range(min(50, len(df))):
                    if df.iloc[i].astype(str).str.lower().eq("date").any():
                        header_row = i
                        break
                if header_row is None:
                    raise ValueError("No header row containing 'Date' found in sheet.")

                cols = df.iloc[header_row].astype(str).str.strip().tolist()
                data_df = df.iloc[header_row + 1:].copy()
                data_df.columns = cols
                data_df = data_df.loc[:, ~(data_df.isna().all())]

                date_col = next((c for c in data_df.columns if str(c).strip().lower() == "date"), None)
                if not date_col:
                    raise ValueError("No 'Date' column found in sheet.")
                if date_col != "Date":
                    data_df = data_df.rename(columns={date_col: "Date"})

                _write_progress(upload_id, {
                    "status": "processing", "stage": "Parsing dates", "progress": 12
                })

                data_df["Date"] = pd.to_datetime(data_df["Date"], errors="coerce")
                data_df = data_df.dropna(subset=["Date"])

                data_type = "return"
                stock_names = [c for c in data_df.columns if c != "Date"]
                if not stock_names:
                    raise ValueError("No stock columns found in sheet.")

                _write_progress(upload_id, {
                    "status": "processing",
                    "stage": "Preparing symbols",
                    "progress": 18,
                    "tickers": len(stock_names),
                    "rows_total": int(len(data_df))
                })

                stocks_map = {name.strip(): Stock.objects.get_or_create(name=name.strip())[0]
                              for name in stock_names}

                # Collect datapoints
                data_to_process = []
                # progress in chunks
                total_rows = len(data_df)
                chunk_size = max(1000, total_rows // 20 or 1)
                rows_done = 0

                for start in range(0, total_rows, chunk_size):
                    end = min(start + chunk_size, total_rows)
                    block = data_df.iloc[start:end]
                    for _, row in block.iterrows():
                        d = row["Date"].date()
                        for sn in stock_names:
                            v = row[sn]
                            if pd.isna(v):
                                continue
                            try:
                                v = float(v)
                            except Exception:
                                continue
                            data_to_process.append({
                                "stock": stocks_map[sn],
                                "date": d,
                                "data_type": data_type,
                                "value": v,
                            })

                    # Upsert for this block
                    if data_to_process:
                        existing = StockData.objects.filter(
                            stock__in=[d["stock"] for d in data_to_process],
                            data_type=data_type,
                            date__in=[d["date"] for d in data_to_process]
                        ).values("stock_id", "date", "data_type", "id")
                        idx = {(e["stock_id"], e["date"], e["data_type"]): e["id"] for e in existing}

                        to_create, to_update = [], []
                        for dp in data_to_process:
                            key = (dp["stock"].id, dp["date"], dp["data_type"])
                            if key in idx:
                                to_update.append(StockData(id=idx[key], **dp))
                            else:
                                to_create.append(StockData(**dp))

                        if to_create:
                            StockData.objects.bulk_create(to_create, batch_size=5000)
                        if to_update:
                            StockData.objects.bulk_update(to_update, ["value"], batch_size=5000)

                        data_to_process.clear()

                    rows_done = end
                    pct = 18 + int(72 * (rows_done / max(total_rows, 1)))  # 18..90
                    _write_progress(upload_id, {
                        "status": "processing",
                        "stage": "Writing to database",
                        "progress": min(pct, 90),
                        "rows_done": int(rows_done),
                        "rows_total": int(total_rows)
                    })

        # ---- CSV branch (reuses your process_data) ----
        elif file_path.endswith(".csv"):
            name_lower = upload_record.filename.name.lower()
            if "prices" in name_lower:
                data_type = "price"
            elif "equity" in name_lower or "bql_query" in name_lower:
                data_type = "equity"
            else:
                data_type = "return"

            _write_progress(upload_id, {
                "status": "processing", "stage": "Reading CSV", "progress": 10, "data_type": data_type
            })

            df = pd.read_csv(file_path, header=None)
            # Your existing helper will do the heavy lifting
            process_data(df, upload_record.filename, data_type, upload_record)

            _write_progress(upload_id, {
                "status": "processing", "stage": "Finalizing", "progress": 95
            })

        else:
            raise ValueError("Unsupported file format.")

        _write_progress(upload_id, {
            "status": "completed", "stage": "Complete", "progress": 100
        })

    except Exception as e:
        logger.exception("Upload processing failed")
        _write_progress(upload_id, {
            "status": "failed", "stage": "Error", "progress": 100, "error": str(e)
        })



@api_view(["GET"])
@permission_classes([IsAuthenticated])
def upload_status(request, pk: int):
    try:
        # ensure ownership
        CSVUploadRecord.objects.get(pk=pk, user=request.user)
    except CSVUploadRecord.DoesNotExist:
        return Response({"error": "Not found"}, status=404)

    prog = _read_progress(pk) or {}
    return Response(prog or {"status": "unknown"}, status=200)



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



# views.py  (replace factor_summary with this)
@api_view(["GET"])
def factor_summary(request):
    """
    Return per-ticker results for a specific FactorSharedStats:
      - ?shared_id=<int> has precedence
      - else ?horizon=<int> picks latest for that horizon
      - else falls back to latest created across all horizons
    """
    import math

    def safe_json(obj):
        if isinstance(obj, float):
            if math.isnan(obj) or math.isinf(obj):
                return None
            return obj
        if isinstance(obj, list):
            return [safe_json(x) for x in obj]
        if isinstance(obj, dict):
            return {k: safe_json(v) for k, v in obj.items()}
        return obj

    shared_id = request.GET.get("shared_id")
    horizon_q = request.GET.get("horizon")

    if shared_id:
        shared = get_object_or_404(FactorSharedStats, pk=int(shared_id))
    elif horizon_q:
        shared = (FactorSharedStats.objects
                  .filter(horizon_days=int(horizon_q))
                  .order_by("-created_at")
                  .first())
        if not shared:
            return Response({"summary": [], "shared_id": None, "horizon": int(horizon_q)})
    else:
        shared = FactorSharedStats.objects.latest("created_at")

    stock_results = (
        StockFactorResult.objects
        .filter(shared_stats=shared)
        .order_by("ticker", "-created_at")
        .distinct("ticker")
    )
    serializer = StockFactorResultSerializer(stock_results, many=True)
    cleaned = safe_json(serializer.data)

    return Response({
        "summary": cleaned,
        "shared_id": shared.id,
        "horizon": shared.horizon_days,
        "created_at": shared.created_at,
    })

from datetime import date as _date, datetime
from rest_framework.decorators import api_view
from rest_framework.response import Response
# views.py  (drop-in replacement)
from datetime import date as _date, datetime
from django.db.models import Q
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .serializers import StockFactorTimeSeriesSerializer
from .models import StockFactorResult, FactorSharedStats, ForecastEvaluation


@api_view(["GET"])
def beta_timeseries(request, ticker):
    # 0) Normalise and alias the ticker to avoid space/no-space mismatches
    raw = (ticker or "").strip().upper()
    aliases = {raw, raw.replace(" ", ""), raw.replace("/", "-"), raw.replace("/", ""), raw.replace(".", "")}

    # 1) Select StockFactorResult rows for this ticker and horizon context
    shared_id = request.GET.get("shared_id")
    horizon_q = request.GET.get("horizon")
    qs = StockFactorResult.objects.filter(Q(ticker__in=aliases) | Q(ticker__iexact=raw))

    if shared_id:
        qs = qs.filter(shared_stats_id=int(shared_id))
    elif horizon_q:
        qs = qs.filter(shared_stats__horizon_days=int(horizon_q))
    else:
        latest_shared = FactorSharedStats.objects.latest("created_at")
        qs = qs.filter(shared_stats=latest_shared)

    qs = qs.order_by("created_at")
    if not qs.exists():
        # Graceful empty series so the modal still opens
        return Response({"ticker": raw, "horizon": int(horizon_q or 5),
                         "dates": [], "beta_pred": [], "beta_true": [], "confidence_bands": []})

    # 2) Serialize prediction series from SFR
    data = StockFactorTimeSeriesSerializer(qs, many=True).data
    dates_raw = [row["created_at"] for row in data]
    preds = [row["b_coefficient"] for row in data]

    # 3) Normalise dates to pure date objects
    def _to_date(x):
        if isinstance(x, _date): return x
        if isinstance(x, str):
            try: return datetime.fromisoformat(x).date()
            except ValueError: return datetime.strptime(x[:10], "%Y-%m-%d").date()
        return x.date()

    dates_dt = [_to_date(d) for d in dates_raw]

    # 4) Optional truth join from ForecastEvaluation
    fe = (ForecastEvaluation.objects
          .filter(Q(ticker__in=aliases) | Q(ticker__iexact=raw), date__in=dates_dt)
          .values("date", "beta_true", "band"))
    fe_true = {r["date"]: r["beta_true"] for r in fe}
    fe_band = {r["date"]: r["band"] for r in fe}
    truths = [fe_true.get(d) for d in dates_dt]

    # 5) Confidence bands: use FE band when present, else small symmetric default
    confidence_bands = []
    for d, p in zip(dates_dt, preds):
        b = fe_band.get(d)
        if p is None:
            confidence_bands.append({"lower": None, "upper": None})
        elif b is not None:
            confidence_bands.append({"lower": p - b, "upper": p + b})
        else:
            confidence_bands.append({"lower": p - 0.02, "upper": p + 0.02})

    return Response({
        "ticker": raw,
        "horizon": data[0].get("horizon_days"),  # from SFR serializer
        "dates": [d.isoformat() for d in dates_dt],
        "beta_pred": preds,
        "beta_true": truths,
        "confidence_bands": confidence_bands,
    })


# 2. Authentication and Permissions
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
        # Parse model configuration safely from frontend POST
        config = {
            "horizon_days": int(request.data.get("horizon_days", 5)),
            "training_days": int(request.data.get("training_days", 756)),
            "testing_days": int(request.data.get("testing_days", 252)),
            "alpha": float(request.data.get("alpha", 0.003)),
            "l1_ratio": float(request.data.get("l1_ratio", 0.2)),
            "multi_period": bool(request.data.get("multi_period", False)),
        }

        result = run_analysis_from_web(
            upload_pk=pk,
            model_for_pred="enet",
            config=config,
        )

        if not result.get("ok"):
            raise RuntimeError(result.get("error", "Unknown error"))

        return Response(result, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"ok": False, "error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

# Pooled Model Output API Views
from .serializers import (
    AnalysisRunSerializer, AnalysisRunDetailSerializer, DashboardSummarySerializer,
    StockPredictionSerializer, StockPerformanceMetricsSerializer, OutOfSamplePredictionSerializer,
    ModelCoefficientSerializer, FoldStatisticsSerializer, StockAnalysisSerializer,
    TimeSeriesAnalysisSerializer, PredictionDistributionSerializer
)
from .models import AnalysisRun, ModelCoefficient, StockPrediction, StockPerformanceMetrics, OutOfSamplePrediction, FoldStatistics, StockOOSMetric

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