# filepath: b_forecast_pipeline_pooled_fixed_parallel_v6.py
# -*- coding: utf-8 -*-
"""
Predicting future b with a pooled ElasticNet model using FIXED parameters.
- Layer 1 (Outer Parallel): Run the full pipeline for each horizon (1d, 5d, etc.) in parallel.
- Layer 2 (Inner Parallel): For each horizon, run parallel data prep to create a single "pooled" learning table.
- Layer 3: Walk-forward OOS evaluation using the pooled data and fixed params.
- Layer 4: Save artifacts (ONLY the actual-vs-predicted plot + R²-over-time plot) and RETURN dictionaries (no CSVs).

This version:
- Returns JSON-ready dictionaries (no CSVs anywhere).
- Saves exactly two plots per horizon:
  (1) oos_pred_vs_actual.png
  (2) oos_r2_over_time.png
- Excludes from the returned dictionary:
  * OOS prediction table
  * Pooled learning table
  * oos_fold_stats
- Includes in the returned dictionary:
  * oos_metrics
  * per_stock_metrics
  * enet_coefficients (non-zero)
  * enet_intercept (float)
  * model_equation (string)
  * final_predictions (per-ticker next-period prediction + **ALL predictor values**)
  * artifacts (plot paths)
"""
from __future__ import annotations
import warnings
warnings.filterwarnings("ignore")

from typing import Optional, List, Tuple, Dict
from pathlib import Path
import traceback
import time
import os
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

import statsmodels.api as sm
from statsmodels.tsa.arima.model import ARIMA

from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import ElasticNet
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

# =========================
# Output paths (next to this file)
# =========================
SCRIPT_DIR  = Path(__file__).resolve().parent
OUTPUT_ROOT = SCRIPT_DIR / "PLOTS"
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
            date_col = c; break
    if date_col is None:
        for c in df.columns:
            if "date" in str(c).strip().lower():
                date_col = c; break
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
                try: return float(s[:-1]) / 100.0
                except: return np.nan
            try: return float(s)
            except: return np.nan
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

    ticker_cols = [c for c in daily_returns.columns if c != "Date"]

    period_returns = (1 + daily_returns[ticker_cols]).rolling(
        window=period_days,
        min_periods=period_days
    ).apply(np.prod, raw=True) - 1

    non_overlapping = period_returns.iloc[period_days-1::period_days].reset_index(drop=True)
    non_overlapping["Date"] = daily_returns["Date"].iloc[period_days-1::period_days].reset_index(drop=True)
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
    return float(num / den) if den and np.isfinite(num/den) else np.nan

def rich_features_from_returns(wide_returns: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if ticker not in wide_returns.columns:
        raise ValueError(f"Ticker {ticker} not found in returns.")

    df = wide_returns[["Date", ticker]].rename(columns={ticker: "ret"}).copy()
    df = df.sort_values("Date").reset_index(drop=True)

    # AR(1) correlations
    df["ar1_corr_10d"] = df["ret"].rolling(10, min_periods=6).apply(_rolling_acf1, raw=True)
    df["ar1_corr_20d"] = df["ret"].rolling(20, min_periods=10).apply(_rolling_acf1, raw=True)
    df["ar1_corr_60d"] = df["ret"].rolling(60, min_periods=20).apply(_rolling_acf1, raw=True)

    # Sign persistence
    def sign_persist(x):
        x = np.asarray(x, dtype=float)
        if x.size < 2: return np.nan
        s = np.sign(x)
        return float(np.nanmean(s[1:] == s[:-1]))
    df["sign_persist_20d"] = df["ret"].rolling(20, min_periods=10).apply(sign_persist, raw=False)
    df["sign_persist_60d"] = df["ret"].rolling(60, min_periods=20).apply(sign_persist, raw=False)

    # Recent returns
    df["ret_1d"]  = df["ret"]
    df["ret_5d"]  = df["ret"].rolling(5, min_periods=3).sum()
    df["ret_20d"] = df["ret"].rolling(20, min_periods=10).sum()

    # Volatility
    df["vol_63d"]  = df["ret"].rolling(63,   min_periods=30).std()
    df["vol_126d"] = df["ret"].rolling(126,  min_periods=60).std()
    df["vol_252d"] = df["ret"].rolling(252,  min_periods=120).std()
    df["vol_756d"] = df["ret"].rolling(756,  min_periods=252).std()

    # Moving-average Z of reconstructed price
    price = (1.0 + df["ret"].fillna(0)).cumprod()
    ma20  = price.rolling(20, min_periods=10).mean()
    sd20  = price.rolling(20, min_periods=10).std()
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

    ret5  = wide_returns[cols].rolling(5,  min_periods=3).sum()
    ret20 = wide_returns[cols].rolling(20, min_periods=10).sum()
    ret5.insert(0, "Date", wide_returns["Date"].values)
    ret20.insert(0, "Date", wide_returns["Date"].values)

    prices = (1.0 + wide_returns[cols].fillna(0)).cumprod()
    ma20   = prices.rolling(20, min_periods=10).mean()
    sd20   = prices.rolling(20, min_periods=10).std()
    zma20  = (prices - ma20) / sd20
    zma20.insert(0, "Date", wide_returns["Date"].values)

    vol63  = wide_returns[cols].rolling(63,   min_periods=30).std()
    vol126 = wide_returns[cols].rolling(126,  min_periods=60).std()
    vol252 = wide_returns[cols].rolling(252,  min_periods=120).std()
    vol756 = wide_returns[cols].rolling(756,  min_periods=252).std()
    vol63.insert(0, "Date", wide_returns["Date"].values)
    vol126.insert(0, "Date", wide_returns["Date"].values)
    vol252.insert(0, "Date", wide_returns["Date"].values)
    vol756.insert(0, "Date", wide_returns["Date"].values)

    r1  = _cs_percentile_rank_wide(wide1, ticker)
    r5  = _cs_percentile_rank_wide(ret5,  ticker)
    r20 = _cs_percentile_rank_wide(ret20, ticker)
    rz  = _cs_percentile_rank_wide(zma20, ticker)
    rv63  = _cs_percentile_rank_wide(vol63,  ticker)
    rv126 = _cs_percentile_rank_wide(vol126, ticker)
    rv252 = _cs_percentile_rank_wide(vol252, ticker)
    rv756 = _cs_percentile_rank_wide(vol756, ticker)

    out = out.merge(r1.rename("cs_rank_ret_1d").reset_index(),  on="Date", how="left")
    out = out.merge(r5.rename("cs_rank_ret_5d").reset_index(),  on="Date", how="left")
    out = out.merge(r20.rename("cs_rank_ret_20d").reset_index(), on="Date", how="left")
    out = out.merge(rz.rename("cs_rank_z_ma_20d").reset_index(), on="Date", how="left")
    out = out.merge(rv63.rename("cs_rank_vol_63d").reset_index(),   on="Date", how="left")
    out = out.merge(rv126.rename("cs_rank_vol_126d").reset_index(), on="Date", how="left")
    out = out.merge(rv252.rename("cs_rank_vol_252d").reset_index(), on="Date", how="left")
    out = out.merge(rv756.rename("cs_rank_vol_756d").reset_index(), on="Date", how="left")

    return out

# ==================================
# 3) b-ESTIMATION (ARIMA + FALLBACK)
# ==================================

def fit_arima_and_get_b(returns: pd.Series,
                        order=(1,0,0),
                        verbose=False) -> Optional[float]:
    """
    Return an AR(1)-style 'b' with robust fallbacks:
      1) ARIMA(order) → ar.L1 coefficient
      2) Lag-1 autocorrelation
    """
    r = returns.dropna().astype(float)
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

    # 2) Lag-1 autocorr
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
    arima_order=(1,0,0),
    min_train_obs: int = 20,
    min_test_obs: int = 10,
    verbose: bool = True
) -> pd.DataFrame:
    """
    Rolling windows:
      - Fit model on train → train_b
      - Fit model on test  → test_b
    Returns rows keyed by end-of-train Date and Ticker.
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
        return pd.DataFrame(columns=["Date","Ticker","train_b","test_b","train_start_idx",
                                     "train_end_idx","test_start_idx","test_end_idx","lag_train_b"])

    ret   = ser["ret"].values
    dates = ser["Date"].values
    N = len(ser)
    if N < (train_len + test_len):
        if verbose: print(f"[{ticker}] Not enough rows: have {N}, need {train_len + test_len}.")
        return pd.DataFrame(columns=["Date","Ticker","train_b","test_b","train_start_idx",
                                     "train_end_idx","test_start_idx","test_end_idx","lag_train_b"])

    rows, attempted, kept = [], 0, 0
    i = 0
    while i + train_len + test_len <= N:
        tr = slice(i, i + train_len)
        te = slice(i + train_len, i + train_len + test_len)
        train_returns = pd.Series(ret[tr])
        test_returns  = pd.Series(ret[te])

        if train_returns.dropna().shape[0] < min_train_obs or test_returns.dropna().shape[0] < min_test_obs:
            i += 1; continue

        attempted += 1
        b_train = fit_arima_and_get_b(train_returns, order=arima_order)
        b_test  = fit_arima_and_get_b(test_returns,  order=arima_order)

        if b_train is not None and b_test is not None:
            kept += 1
            rows.append({
                "Date": pd.to_datetime(dates[tr][-1]),
                "Ticker": ticker,
                "train_b": float(b_train),
                "test_b":  float(b_test),
                "train_start_idx": i,
                "train_end_idx": i + train_len - 1,
                "test_start_idx":  i + train_len,
                "test_end_idx":    i + train_len + test_len - 1
            })
        i += 1

    out = pd.DataFrame(rows)
    if out.empty:
        if verbose:
            print(f"[{ticker}] No valid b coefficients kept (attempted windows: {attempted}, kept: {kept}).")
        return pd.DataFrame(columns=["Date","Ticker","train_b","test_b","train_start_idx",
                                     "train_end_idx","test_start_idx","test_end_idx","lag_train_b"])

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
    feat_cols = [c for c in feature_frame.columns if c not in ["Date","Ticker","ret"]]
    merged = b_pairs.merge(feature_frame[["Date","Ticker"] + feat_cols], on=["Date","Ticker"], how="left")
    if market_features is not None and not market_features.empty:
        merged = merged.merge(market_features, on="Date", how="left")
    return merged.dropna(subset=["train_b","test_b"])

_FEATURE_PREFIXES = [
    "train_b", "lag_train_b",
    "vol_", "perf_", "absret_mean_", "acf1_",
    "ar1_corr_", "sign_persist_", "ret_", "Z_ma_", "cs_rank_",
    "xsec_disp_"
]

def get_feature_cols(df: pd.DataFrame) -> List[str]:
    return [c for c in df.columns if any(c.startswith(p) for p in _FEATURE_PREFIXES) and c != "ret"]

def build_training_matrices(learning_df: pd.DataFrame, dropna_rows: bool = True) -> Tuple[pd.DataFrame, pd.Series, List[str]]:
    feats = get_feature_cols(learning_df)
    if not feats:
        raise ValueError("No feature columns matched. Ensure at least ['train_b','lag_train_b'] exist.")

    df = learning_df.copy()

    if dropna_rows:
        df = df.dropna(subset=["test_b"] + feats)
    else:
        df[feats] = df[feats].replace([np.inf, -np.inf], np.nan).fillna(0.0)
        df = df.dropna(subset=["test_b"])

    if df.empty:
        raise ValueError("Training data is empty after NA handling.")

    X = df[feats].copy()
    y = df["test_b"].astype(float).copy()
    return X, y, feats

def train_final_model_bundle(learning_df: pd.DataFrame,
                             alpha: float = 0.01,
                             l1_ratio: float = 0.5,
                             dropna_rows: bool = True) -> Dict:
    X_train, y_train, feats = build_training_matrices(learning_df, dropna_rows=dropna_rows)

    pipe = Pipeline([
        ('scaler', StandardScaler(with_mean=True, with_std=True)),
        ('model',  ElasticNet(alpha=alpha, l1_ratio=l1_ratio, max_iter=10000))
    ])
    pipe.fit(X_train, y_train)

    return {
        "pipe": pipe,
        "train_cols": X_train.columns.tolist(),
        "feature_cols": feats
    }

def align_to_training_schema(X_new: pd.DataFrame, train_cols: List[str]) -> pd.DataFrame:
    return X_new.reindex(columns=train_cols, fill_value=0.0)

def compute_feature_training_means(pooled_df: pd.DataFrame, train_cols: List[str]) -> Dict[str, float]:
    """
    Compute per-feature averages on the *training matrix* for this horizon.
    Mirrors training NA handling (fillna(0.0)) and uses the same schema.
    """
    X = pooled_df[train_cols].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    means = X.mean(numeric_only=True).astype(float).to_dict()
    return means

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
    dropna_rows: bool = True,
    min_train_rows: int = 80,
    val_rows: int = 20,
    embargo_rows: int = 0
) -> Tuple[pd.DataFrame, Dict[str, float], pd.DataFrame]:
    """
    Expanding-window walk-forward CV with optional purge/embargo.
    Respects schema freeze per fold (ElasticNet) and OLS fitted features per fold.
    Returns (oos_predictions_df, metrics_dict, fold_stats_df).
    """
    df = learning_df.sort_values("Date").reset_index(drop=True).copy()
    feats = get_feature_cols(df)
    
    # --- Empty placeholders ---
    empty_preds = pd.DataFrame(columns=["Date","Ticker","actual_b","pred_b","fold", "n_train"])
    empty_metrics = {"MAE": np.nan, "RMSE": np.nan, "R2": np.nan, "DirectionalAcc": np.nan, "N": 0}
    empty_fold_stats = pd.DataFrame(columns=["fold", "n_pred", "n_train", "r2", "end_date"])
    
    if len(df) < (min_train_rows + embargo_rows + max(1, val_rows)):
        return empty_preds, empty_metrics, empty_fold_stats

    preds = []
    train_end = min_train_rows - 1
    fold = 0
    N = len(df)

    while True:
        val_start = train_end + 1 + max(0, embargo_rows)
        val_end   = val_start + val_rows - 1

        if val_end >= N:
            break  # no more complete validation blocks

        tr = df.iloc[:train_end+1].copy()
        va = df.iloc[val_start:val_end+1].copy()

        tr = tr.dropna(subset=["test_b"] + feats) if dropna_rows else tr.dropna(subset=["test_b"])
        n_train_rows = len(tr)
        if tr.empty:
            break

        # === Train per fold ===
        if model_kind.lower() == "enet":
            X_tr = tr[feats].copy()
            y_tr = tr["test_b"].astype(float).values
            pipe = Pipeline([
                ('scaler', StandardScaler(with_mean=True, with_std=True)),
                ('model',  ElasticNet(alpha=enet_alpha, l1_ratio=enet_l1_ratio, max_iter=10000))
            ])
            pipe.fit(X_tr, y_tr)
            train_cols = X_tr.columns.tolist()

            # Validate
            if dropna_rows:
                va = va.dropna(subset=["test_b"] + feats)
            else:
                va[feats] = va[feats].replace([np.inf, -np.inf], np.nan).fillna(0.0)
                va = va.dropna(subset=["test_b"])
            if not va.empty:
                X_va = align_to_training_schema(va[feats].copy(), train_cols)
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
            X_tr = sm.add_constant(tr[feats].copy(), has_constant="add")
            y_tr = tr["test_b"].astype(float).values
            ols = sm.OLS(y_tr, X_tr).fit()

            if dropna_rows:
                va = va.dropna(subset=["test_b"] + feats)
            else:
                va[feats] = va[feats].replace([np.inf, -np.inf], np.nan).fillna(0.0)
                va = va.dropna(subset=["test_b"])
            if not va.empty:
                X_va = sm.add_constant(va[feats], has_constant="add")
                y_hat = ols.predict(X_va).values
                preds.append(pd.DataFrame({
                    "Date": va["Date"].values,
                    "Ticker": va["Ticker"].values,
                    "actual_b": va["test_b"].values,
                    "pred_b": y_hat,
                    "fold": fold,
                    "n_train": n_train_rows
                }))

        # Expand window
        train_end = val_end
        fold += 1

    if not preds:
        return empty_preds, empty_metrics, empty_fold_stats

    # === Combine and compute metrics ===
    oos = pd.concat(preds, ignore_index=True)
    oos = oos.sort_values("Date").reset_index(drop=True)

    m = _calc_metrics(oos["actual_b"].values, oos["pred_b"].values)

    # --- Per-fold R²s ---
    fold_stats = []
    for f, df_f in oos.groupby("fold"):
        if len(df_f) >= 2:
            try:
                r2_f = r2_score(df_f["actual_b"].values, df_f["pred_b"].values)
                n_train_weight = df_f["n_train"].iloc[0]
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
        n_tot_weight = fold_stats_df["n_train"].sum()
        r2_fold_mean = float(fold_stats_df["r2"].mean())
        r2_fold_weighted = (
            float((fold_stats_df["r2"] * fold_stats_df["n_train"]).sum() / n_tot_weight)
            if n_tot_weight > 0 else np.nan
        )
    else:
        r2_fold_mean = r2_fold_weighted = np.nan

    m["R2_global"] = m.pop("R2")
    m["R2_fold_mean"] = r2_fold_mean
    m["R2_fold_weighted"] = r2_fold_weighted

    return oos, m, fold_stats_df

# =========================
# 5) PLOTTING (Actual vs Predicted + R²-over-time)
# =========================
def plot_pred_vs_actual(df: pd.DataFrame, outpath: str, title: str = "Predicted vs Actual b"):
    """
    Scatter of predicted vs actual with 45° line and an OLS fit line.
    """
    if df is None or df.empty or not {"actual_b", "pred_b"}.issubset(df.columns):
        print("  No data to plot (pred vs actual).")
        return

    clean = df.dropna(subset=["actual_b", "pred_b"])
    if len(clean) > 50000:
        clean = clean.sample(50000, random_state=42).copy()

    if clean.empty:
        print("  No rows after NA drop (pred vs actual).")
        return

    x = clean["actual_b"].values
    y = clean["pred_b"].values

    try:
        X = sm.add_constant(x)
        lin = sm.OLS(y, X).fit()
        xgrid = np.linspace(np.nanmin(x), np.nanmax(x), 200)
        yhat  = lin.predict(sm.add_constant(xgrid))
    except Exception:
        xgrid, yhat = None, None

    lo = float(np.nanmin(np.concatenate([x, y])))
    hi = float(np.nanmax(np.concatenate([x, y])))
    lo = lo - abs(lo * 0.1) if lo != 0 else -0.1
    hi = hi + abs(hi * 0.1) if hi != 0 else 0.1
    if lo >= hi:
        lo, hi = hi - 0.1, lo + 0.1

    plt.figure(figsize=(6,5))
    plt.scatter(x, y, alpha=0.2, s=10, rasterized=True)
    plt.plot([lo, hi], [lo, hi], linestyle="--", linewidth=1, label="45° line")
    if xgrid is not None and yhat is not None:
        plt.plot(xgrid, yhat, linewidth=2, label="OLS fit")
    plt.xlabel("Actual b")
    plt.ylabel("Predicted b")
    plt.title(title)
    plt.xlim(lo, hi)
    plt.ylim(lo, hi)
    plt.legend()
    plt.tight_layout()
    plt.savefig(outpath, dpi=140)
    plt.close()

def plot_r2_over_time(fold_stats_df: pd.DataFrame, outpath: str, title: str = "OOS R-squared Over Time (by Fold)"):
    """
    Plots the R-squared for each fold against the fold's end date.
    """
    if fold_stats_df is None or fold_stats_df.empty or "r2" not in fold_stats_df or "end_date" not in fold_stats_df:
        print("  No R2-over-time data to plot.")
        return

    df_plot = fold_stats_df.dropna(subset=["r2", "end_date"]).sort_values("end_date")
    if df_plot.empty:
        print("  No valid R2-over-time rows after NA drop.")
        return

    plt.figure(figsize=(10, 5))
    plt.plot(df_plot["end_date"], df_plot["r2"], marker='o', linestyle='-', markersize=5)
    plt.axhline(0, color='k', linestyle='--', linewidth=0.8)
    plt.title(title)
    plt.xlabel("Fold End Date")
    plt.ylabel("Fold R-squared")
    plt.grid(axis='y', linestyle=':', alpha=0.7)
    plt.tight_layout()
    plt.savefig(outpath, dpi=140)
    plt.close()

# =========================
# 6) DICT HELPERS (no CSV writes)
# =========================

def per_stock_metrics_as_dict(oos_preds_df: pd.DataFrame) -> List[Dict]:
    """
    Returns per-stock OOS metrics (R2, RMSE, MAE, MASE, DirAcc, N) as a list of dicts.
    """
    if oos_preds_df is None or oos_preds_df.empty or not {'Ticker','actual_b','pred_b'}.issubset(oos_preds_df.columns):
        return []

    oos_clean = oos_preds_df[['Ticker','actual_b','pred_b']].copy()
    oos_clean['actual_b'] = pd.to_numeric(oos_clean['actual_b'], errors='coerce')
    oos_clean['pred_b']   = pd.to_numeric(oos_clean['pred_b'], errors='coerce')
    oos_clean = oos_clean.replace([np.inf, -np.inf], np.nan).dropna().sort_values(["Ticker"]).reset_index(drop=True)
    if oos_clean.empty:
        return []

    rows = []
    for name, g in oos_clean.groupby('Ticker'):
        if len(g) == 0:
            continue

        # R2 safe
        r2 = np.nan
        try:
            if len(g) > 1 and np.std(g['actual_b']) >= 1e-9:
                r2 = float(r2_score(g['actual_b'], g['pred_b']))
        except Exception:
            r2 = np.nan

        rmse = float(np.sqrt(mean_squared_error(g['actual_b'], g['pred_b'])))
        mae  = float(mean_absolute_error(g['actual_b'], g['pred_b']))

        # MASE (naive = lag-1 of actual)
        if len(g) > 1:
            mae_naive = float(mean_absolute_error(g['actual_b'].iloc[1:], g['actual_b'].shift(1).iloc[1:]))
            mase = (mae / mae_naive) if mae_naive != 0 else np.nan
        else:
            mase = np.nan

        dir_acc = float(np.mean(np.sign(g['actual_b']) == np.sign(g['pred_b'])))

        rows.append({
            "Ticker": name,
            "R2_OOS": r2,
            "RMSE_OOS": rmse,
            "MAE_OOS": mae,
            "MASE_OOS": mase,
            "DirAcc_OOS": dir_acc,
            "N_OOS": int(len(g))
        })
    return rows

def generate_final_predictions_dict(
    enet_bundle: Dict,
    pooled_df: pd.DataFrame,
    used_feature_names: Optional[List[str]] = None,
    include_all_features: bool = False,
) -> List[Dict]:
    """
    Returns the latest per-ticker prediction, plus feature values.
    - By default, includes only features with non-zero coefficients (used_feature_names).
    - Set include_all_features=True to include every feature in the training schema.
    """
    try:
        train_cols = enet_bundle['train_cols']
        pipe = enet_bundle['pipe']

        latest_features = pooled_df.sort_values('Date').groupby('Ticker').last().reset_index()
        if latest_features.empty:
            return []

        X_pred = latest_features[train_cols].replace([np.inf, -np.inf], np.nan).fillna(0.0)
        preds = pipe.predict(X_pred)

        # Decide which features to attach
        if include_all_features or not used_feature_names:
            feature_cols_to_keep = train_cols
        else:
            feature_cols_to_keep = [c for c in used_feature_names if c in train_cols]

        out = []
        for i, row in latest_features.iterrows():
            dt = pd.to_datetime(row["Date"])
            rec = {
                "Ticker": row["Ticker"],
                "Date": dt.isoformat(),
                "final_prediction": float(preds[i]),
                "features": {col: float(X_pred.iloc[i][col]) for col in feature_cols_to_keep}
            }
            out.append(rec)
        return out

    except Exception as e:
        print(f"  ❌ FAILED to produce final predictions dict with features: {e}")
        traceback.print_exc()
        return []

# =========================
# 7) ORCHESTRATION (POOLING)
# =========================

def generate_single_ticker_learning_table(
    ticker: str,
    returns_for_b: pd.DataFrame,
    daily_returns_for_features: pd.DataFrame,
    market_features: pd.DataFrame,
    train_len_periods: int,
    test_len_periods: int,
    arima_order: Tuple[int,int,int] = (1,0,0),
    min_train_obs_b: Optional[int] = None,
    verbose: bool = False
) -> Optional[pd.DataFrame]:

    min_obs_guard = (min_train_obs_b if (min_train_obs_b is not None)
                     else max(10, min(train_len_periods, test_len_periods)))

    b_pairs = historical_b(
        daily_returns=returns_for_b,
        ticker=ticker,
        train_len=train_len_periods,
        test_len=test_len_periods,
        arima_order=arima_order,
        min_train_obs=min_obs_guard,
        min_test_obs=10,
        verbose=verbose
    )
    if b_pairs.empty:
        if verbose: print(f"[{ticker}] No valid b pairs.")
        return None

    feat_df = rich_features_from_returns(daily_returns_for_features, ticker)
    feat_df = add_cross_sectional_ranks(daily_returns_for_features, feat_df, ticker)

    learning_df = assemble_learning_table(b_pairs, feat_df, market_features)
    if learning_df.empty:
        if verbose: print(f"[{ticker}] No valid learning table rows after merge/dropna.")
        return None

    return learning_df

def process_ticker_task_for_pooling(
    ticker: str,
    horizon: int,
    mxus_returns_data: pd.DataFrame,
    market_features_data: pd.DataFrame,
    base_train_len_days: int,
    base_test_len_days: int,
) -> Optional[pd.DataFrame]:
    try:
        period_returns_df = aggregate_to_period_returns(mxus_returns_data, period_days=horizon)
        train_len_periods = base_train_len_days // horizon
        test_len_periods  = base_test_len_days  // horizon
        if train_len_periods < 20 or test_len_periods < 2:
            return None

        learning_df = generate_single_ticker_learning_table(
            ticker=ticker,
            returns_for_b=period_returns_df,
            daily_returns_for_features=mxus_returns_data,
            market_features=market_features_data,
            train_len_periods=train_len_periods,
            test_len_periods=test_len_periods,
            arima_order=(1,0,0),
            min_train_obs_b=20,
            verbose=False
        )
        return learning_df
    except Exception:
        return None

def run_parallel_data_prep(
    mxus_returns: pd.DataFrame,
    market_features: pd.DataFrame,
    tickers: List[str],
    horizon: int,
    base_train_len: int,
    base_test_len: int,
    max_workers: int
) -> Optional[pd.DataFrame]:
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
            try:
                result_df = future.result()
                if result_df is not None and not result_df.empty:
                    all_learning_tables.append(result_df)
                if i % 100 == 0 or i == len(jobs):
                    print(f"  ... data prep progress: {i}/{len(jobs)} tickers processed")
            except Exception as e:
                print(f"  ❌ Error gathering result: {e}")

    if not all_learning_tables:
        print("  ⚠️ No learning tables generated. Skipping.")
        return None

    pooled_df = pd.concat(all_learning_tables, ignore_index=True).sort_values("Date").reset_index(drop=True)
    end_time = time.time()
    print(f"  ✓ Data Prep Complete. {len(pooled_df)} rows. ({end_time - start_time:.2f}s)")
    return pooled_df

# =========================
# 8) FINAL MODEL + RETURN DICTS (TWO PLOTS)
# =========================

def train_final_model_and_return_dicts(
    pooled_df: pd.DataFrame,
    best_params: pd.Series,
    horizon: int
) -> Dict:
    """
    Trains final model, evaluates OOS, saves:
      - oos_pred_vs_actual.png
      - oos_r2_over_time.png
    and returns JSON-ready dictionaries (without OOS table or fold stats).
    """
    print(f"\n--- Training Final Model for H={horizon}d ---")
    print("Using fixed params:\n", best_params)

    alpha    = float(best_params['enet_alpha'])
    l1_ratio = float(best_params['enet_l1_ratio'])
    min_rows = int(best_params.get('oos_min_train_rows_fixed', 5000))

    # Output dir per horizon (for the plots)
    out_prefix = f"POOLED_MODEL_{horizon}d"
    out_dir = OUTPUT_ROOT / out_prefix
    out_dir.mkdir(parents=True, exist_ok=True)

    # Train final ENET on all pooled data (impute NaNs with 0.0)
    try:
        enet_bundle = train_final_model_bundle(
            pooled_df,
            alpha=alpha,
            l1_ratio=l1_ratio,
            dropna_rows=False
        )
        print("  ✓ Final model trained.")
        # Per-feature averages on the exact training matrix/schema
        train_cols = enet_bundle["train_cols"]
        feature_training_means = compute_feature_training_means(pooled_df, train_cols)

    except Exception as e:
        print(f"  ❌ FINAL MODEL TRAINING FAILED: {e}")
        traceback.print_exc()
        return {"horizon": horizon, "error": str(e)}

    # OOS evaluation (for plots/metrics)
    print("  Running final OOS evaluation for plots/metrics...")
    try:
        test_len_periods = int(best_params['base_test_len_days'] // horizon)

        oos_preds, oos_metrics, oos_folds = walk_forward_oos_eval(
            learning_df=pooled_df,
            enet_alpha=alpha,
            enet_l1_ratio=l1_ratio,
            dropna_rows=False,
            min_train_rows=min_rows,
            val_rows=test_len_periods,
            embargo_rows=test_len_periods
        )

        # --- Plots we keep ---
        plot_pred_vs_actual(
            oos_preds,
            str(out_dir / "oos_pred_vs_actual.png"),
            title=f"POOLED H={horizon}d — OOS Predicted vs Actual b"
        )
        plot_r2_over_time(
            oos_folds,
            str(out_dir / "oos_r2_over_time.png"),
            title=f"POOLED H={horizon}d — OOS R² Over Time (by Fold)"
        )

        # Per-stock metrics and final predictions as dicts
        per_stock = per_stock_metrics_as_dict(oos_preds) if not oos_preds.empty else []

        # Coefficients (non-zero) + intercept and equation string
        trained_model = enet_bundle["pipe"].named_steps["model"]
        coeffs_series = pd.Series(trained_model.coef_, index=enet_bundle["train_cols"])
        used_coeffs_series = coeffs_series[coeffs_series.abs() > 1e-6].sort_values(key=abs, ascending=False)
        used_coeffs = used_coeffs_series.to_dict()
        intercept = float(trained_model.intercept_)
        equation = "b_pred = {:.6f}".format(intercept)
        for feat, beta in used_coeffs.items():
            sign = "+" if beta >= 0 else "-"
            equation += f" {sign} {abs(beta):.6f}*{feat}"

        # FINAL PREDICTIONS: include ALL features per stock
        final_preds = generate_final_predictions_dict(
            enet_bundle,
            pooled_df,
            used_feature_names=list(used_coeffs_series.index),
            include_all_features=True,   # include ALL predictors for each stock
        )

        results = {
            "horizon": int(horizon),
            "params": {
                "enet_alpha": alpha,
                "enet_l1_ratio": l1_ratio,
                "oos_min_train_rows_fixed": min_rows,
                "base_test_len_days": int(best_params['base_test_len_days'])
            },
            "feature_training_means": feature_training_means,  # dict: feature -> average (raw, pre-scaling)
            "oos_metrics": oos_metrics,                  # dict
            "per_stock_metrics": per_stock,              # list[dict]
            "enet_coefficients": used_coeffs,            # dict: feature -> coef (non-zero only)
            "enet_intercept": intercept,                 # float
            "model_equation": equation,                  # human-readable equation string
            "final_predictions": final_preds,            # list[dict]: includes ALL feature values
            "artifacts": {
                "oos_pred_vs_actual_png": str((out_dir / "oos_pred_vs_actual.png").resolve()),
                "oos_r2_over_time_png": str((out_dir / "oos_r2_over_time.png").resolve())
            }
        }
        print(f"  ✓ Artifacts saved (plots) and dicts prepared for H={horizon}d.")
        return results

    except Exception as e:
        print(f"  ❌ FAILED during final OOS eval/plotting/per-stock metrics: {e}")
        traceback.print_exc()
        return {"horizon": horizon, "error": str(e)}

# =========================
# 9) HORIZON RUNNER
# =========================

def run_pipeline_for_horizon(
    horizon: int,
    mxus_returns_data: pd.DataFrame,
    market_features_data: pd.DataFrame,
    all_tickers: List[str],
    max_workers_data_prep: int,
    fixed_params: Dict
) -> Dict:
    """
    Runs the full data-prep and final-model pipeline for a single horizon.
    Returns JSON-ready dictionaries (and saves only the two specified plots).
    """
    print(f"\n{'='*60}\nSTARTING PIPELINE FOR HORIZON: {horizon} DAY(S)\n{'='*60}")
    print(f"  [H={horizon}d] Using {max_workers_data_prep} workers for data preparation.")
    try:
        base_train_len = int(fixed_params['base_train_len_days'])
        base_test_len  = int(fixed_params['base_test_len_days'])
        alpha          = float(fixed_params['enet_alpha'])
        l1_ratio       = float(fixed_params['enet_l1_ratio'])
        min_train_rows = int(fixed_params['oos_min_train_rows_fixed'])

        # Parallel data prep
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
            return {"horizon": horizon, "error": "no_pooled_data"}

        print(f"  [H={horizon}d] Data prep complete. {len(final_pooled_df)} rows.")

        best_params_series = pd.Series({
            'base_train_len_days': base_train_len,
            'base_test_len_days':  base_test_len,
            'enet_alpha':          alpha,
            'enet_l1_ratio':       l1_ratio,
            'oos_min_train_rows_fixed': min_train_rows
        })

        print(f"  [H={horizon}d] Training final model and preparing dict outputs...")
        result = train_final_model_and_return_dicts(
            pooled_df=final_pooled_df,
            best_params=best_params_series,
            horizon=horizon
        )
        print(f"\n{'='*60}\nCOMPLETED PIPELINE FOR HORIZON: {horizon} DAY(S)\n{'='*60}")
        return result

    except Exception as e:
        print(f"  [H={horizon}d] ❌ PIPELINE FAILED with exception: {e}")
        traceback.print_exc()
        return {"horizon": horizon, "error": str(e)}

# =========================
# 10) MAIN
# =========================

if __name__ == "__main__":

    # --- 1. Load Data ---
    MXUS_XLSX_PATH     = "C:/Users/shawn/OneDrive/Documents/University of Auckland/YEAR 3/COMPSCI 399 - 2/Algo 2/MXUS_Data.xlsx"  # EDIT THIS PATH
    MXUS_RETURNS_SHEET = "Returns"

    print("Loading data...")
    mxus_returns = load_mxus_returns(MXUS_XLSX_PATH, sheet=MXUS_RETURNS_SHEET)
    for c in mxus_returns.columns:
        if c != "Date":
            mxus_returns[c] = pd.to_numeric(mxus_returns[c], errors="coerce")

    tickers = [col for col in mxus_returns.columns if col != "Date"]
    print(f"Data loaded. Found {len(tickers)} tickers.")

    # --- 2. Market-Wide Features ---
    print("Calculating market-wide features...")
    market_features = pd.DataFrame(index=mxus_returns['Date'])
    market_features.index.name = "Date"

    # Cross-sectional dispersion (30d)
    xsec_disp_1d = mxus_returns[tickers].std(axis=1)
    xsec_disp_30d = xsec_disp_1d.rolling(30, min_periods=10).mean()
    market_features['xsec_disp_30d'] = xsec_disp_30d.values
    market_features = market_features.reset_index()
    print("  ✓ Market features calculated.")

    # --- 3. Fixed Parameters ---
    # Hyperparameters
    FIXED_PARAMS = {
        'base_train_len_days': 756,   # ~3 years
        'base_test_len_days':  252,   # ~6 months
        'enet_alpha':    0.003,
        'enet_l1_ratio': 0.2,
        'oos_min_train_rows_fixed': 5000 # do not change this
    }

    print(f"\n{'!'*80}")
    print(f"WARNING: Using fixed parameters: {FIXED_PARAMS}")
    print("If base_test_len_days is too short for higher horizons (10d/20d), adjust accordingly.")
    print(f"{'!'*80}\n")

    # Horizons to run
    HORIZONS_IN_DAYS = [1, 5, 10, 20]

    # --- 4. Parallelism ---
    total_cpus = os.cpu_count()
    cores_to_use = max(1, total_cpus - 2) # Leave 2 cores free
    n_horizons = len(HORIZONS_IN_DAYS)

    max_workers_main_pool = min(n_horizons, cores_to_use)
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

    all_results = []
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
                    workers_per_horizon_job,
                    FIXED_PARAMS
                )
            )

        for future in as_completed(futures):
            try:
                result = future.result()
                all_results.append(result)
                hz = result.get("horizon", "?")
                err = result.get("error")
                print(f"  ✓ Future completed for horizon: {hz}" + (f" (error={err})" if err else ""))
            except Exception as e:
                print(f"  ❌ A horizon job failed: {e}")
                traceback.print_exc()

    global_end_time = time.time()
    print(f"\n{'='*80}\nALL PIPELINES COMPLETE\n{'='*80}")
    print(f"Total execution time: {global_end_time - global_start_time:.2f} seconds.")
    print("Script finished.")
    # all_results is a list of JSON-ready dicts you can serialize or return from an API
