import os
import django
import time
import pandas as pd
from pathlib import Path
from django.utils import timezone

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
django.setup()

from .models import CSVUploadRecord
from .b_forecast_pipeline_extended import (
    load_mxus_returns,
    run_parallel_data_prep,
    train_final_model_and_save,
)

def run_analysis_from_web(upload_pk: int, model_for_pred: str = "enet"):
    """
    Web entrypoint for running the pooled ElasticNet pipeline on an uploaded Excel file.
    Includes:
      • Data load & cleaning
      • Feature derivation (train_b, lag_train_b, etc.)
      • Model training and database persistence
    """
    print("=" * 90)
    print(f"🚀 Starting pooled ElasticNet analysis for upload={upload_pk} at {timezone.now()}")

    try:
        # ----------------------------------------------------------------------
        # STEP 1. Load uploaded Excel (raw returns)
        # ----------------------------------------------------------------------
        upload = CSVUploadRecord.objects.get(pk=upload_pk)
        file_path = Path(upload.filename.path)
        print(f"📂 Loading file: {file_path.name}")

        raw_df = load_mxus_returns(str(file_path), sheet="Returns")
        print(f"✅ Loaded returns: {raw_df.shape[0]} rows × {raw_df.shape[1]} columns")

        tickers = [c for c in raw_df.columns if c != "Date"]
        print(f"📊 Found {len(tickers)} tickers (showing first 10): {tickers[:10]}")

        # ----------------------------------------------------------------------
        # STEP 2. Define fixed parameters
        # ----------------------------------------------------------------------
        fixed_params = {
            "enet_alpha": 0.003,
            "enet_l1_ratio": 0.2,
            "base_train_len_days": 756,       # ~3 years
            "base_test_len_days": 252,        # ~6 months
            "oos_min_train_rows_fixed": 5000  # required for walk-forward CV
        }

        print("⚙️  Using model parameters:")
        for k, v in fixed_params.items():
            print(f"   • {k}: {v}")

        # ----------------------------------------------------------------------
        # STEP 3. Build pooled learning table (feature generation)
        # ----------------------------------------------------------------------
        print("🏗️  Generating feature table (train_b, lag_train_b, ar1_corr_*, etc.)...")
        t0 = time.time()
        learning_df = run_parallel_data_prep(
            mxus_returns=raw_df,
            market_features=pd.DataFrame(),
            tickers=tickers,
            horizon=5,
            base_train_len=fixed_params["base_train_len_days"],
            base_test_len=fixed_params["base_test_len_days"],
            max_workers=os.cpu_count() - 2
        )
        t1 = time.time()

        if learning_df is None or learning_df.empty:
            raise RuntimeError("Learning table generation failed: no valid feature data.")

        print(f"✅ Feature table built in {t1 - t0:.1f}s → {learning_df.shape[0]} rows × {learning_df.shape[1]} cols")

        # ----------------------------------------------------------------------
        # STEP 4. Train model & save to DB
        # ----------------------------------------------------------------------
        print("🏋️‍♂️ Training pooled ElasticNet model and saving to database...")
        t2 = time.time()
        result = train_final_model_and_save(
            pooled_df=learning_df,
            best_params=pd.Series(fixed_params),
            horizon=5
        )
        t3 = time.time()

        if not result.get("ok"):
            raise RuntimeError(result.get("error", "Unknown model error."))

        print(f"🎉 Model training complete in {t3 - t2:.1f}s")
        print(f"🧠 SharedStats ID: {result.get('shared_stats_id')}")
        print(f"📈 Stocks processed: {result.get('tickers_saved')}")

        total_time = time.time() - t0
        print(f"⏱️  Total pipeline runtime: {total_time:.1f}s")
        print("=" * 90)

        return {
            "ok": True,
            "timestamp": timezone.now(),
            "shared_stats_id": result.get("shared_stats_id"),
            "tickers_saved": result.get("tickers_saved"),
            "params": fixed_params,
        }

    except Exception as e:
        print(f"❌ Pipeline failed for upload {upload_pk}: {e}")
        print("=" * 90)
        return {"ok": False, "error": str(e)}
