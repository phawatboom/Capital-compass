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

def run_analysis_from_web(upload_pk: int, model_for_pred: str = "enet", config: dict | None = None):
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
        # STEP 2. Define and override parameters from config
        # ----------------------------------------------------------------------
        print("📈 Calculating market-wide features...")
        market_features = pd.DataFrame(index=raw_df["Date"])
        market_features.index.name = "Date"

        # Cross-sectional dispersion of returns each day
        xsec_disp_1d = raw_df[tickers].std(axis=1)
        xsec_disp_30d = xsec_disp_1d.rolling(30, min_periods=10).mean()

        market_features["xsec_disp_1d"] = xsec_disp_1d.values
        market_features["xsec_disp_30d"] = xsec_disp_30d.values

        # Forward-fill to align with any period returns later on
        market_features = market_features.sort_index().ffill().reset_index()
        print(f"✅ Market features calculated → {len(market_features)} rows")

        fixed_params = {
            "enet_alpha": 0.003,
            "enet_l1_ratio": 0.2,
            "base_train_len_days": 756,       # ~3 years
            "base_test_len_days": 252,        # ~6 months
            "oos_min_train_rows_fixed": 5000  # required for walk-forward CV
        }

        # Default values
        horizon_days = 5
        multi_period = False

        if config:
            try:
                fixed_params["enet_alpha"] = float(config.get("alpha", fixed_params["enet_alpha"]))
                fixed_params["enet_l1_ratio"] = float(config.get("l1_ratio", fixed_params["enet_l1_ratio"]))
                fixed_params["base_train_len_days"] = int(config.get("training_days", fixed_params["base_train_len_days"]))
                fixed_params["base_test_len_days"] = int(config.get("testing_days", fixed_params["base_test_len_days"]))
                horizon_days = int(config.get("horizon_days", horizon_days))
                multi_period = bool(config.get("multi_period", False))
            except Exception as e:
                print(f"⚠️ Could not parse model config values: {e}")

        print("⚙️ Using model parameters:")
        for k, v in fixed_params.items():
            print(f"   • {k}: {v}")
        print(f"   • horizon_days: {horizon_days}")
        print(f"   • multi_period: {multi_period}")

        # ----------------------------------------------------------------------
        # STEP 3. Determine horizons to run
        # ----------------------------------------------------------------------
        horizons_to_run = [1, 5, 10, 20] if multi_period else [horizon_days]
        shared_stats_ids = []
        tickers_total = 0

        overall_start = time.time()

        # ----------------------------------------------------------------------
        # STEP 4. Run analysis for each horizon
        # ----------------------------------------------------------------------
        for horizon in horizons_to_run:
            print(f"\n🏗️ Building features for horizon={horizon}d...")
            t0 = time.time()

            learning_df = run_parallel_data_prep(
                mxus_returns=raw_df,
                market_features=market_features,
                tickers=tickers,
                horizon=horizon,
                base_train_len=fixed_params["base_train_len_days"],
                base_test_len=fixed_params["base_test_len_days"],
                max_workers=max(os.cpu_count() - 2, 1),
            )

            if learning_df is None or learning_df.empty:
                print(f"❌ No feature data produced for horizon {horizon}d. Skipping.")
                continue

            print(f"✅ Feature table built in {time.time() - t0:.1f}s → {learning_df.shape[0]} rows × {learning_df.shape[1]} cols")

            # Train & save
            print(f"🏋️‍♂️ Training ElasticNet model for horizon={horizon}d...")
            t2 = time.time()

            result = train_final_model_and_save(
                pooled_df=learning_df,
                best_params=pd.Series(fixed_params),
                horizon=horizon
            )

            if not result.get("ok"):
                print(f"⚠️ Model training failed for horizon={horizon}d: {result.get('error')}")
                continue

            shared_stats_ids.append(result.get("shared_stats_id"))
            tickers_total += result.get("tickers_saved", 0)
            print(f"🎉 Horizon={horizon}d complete in {time.time() - t2:.1f}s → SharedStats ID={result.get('shared_stats_id')}")

        total_time = time.time() - overall_start
        print(f"\n✅ All horizon(s) complete in {total_time:.1f}s")
        print(f"🧠 Total SharedStats created: {len(shared_stats_ids)}")
        print(f"📈 Total tickers processed: {tickers_total}")
        print("=" * 90)

        return {
            "ok": True,
            "timestamp": timezone.now(),
            "shared_stats_ids": shared_stats_ids,
            "tickers_saved_total": tickers_total,
            "params": fixed_params,
            "multi_period": multi_period,
            "horizons_run": horizons_to_run
        }

    except Exception as e:
        print(f"❌ Pipeline failed for upload {upload_pk}: {e}")
        print("=" * 90)
        return {"ok": False, "error": str(e)}