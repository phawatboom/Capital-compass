# filepath: b_forecast_pipeline_pooled_fixed_parallel_v6.py
# -*- coding: utf-8 -*-
"""
Predicting future b with a pooled ElasticNet model using FIXED parameters.
- Layer 1 (Outer Parallel): Run the full pipeline for each horizon (1d, 5d, etc.) in parallel.
- Layer 2 (Inner Parallel): For each horizon, run parallel data prep to create a single "pooled" learning table.
- Layer 3: Walk-forward OOS evaluation using the pooled data and fixed params.
- Layer 4: Save all artifacts (model, plots, metrics) for each horizon.

Changes from v5:
- Fixed bug in `historical_b` where `min_train_obs` was used for the test window.
  Added a new `min_test_obs` parameter to fix this.
- Added `MAE_OOS` and `MASE_OOS` to `calculate_and_save_per_stock_metrics`.
- Implemented robust `0.0` imputation. Model now trains on all data by setting
  `dropna_rows=False` and filling NaNs with 0.0 before scaling.
- Added new function `generate_final_predictions` to output a sheet with the
  latest prediction, features, and model coefficients for every stock.
"""
from __future__ import annotations
import warnings

from django.db import transaction

warnings.filterwarnings("ignore")

from typing import Optional, List, Tuple, Dict
from pathlib import Path
import traceback
import time
import django
import os
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
import pandas as pd

import statsmodels.api as sm
from statsmodels.tsa.arima.model import ARIMA

from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import ElasticNet
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from django.utils import timezone

# =========================
# Output paths (next to this file)
# =========================
SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_ROOT = SCRIPT_DIR / "Pooled_Outputs_v6_Fixed"  # --- CHANGE: Updated output dir name ---
OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)


# =========================
# 1) ROBUST DATA LOADERS
# =========================

def _coerce_date(df: pd.DataFrame, col="Date") -> pd.DataFrame:
    out = df.copy()
    out[col] = pd.to_datetime(out[col], errors="coerce", infer_datetime_format=True)
    out = out.dropna(subset=[col]).sort_values(col).reset_index(drop=True)
    return out


def load_mxus_returns(xlsx_path: str, sheet: str = "Returns") -> pd.DataFrame:
    """
    Robust loader for MXUS_Data.xlsx / 'Returns' where the true header row may be below row 1.
    - Finds the first row containing 'Date' (case-insensitive) and uses it as header.
    - Converts percent strings like '0.79%' → 0.0079
    """
    raw = pd.read_excel(xlsx_path, sheet_name=sheet, header=None, dtype=object)

    header_row = None
    scan_rows = min(50, len(raw))
    for i in range(scan_rows):
        row = raw.iloc[i].astype(str).str.strip()
        if row.str.lower().eq("date").any():
            header_row = i
            break
    if header_row is None:
        raise KeyError("Could not find a header row containing 'Date' in the sheet.")

    cols = raw.iloc[header_row].astype(str).str.strip().tolist()
    df = raw.iloc[header_row + 1:].copy()
    df.columns = cols
    df = df.loc[:, ~(df.isna().all())]

    # find/rename Date
    date_col = None
    for c in df.columns:
        if str(c).strip().lower() == "date":
            date_col = c;
            break
    if date_col is None:
        for c in df.columns:
            if "date" in str(c).strip().lower():
                date_col = c;
                break
    if date_col is None:
        raise KeyError("Found header row but no column named 'Date'.")

    if date_col != "Date":
        df = df.rename(columns={date_col: "Date"})

    # convert values
    def _clean_numeric(x):
        if isinstance(x, str):
            s = x.strip().replace(",", "")
            if s == "": return np.nan
            if s.endswith("%"):
                try:
                    return float(s[:-1]) / 100.0
                except:
                    return np.nan
            try:
                return float(s)
            except:
                return np.nan
        return x

    for c in df.columns:
        if c != "Date":
            df[c] = df[c].map(_clean_numeric)

    return _coerce_date(df, "Date")


# --------------------------------------------
# Convert AGGREGATE daily returns to multi-day period returns
def aggregate_to_period_returns(daily_returns: pd.DataFrame, period_days: int) -> pd.DataFrame:
    """
    Aggregates daily simple returns into non-overlapping multi-day period returns.
    Example: period_days=5 aggregates daily returns into weekly returns.
    """
    if period_days == 1:
        return daily_returns.copy()

    # Isolate ticker columns (all columns except 'Date')
    ticker_cols = [c for c in daily_returns.columns if c != "Date"]

    # Calculate geometric returns: (1+R1)*(1+R2)*...*(1+Rn) - 1
    # We use rolling().apply() for a robust product that handles NaNs well
    period_returns = (1 + daily_returns[ticker_cols]).rolling(
        window=period_days,
        min_periods=period_days  # Ensure full periods
    ).apply(np.prod, raw=True) - 1

    # Select only the end-of-period, non-overlapping rows
    # .iloc[period_days-1::period_days] takes every 'period_days'-th row, starting from the first full one
    non_overlapping = period_returns.iloc[period_days - 1::period_days].reset_index(drop=True)

    # Bring the corresponding dates back
    non_overlapping["Date"] = daily_returns["Date"].iloc[period_days - 1::period_days].reset_index(drop=True)

    # Reorder columns to have 'Date' first
    return non_overlapping[["Date"] + ticker_cols]


# ============================================
# 2) FEATURE ENGINEERING (RICH PREDICTORS)
# ============================================

def _rolling_acf1(arr: np.ndarray) -> float:
    x = np.asarray(arr, dtype=float)
    if x.size < 5 or np.all(np.isnan(x)): return np.nan
    x = x - np.nanmean(x)
    s = np.nanstd(x)
    if not np.isfinite(s) or s == 0: return np.nan
    x0, x1 = x[:-1], x[1:]
    num = np.nanmean((x0 - np.nanmean(x0)) * (x1 - np.nanmean(x1)))
    den = np.nanstd(x0) * np.nanstd(x1)
    return float(num / den) if den and np.isfinite(num / den) else np.nan


def rich_features_from_returns(wide_returns: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """
    Per-ticker features (daily returns table: Date + all tickers).
    """
    if ticker not in wide_returns.columns:
        raise ValueError(f"Ticker {ticker} not found in returns.")

    df = wide_returns[["Date", ticker]].rename(columns={ticker: "ret"}).copy()
    df = df.sort_values("Date").reset_index(drop=True)

    # --- AR(1) correlations ---
    df["ar1_corr_10d"] = df["ret"].rolling(10, min_periods=6).apply(_rolling_acf1, raw=True)
    df["ar1_corr_20d"] = df["ret"].rolling(20, min_periods=10).apply(_rolling_acf1, raw=True)
    df["ar1_corr_60d"] = df["ret"].rolling(60, min_periods=20).apply(_rolling_acf1, raw=True)

    # --- Sign persistence ---
    def sign_persist(x):
        x = np.asarray(x, dtype=float)
        if x.size < 2: return np.nan
        s = np.sign(x)
        return float(np.nanmean(s[1:] == s[:-1]))

    df["sign_persist_20d"] = df["ret"].rolling(20, min_periods=10).apply(sign_persist, raw=False)
    df["sign_persist_60d"] = df["ret"].rolling(60, min_periods=20).apply(sign_persist, raw=False)

    # --- Recent returns ---
    df["ret_1d"] = df["ret"]
    df["ret_5d"] = df["ret"].rolling(5, min_periods=3).sum()
    df["ret_20d"] = df["ret"].rolling(20, min_periods=10).sum()

    # --- Volatility (Short and Long Term) ---
    df["vol_63d"] = df["ret"].rolling(63, min_periods=30).std()  # ~3mo
    df["vol_126d"] = df["ret"].rolling(126, min_periods=60).std()  # ~6mo
    df["vol_252d"] = df["ret"].rolling(252, min_periods=120).std()  # ~1yr
    df["vol_756d"] = df["ret"].rolling(756, min_periods=252).std()  # ~3yr

    # --- Moving-average Z of "price" reconstructed from returns ---
    price = (1.0 + df["ret"].fillna(0)).cumprod()
    ma20 = price.rolling(20, min_periods=10).mean()
    sd20 = price.rolling(20, min_periods=10).std()
    df["Z_ma_20d"] = (price - ma20) / sd20

    df["Ticker"] = ticker
    return df


def _cs_percentile_rank_wide(wide: pd.DataFrame, ticker: str) -> pd.Series:
    cols = [c for c in wide.columns if c != "Date"]
    ranked = wide[cols].apply(lambda row: row.rank(pct=True), axis=1)
    ranked["Date"] = wide["Date"].values
    ranked_ticker = pd.DataFrame({"Date": wide["Date"].values,
                                  "rank": ranked[ticker].values if ticker in ranked.columns else np.nan})
    return ranked_ticker.set_index("Date")["rank"]


def add_cross_sectional_ranks(wide_returns: pd.DataFrame, feat_df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    out = feat_df.copy()

    wide1 = wide_returns.copy()

    cols = [c for c in wide_returns.columns if c != "Date"]
    ret5 = wide_returns[cols].rolling(5, min_periods=3).sum()
    ret20 = wide_returns[cols].rolling(20, min_periods=10).sum()
    ret5.insert(0, "Date", wide_returns["Date"].values)
    ret20.insert(0, "Date", wide_returns["Date"].values)

    prices = (1.0 + wide_returns[cols].fillna(0)).cumprod()
    ma20 = prices.rolling(20, min_periods=10).mean()
    sd20 = prices.rolling(20, min_periods=10).std()
    zma20 = (prices - ma20) / sd20
    zma20.insert(0, "Date", wide_returns["Date"].values)

    vol63 = wide_returns[cols].rolling(63, min_periods=30).std()
    vol126 = wide_returns[cols].rolling(126, min_periods=60).std()
    vol252 = wide_returns[cols].rolling(252, min_periods=120).std()
    vol756 = wide_returns[cols].rolling(756, min_periods=252).std()
    vol63.insert(0, "Date", wide_returns["Date"].values)
    vol126.insert(0, "Date", wide_returns["Date"].values)
    vol252.insert(0, "Date", wide_returns["Date"].values)
    vol756.insert(0, "Date", wide_returns["Date"].values)

    r1 = _cs_percentile_rank_wide(wide1, ticker)
    r5 = _cs_percentile_rank_wide(ret5, ticker)
    r20 = _cs_percentile_rank_wide(ret20, ticker)
    rz = _cs_percentile_rank_wide(zma20, ticker)
    rv63 = _cs_percentile_rank_wide(vol63, ticker)
    rv126 = _cs_percentile_rank_wide(vol126, ticker)
    rv252 = _cs_percentile_rank_wide(vol252, ticker)
    rv756 = _cs_percentile_rank_wide(vol756, ticker)

    out = out.merge(r1.rename("cs_rank_ret_1d").reset_index(), on="Date", how="left")
    out = out.merge(r5.rename("cs_rank_ret_5d").reset_index(), on="Date", how="left")
    out = out.merge(r20.rename("cs_rank_ret_20d").reset_index(), on="Date", how="left")
    out = out.merge(rz.rename("cs_rank_z_ma_20d").reset_index(), on="Date", how="left")
    out = out.merge(rv63.rename("cs_rank_vol_63d").reset_index(), on="Date", how="left")
    out = out.merge(rv126.rename("cs_rank_vol_126d").reset_index(), on="Date", how="left")
    out = out.merge(rv252.rename("cs_rank_vol_252d").reset_index(), on="Date", how="left")
    out = out.merge(rv756.rename("cs_rank_vol_756d").reset_index(), on="Date", how="left")

    return out


# ==================================
# 3) b-ESTIMATION (ARIMA + FALLBACK)
# ==================================

def fit_arima_and_get_b(returns: pd.Series,
                        order=(1, 0, 0),
                        verbose=False) -> Optional[float]:
    """
    Return an AR(1)-style 'b' with robust fallbacks:
      1) ARIMA(order) → ar.L1 coefficient
      2) OLS AR(1): r_t ~ r_{t-1}
      3) Lag-1 autocorrelation
    """
    r = returns.dropna().astype(float)
    # --- BUG FIX: This is the minimum required for ARIMA/OLS/AC1 ---
    if len(r) < 10:
        return None

    # 1) ARIMA
    try:
        model = ARIMA(r.values, order=order).fit(method="statespace", disp=0)
        params = model.params
        for k in params.index:
            if "ar.L1" in k:
                return float(params[k])
    except Exception as e:
        if verbose: print("ARIMA fail:", e)

    # 2) OLS AR(1)
    try:
        x = r.shift(1)
        df = pd.DataFrame({"y": r.values, "x": x.values}).dropna()
        if len(df) >= 10:
            X = sm.add_constant(df["x"])
            ols = sm.OLS(df["y"], X).fit()
            return float(ols.params[1])
    except Exception as e:
        if verbose: print("OLS fail:", e)

    # 3) Lag-1 autocorr
    try:
        ac1 = r.autocorr(lag=1)
        return float(ac1)
    except Exception as e:
        if verbose: print("AC fail:", e)

    return None


def historical_b(
        daily_returns: pd.DataFrame,
        ticker: str,
        train_len: int,
        test_len: int,
        arima_order=(1, 0, 0),
        min_train_obs: int = 20,
        min_test_obs: int = 10,  # <-- *** BUG FIX: Added min_test_obs ***
        verbose: bool = True
) -> pd.DataFrame:
    """
    Rolling windows:
      - Fit model on train → train_b
      - Fit model on test  → test_b
    Returns a frame with Date (end of train), Ticker, b’s, and indices.
    """
    if ticker not in daily_returns.columns:
        raise ValueError(f"Ticker '{ticker}' not in returns table.")

    ser = (daily_returns[["Date", ticker]]
           .rename(columns={ticker: "ret"})
           .dropna(subset=["ret"])
           .sort_values("Date")
           .reset_index(drop=True))

    if ser.empty:
        if verbose: print(f"[{ticker}] No non-NaN returns after dropna.")
        return pd.DataFrame(columns=["Date", "Ticker", "train_b", "test_b", "train_start_idx",
                                     "train_end_idx", "test_start_idx", "test_end_idx", "lag_train_b"])

    ret = ser["ret"].values
    dates = ser["Date"].values
    N = len(ser)
    if N < (train_len + test_len):
        if verbose: print(f"[{ticker}] Not enough rows: have {N}, need {train_len + test_len}.")
        return pd.DataFrame(columns=["Date", "Ticker", "train_b", "test_b", "train_start_idx",
                                     "train_end_idx", "test_start_idx", "test_end_idx", "lag_train_b"])

    rows, attempted, kept = [], 0, 0
    i = 0
    while i + train_len + test_len <= N:
        tr = slice(i, i + train_len)
        te = slice(i + train_len, i + train_len + test_len)
        train_returns = pd.Series(ret[tr])
        test_returns = pd.Series(ret[te])

        # --- *** BUG FIX: Use min_test_obs for test_returns *** ---
        if train_returns.dropna().shape[0] < min_train_obs or test_returns.dropna().shape[0] < min_test_obs:
            i += 1;
            continue

        attempted += 1
        b_train = fit_arima_and_get_b(train_returns, order=arima_order)
        b_test = fit_arima_and_get_b(test_returns, order=arima_order)

        if b_train is not None and b_test is not None:
            kept += 1
            rows.append({
                "Date": pd.to_datetime(dates[tr][-1]),
                "Ticker": ticker,
                "train_b": float(b_train),
                "test_b": float(b_test),
                "train_start_idx": i,
                "train_end_idx": i + train_len - 1,
                "test_start_idx": i + train_len,
                "test_end_idx": i + train_len + test_len - 1
            })
        i += 1  # Note: This is a 1-period step (rolling), not non-overlapping

    out = pd.DataFrame(rows)
    if out.empty:
        if verbose:
            print(f"[{ticker}] No valid b coefficients kept (attempted windows: {attempted}, kept: {kept}).")
        return pd.DataFrame(columns=["Date", "Ticker", "train_b", "test_b", "train_start_idx",
                                     "train_end_idx", "test_start_idx", "test_end_idx", "lag_train_b"])

    out = out.sort_values("Date").reset_index(drop=True)
    out["lag_train_b"] = out["train_b"].shift(1)
    return out


# ==================================
# 4) MERGE & MODEL
# ==================================

def assemble_learning_table(
        b_pairs: pd.DataFrame,
        feature_frame: pd.DataFrame,
        market_features: pd.DataFrame
) -> pd.DataFrame:
    """
    Merges b_pairs, single-stock features, and market features.
    """
    feat_cols = [c for c in feature_frame.columns if c not in ["Date", "Ticker", "ret"]]

    # Merge 1: b_pairs (one-to-one by Ticker/Date)
    merged = b_pairs.merge(feature_frame[["Date", "Ticker"] + feat_cols], on=["Date", "Ticker"], how="left")

    # Merge 2: market_features (many-to-one by Date)
    if market_features is not None and not market_features.empty:
        merged = merged.merge(market_features, on="Date", how="left")

    return merged.dropna(subset=["train_b", "test_b"])


# ---- Feature list helper (ensure consistent selection everywhere)

_FEATURE_PREFIXES = [
    "train_b", "lag_train_b",
    "vol_", "perf_", "absret_mean_", "acf1_",
    "ar1_corr_", "sign_persist_", "ret_", "Z_ma_", "cs_rank_",
    "xsec_disp_"
]


def get_feature_cols(df: pd.DataFrame) -> List[str]:
    feats = [c for c in df.columns if any(c.startswith(p) for p in _FEATURE_PREFIXES) and c != "ret"]
    return feats


# ---- ElasticNet (pre-CV) with strict NA drop + schema freeze

def build_training_matrices(learning_df: pd.DataFrame, dropna_rows: bool = True) -> Tuple[
    pd.DataFrame, pd.Series, List[str]]:
    feats = get_feature_cols(learning_df)
    if not feats:
        raise ValueError(
            "No feature columns matched. Check get_feature_cols() prefixes and "
            "confirm your learning_df includes at least ['train_b','lag_train_b']."
        )

    df = learning_df.copy()

    # --- *** IMPUTATION CHANGE *** ---
    if dropna_rows:
        # Original behavior: drop rows with any missing features
        df = df.dropna(subset=["test_b"] + feats)
    else:
        # New behavior: Impute 0.0 for missing features
        df[feats] = df[feats].replace([np.inf, -np.inf], np.nan).fillna(0.0)
        df = df.dropna(subset=["test_b"])  # Still drop rows with missing targets

    if df.empty:
        raise ValueError("Training data is empty after NA handling. Check features or imputation logic.")

    X = df[feats].copy()
    y = df["test_b"].astype(float).copy()
    return X, y, feats


def train_final_model_bundle(learning_df: pd.DataFrame,
                             alpha: float = 0.01,
                             l1_ratio: float = 0.5,
                             dropna_rows: bool = True) -> Dict:  # --- *** IMPUTATION CHANGE *** ---
    """
    Trains the final model.
    `dropna_rows=False` will impute 0.0 for missing values.
    """
    # --- *** IMPUTATION CHANGE: pass dropna_rows to build_training_matrices *** ---
    X_train, y_train, feats = build_training_matrices(learning_df, dropna_rows=dropna_rows)

    if X_train is Ellipsis:
        raise TypeError("Internal error: X_train became Ellipsis. Remove any '...' placeholders.")
    if not isinstance(X_train, pd.DataFrame):
        raise TypeError(f"Expected DataFrame for X_train, got {type(X_train)}")
    if X_train.empty:
        raise ValueError("Training matrix is empty after NA-drop. Loosen dropna_rows or fix features.")

    pipe = Pipeline([
        # Note: Imputation is now handled *before* this function
        ('scaler', StandardScaler(with_mean=True, with_std=True)),
        ('model', ElasticNet(alpha=alpha, l1_ratio=l1_ratio, max_iter=10000))
    ])
    pipe.fit(X_train, y_train)

    bundle = {
        "pipe": pipe,
        "train_cols": X_train.columns.tolist(),  # schema freeze
        "feature_cols": feats
    }
    return bundle


def align_to_training_schema(X_new: pd.DataFrame, train_cols: List[str]) -> pd.DataFrame:
    # Any missing columns get 0.0; extras are dropped
    return X_new.reindex(columns=train_cols, fill_value=0.0)


# --- OOS Evaluation ---

def _calc_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, float]:
    mask = ~(np.isnan(y_true) | np.isnan(y_pred))
    if mask.sum() == 0:
        return {"MAE": np.nan, "RMSE": np.nan, "R2": np.nan, "DirectionalAcc": np.nan, "N": 0}
    yt = y_true[mask]
    yp = y_pred[mask]
    mae = mean_absolute_error(yt, yp)
    rmse = float(np.sqrt(mean_squared_error(yt, yp)))
    r2 = r2_score(yt, yp) if len(yt) >= 2 else np.nan
    dir_acc = float(np.mean(np.sign(yt) == np.sign(yp)))
    return {"MAE": float(mae), "RMSE": rmse, "R2": float(r2), "DirectionalAcc": dir_acc, "N": int(len(yt))}


def walk_forward_oos_eval(
        learning_df: pd.DataFrame,
        model_kind: str = "enet",
        enet_alpha: float = 0.003,
        enet_l1_ratio: float = 0.2,
        dropna_rows: bool = True,  # --- *** IMPUTATION CHANGE *** ---
        min_train_rows: int = 5000,
        val_rows: int = 20,
        embargo_rows: int = 0
) -> Tuple[pd.DataFrame, Dict[str, float], pd.DataFrame]:
    """
    Expanding-window walk-forward CV with optional purge/embargo.
    Returns (oos_predictions_df, metrics_dict, fold_stats_df).

    `dropna_rows=False` will impute 0.0 for missing values.
    """
    df = learning_df.sort_values("Date").reset_index(drop=True).copy()
    feats = get_feature_cols(df)

    empty_preds = pd.DataFrame(columns=["Date", "Ticker", "actual_b", "pred_b", "fold", "n_train"])
    empty_metrics = {"MAE": np.nan, "RMSE": np.nan, "R2": np.nan, "DirectionalAcc": np.nan, "N": 0}
    empty_fold_stats = pd.DataFrame(columns=["fold", "n_pred", "n_train", "r2", "end_date"])

    if len(df) < (min_train_rows + embargo_rows + max(1, val_rows)):
        print(
            f"  OOS Eval skipped: Not enough rows. Have {len(df)}, need {min_train_rows + embargo_rows + max(1, val_rows)}")
        return empty_preds, empty_metrics, empty_fold_stats

    preds = []
    train_end = min_train_rows - 1
    fold = 0
    N = len(df)

    # We must have enough *rows* in the first training split
    first_train_end_date = df.iloc[train_end]['Date']

    while True:
        # Define train/val *indices* based on row counts
        val_start = train_end + 1 + max(0, embargo_rows)
        val_end = val_start + val_rows - 1

        if val_start >= N:
            break  # No more data to start a validation block

        # Ensure val_end doesn't go past the end
        val_end = min(val_end, N - 1)

        tr_df = df.iloc[:train_end + 1].copy()
        va_df = df.iloc[val_start:val_end + 1].copy()

        # Ensure validation block is valid
        if va_df.empty:
            break

        # TRAIN: build matrices and fit per chosen model
        # --- *** IMPUTATION CHANGE: Select rows based on dropna_rows param *** ---
        tr = tr_df.dropna(subset=["test_b"] + feats) if dropna_rows else tr_df.dropna(subset=["test_b"])
        n_train_rows = len(tr)

        if n_train_rows < min_train_rows:
            # Advance window to try again
            train_end = val_end
            fold += 1
            continue

        if model_kind.lower() == "enet":
            # --- *** IMPUTATION CHANGE: Fill NaNs with 0.0 *** ---
            X_tr = tr[feats].replace([np.inf, -np.inf], np.nan).fillna(0.0).copy()
            y_tr = tr["test_b"].astype(float).values

            if np.std(y_tr) < 1e-6:
                train_end = val_end
                fold += 1
                continue

            pipe = Pipeline([
                ('scaler', StandardScaler(with_mean=True, with_std=True)),
                ('model', ElasticNet(alpha=enet_alpha, l1_ratio=enet_l1_ratio, max_iter=10000))
            ])
            pipe.fit(X_tr, y_tr)
            train_cols = X_tr.columns.tolist()

            # VALIDATE: align to train schema and predict
            # --- *** IMPUTATION CHANGE: Select rows based on dropna_rows param *** ---
            va = va_df.dropna(subset=["test_b"] + feats) if dropna_rows else va_df.dropna(subset=["test_b"])

            if not va.empty:
                # --- *** IMPUTATION CHANGE: Fill NaNs with 0.0 *** ---
                X_va = va[feats].replace([np.inf, -np.inf], np.nan).fillna(0.0).copy()
                X_va = align_to_training_schema(X_va, train_cols)
                y_hat = pipe.predict(X_va)
                preds.append(pd.DataFrame({
                    "Date": va["Date"].values,
                    "Ticker": va["Ticker"].values,
                    "actual_b": va["test_b"].values,
                    "pred_b": y_hat,
                    "fold": fold,
                    "n_train": n_train_rows
                }))

        else:  # OLS
            # --- *** IMPUTATION CHANGE: Fill NaNs with 0.0 *** ---
            X_tr = sm.add_constant(tr[feats].replace([np.inf, -np.inf], np.nan).fillna(0.0), has_constant="add")
            y_tr = tr["test_b"].astype(float).values
            if np.std(y_tr) < 1e-6:
                train_end = val_end
                fold += 1
                continue
            ols = sm.OLS(y_tr, X_tr).fit()

            # --- *** IMPUTATION CHANGE: Select rows based on dropna_rows param *** ---
            va = va_df.dropna(subset=["test_b"] + feats) if dropna_rows else va_df.dropna(subset=["test_b"])
            if not va.empty:
                # --- *** IMPUTATION CHANGE: Fill NaNs with 0.0 *** ---
                X_va = sm.add_constant(va[feats].replace([np.inf, -np.inf], np.nan).fillna(0.0), has_constant="add")
                y_hat = ols.predict(X_va).values
                preds.append(pd.DataFrame({
                    "Date": va["Date"].values,
                    "Ticker": va["Ticker"].values,
                    "actual_b": va["test_b"].values,
                    "pred_b": y_hat,
                    "fold": fold,
                    "n_train": n_train_rows
                }))

        # advance window (expanding)
        train_end = val_end
        fold += 1

        if val_end == N - 1:
            break  # We've used all the data

    if not preds:
        return empty_preds, empty_metrics, empty_fold_stats

    oos = pd.concat(preds, ignore_index=True)
    oos = oos.sort_values("Date").reset_index(drop=True)

    # --- Global R² (computed over all folds combined)
    m = _calc_metrics(oos["actual_b"].values, oos["pred_b"].values)

    # --- Compute fold-wise R² metrics ---
    fold_stats = []
    for f, df_f in oos.groupby("fold"):
        if len(df_f) >= 2:
            try:
                r2_f = r2_score(df_f["actual_b"].values, df_f["pred_b"].values)
                n_train_weight = df_f["n_train"].iloc[0]  # Get the new weight
                end_date = df_f["Date"].max()

                fold_stats.append({
                    "fold": int(f),
                    "n_pred": len(df_f),
                    "n_train": int(n_train_weight),
                    "r2": float(r2_f),
                    "end_date": end_date
                })
            except Exception:
                continue

    fold_stats_df = pd.DataFrame(fold_stats)
    if not fold_stats_df.empty:
        fold_stats_df["end_date"] = pd.to_datetime(fold_stats_df["end_date"])

    if not fold_stats_df.empty:
        # --- Use n_train as the weight ---
        n_tot_weight = fold_stats_df["n_train"].sum()
        r2_fold_mean = float(fold_stats_df["r2"].mean())

        if n_tot_weight > 0:
            r2_fold_weighted = float((fold_stats_df["r2"] * fold_stats_df["n_train"]).sum() / n_tot_weight)
        else:
            r2_fold_weighted = np.nan
    else:
        r2_fold_mean = r2_fold_weighted = np.nan

    m["R2_global"] = m.pop("R2")
    m["R2_fold_mean"] = r2_fold_mean
    m["R2_fold_weighted"] = r2_fold_weighted

    # --- additional robustness metrics (scale-free) ---
    def mae_ratio_global(y, yhat):
        denom = np.abs(y - y.mean()).mean()
        if denom == 0: return np.nan
        return (np.abs(y - yhat).mean()) / denom

    y_all = oos["actual_b"].values
    yhat_all = oos["pred_b"].values
    m["MAE_ratio_global"] = float(mae_ratio_global(y_all, yhat_all))

    mae_fold = []
    for f, df_f in oos.groupby("fold"):
        y, yhat = df_f["actual_b"].values, df_f["pred_b"].values
        if len(y) >= 2:
            mae_fold.append({"n": len(y), "ratio": mae_ratio_global(y, yhat)})

    if mae_fold:
        m["MAE_ratio_fold_mean"] = float(np.nanmean([d["ratio"] for d in mae_fold]))
        n_tot = sum(d["n"] for d in mae_fold)
        if n_tot > 0:
            m["MAE_ratio_fold_weighted"] = float(np.nansum([d["ratio"] * d["n"] for d in mae_fold]) / n_tot)
        else:
            m["MAE_ratio_fold_weighted"] = np.nan

    return oos, m, fold_stats_df


# --- Helper function for per-stock metrics ---
def calculate_and_save_per_stock_metrics(oos_preds_df: pd.DataFrame, out_dir: Path):
    """
    Calculates R2, RMSE, MAE, Directional Accuracy, and Prediction StdDev
    for each stock based on OOS predictions and saves to a CSV.

    --- CHANGE: Added MAE_OOS and MASE_OOS ---
    """
    print("  Calculating per-stock OOS metrics...")
    if oos_preds_df is None or oos_preds_df.empty or not {'Ticker', 'actual_b', 'pred_b'}.issubset(
            oos_preds_df.columns):
        print("  Skipping per-stock metrics: No OOS prediction data available.")
        return

    # Ensure necessary columns are numeric and handle NaNs/Infs
    oos_clean = oos_preds_df[['Ticker', 'actual_b', 'pred_b']].copy()
    oos_clean['actual_b'] = pd.to_numeric(oos_clean['actual_b'], errors='coerce')
    oos_clean['pred_b'] = pd.to_numeric(oos_clean['pred_b'], errors='coerce')
    oos_clean = oos_clean.replace([np.inf, -np.inf], np.nan).dropna()

    # --- NEW: Sort by Ticker to ensure groups are contiguous for MASE calcs ---
    # (OOS data is already sorted by Date, so this creates Ticker-Date blocks)
    oos_clean = oos_clean.sort_values("Ticker").reset_index(drop=True)

    if oos_clean.empty:
        print("  Skipping per-stock metrics: No valid numeric prediction data after cleaning.")
        return

    # --- Define aggregation functions ---
    def safe_r2(group):
        if len(group) < 2:
            return np.nan
        try:
            if np.std(group['actual_b']) < 1e-9:
                return np.nan
            return r2_score(group['actual_b'], group['pred_b'])
        except ValueError:
            return np.nan

    def rmse(group):
        if len(group) < 1:
            return np.nan
        return np.sqrt(mean_squared_error(group['actual_b'], group['pred_b']))

    # --- NEW: MAE function ---
    def mae(group):
        if len(group) < 1:
            return np.nan
        return mean_absolute_error(group['actual_b'], group['pred_b'])

    # --- NEW: MASE function ---
    def mase(group):
        """
        Mean Absolute Scaled Error.
        Scales the model's MAE by the MAE of a naive 1-step-ahead forecast
        from the OOS data (y_pred[t] = y_actual[t-1]).
        A value < 1.0 means the model is better than the naive forecast.
        """
        if len(group) < 2:
            return np.nan

        y_true = group['actual_b']
        y_pred = group['pred_b']

        # 1. Model's MAE
        mae_model = mean_absolute_error(y_true, y_pred)

        # 2. Naive forecast MAE (on the same OOS data)
        # We must drop the first item since it has no lag
        y_true_shifted = y_true.shift(1)
        mae_naive = mean_absolute_error(y_true[1:], y_true_shifted[1:])

        if mae_naive == 0:
            return np.nan  # Avoid division by zero if data is constant

        return mae_model / mae_naive

    def dir_acc(group):
        if len(group) < 1:
            return np.nan
        actual_sign = np.sign(group['actual_b'])
        pred_sign = np.sign(group['pred_b'])
        correct_sign = (actual_sign == pred_sign)
        return np.mean(correct_sign)

    def pred_std(group):
        if len(group) < 2:
            return np.nan
        return group['pred_b'].std()

    # Perform grouped aggregation
    grouped = oos_clean.groupby('Ticker')
    per_stock_metrics_list = []

    for name, group in grouped:
        metrics = {
            'Ticker': name,
            'R2_OOS': safe_r2(group),
            'RMSE_OOS': rmse(group),
            'MAE_OOS': mae(group),  # <-- NEW
            'MASE_OOS': mase(group),  # <-- NEW
            'DirAcc_OOS': dir_acc(group),
            'PredStd_OOS': pred_std(group),
            'N_OOS': len(group)
        }
        per_stock_metrics_list.append(metrics)

    if not per_stock_metrics_list:
        print("  Skipping per-stock metrics: No data after grouping.")
        return

    per_stock_metrics = pd.DataFrame(per_stock_metrics_list)


# =========================
# 5) ORCHESTRATION (REFACTORED FOR POOLING)
# =========================

SAVE_LEARNING_TABLE_CSV = False  # Save the final, best pooled learning table


def generate_single_ticker_learning_table(
        ticker: str,
        returns_for_b: pd.DataFrame,  # This is already period-aggregated
        daily_returns_for_features: pd.DataFrame,
        market_features: pd.DataFrame,
        train_len_periods: int,  # Now passed directly
        test_len_periods: int,  # Now passed directly
        arima_order: Tuple[int, int, int] = (1, 0, 0),
        min_train_obs_b: Optional[int] = None,
        verbose: bool = False
) -> Optional[pd.DataFrame]:
    """
    This function ONLY does data prep.
    It generates the learning_df for a single ticker, to be pooled later.
    """

    # Determine min_train_obs if not provided
    min_obs_guard = (min_train_obs_b if (min_train_obs_b is not None)
                     else max(10, min(train_len_periods, test_len_periods)))

    # 1. Generate b labels
    b_pairs = historical_b(
        daily_returns=returns_for_b,  # Use period returns
        ticker=ticker,
        train_len=train_len_periods,
        test_len=test_len_periods,
        arima_order=arima_order,
        min_train_obs=min_obs_guard,
        min_test_obs=10,  # <-- *** BUG FIX: Explicitly set min_test_obs ***
        verbose=verbose
    )

    if b_pairs.empty:
        if verbose: print(f"[{ticker}] No valid b pairs.")
        return None

    # 2. Build features (daily)
    feat_df = rich_features_from_returns(daily_returns_for_features, ticker)
    feat_df = add_cross_sectional_ranks(daily_returns_for_features, feat_df, ticker)

    # 3. Merge
    learning_df = assemble_learning_table(
        b_pairs,
        feat_df,
        market_features
    )

    if learning_df.empty:
        if verbose: print(f"[{ticker}] No valid learning table rows after merge/dropna.")
        return None

    return learning_df


# =========================
# 6) PARALLEL WORKER FUNCTION (REFACTORED)
# =========================

def process_ticker_task_for_pooling(
        ticker: str,
        horizon: int,
        mxus_returns_data: pd.DataFrame,
        market_features_data: pd.DataFrame,
        base_train_len_days: int,
        base_test_len_days: int,
) -> Optional[pd.DataFrame]:
    """
    Worker function to be run in parallel.
    Generates the learning_df for a single ticker/horizon/param set.
    """
    try:
        # 1. Aggregate daily returns to the desired period
        period_returns_df = aggregate_to_period_returns(mxus_returns_data, period_days=horizon)

        # 2. Adjust train/test lengths for the new frequency
        train_len_periods = base_train_len_days // horizon
        test_len_periods = base_test_len_days // horizon

        # Guard against zero-length periods
        # --- *** BUG FIX: Check against min obs needed *** ---
        if train_len_periods < 20 or test_len_periods < 2:  # 20 for min_train_obs, 2 is arbitrary floor
            # print(f"Skipping {ticker} H={horizon}: train/test periods {train_len_periods}/{test_len_periods} too small.")
            return None

        # 3. Generate the learning table
        learning_df = generate_single_ticker_learning_table(
            ticker=ticker,
            returns_for_b=period_returns_df,
            daily_returns_for_features=mxus_returns_data,
            market_features=market_features_data,
            train_len_periods=train_len_periods,
            test_len_periods=test_len_periods,
            arima_order=(1, 0, 0),  # --- Fixed to AR(1) per client spec ---
            min_train_obs_b=20,  # Keep a reasonable floor
            verbose=False  # Set to True for debugging
        )

        return learning_df  # This is either a DataFrame or None

    except Exception as e:
        # Don't print full traceback, too noisy in parallel
        # print(f"❌ Error processing {ticker} at {horizon}d: {e}")
        return None


# =========================
# 7) MAIN ORCHESTRATOR (NEW)
# =========================

# --- Helper: Parallel Data Prep ---
def run_parallel_data_prep(
        mxus_returns: pd.DataFrame,
        market_features: pd.DataFrame,
        tickers: List[str],
        horizon: int,
        base_train_len: int,
        base_test_len: int,
        max_workers: int
) -> Optional[pd.DataFrame]:
    """
    Generates one pooled_learning_df for a *single set* of data-gen params.
    """
    print(f"--- Starting Data Prep: H={horizon}d, Train={base_train_len}d, Test={base_test_len}d ---")
    start_time = time.time()

    all_learning_tables = []
    jobs = [(t, horizon, mxus_returns, market_features, base_train_len, base_test_len) for t in tickers]

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_ticker = {
            executor.submit(process_ticker_task_for_pooling, *job): job[0]
            for job in jobs
        }

        for i, future in enumerate(as_completed(future_to_ticker), 1):
            ticker = future_to_ticker[future]
            try:
                result_df = future.result()
                if result_df is not None and not result_df.empty:
                    all_learning_tables.append(result_df)

                if i % 100 == 0 or i == len(jobs):
                    print(f"  ... data prep progress: {i}/{len(jobs)} tickers processed")

            except Exception as e:
                print(f"  ❌ Error gathering result for {ticker}: {e}")

    if not all_learning_tables:
        print("  ⚠️ No learning tables generated. Skipping.")
        return None

    pooled_df = pd.concat(all_learning_tables, ignore_index=True)
    pooled_df = pooled_df.sort_values("Date").reset_index(drop=True)

    end_time = time.time()
    print(f"  ✓ Data Prep Complete. {len(pooled_df)} rows. ({end_time - start_time:.2f}s)")
    return pooled_df


# --- >>> NEW: Function to generate final prediction sheet <<< ---
def generate_final_predictions(
        enet_bundle: Dict,
        pooled_df: pd.DataFrame,
        out_dir: Path
):
    """
    Takes the final trained model and the full pooled data, and generates a
    prediction for the *next* period for every stock based on its
    most recent available features.

    Saves a CSV with: Ticker, Date, final_prediction, all_features, all_coefficients
    """
    print("  Generating final predictions sheet...")
    try:
        train_cols = enet_bundle['train_cols']
        pipe = enet_bundle['pipe']

        # Get the coefficients from the final trained model
        coeffs = pd.Series(pipe.named_steps['model'].coef_, index=train_cols)

        # Get the single most recent row of features for every stock
        latest_features = pooled_df.sort_values('Date').groupby('Ticker').last().reset_index()

        if latest_features.empty:
            print("  ⚠️ Skipping final predictions: No latest feature data found.")
            return

        # Isolate the feature matrix, align to model's schema, and IMPUTE
        X_pred = latest_features[train_cols].replace([np.inf, -np.inf], np.nan).fillna(0.0)

        # Generate final predictions
        latest_features['final_prediction'] = pipe.predict(X_pred)

        # Build the final output dataframe
        output_df = latest_features[['Ticker', 'Date', 'final_prediction'] + train_cols].copy()

        # Add all coefficient values as new columns
        for col, val in coeffs.items():
            output_df[f'coeff_{col}'] = val

        # Save to CSV
        out_path = out_dir / "final_predictions.csv"
        output_df.to_csv(out_path, index=False)
        print(f"  Saved final predictions → {out_path.resolve()}")

    except Exception as e:
        print(f"  ❌ FAILED to generate final predictions sheet: {e}")
        traceback.print_exc()


# --- <<< END NEW FUNCTION >>> ---


# --- Helper: Train Final Model & Save ---
def train_final_model_and_save(pooled_df: pd.DataFrame, best_params: pd.Series, horizon: int):
    from .models import FactorSharedStats, StockFactorResult
    print(f"\n--- Training Final Model for H={horizon}d ---")

    alpha    = best_params['enet_alpha']
    l1_ratio = best_params['enet_l1_ratio']
    min_rows = int(best_params.get('oos_min_train_rows_fixed', 5000))

    # --- Train pooled ElasticNet ---
    enet_bundle = train_final_model_bundle(
        pooled_df,
        alpha=alpha,
        l1_ratio=l1_ratio,
        dropna_rows=False
    )

    pipeline = enet_bundle['pipe']
    model = pipeline.named_steps['model']
    coeffs = dict(zip(enet_bundle['train_cols'], model.coef_))
    intercept = model.intercept_

    # add this:
    scaler = pipeline.named_steps.get('scaler', None)
    cols = enet_bundle['train_cols']

    import numpy as np
    import pandas as pd

    coef_std = pd.Series(model.coef_, index=cols, dtype=float)
    b0_std = float(model.intercept_)

    # pull scaler stats safely
    if scaler is not None and hasattr(scaler, "mean_") and hasattr(scaler, "scale_"):
        mu = scaler.mean_
        sigma = scaler.scale_
    else:
        # fallback if no scaler present
        mu = np.zeros(len(cols))
        sigma = np.ones(len(cols))

    # convert to original feature scale
    coef_raw_vals = (coef_std.values / sigma).astype(float)
    b0_raw = float(b0_std - np.sum(coef_std.values * mu / sigma))

    coef_std_dict = {c: float(v) for c, v in zip(cols, coef_std.values)}
    coef_raw_dict = {c: float(v) for c, v in zip(cols, coef_raw_vals)}
    feature_means_dict = {c: float(m) for c, m in zip(cols, mu)}
    feature_scales_dict = {c: float(s) for c, s in zip(cols, sigma)}

    # human readable equation string (raw space, top 8 by |coef|)
    top_terms = sorted(coef_raw_dict.items(), key=lambda kv: abs(kv[1]), reverse=True)[:8]
    model_equation = "y = " + f"{b0_raw:+.6f} " + " ".join([f"{v:+.6f}·{k}" for k, v in top_terms])

    # --- Global R² ---
    oos_preds, metrics, _ = walk_forward_oos_eval(
        pooled_df,
        model_kind="enet",
        enet_alpha=alpha,
        enet_l1_ratio=l1_ratio,
        dropna_rows=False,
        min_train_rows=min_rows,
        val_rows=int(best_params['base_test_len_days'] // horizon),
        embargo_rows=int(best_params['base_test_len_days'] // horizon)
    )

    print(f"  ✓ Model trained with R²_global={metrics.get('R2_global')}")

    # --- Save shared stats (model-level summary) ---
    shared = FactorSharedStats.objects.create(
        created_at=timezone.now(),
        model_used="enet",
        r2_global=metrics.get("R2_global"),
        volatility_coeff=intercept,
        horizon_days=horizon,

        # new fields
        coef_std=coef_std_dict,         # keep standardized coefs for audit
        intercept_raw=b0_raw,           # raw intercept for human equation
        coef_raw=coef_raw_dict,         # raw coefs for UI
        feature_means=feature_means_dict,
        feature_scales=feature_scales_dict,
        model_equation=model_equation,

        # new config fields
        training_days=int(best_params.get("base_train_len_days", None)),
        testing_days=int(best_params.get("base_test_len_days", None)),
        enet_alpha=float(best_params.get("enet_alpha", None)),
        enet_l1_ratio=float(best_params.get("enet_l1_ratio", None)),
        oos_min_train_rows=int(best_params.get("oos_min_train_rows_fixed", None)),
        run_params={
            "base_train_len_days": int(best_params.get("base_train_len_days", 0)),
            "base_test_len_days":  int(best_params.get("base_test_len_days", 0)),
            "enet_alpha":          float(best_params.get("enet_alpha", 0.0)),
            "enet_l1_ratio":       float(best_params.get("enet_l1_ratio", 0.0)),
            "dropna_rows":         False,  # since you pass dropna_rows=False
        },

        **{f"coef_{k}": v for k, v in coeffs.items() if hasattr(FactorSharedStats, f"coef_{k}")},
        **{f"avg_{k}": pooled_df[k].mean() if k in pooled_df.columns else None
           for k in [c for c in enet_bundle['train_cols'] if hasattr(FactorSharedStats, f"avg_{c}")]},
    )

    # --- Save per-ticker OUT-OF-SAMPLE metrics for the frontend table ---
    from .models import StockOOSMetric

    # Defensive: skip if no OOS preds
    if oos_preds is not None and not oos_preds.empty:
        # Clean and aggregate per ticker
        oos_clean = oos_preds[['Ticker', 'actual_b', 'pred_b']].copy()
        oos_clean['actual_b'] = pd.to_numeric(oos_clean['actual_b'], errors='coerce')
        oos_clean['pred_b'] = pd.to_numeric(oos_clean['pred_b'], errors='coerce')
        oos_clean = oos_clean.replace([np.inf, -np.inf], np.nan).dropna()

        def safe_r2(g):
            if len(g) < 2 or np.std(g['actual_b']) < 1e-9:
                return np.nan
            try:
                return r2_score(g['actual_b'], g['pred_b'])
            except ValueError:
                return np.nan

        def rmse(g):
            if len(g) < 1:
                return np.nan
            return np.sqrt(mean_squared_error(g['actual_b'], g['pred_b']))

        def mae(g):
            if len(g) < 1:
                return np.nan
            return mean_absolute_error(g['actual_b'], g['pred_b'])

        def dir_acc(g):
            if len(g) < 1:
                return np.nan
            return float(np.mean(np.sign(g['actual_b']) == np.sign(g['pred_b'])))

        def pred_std(g):
            if len(g) < 1:
                return np.nan
            return float(np.std(g['pred_b']))

        agg = (
            oos_clean.groupby('Ticker')
            .apply(lambda g: pd.Series({
                'r2_oos': safe_r2(g),
                'rmse_oos': rmse(g),
                'mae_oos': mae(g),
                # simple MASE proxy: MAE divided by in-sample MAE baseline is not available here,
                # so keep NaN or compute a simple scale by MAE of a naive model if you have it.
                'mase_oos': np.nan,
                'diracc_oos': dir_acc(g),
                'predstd_oos': pred_std(g),
                'n_oos': int(len(g)),
            }))
            .reset_index()
            .rename(columns={'Ticker': 'ticker'})
        )

        # Optional: drop very small n
        # agg = agg[agg['n_oos'] >= 10]

        # Replace existing rows for this shared run to avoid duplicates on rerun
        StockOOSMetric.objects.filter(shared_stats=shared).delete()

        # Bulk insert into the table the frontend endpoint reads
        rows = [
            StockOOSMetric(
                shared_stats=shared,
                ticker=row['ticker'],
                horizon_days=horizon,
                r2_oos=None if pd.isna(row['r2_oos']) else float(row['r2_oos']),
                rmse_oos=None if pd.isna(row['rmse_oos']) else float(row['rmse_oos']),
                mae_oos=None if pd.isna(row['mae_oos']) else float(row['mae_oos']),
                mase_oos=None if pd.isna(row['mase_oos']) else float(row['mase_oos']),
                diracc_oos=None if pd.isna(row['diracc_oos']) else float(row['diracc_oos']),
                predstd_oos=None if pd.isna(row['predstd_oos']) else float(row['predstd_oos']),
                n_oos=int(row['n_oos']),
            )
            for _, row in agg.iterrows()
        ]
        if rows:
            StockOOSMetric.objects.bulk_create(rows, batch_size=1000)

    # --- ✅ NEW: Generate rolling time series predictions ---
    print("📈 Generating rolling stock time series for visualization...")

    rolling_df = pooled_df.sort_values(["Ticker", "Date"])
    stock_objs = []

    for ticker, group in rolling_df.groupby("Ticker"):
        try:
            X = group[enet_bundle["train_cols"]].replace([np.inf, -np.inf], np.nan).fillna(0.0)
            preds = pipeline.predict(X)

            # ✅ Safer: use enumerate so we don’t depend on DataFrame index alignment
            for j, (idx, row) in enumerate(group.iterrows()):
                if j >= len(preds):
                    # Skip if predictions shorter than group (edge cases)
                    break

                stock_objs.append(StockFactorResult(
                    created_at=row["Date"],
                    ticker=ticker,
                    shared_stats=shared,
                    horizon_days=horizon,
                    b_coefficient=float(preds[j]),
                    y_intercept=intercept,
                    volatility=row.get("vol_63d") or row.get("vol_126d"),
                    xsec_disp_1d=row.get("xsec_disp_1d"),
                    xsec_disp_30d=row.get("xsec_disp_30d"),
                    **{k: row.get(k) for k in [
                        "train_b", "lag_train_b", "ar1_corr_10d", "ar1_corr_20d", "ar1_corr_60d",
                        "sign_persist_20d", "sign_persist_60d", "ret_1d", "ret_5d", "ret_20d",
                        "vol_63d", "vol_126d", "vol_252d", "vol_756d", "Z_ma_20d",
                        "cs_rank_ret_1d", "cs_rank_ret_5d", "cs_rank_ret_20d", "cs_rank_z_ma_20d",
                        "cs_rank_vol_63d", "cs_rank_vol_126d", "cs_rank_vol_252d", "cs_rank_vol_756d",
                    ]}
                ))
        except IndexError as e:
            print(f"⚠️ Skipped {ticker} due to index mismatch: {e}")
        except Exception as e:
            print(f"⚠️ Unexpected error for {ticker}: {e}")

    StockFactorResult.objects.bulk_create(stock_objs, batch_size=1000)
    print(f"  ✓ Saved {len(stock_objs)} rolling predictions across {rolling_df['Ticker'].nunique()} tickers.")

    print(f"  ✓ Model snapshot complete — shared_stats_id={shared.id}")
    return {"ok": True, "shared_stats_id": shared.id, "tickers_saved": rolling_df['Ticker'].nunique()}

# --- Worker Function for Horizons ---
def run_pipeline_for_horizon(
        horizon: int,
        mxus_returns_data: pd.DataFrame,
        market_features_data: pd.DataFrame,
        all_tickers: List[str],
        max_workers_data_prep: int,
        fixed_params: Dict
) -> int:  # Return the horizon to confirm completion
    """
    Runs the full data-prep and final-model pipeline for a single horizon
    using a fixed set of parameters.
    This function is designed to be run in parallel for each horizon.
    """
    print(f"\n{'=' * 60}\nSTARTING PIPELINE FOR HORIZON: {horizon} DAY(S)\n{'=' * 60}")
    print(f"  [H={horizon}d] Using {max_workers_data_prep} workers for data preparation.")

    try:
        # 1. Get fixed params
        base_train_len = fixed_params['base_train_len_days']
        base_test_len = fixed_params['base_test_len_days']
        alpha = fixed_params['enet_alpha']
        l1_ratio = fixed_params['enet_l1_ratio']
        min_train_rows = fixed_params['oos_min_train_rows_fixed']

        # 2. Run parallel data prep
        print(f"  [H={horizon}d] Running parallel data prep...")
        final_pooled_df = run_parallel_data_prep(
            mxus_returns=mxus_returns_data,
            market_features=market_features_data,
            tickers=all_tickers,
            horizon=horizon,
            base_train_len=base_train_len,
            base_test_len=base_test_len,
            max_workers=max_workers_data_prep
        )

        if final_pooled_df is None or final_pooled_df.empty:
            print(f"  [H={horizon}d] ❌ FAILED: No data generated from run_parallel_data_prep. Skipping.")
            return horizon

        print(f"  [H={horizon}d] Data prep complete. {len(final_pooled_df)} rows.")

        # 3. Create the 'best_params' series needed by the save function
        best_params_series = pd.Series({
            'base_train_len_days': base_train_len,
            'base_test_len_days': base_test_len,
            'enet_alpha': alpha,
            'enet_l1_ratio': l1_ratio,
            'oos_min_train_rows_fixed': min_train_rows
        })

        # 4. Train and Save Final Model & Artifacts
        print(f"  [H={horizon}d] Training final model and saving artifacts...")
        train_final_model_and_save(
            pooled_df=final_pooled_df,
            best_params=best_params_series,
            horizon=horizon
        )

        print(f"\n{'=' * 60}\nCOMPLETED PIPELINE FOR HORIZON: {horizon} DAY(S)\n{'=' * 60}")
        return horizon

    except Exception as e:
        print(f"  [H={horizon}d] ❌ PIPELINE FAILED with exception: {e}")
        traceback.print_exc()
        return horizon


if __name__ == "__main__":

    # --- 1. Load Data ---
    # !!! EDIT YOUR PATH HERE !!!
    MXUS_XLSX_PATH = "Josh_Data/MXUS_Data.xlsx"
    MXUS_RETURNS_SHEET = "Returns"

    print("Loading data...")
    mxus_returns = load_mxus_returns(MXUS_XLSX_PATH, sheet=MXUS_RETURNS_SHEET)
    for c in mxus_returns.columns:
        if c != "Date":
            mxus_returns[c] = pd.to_numeric(mxus_returns[c], errors="coerce")

    tickers = [col for col in mxus_returns.columns if col != "Date"]
    print(f"Data loaded. Found {len(tickers)} tickers.")

    # --- 2. Calculate Market-Wide Features (Once) ---
    print("Calculating market-wide features...")
    market_features = pd.DataFrame(index=mxus_returns['Date'])
    market_features.index.name = "Date"

    # Calculate xsec_disp_30d
    xsec_disp_1d = mxus_returns[tickers].std(axis=1)
    xsec_disp_30d = xsec_disp_1d.rolling(30, min_periods=10).mean()
    market_features['xsec_disp_30d'] = xsec_disp_30d.values
    market_features['xsec_disp_1d'] = xsec_disp_1d.values
    market_features = market_features.reset_index()
    print("  ✓ Market features calculated.")

    # --- 3. Define FIXED Parameters (No Grid Search) ---
    # !!! EDIT YOUR PARAMETERS HERE !!!
    FIXED_PARAMS = {
        # Data-Generation Params
        'base_train_len_days': 756,  # ~3 years
        'base_test_len_days': 252,  # ~6 months <-- *** WARNING: MAY BE TOO SHORT FOR H=10 & H=20 ***

        # Model Hyperparameters
        'enet_alpha': 0.003,
        'enet_l1_ratio': 0.2,

        # OOS Evaluation Params
        'oos_min_train_rows_fixed': 5000  # Min rows for first OOS fold
    }

    # --- *** WARNING: CHECK YOUR PARAMETERS *** ---
    print(f"\n{'!' * 80}")
    print(f"WARNING: Using fixed parameters: {FIXED_PARAMS}")
    print(f"Your `base_test_len_days` is {FIXED_PARAMS['base_test_len_days']}.")
    print("If this is too short (e.g., < 252), the 10d and 20d horizons may fail.")
    print(f"Recommend setting `base_test_len_days` to 252 or more.")
    print(f"{'!' * 80}\n")
    # --- *** END WARNING *** ---

    # Horizons to run for
    HORIZONS_IN_DAYS = [1, 5, 10, 20]

    # --- 4. Define Parallelism Settings ---
    total_cpus = os.cpu_count()
    cores_to_use = max(1, total_cpus - 1)  # Leave 1 core free
    n_horizons = len(HORIZONS_IN_DAYS)

    # Cap main pool at number of horizons.
    max_workers_main_pool = min(n_horizons, cores_to_use)

    # Divide remaining cores among the horizon jobs
    workers_per_horizon_job = max(1, cores_to_use // max(1, max_workers_main_pool))

    print(f"\n--- Parallel Execution Plan ---")
    print(f"Total logical cores: {total_cpus}")
    print(f"Cores to use (Total - 2): {cores_to_use}")
    print(f"Horizons to run: {n_horizons} ({HORIZONS_IN_DAYS})")
    print(f"Main parallel pool (for horizons): {max_workers_main_pool} workers")
    print(f"Sub-pool (for tickers): {workers_per_horizon_job} workers per horizon job")
    print(f"---------------------------------")

    # --- 5. Run the Pipeline in Parallel for Each Horizon ---
    global_start_time = time.time()
    print(f"Starting parallel pipeline run for {n_horizons} horizons...")

    with ProcessPoolExecutor(max_workers=max_workers_main_pool) as executor:
        futures = []
        for horizon in HORIZONS_IN_DAYS:
            futures.append(
                executor.submit(
                    run_pipeline_for_horizon,
                    horizon,
                    mxus_returns,
                    market_features,
                    tickers,
                    workers_per_horizon_job,  # Pass the allocated sub-worker count
                    FIXED_PARAMS
                )
            )

        for future in as_completed(futures):
            try:
                result_horizon = future.result()
                print(f"  ✓ Future completed for horizon: {result_horizon}")
            except Exception as e:
                print(f"  ❌ A horizon job failed: {e}")
                traceback.print_exc()

    global_end_time = time.time()
    print(f"\n{'=' * 80}\nALL PIPELINES COMPLETE\n{'=' * 80}")
    print(f"Total execution time: {global_end_time - global_start_time:.2f} seconds.")
    print("Script finished.")