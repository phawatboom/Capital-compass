# filepath: b_forecast_pipeline_extended.py
# -*- coding: utf-8 -*-

"""
Stock Reversion/Trend Forecasting (EMXUS-only)
======================================================

Edit near the bottom:
- TICKER, train_len, test_len, freq_window, etc.
"""

from __future__ import annotations
import warnings
warnings.filterwarnings("ignore")

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from typing import Tuple, Optional, List, Dict

from statsmodels.tsa.arima.model import ARIMA
from statsmodels.stats.diagnostic import acorr_ljungbox
import statsmodels.api as sm

from sklearn.linear_model import ElasticNetCV
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import mean_absolute_error, r2_score

# -----------------------------
# Config (EDIT PATHS IF NEEDED)
# -----------------------------
MXUS_XLSX_PATH      = "C:/Users/shawn/OneDrive/Documents/University of Auckland/YEAR 3/COMPSCI 399 - 2/Algo 2/MXUS_Data.xlsx"
MXUS_RETURNS_SHEET  = "Returns"   # wide daily *simple* returns (Date + tickers)

SAVE_LEARNING_TABLE_CSV = True
SAVE_PLOT = True

# -----------------------------
# Utilities: I/O
# -----------------------------
def _coerce_date(df: pd.DataFrame, date_col: str = "Date") -> pd.DataFrame:
    out = df.copy()
    out[date_col] = pd.to_datetime(out[date_col])
    out = out.sort_values(date_col).reset_index(drop=True)
    return out

def load_mxus_returns(xlsx_path: str, sheet: str = "Returns") -> pd.DataFrame:
    """
    Robust loader for MXUS_Data.xlsx / 'Returns' where the true header row is not row 1.
    - Finds the first row that contains a 'Date' cell (case-insensitive) and uses it as the header.
    - Converts percentage strings (e.g., '0.79%') to decimals (0.0079).
    - Coerces all non-Date columns to numeric.
    """
    import numpy as np
    import pandas as pd

    # Read raw sheet with no header so we can detect it ourselves
    raw = pd.read_excel(xlsx_path, sheet_name=sheet, header=None, dtype=object)

    # Locate the header row (first row that contains a cell equal to 'date' ignoring case/whitespace)
    header_row = None
    max_scan_rows = min(50, len(raw))  # scan only the top 50 rows for speed/safety
    for i in range(max_scan_rows):
        row = raw.iloc[i].astype(str).str.strip()
        if row.str.lower().eq("date").any():
            header_row = i
            break
    if header_row is None:
        raise KeyError("Could not find a header row containing 'Date' in the sheet.")

    # Build a DataFrame starting from the row after the header
    cols = raw.iloc[header_row].astype(str).str.strip().tolist()
    df = raw.iloc[header_row + 1:].copy()
    df.columns = cols

    # Keep only columns that are not entirely empty
    df = df.loc[:, ~(df.isna().all())]

    # Identify/rename the Date column (in case the casing differs)
    date_col = None
    for c in df.columns:
        if str(c).strip().lower() == "date":
            date_col = c
            break
    if date_col is None:
        # fallback: any column containing 'date'
        for c in df.columns:
            if "date" in str(c).strip().lower():
                date_col = c
                break
    if date_col is None:
        raise KeyError("Found header row but no column named 'Date' (any case).")

    if date_col != "Date":
        df = df.rename(columns={date_col: "Date"})

    # Drop rows with empty Date, coerce Date to datetime
    df = df.dropna(subset=["Date"])
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce", infer_datetime_format=True)
    df = df.dropna(subset=["Date"]).sort_values("Date").reset_index(drop=True)

    # Helper to convert cells to numeric, handling percentages like '0.79%' → 0.0079
    def _to_numeric(x):
        if isinstance(x, str):
            s = x.strip().replace(",", "")
            if s == "":
                return np.nan
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

    # Convert all non-Date columns to numeric
    for c in df.columns:
        if c == "Date":
            continue
        df[c] = df[c].map(_to_numeric)

    return df


# -----------------------------
# Feature engineering (from returns)
# -----------------------------
def rolling_features_from_returns(
    wide_returns: pd.DataFrame,
    ticker: str,
    lookback_vol: int = 252,
    lookback_perf: int = 252,
    lookback_abs: int = 63,
    lookback_autocorr: int = 63
) -> pd.DataFrame:
    """
    Compute rolling features from a wide returns table (Date + tickers).
    Features (for one ticker):
      - vol_{lookback_vol}: rolling std of daily returns
      - perf_{lookback_perf}: rolling cumulative return over lookback_perf
      - absret_mean_{lookback_abs}: rolling mean of |ret|
      - acf1_{lookback_autocorr}: rolling lag-1 autocorrelation
    Returns: DataFrame[Date, Ticker, vol_*, perf_*, absret_mean_*, acf1_*]
    """
    if ticker not in wide_returns.columns:
        raise ValueError(f"Ticker '{ticker}' not found in returns frame.")

    df = wide_returns[["Date", ticker]].rename(columns={ticker: "ret"}).copy()

    # volatility
    df[f"vol_{lookback_vol}"] = df["ret"].rolling(lookback_vol, min_periods=max(10, lookback_vol // 4)).std()

    # performance: product(1+ret)-1 over window
    df[f"perf_{lookback_perf}"] = (1.0 + df["ret"]).rolling(lookback_perf, min_periods=max(10, lookback_perf // 4)).apply(
        lambda x: np.prod(1 + x) - 1, raw=False
    )

    # abs-range proxy
    df[f"absret_mean_{lookback_abs}"] = df["ret"].abs().rolling(lookback_abs, min_periods=max(10, lookback_abs // 4)).mean()

    # autocorrelation lag-1 (rolling)
    def _rolling_acf1(a: pd.Series) -> float:
        x = a.values
        if len(x) < 5:
            return np.nan
        x = x - np.nanmean(x)
        s = np.nanstd(x)
        if s == 0 or np.isnan(s):
            return 0.0
        x0, x1 = x[:-1], x[1:]
        return float(np.nan_to_num(np.corrcoef(x0, x1)[0, 1]))

    df[f"acf1_{lookback_autocorr}"] = df["ret"].rolling(lookback_autocorr, min_periods=max(10, lookback_autocorr // 4)).apply(
        _rolling_acf1, raw=False
    )

    df["Ticker"] = ticker
    return df

# -----------------------------
# ARIMA “b” estimation helpers
# -----------------------------
def check_coefficients_significance(model, alpha=0.05, lb_lags: List[int] = [1]) -> Optional[float]:
    """
    Returns AR(1) coefficient (b) if:
      1) Residuals pass Ljung-Box (white noise) for lags in lb_lags, AND
      2) ar.L1 p-value < alpha
    Else returns None.
    """
    try:
        resid = model.resid
        lb = acorr_ljungbox(resid, lags=lb_lags, return_df=True)
        if (lb["lb_pvalue"] < alpha).any():
            return None

        pvals = model.pvalues
        ar1_key = next((k for k in pvals.index if "ar.L1" in k), None)
        if ar1_key is None:
            return None

        if pvals[ar1_key] < alpha:
            return float(model.params[ar1_key])
        return None
    except Exception:
        return None

def fit_arima_and_get_b(returns: pd.Series,
                        order=(1,0,1),
                        alpha=None,
                        lb_lags=[],
                        verbose=False) -> Optional[float]:
    """
    Fit ARIMA(order) on returns and return AR(1) coefficient.
    Always attempts multiple fallbacks to avoid None.
    """
    r = returns.dropna().astype(float)
    if len(r) < 10:
        return None

    # 1) Try ARIMA
    try:
        model = ARIMA(r.values, order=order).fit(method="statespace", disp=0)
        params = model.params
        for k in params.index:
            if "ar.L1" in k:
                return float(params[k])
    except Exception as e:
        if verbose:
            print("ARIMA fail:", e)

    # 2) Fallback: simple AR(1) by OLS
    try:
        x = r.shift(1)
        df = pd.DataFrame({"y": r.values, "x": x.values}).dropna()
        if len(df) >= 10:
            X = sm.add_constant(df["x"])
            ols = sm.OLS(df["y"], X).fit()
            return float(ols.params[1])
    except Exception as e:
        if verbose:
            print("OLS fail:", e)

    # 3) Fallback: lag-1 autocorrelation
    try:
        ac1 = r.autocorr(lag=1)
        return float(ac1)
    except Exception as e:
        if verbose:
            print("AC fail:", e)

    return None


# -----------------------------
# Historical b (rolling windows)
# -----------------------------
def historical_b(
    daily_returns: pd.DataFrame,   # wide daily returns (Date + tickers)
    ticker: str,
    train_len: int,
    test_len: int,
    arima_order=(1,0,1),
    alpha: float = 0.05,
    lb_lags: List[int] = [1],
    min_train_obs: int = 20,       # minimum non-NaN obs required to attempt ARIMA
    verbose: bool = True
) -> pd.DataFrame:
    """
    Rolling windows on (optionally subsampled) returns for one ticker.
      - Fit ARIMA on train → train_b
      - Fit ARIMA on test  → test_b
    Returns DataFrame with Date (end of train), Ticker, train_b, test_b, indices, and lag_train_b.
    Never raises KeyError when no valid rows; returns an empty, well-formed frame instead.
    """
    if ticker not in daily_returns.columns:
        raise ValueError(f"Ticker '{ticker}' not in returns table.")

    ser = (daily_returns[["Date", ticker]]
           .copy()
           .rename(columns={ticker: "ret"})
           .dropna(subset=["ret"]))
    if ser.empty:
        if verbose:
            print(f"[{ticker}] No non-NaN returns found after dropping missing values.")
        return pd.DataFrame(columns=["Date","Ticker","train_b","test_b","train_start_idx",
                                     "train_end_idx","test_start_idx","test_end_idx","lag_train_b"])

    ret   = ser["ret"].values
    dates = ser["Date"].values

    rows = []
    N = len(ser)
    if N < (train_len + test_len):
        if verbose:
            print(f"[{ticker}] Not enough rows for one window: have {N}, need {train_len + test_len}.")
        return pd.DataFrame(columns=["Date","Ticker","train_b","test_b","train_start_idx",
                                     "train_end_idx","test_start_idx","test_end_idx","lag_train_b"])

    i = 0
    attempted, kept = 0, 0
    while i + train_len + test_len <= N:
        train_slice = slice(i, i + train_len)
        test_slice  = slice(i + train_len, i + train_len + test_len)

        train_returns = pd.Series(ret[train_slice])
        test_returns  = pd.Series(ret[test_slice])

        # basic guard on non-NaN counts
        if train_returns.dropna().shape[0] < min_train_obs or test_returns.dropna().shape[0] < min_train_obs:
            i += 1
            continue

        attempted += 1
        b_train = fit_arima_and_get_b(train_returns, order=arima_order, alpha=alpha, lb_lags=lb_lags)
        b_test  = fit_arima_and_get_b(test_returns,  order=arima_order, alpha=alpha, lb_lags=lb_lags)

        if (b_train is not None) and (b_test is not None):
            kept += 1
            end_train_date = pd.to_datetime(dates[train_slice][-1])
            rows.append({
                "Date": end_train_date,
                "Ticker": ticker,
                "train_b": b_train,
                "test_b":  b_test,
                "train_start_idx": i,
                "train_end_idx": i + train_len - 1,
                "test_start_idx":  i + train_len,
                "test_end_idx":    i + train_len + test_len - 1
            })

        i += 1  # 1-step rolling window

    # Build output safely
    out = pd.DataFrame(rows)
    if out.empty:
        if verbose:
            msg = (f"[{ticker}] No valid b coefficients kept "
                   f"(attempted windows: {attempted}, kept: {kept}). "
                   f"Try: freq_window=1, smaller train_len/test_len, higher alpha (e.g. 0.10), "
                   f"or disable Ljung-Box via lb_lags=[].")
            print(msg)
        # return an empty but well-formed frame to avoid KeyError downstream
        return pd.DataFrame(columns=["Date","Ticker","train_b","test_b","train_start_idx",
                                     "train_end_idx","test_start_idx","test_end_idx","lag_train_b"])

    out = out.sort_values("Date").reset_index(drop=True)
    out["lag_train_b"] = out["train_b"].shift(1)
    return out


# -----------------------------
# Merge Features with b-pairs
# -----------------------------
def assemble_learning_table(b_pairs: pd.DataFrame, feature_frame: pd.DataFrame) -> pd.DataFrame:
    """
    Left-join b_pairs (Date, Ticker) with features (Date, Ticker, ...).
    """
    feat_cols = [c for c in feature_frame.columns if c not in ["Date", "Ticker", "ret"]]
    merged = b_pairs.merge(feature_frame[["Date", "Ticker"] + feat_cols], on=["Date", "Ticker"], how="left")
    merged = merged.dropna(subset=["train_b", "test_b"])
    return merged

# -----------------------------
# Modeling: OLS + optional ElasticNet
# -----------------------------
def fit_ols_predict_future_b(learning_df: pd.DataFrame) -> sm.regression.linear_model.RegressionResultsWrapper:
    """
    OLS: test_b ~ lag_train_b + vol_* + perf_* + absret_mean_* + acf1_*
    """
    candidate_X = [c for c in learning_df.columns if any(
        c.startswith(p) for p in ["lag_train_b", "vol_", "perf_", "absret_mean_", "acf1_"]
    )]
    X = learning_df[candidate_X].copy()
    X = sm.add_constant(X, has_constant="add")
    y = learning_df["test_b"].values

    mask = ~np.isnan(X).any(axis=1)
    Xc = X.loc[mask]
    yc = y[mask.values] if hasattr(mask, "values") else y[mask]

    model = sm.OLS(yc, Xc).fit()
    return model

def fit_elastic_net_cv(learning_df: pd.DataFrame, n_splits: int = 5, random_state: int = 0):
    """
    ElasticNetCV with TimeSeriesSplit for robustness (optional).
    Returns fitted model, OOF metrics, and feature names.
    """
    candidate_X = [c for c in learning_df.columns if any(
        c.startswith(p) for p in ["lag_train_b", "vol_", "perf_", "absret_mean_", "acf1_"]
    )]
    df = learning_df.dropna(subset=["test_b"] + candidate_X).copy()

    X = df[candidate_X].values
    y = df["test_b"].values

    tscv = TimeSeriesSplit(n_splits=min(n_splits, max(2, len(df) // 50)))
    enet = ElasticNetCV(l1_ratio=[0.1, 0.3, 0.5, 0.7, 0.9], alphas=None, cv=tscv, random_state=random_state)

    oof_preds = np.full_like(y, np.nan, dtype=float)
    for train_idx, test_idx in tscv.split(X):
        enet.fit(X[train_idx], y[train_idx])
        oof_preds[test_idx] = enet.predict(X[test_idx])

    mae = mean_absolute_error(y[~np.isnan(oof_preds)], oof_preds[~np.isnan(oof_preds)])
    r2  = r2_score(y[~np.isnan(oof_preds)], oof_preds[~np.isnan(oof_preds)])

    enet.fit(X, y)
    return enet, {"MAE_oof": mae, "R2_oof": r2}, candidate_X

# -----------------------------
# Plotting
# -----------------------------
def plot_b_lagged_b(df: pd.DataFrame, outpath: Optional[str] = None, title: Optional[str] = None):
    tmp = df.dropna(subset=["train_b", "test_b"]).copy()
    if tmp.empty:
        print("Nothing to plot (no valid pairs).")
        return
    x = tmp["train_b"].values
    y = tmp["test_b"].values

    X = sm.add_constant(x)
    lin = sm.OLS(y, X).fit()
    xgrid = np.linspace(np.nanmin(x), np.nanmax(x), 200)
    yhat = lin.predict(sm.add_constant(xgrid))

    plt.figure(figsize=(6, 5))
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

# -----------------------------
# Orchestration for ONE ticker
# -----------------------------
def run_for_one_ticker(
    ticker: str,
    mxus_returns_wide: pd.DataFrame,
    train_len: int = 750,   # ~3y of daily rows BEFORE subsampling
    test_len:  int = 120,   # ~6m of daily rows BEFORE subsampling
    freq_window: int = 5,   # 5 → approximate weekly sampling by row slicing
    arima_order: Tuple[int,int,int] = (1,0,1),
    alpha: float = 0.05,
    lb_lags: List[int] = [1],
    feature_lookbacks: Dict[str, int] = None,
    out_prefix: Optional[str] = None,
):
    """
    Full flow for a single ticker using only MXUS returns for both ARIMA and features.
    """
    if feature_lookbacks is None:
        feature_lookbacks = dict(vol=252, perf=252, absret=63, acf1=63)

    # 1) Subsample returns for ARIMA b-estimation (non-overlapping lower frequency)
    sub = mxus_returns_wide.iloc[::freq_window, :].reset_index(drop=True)

    # 2) Compute b-pairs on subsampled returns (train_len/test_len are in *daily* rows, so scale)
    b_pairs = historical_b(
        daily_returns=sub,
        ticker=ticker,
        train_len=max(10, train_len // freq_window),
        test_len=max(5,  test_len  // freq_window),
        arima_order=arima_order,
        alpha=alpha,
        lb_lags=lb_lags,
    )
    if b_pairs.empty:
        print(f"[{ticker}] No valid (train_b, test_b) pairs found with current settings.")
        return None

    # 3) Rolling features from full-frequency MXUS returns (not subsampled)
    feat_df = rolling_features_from_returns(
        mxus_returns_wide,
        ticker=ticker,
        lookback_vol=feature_lookbacks["vol"],
        lookback_perf=feature_lookbacks["perf"],
        lookback_abs=feature_lookbacks["absret"],
        lookback_autocorr=feature_lookbacks["acf1"],
    )

    # Align feature dates to b_pairs Date (end of train window on the subsampled axis).
    # Because b_pairs dates come from the subsampled timeline, they should still exist in the full daily table.
    learning_df = assemble_learning_table(b_pairs, feat_df)

    # 4) OLS
    ols_model = fit_ols_predict_future_b(learning_df)
    print("/n=== OLS: test_b ~ features ===")
    print(ols_model.summary())

    # 5) Optional ElasticNet with TSCV
    try:
        enet_model, enet_metrics, used_cols = fit_elastic_net_cv(learning_df, n_splits=5, random_state=42)
        print("/n=== ElasticNet (TimeSeriesSplit OOF) ===")
        print(f"Features used: {used_cols}")
        print(f"MAE_oof: {enet_metrics['MAE_oof']:.6f}")
        print(f"R2_oof : {enet_metrics['R2_oof']:.6f}")
    except Exception as e:
        print(f"ElasticNet step skipped due to error: {e}")

    # 6) Save artifacts
    if SAVE_LEARNING_TABLE_CSV:
        prefix = out_prefix or f"{ticker.replace(' ', '_')}"
        learning_df.to_csv(f"{prefix}__learning_table.csv", index=False)
        print(f"Saved learning table → {prefix}__learning_table.csv")

    if SAVE_PLOT:
        prefix = out_prefix or f"{ticker.replace(' ', '_')}"
        plot_b_lagged_b(learning_df, outpath=f"{prefix}__train_vs_test_b.png", title=f"{ticker} — train_b vs test_b")
        print(f"Saved plot → {prefix}__train_vs_test_b.png")

    return {"learning_df": learning_df, "ols_model": ols_model}

# -----------------------------
# Main
# -----------------------------
if __name__ == "__main__":
    # Load the single source of returns
    
    mxus_returns = load_mxus_returns(MXUS_XLSX_PATH, sheet=MXUS_RETURNS_SHEET)


    # ---- EDIT YOUR TICKER / PARAMS HERE ----
    TICKER = "KO UN"

    result = run_for_one_ticker(
        ticker="KO UN",
        mxus_returns_wide=mxus_returns,
        train_len=200,
        test_len=60,
        freq_window=1,
        arima_order=(1,0,0),  # simple AR(1)
        alpha=None,           # skip significance
        lb_lags=[],
        feature_lookbacks=dict(vol=63, perf=126, absret=21, acf1=21),
        out_prefix=None,
)
