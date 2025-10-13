# filepath: b_forecast_pipeline_extended.py
# -*- coding: utf-8 -*-
"""
Predicting future b with a regularized model (ElasticNet) built on top of AR(1)-style b extraction.
- Layer 1: ARIMA/AR(1) in rolling windows to compute train_b (past) and test_b (future realized)
- Layer 2: OLS + ElasticNet (pre-CV) to predict test_b from train_b and rich features

Shawna: edit the section under `if __name__ == "__main__":` to choose TICKER and settings.
"""
from __future__ import annotations
import warnings
warnings.filterwarnings("ignore")

from typing import Optional, List, Tuple, Dict
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

import statsmodels.api as sm
from statsmodels.tsa.arima.model import ARIMA

# NOTE: We use ElasticNet (pre-CV) instead of ElasticNetCV to avoid schema drift issues.
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import ElasticNet
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

# =========================
# Output paths (next to this file)
# =========================
SCRIPT_DIR  = Path(__file__).resolve().parent
OUTPUT_ROOT = SCRIPT_DIR / "Outputs"
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
    """
    Per-ticker features (daily returns table: Date + all tickers).
    Returns columns:
      ar1_corr_10d/20d/60d, sign_persist_20d/60d,
      ret_1d/5d/20d, vol_10d/20d, Z_ma_20d,
      cs_rank_ret_1d/5d/20d, cs_rank_z_ma_20d
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
    df["ret_1d"]  = df["ret"]
    df["ret_5d"]  = df["ret"].rolling(5, min_periods=3).sum()
    df["ret_20d"] = df["ret"].rolling(20, min_periods=10).sum()

    # --- Volatility ---
    df["vol_10d"] = df["ret"].rolling(10, min_periods=6).std()
    df["vol_20d"] = df["ret"].rolling(20, min_periods=10).std()

    # --- Moving-average Z of "price" reconstructed from returns ---
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

    r1  = _cs_percentile_rank_wide(wide1, ticker)
    r5  = _cs_percentile_rank_wide(ret5,  ticker)
    r20 = _cs_percentile_rank_wide(ret20, ticker)
    rz  = _cs_percentile_rank_wide(zma20, ticker)

    out = out.merge(r1.rename("cs_rank_ret_1d").reset_index(),  on="Date", how="left")
    out = out.merge(r5.rename("cs_rank_ret_5d").reset_index(),  on="Date", how="left")
    out = out.merge(r20.rename("cs_rank_ret_20d").reset_index(), on="Date", how="left")
    out = out.merge(rz.rename("cs_rank_z_ma_20d").reset_index(), on="Date", how="left")
    return out

# ==================================
# 3) b-ESTIMATION (ARIMA + FALLBACK)
# ==================================

def fit_arima_and_get_b(returns: pd.Series,
                        order=(1,0,0),
                        alpha=None,
                        lb_lags: List[int] = [],
                        verbose=False) -> Optional[float]:
    """
    Return an AR(1)-style 'b' with robust fallbacks:
      1) ARIMA(order) → ar.L1 coefficient
      2) OLS AR(1): r_t ~ r_{t-1}
      3) Lag-1 autocorrelation
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
    arima_order=(1,0,0),
    alpha: Optional[float] = None,
    lb_lags: List[int] = [],
    min_train_obs: int = 20,
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

        if train_returns.dropna().shape[0] < min_train_obs or test_returns.dropna().shape[0] < min_train_obs:
            i += 1; continue

        attempted += 1
        b_train = fit_arima_and_get_b(train_returns, order=arima_order, alpha=alpha, lb_lags=lb_lags)
        b_test  = fit_arima_and_get_b(test_returns,  order=arima_order, alpha=alpha, lb_lags=lb_lags)

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

def assemble_learning_table(b_pairs: pd.DataFrame, feature_frame: pd.DataFrame) -> pd.DataFrame:
    feat_cols = [c for c in feature_frame.columns if c not in ["Date","Ticker","ret"]]
    merged = b_pairs.merge(feature_frame[["Date","Ticker"] + feat_cols], on=["Date","Ticker"], how="left")
    return merged.dropna(subset=["train_b","test_b"])

# ---- Feature list helper (ensure consistent selection everywhere)

_FEATURE_PREFIXES = [
    "train_b", "lag_train_b",
    "vol_", "perf_", "absret_mean_", "acf1_",
    "ar1_corr_", "sign_persist_", "ret_", "Z_ma_", "cs_rank_"
]

def get_feature_cols(df: pd.DataFrame) -> List[str]:
    feats = [c for c in df.columns if any(c.startswith(p) for p in _FEATURE_PREFIXES) and c != "ret"]
    return feats

# ---- OLS

def fit_ols_predict_future_b(learning_df: pd.DataFrame) -> sm.regression.linear_model.RegressionResultsWrapper:
    candidates = get_feature_cols(learning_df)
    X = learning_df[candidates].copy()
    X = sm.add_constant(X, has_constant="add")
    y = learning_df["test_b"].values

    mask = ~np.isnan(X).any(axis=1)
    Xc = X.loc[mask]
    yc = y[mask.values] if hasattr(mask, "values") else y[mask]
    model = sm.OLS(yc, Xc).fit()
    return model

# ---- ElasticNet (pre-CV) with strict NA drop + schema freeze

def build_training_matrices(learning_df: pd.DataFrame, dropna_rows: bool = True) -> Tuple[pd.DataFrame, pd.Series, List[str]]:
    feats = get_feature_cols(learning_df)
    df = learning_df.copy()

    # Keep only rows with all features present if dropna_rows=True
    if dropna_rows:
        df = df.dropna(subset=["test_b"] + feats)
    else:
        df[feats] = df[feats].replace([np.inf, -np.inf], np.nan).fillna(0.0)
        df = df.dropna(subset=["test_b"])

    X = df[feats].copy()
    y = df["test_b"].astype(float).copy()

    return X, y, feats

def train_elasticnet_preCV(learning_df: pd.DataFrame,
                           alpha: float = 0.01,
                           l1_ratio: float = 0.5,
                           dropna_rows: bool = True) -> Dict:
    X_train, y_train, feats = build_training_matrices(learning_df, dropna_rows=dropna_rows)

    pipe = Pipeline([
        ('scaler', StandardScaler(with_mean=True, with_std=True)),
        ('model',  ElasticNet(alpha=alpha, l1_ratio=l1_ratio, max_iter=10000))
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

def predict_on_learning_table(bundle: Dict, learning_df: pd.DataFrame, dropna_rows: bool = True) -> pd.DataFrame:
    """
    Predict on the *learning table* (this is *not* unbiased CV; it's to show test-set fit pre-CV).
    Returns DataFrame indexed by Date with pred_b (and actual test_b if available).
    """
    feats = bundle["feature_cols"]
    df = learning_df.copy()
    if dropna_rows:
        df = df.dropna(subset=feats)  # strict: drop rows with any NA in features
    else:
        df[feats] = df[feats].replace([np.inf, -np.inf], np.nan).fillna(0.0)

    X = align_to_training_schema(df[feats], bundle["train_cols"])
    preds = bundle["pipe"].predict(X)

    out = pd.DataFrame({"Date": df["Date"].values, "Ticker": df["Ticker"].values, "pred_b": preds})
    if "test_b" in df.columns:
        out["actual_b"] = df["test_b"].values
    return out.set_index("Date")

# --- forecast helpers (future one-row prediction)

def forecast_next_b_with_ols(ticker: str,
                             mxus_returns: pd.DataFrame,
                             ols_model,
                             last_train_b: float,
                             last_lag_train_b: float) -> float:
    feat_df = rich_features_from_returns(mxus_returns, ticker)
    feat_df = add_cross_sectional_ranks(mxus_returns, feat_df, ticker)
    latest = feat_df.dropna().tail(1).copy()
    if latest.empty:
        raise ValueError("No complete latest feature row available for OLS forecasting.")

    # Inject AR(1)-layer predictors
    latest["train_b"] = last_train_b
    latest["lag_train_b"] = last_lag_train_b

    model_feats = [c for c in getattr(ols_model.model, "exog_names", []) if c != "const"]
    avail_feats = [c for c in model_feats if c in latest.columns]
    if not avail_feats:
        raise ValueError("No overlapping feature names between OLS model and latest features.")
    X_latest = sm.add_constant(latest[avail_feats], has_constant="add")
    return float(ols_model.predict(X_latest)[0])


def forecast_next_b_with_enet_preCV(ticker: str,
                                    mxus_returns: pd.DataFrame,
                                    bundle: Dict,
                                    last_train_b: float,
                                    last_lag_train_b: float) -> float:
    feat_df = rich_features_from_returns(mxus_returns, ticker)
    feat_df = add_cross_sectional_ranks(mxus_returns, feat_df, ticker)

    latest_raw = feat_df.tail(1).copy()

    # >>> Inject AR(1)-layer predictors so the schema matches training
    latest_raw["train_b"] = last_train_b
    latest_raw["lag_train_b"] = last_lag_train_b

    feats = bundle["feature_cols"]
    latest = latest_raw[feats].replace([np.inf, -np.inf], np.nan).dropna(axis=0, how="any")
    if latest.empty:
        raise ValueError("Latest feature row has NA values after engineering; cannot forecast under strict drop.")

    X_last = align_to_training_schema(latest, bundle["train_cols"])
    # Optional debug:
    # print("Predict-time columns:", list(X_last.columns))

    return float(bundle["pipe"].predict(X_last)[0])

# =========================
# 5) PLOTTING
# =========================

def plot_b_lagged_b(df: pd.DataFrame, outpath: Optional[str] = None, title: Optional[str] = None):
    tmp = df.dropna(subset=["train_b","test_b"]).copy()
    if tmp.empty:
        print("Nothing to plot.")
        return
    x = tmp["train_b"].values
    y = tmp["test_b"].values
    X = sm.add_constant(x)
    lin = sm.OLS(y, X).fit()
    xgrid = np.linspace(np.nanmin(x), np.nanmax(x), 200)
    yhat = lin.predict(sm.add_constant(xgrid))

    plt.figure(figsize=(6,5))
    plt.scatter(x, y, alpha=0.5, s=18)
    plt.plot(xgrid, yhat, linewidth=2)
    plt.axhline(0, linestyle="--", linewidth=1)
    plt.axvline(0, linestyle="--", linewidth=1)
    plt.xlabel("Historical b (train_b)")
    plt.ylabel("Future b (test_b)")
    plt.title(title or "train_b vs test_b")
    plt.tight_layout()
    if outpath:
        plt.savefig(outpath, dpi=140)
    plt.close()

# =========================
# 6) ORCHESTRATION (ONE TICKER)
# =========================

SAVE_LEARNING_TABLE_CSV = True
SAVE_PLOT = True

def run_for_one_ticker(
    ticker: str,
    mxus_returns_wide: pd.DataFrame,
    train_len: int = 750,
    test_len:  int = 120,
    freq_window: int = 5,
    arima_order: Tuple[int,int,int] = (1,0,0),  # AR(1) for stability & interpretability
    alpha: Optional[float] = None,
    lb_lags: List[int] = [],
    out_prefix: Optional[str] = None,
    model_for_prediction: str = "enet",  # "enet" or "ols"
    enet_alpha: float = 0.01,
    enet_l1_ratio: float = 0.5
) -> Optional[Dict]:

    # Subsample for ARIMA fitting speed if desired
    sub = mxus_returns_wide.iloc[::freq_window, :].reset_index(drop=True)
    b_pairs = historical_b(
        daily_returns=sub,
        ticker=ticker,
        train_len=max(10, train_len//freq_window),
        test_len=max(5,  test_len//freq_window),
        arima_order=arima_order,
        alpha=alpha,
        lb_lags=lb_lags,
        verbose=True
    )
    if b_pairs.empty:
        print(f"[{ticker}] No valid b pairs.")
        return None

    # latest AR(1) estimates to use as predictors at forecast time
    last_train_b = float(b_pairs["train_b"].iloc[-1])
    last_lag_train_b = float(b_pairs["lag_train_b"].iloc[-1]) if not pd.isna(b_pairs["lag_train_b"].iloc[-1]) else float(b_pairs["train_b"].iloc[-2]) if len(b_pairs) > 1 else np.nan

    # Build features (daily) and merge
    feat_df = rich_features_from_returns(mxus_returns_wide, ticker)
    feat_df = add_cross_sectional_ranks(mxus_returns_wide, feat_df, ticker)
    learning_df = assemble_learning_table(b_pairs, feat_df)

    # --- OLS ---
    ols_model = fit_ols_predict_future_b(learning_df)
    print("\n=== OLS: test_b ~ features ===")
    print(ols_model.summary())

    # --- ElasticNet (pre-CV, strict NA row-drop, schema frozen) ---
    enet_bundle = None
    try:
        enet_bundle = train_elasticnet_preCV(
            learning_df,
            alpha=enet_alpha,
            l1_ratio=enet_l1_ratio,
            dropna_rows=True  # STRICT: drop rows with any NA
        )
        # In-sample (pre-CV) diagnostics on learning table
        enet_preds_df = predict_on_learning_table(enet_bundle, learning_df, dropna_rows=True)
        if "actual_b" in enet_preds_df.columns:
            mask = ~enet_preds_df["actual_b"].isna()
            mae = mean_absolute_error(enet_preds_df.loc[mask, "actual_b"], enet_preds_df.loc[mask, "pred_b"])
            r2  = r2_score(enet_preds_df.loc[mask, "actual_b"], enet_preds_df.loc[mask, "pred_b"])
            print("\n=== ElasticNet (pre-CV, in-sample on learning table) ===")
            print(f"Rows used: {mask.sum()} | Features: {len(enet_bundle['train_cols'])}")
            print(f"MAE_in: {mae:.6f} | R2_in: {r2:.6f}")
    except Exception as e:
        print(f"ElasticNet training skipped due to error: {e}")

    # --- Save artifacts ---
    prefix = out_prefix or ticker.replace(" ", "_")
    out_dir = OUTPUT_ROOT / prefix
    out_dir.mkdir(parents=True, exist_ok=True)

    if SAVE_LEARNING_TABLE_CSV:
        lt_path = out_dir / "learning_table.csv"
        learning_df.to_csv(lt_path, index=False)
        print(f"Saved learning table → {lt_path.resolve()}")

    if SAVE_PLOT:
        png_path = out_dir / "train_vs_test_b.png"
        plot_b_lagged_b(learning_df, str(png_path), f"{ticker} — train_b vs test_b")
        print(f"Saved plot → {png_path.resolve()}")

    # --- Forecast next-period b (choose regularized or OLS) ---
    pred_ols  = np.nan
    pred_enet = np.nan
    
    try:
        if model_for_prediction.lower() == "enet" and enet_bundle is not None:
            pred_enet = forecast_next_b_with_enet_preCV(
                ticker, mxus_returns_wide, enet_bundle,
                last_train_b=last_train_b,
                last_lag_train_b=last_lag_train_b
            )
            print(f"\nPredicted next-period b (ElasticNet): {pred_enet:.4f}")
        else:
            pred_ols = forecast_next_b_with_ols(
                ticker, mxus_returns_wide, ols_model,
                last_train_b=last_train_b,
                last_lag_train_b=last_lag_train_b
            )
            print(f"\nPredicted next-period b (OLS): {pred_ols:.4f}")
    except Exception as e:
        print(f"Forecast step failed: {e}")

    # --- Build & save summary ---
    summary_rows = [{
        "Ticker": ticker,
        "ENET_in_MAE": float(mae) if enet_bundle is not None and 'mae' in locals() else np.nan,
        "ENET_in_R2":  float(r2)  if enet_bundle is not None and 'r2'  in locals() else np.nan,
        "Pred_b_OLS":  pred_ols,
        "Pred_b_ENET": pred_enet,
        "ModelUsed":   model_for_prediction
    }]
    summary = pd.DataFrame(summary_rows)

    try:
        summary_path = out_dir / "summary_metrics.csv"
        summary.to_csv(summary_path, index=False)
        print(f"Saved summary metrics → {summary_path.resolve()}")
    except Exception as e:
        print(f"⚠️  Could not save summary: {e}")

    # Also save ElasticNet test predictions table if available
    try:
        if enet_bundle is not None:
            enet_preds_path = out_dir / "enet_learning_table_predictions.csv"
            enet_preds_df.to_csv(enet_preds_path)
            print(f"Saved ENET learning-table predictions → {enet_preds_path.resolve()}")
    except Exception as e:
        print(f"⚠️  Could not save ENET predictions table: {e}")

    return {
        "learning_df": learning_df,
        "ols_model": ols_model,
        "enet_bundle": enet_bundle,
        "enet_in_mae": float(mae) if enet_bundle is not None and 'mae' in locals() else np.nan,
        "enet_in_r2":  float(r2)  if enet_bundle is not None and 'r2'  in locals() else np.nan,
        "pred_b_ols": pred_ols,
        "pred_b_enet": pred_enet,
        "summary": summary,
    }

# =========================
# 7) MAIN
# =========================

if __name__ == "__main__":
    # --- EDIT HERE ---
    MXUS_XLSX_PATH     = "C:/Users/shawn/OneDrive/Documents/University of Auckland/YEAR 3/COMPSCI 399 - 2/Algo 2/MXUS_Data.xlsx"
    MXUS_RETURNS_SHEET = "Returns"

    mxus_returns = load_mxus_returns(MXUS_XLSX_PATH, sheet=MXUS_RETURNS_SHEET)

    # Ensure numerics (belt-and-braces)
    for c in mxus_returns.columns:
        if c != "Date":
            mxus_returns[c] = pd.to_numeric(mxus_returns[c], errors="coerce")

    # ---- Choose ticker & settings ----
    TICKER = "KO UN"             # e.g., "KO UN" or "AVGO UW"
    MODEL_FOR_PRED = "enet"      # "enet" (regularized) or "ols"

    result = run_for_one_ticker(
        ticker=TICKER,
        mxus_returns_wide=mxus_returns,
        train_len=200,     # start small for stability, then scale up
        test_len=60,
        freq_window=1,     # daily first; move to 5 when happy
        arima_order=(1,0,0),
        alpha=None,
        lb_lags=[],
        out_prefix=None,
        model_for_prediction=MODEL_FOR_PRED,
        enet_alpha=0.01,
        enet_l1_ratio=0.5
    )
