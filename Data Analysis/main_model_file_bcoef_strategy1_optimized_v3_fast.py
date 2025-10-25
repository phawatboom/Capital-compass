#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main_model_file_bcoef_strategy1_optimized_v3_fast.py

Drop-in faster variant of your β Strategy‑1 + ML pipeline with:
  • Vectorized rolling OLS (per‑ticker) using cumulative sums → ~10–30× speedup.
  • Optional stride computation (--stride-days) to downsample windows and forward-fill.
  • Progress logging inside OLS loop so you can see it moving.
  • Minor hygiene: fewer copies, float32 downcast where safe.

CLI stays compatible with your v3 file, plus one new flag:
  --stride-days K    # compute β every K days (default 1 = every day)

Author: You + ChatGPT
"""

from __future__ import annotations

import argparse
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple, Optional, Iterable, Dict

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.linear_model import Ridge, ElasticNet
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.model_selection import TimeSeriesSplit

# ======================================================
# Logging
# ======================================================

def setup_logger(output_directory: Path) -> logging.Logger:
    output_directory.mkdir(parents=True, exist_ok=True)
    log_directory = output_directory / "logs"
    log_directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("beta_pipeline")
    logger.setLevel(logging.INFO)
    logger.handlers = []
    file_handler = logging.FileHandler(log_directory / "run.log", mode="w", encoding="utf-8")
    stream_handler = logging.StreamHandler()
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    file_handler.setFormatter(fmt); stream_handler.setFormatter(fmt)
    logger.addHandler(file_handler); logger.addHandler(stream_handler)
    return logger

# ======================================================
# Excel/Data Loading (same behaviour as your v3)
# ======================================================

def autodiscover_excel_and_sheet(excel_arg: Optional[str], sheet_arg: Optional[str], logger: Optional[logging.Logger] = None) -> Tuple[Path, str]:
    def choose_sheet(xls: pd.ExcelFile, preferred: Optional[str]) -> str:
        names = list(xls.sheet_names)
        if preferred and preferred in names:
            return preferred
        candidates = [n for n in names if any(k in n.lower() for k in ["return", "data", "sheet1"])]
        return candidates[0] if candidates else names[0]

    if excel_arg:
        excel_path = Path(excel_arg)
        if not excel_path.exists():
            raise FileNotFoundError(f"Excel file not found: {excel_path}")
        xls = pd.ExcelFile(excel_path, engine="openpyxl")
        sheet_name = choose_sheet(xls, sheet_arg)
        if logger: logger.info(f"Using Excel: {excel_path.name}, sheet: {sheet_name}")
        return excel_path, sheet_name

    for base in [Path.cwd()]:
        for pattern in ["MXUS_Data_*.xlsx", "MXUS_Data.xlsx"]:
            candidates = list(base.glob(pattern))
            if candidates:
                excel_path = sorted(candidates)[-1]
                xls = pd.ExcelFile(excel_path, engine="openpyxl")
                sheet_name = choose_sheet(xls, sheet_arg)
                if logger: logger.info(f"Auto-discovered Excel: {excel_path.name}, sheet: {sheet_name}")
                return excel_path, sheet_name
        candidates = list(base.glob("*.xlsx"))
        if candidates:
            excel_path = sorted(candidates)[-1]
            xls = pd.ExcelFile(excel_path, engine="openpyxl")
            sheet_name = choose_sheet(xls, sheet_arg)
            if logger: logger.info(f"Auto-discovered Excel: {excel_path.name}, sheet: {sheet_name}")
            return excel_path, sheet_name
    raise FileNotFoundError("Excel file not specified and not found.")

def load_returns_wide(excel_path: str | Path, sheet_name: str) -> pd.DataFrame:
    raw = pd.read_excel(excel_path, sheet_name=sheet_name, header=None, engine="openpyxl")
    col0 = raw.iloc[:, 0].astype(str).str.strip().str.lower()
    header_idx_candidates = col0[col0.eq("date")].index.tolist()
    header_idx = header_idx_candidates[0] if header_idx_candidates else 0
    headers = raw.iloc[header_idx].astype(str).str.strip().tolist()
    df = raw.iloc[header_idx + 1:].copy()
    df.columns = headers
    if "Date" not in df.columns:
        date_candidates = [c for c in df.columns if "date" in str(c).lower()]
        if date_candidates:
            df = df.rename(columns={date_candidates[0]: "Date"})
        else:
            raise ValueError("No Date column found in the data")
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df[df["Date"].notna()].sort_values("Date").reset_index(drop=True)
    for col in [c for c in df.columns if c != "Date"]:
        if df[col].dtype == "object":
            series = df[col].astype(str).str.replace("%", "", regex=False).str.strip()
            df[col] = pd.to_numeric(series, errors="coerce")
            valid_values = df[col].dropna()
            if len(valid_values) > 0:
                abs_median = valid_values.abs().median()
                if abs_median > 1.0 and abs_median <= 100:
                    df[col] = df[col] / 100.0
    keep_cols = ["Date"] + [c for c in df.columns if c != "Date" and df[c].notna().sum() > 0]
    return df[keep_cols]

# ======================================================
# Config
# ======================================================

@dataclass
class Config:
    excel_path: Optional[Path] = None
    sheet_name: Optional[str] = None
    input_csv_path: Optional[Path] = None
    output_directory: Path = Path("./outputs")

    date_column: str = "Date"
    market_column: str = "SPX"

    rolling_window_days: int = 60
    beta_horizons_days: List[int] = field(default_factory=lambda: [1, 5, 20])
    minimum_observations_per_window: int = 25

    gate_p_value_threshold: float = 0.10
    gate_r2_threshold: float = 0.02

    embargo_days: int = 5

    beta_model_name: str = "ridge"
    ridge_alpha_grid: List[float] = field(default_factory=lambda: list(np.logspace(-3, 3, 13)))
    elastic_alpha_grid: List[float] = field(default_factory=lambda: list(np.logspace(-3, 3, 9)))
    elastic_l1_grid: List[float] = field(default_factory=lambda: [0.05, 0.1, 0.25, 0.5, 0.75])
    random_state: int = 1337

    conformal_alpha: float = 0.10
    float_downcast: bool = True

    fallback_mode: str = "strategy1"  # {"strategy1","median"}

    # NEW: compute every k-th day for OLS, forward-fill to full daily index
    stride_days: int = 1

def parse_cli_arguments() -> Config:
    parser = argparse.ArgumentParser(description="β Strategy‑1 + ML pipeline (fast variant)")
    parser.add_argument("--excel", type=str, help="Excel file path (e.g., MXUS_Data.xlsx)")
    parser.add_argument("--sheet", type=str, default="Returns", help="Excel sheet name")
    parser.add_argument("--input-csv", type=str, help="Returns-wide CSV (Date + market + tickers)")
    parser.add_argument("--date-col", type=str, default="Date")
    parser.add_argument("--market-col", type=str, default="SPX")
    parser.add_argument("--beta-window", type=int, default=60)
    parser.add_argument("--b-horizons", type=int, nargs="+", default=[1,5,20])
    parser.add_argument("--out-dir", type=str, default="./outputs")
    parser.add_argument("--b-model", type=str, default="ridge", choices=["ridge","elastic","hgb"])
    parser.add_argument("--stride-days", type=int, default=1, help="Compute β every k days and forward-fill (default 1)")
    args = parser.parse_args()

    return Config(
        date_column=args.date_col,
        market_column=args.market_col,
        rolling_window_days=args.beta_window,
        beta_horizons_days=args.b_horizons,
        output_directory=Path(args.out_dir),
        beta_model_name=args.b_model,
        excel_path=Path(args.excel) if args.excel else None,
        sheet_name=args.sheet,
        input_csv_path=Path(args.input_csv) if args.input_csv else None,
        stride_days=max(1, int(args.stride_days)),
    )

# ======================================================
# Utilities
# ======================================================

def downcast_to_float32(frame: pd.DataFrame, columns: Optional[List[str]] = None) -> pd.DataFrame:
    if columns is None:
        columns = [c for c in frame.columns if pd.api.types.is_float_dtype(frame[c])]
    for col in columns:
        try:
            frame[col] = pd.to_numeric(frame[col], errors="coerce").astype("float32")
        except Exception:
            pass
    return frame

def winsorize_simple_returns(series: pd.Series, max_abs: float = 0.10) -> pd.Series:
    return series.clip(lower=-max_abs, upper=max_abs)

def rolling_standard_deviation(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window, min_periods=max(5, window//4)).std()

def rolling_mean(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window, min_periods=max(5, window//4)).mean()

def rolling_zscore(series: pd.Series, window: int) -> pd.Series:
    mu = rolling_mean(series, window)
    sd = rolling_standard_deviation(series, window)
    return (series - mu) / sd

def rolling_autocorr_lag1(series: pd.Series, window: int = 20, lag: int = 1) -> pd.Series:
    def _ac(window_values):
        if np.all(~np.isfinite(window_values)):
            return np.nan
        a = window_values[:-lag]
        b = window_values[lag:]
        if a.size < 3:
            return np.nan
        return np.corrcoef(a, b)[0, 1]
    return series.rolling(window).apply(_ac, raw=True)

# ======================================================
# FAST Rolling OLS via cumulative sums
# ======================================================

def _rolling_window_sums(a: np.ndarray, window: int) -> Tuple[np.ndarray, np.ndarray]:
    """Return rolling sum(a) and sum(a^2) with window length (NaNs treated as missing -> results become NaN)."""
    # We treat NaNs by temporarily replacing with 0 but also tracking valid counts.
    valid = np.isfinite(a).astype(np.int32)
    a_safe = np.where(np.isfinite(a), a, 0.0).astype(np.float64)
    csum = np.cumsum(a_safe)
    csum2 = np.cumsum(a_safe * a_safe)
    cvalid = np.cumsum(valid)

    sum_a = csum[window-1:] - np.r_[0.0, csum[:-window]]
    sum_a2 = csum2[window-1:] - np.r_[0.0, csum2[:-window]]
    n = cvalid[window-1:] - np.r_[0, cvalid[:-window]]
    # If any NaNs in the window, n < window. Require full windows for stats to be stable.
    sum_a[n < window] = np.nan
    sum_a2[n < window] = np.nan
    return sum_a, sum_a2

def rolling_ols_stats(y: np.ndarray, x: np.ndarray, window: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Vectorized OLS over a sliding window for y ~ a + b x.
    Returns arrays aligned to original series length with NaN for first window-1 entries:
      alpha, beta, r2, se_beta, t_beta, p_beta, se_alpha
    """
    n_total = len(y)
    if n_total < window:
        pad = np.full(n_total, np.nan, dtype=np.float64)
        return (pad,)*7

    # Rolling sums
    sum_x, sum_x2 = _rolling_window_sums(x, window)
    sum_y, sum_y2 = _rolling_window_sums(y, window)
    sum_xy, _ = _rolling_window_sums(x * y, window)

    # Means per window
    mean_x = sum_x / window
    mean_y = sum_y / window

    # Centered moment sums
    Sxx = sum_x2 - (sum_x**2) / window
    Syy = sum_y2 - (sum_y**2) / window
    Sxy = sum_xy - (sum_x * sum_y) / window

    # Slope, intercept
    with np.errstate(invalid="ignore", divide="ignore"):
        beta = Sxy / Sxx
    alpha = mean_y - beta * mean_x

    # Goodness of fit via moment identities
    SSR = (Sxy ** 2) / Sxx
    SSE = Syy - SSR
    dof = np.maximum(1, window - 2)
    sigma2 = SSE / dof  # residual variance

    # Standard errors
    with np.errstate(invalid="ignore", divide="ignore"):
        se_beta = np.sqrt(sigma2 / Sxx)
        se_alpha = np.sqrt(sigma2 * (1.0 / window + (mean_x**2) / Sxx))

    # r^2
    with np.errstate(invalid="ignore", divide="ignore"):
        r2 = 1.0 - (SSE / Syy)

    # t and p for beta
    with np.errstate(invalid="ignore", divide="ignore"):
        t_beta = beta / se_beta
    # p-value: two-sided t-test
    # For vectorized t->p, use survival function via cdf
    # We'll clip dof to at least 1
    dof_use = np.maximum(1, dof)
    
    # Fix the p-value calculation to handle scalar dof_use
    # Ensure dof_use is broadcastable with t_beta
    if np.isscalar(dof_use) or np.ndim(dof_use) == 0:
        dof_arr = np.full_like(t_beta, int(dof_use))
    else:
        dof_arr = np.asarray(dof_use, dtype=int)
    
    # Vectorized p-value calculation using scipy.stats
    from scipy.stats import t as student_t
    p_beta = 2.0 * student_t.sf(np.abs(t_beta), df=dof_arr)
    
    # If you also compute p_alpha, apply the same fix:
    if 'p_alpha' in locals() or 't_alpha' in locals():
        p_alpha = 2.0 * student_t.sf(np.abs(t_alpha), df=dof_arr)

    # Pad to original length
    pad_len = window - 1
    def _pad_front(z):
        out = np.full(n_total, np.nan, dtype=np.float64)
        out[pad_len:] = z
        return out

    return (
        _pad_front(alpha),
        _pad_front(beta),
        _pad_front(r2),
        _pad_front(se_beta),
        _pad_front(t_beta),
        _pad_front(p_beta),
        _pad_front(se_alpha),
    )

# ======================================================
# Strategy‑1 (vectorized rolling OLS β history)
# ======================================================

def run_strategy1_rolling_ols_fast(returns_wide: pd.DataFrame, config: Config, ticker_list: List[str], logger: logging.Logger) -> Dict[int, pd.DataFrame]:
    results_by_horizon: Dict[int, pd.DataFrame] = {}
    date_col, market_col, window = config.date_column, config.market_column, config.rolling_window_days

    # Precompute forward market returns for all horizons
    market_df = returns_wide[[date_col, market_col]].sort_values(date_col).copy()
    for horizon_days in config.beta_horizons_days:
        market_df[f"market_fwd_{horizon_days}d"] = market_df[market_col].shift(-horizon_days)

    n_tickers = len(ticker_list)
    for horizon_days in config.beta_horizons_days:
        out_frames = []
        for i, ticker in enumerate(ticker_list, 1):
            if i % 25 == 0 or i == n_tickers:
                logger.info(f"[β OLS {horizon_days}d] {i}/{n_tickers} tickers processed…")

            merged = (
                returns_wide[[date_col, ticker]]
                .merge(market_df[[date_col, f"market_fwd_{horizon_days}d"]], on=date_col, how="left")
                .sort_values(date_col)
            )
            # Build y (asset forward) and x (market forward)
            y = merged[ticker].shift(-horizon_days).to_numpy(dtype=np.float64)
            x = merged[f"market_fwd_{horizon_days}d"].to_numpy(dtype=np.float64)
            dates = merged[date_col].to_numpy()

            # Compute rolling stats (vectorized)
            alpha, beta, r2, se_beta, t_beta, p_beta, se_alpha = rolling_ols_stats(y, x, window)

            # Stride & forward-fill
            k = max(1, int(config.stride_days))
            if k > 1:
                # Keep every k-th observation after the first full window
                mask = np.zeros_like(beta, dtype=bool)
                mask_idx = np.arange(window - 1, len(beta), k)
                mask[mask_idx] = True
                # Forward-fill to full daily grid (per-ticker arrays)
                def ffill(arr):
                    s = pd.Series(arr)
                    return s.ffill().to_numpy()
                alpha = ffill(np.where(mask, alpha, np.nan))
                beta = ffill(np.where(mask, beta, np.nan))
                r2 = ffill(np.where(mask, r2, np.nan))
                se_beta = ffill(np.where(mask, se_beta, np.nan))
                t_beta = ffill(np.where(mask, t_beta, np.nan))
                p_beta = ffill(np.where(mask, p_beta, np.nan))
                se_alpha = ffill(np.where(mask, se_alpha, np.nan))

            df_out = pd.DataFrame({
                date_col: dates,
                "Ticker": ticker,
                "Horizon_D": horizon_days,
                "Alpha": alpha,
                "Beta": beta,
                "R2": r2,
                "N": np.where(np.isfinite(beta), window, np.nan),
                "Beta_SE": se_beta,
                "Alpha_SE": se_alpha,
                "Beta_t": t_beta,
                "Beta_p": p_beta,
                "Beta_CI_Low": beta - stats.t.ppf(0.975, df=max(1, window-2)) * se_beta,
                "Beta_CI_High": beta + stats.t.ppf(0.975, df=max(1, window-2)) * se_beta,
            })
            out_frames.append(df_out[np.isfinite(df_out["Beta"])])  # keep rows where β exists

        results_by_horizon[horizon_days] = pd.concat(out_frames, ignore_index=True) if out_frames else pd.DataFrame()

    return results_by_horizon

# ======================================================
# Gate, Features, Conformal, Models (unchanged from your v3)
# ======================================================

def summarize_beta_signal_quality(strategy1_outputs: Dict[int, pd.DataFrame], config: Config, logger: Optional[logging.Logger] = None) -> pd.DataFrame:
    summary_frames = []
    for horizon_days, df_stats in strategy1_outputs.items():
        if df_stats.empty:
            continue
        grouped = df_stats.groupby("Ticker", as_index=False).agg(
            med_p=("Beta_p", "median"),
            med_r2=("R2", "median"),
            n_obs=("Beta", "count")
        )
        grouped["Horizon_D"] = horizon_days
        grouped["ok"] = (
            (grouped["med_p"] < config.gate_p_value_threshold) &
            (grouped["med_r2"] > config.gate_r2_threshold) &
            (grouped["n_obs"] >= config.minimum_observations_per_window)
        )
        summary_frames.append(grouped)
    gate_summary = pd.concat(summary_frames, ignore_index=True) if summary_frames else pd.DataFrame(columns=["Ticker","Horizon_D","med_p","med_r2","n_obs","ok"])
    if logger is not None and not gate_summary.empty:
        logger.info(f"[β gate] {int(gate_summary['ok'].sum())}/{len(gate_summary)} ticker×horizon pairs pass (p<{config.gate_p_value_threshold}, R²>{config.gate_r2_threshold}).")
    return gate_summary

def build_leak_safe_features(returns_wide: pd.DataFrame, config: Config, ticker_list: List[str]) -> pd.DataFrame:
    feature_frames = []
    for ticker in ticker_list:
        returns_series = winsorize_simple_returns(returns_wide[ticker].astype(float), max_abs=0.10)
        ar1_20 = rolling_autocorr_lag1(returns_series, window=20, lag=1).shift(1)
        vol_20 = rolling_standard_deviation(returns_series, 20).shift(1)
        mom_5  = ((1 + returns_series).rolling(5).apply(np.prod, raw=True) - 1).shift(1)
        mom_20 = ((1 + returns_series).rolling(20).apply(np.prod, raw=True) - 1).shift(1)
        price_index = (1 + returns_series.fillna(0)).cumprod()
        price_z20 = rolling_zscore(price_index, 20).shift(1)

        feature_frames.append(pd.DataFrame({
            config.date_column: returns_wide[config.date_column],
            "Ticker": ticker,
            "AR1_20": ar1_20,
            "VOL_20": vol_20,
            "MOM_5": mom_5,
            "MOM_20": mom_20,
            "PRICE_Z20": price_z20,
        }))

    features_panel = pd.concat(feature_frames, ignore_index=True)
    return downcast_to_float32(features_panel, columns=["AR1_20","VOL_20","MOM_5","MOM_20","PRICE_Z20"])

def conformal_interval_from_residuals(residuals: np.ndarray, alpha: float) -> Tuple[float,float]:
    finite = residuals[np.isfinite(residuals)]
    if finite.size == 0:
        return (0.0, 0.0)
    lower = np.quantile(finite, alpha/2.0)
    upper = np.quantile(finite, 1 - alpha/2.0)
    return float(lower), float(upper)

def build_regressor(model_name: str, params: dict, config: Config) -> Pipeline:
    if model_name == "ridge":
        reg = Ridge(alpha=params.get("alpha", 1.0), random_state=config.random_state)
    elif model_name == "elastic":
        reg = ElasticNet(alpha=params.get("alpha", 1.0), l1_ratio=params.get("l1_ratio", 0.1), random_state=config.random_state, max_iter=5000)
    elif model_name == "hgb":
        reg = HistGradientBoostingRegressor(
            max_depth=3, max_iter=300, learning_rate=0.05, l2_regularization=1.0,
            early_stopping='auto', validation_fraction=0.1, random_state=config.random_state
        )
    else:
        raise ValueError(f"Unknown model: {model_name}")
    return Pipeline([("scale", StandardScaler()), ("reg", reg)])

def embargoed_time_splits(unique_dates: np.ndarray, n_splits: int = 5, embargo: int = 5) -> Iterable[Tuple[np.ndarray, np.ndarray]]:
    ordered_unique = np.unique(unique_dates)
    if ordered_unique.size < n_splits + 1:
        n_splits = max(2, min(ordered_unique.size-1, 3))
    splitter = TimeSeriesSplit(n_splits=n_splits)
    for train_u_idx, val_u_idx in splitter.split(ordered_unique):
        train_dates = ordered_unique[train_u_idx]
        val_dates = ordered_unique[val_u_idx]
        if embargo > 0 and train_dates.size > embargo and val_dates.size > 0:
            truncated_train = train_dates[:-embargo]
            train_mask = np.isin(unique_dates, truncated_train)
        else:
            train_mask = np.isin(unique_dates, train_dates)
        val_mask = np.isin(unique_dates, val_dates)
        yield np.where(train_mask)[0], np.where(val_mask)[0]

def embargoed_cv_mse_ridge(X, y, date_array, alpha: float, embargo: int) -> float:
    model = Pipeline([("scale", StandardScaler()), ("reg", Ridge(alpha=alpha))])
    losses = []
    for train_idx, val_idx in embargoed_time_splits(date_array, n_splits=5, embargo=embargo):
        if train_idx.size < 50 or val_idx.size < 10:
            continue
        model.fit(X[train_idx], y[train_idx])
        y_pred = model.predict(X[val_idx])
        losses.append(np.nanmean((y[val_idx] - y_pred)**2))
    return float(np.nanmean(losses)) if losses else np.inf

def embargoed_cv_mse_elastic(X, y, date_array, alpha: float, l1_ratio: float, embargo: int) -> float:
    model = Pipeline([("scale", StandardScaler()), ("reg", ElasticNet(alpha=alpha, l1_ratio=l1_ratio, max_iter=5000))])
    losses = []
    for train_idx, val_idx in embargoed_time_splits(date_array, n_splits=5, embargo=embargo):
        if train_idx.size < 50 or val_idx.size < 10:
            continue
        model.fit(X[train_idx], y[train_idx])
        y_pred = model.predict(X[val_idx])
        losses.append(np.nanmean((y[val_idx] - y_pred)**2))
    return float(np.nanmean(losses)) if losses else np.inf

def choose_hyperparameters(X: np.ndarray, y: np.ndarray, date_array: np.ndarray, config: Config) -> dict:
    sample_count = len(y)
    if config.beta_model_name == "ridge":
        alpha_grid = config.ridge_alpha_grid if sample_count < 200_000 else [0.1, 1.0, 10.0]
        best_params, best_loss = None, np.inf
        for alpha in alpha_grid:
            loss = embargoed_cv_mse_ridge(X, y, date_array, alpha=alpha, embargo=config.embargo_days)
            if loss < best_loss:
                best_loss, best_params = loss, {"alpha": alpha}
        return best_params
    elif config.beta_model_name == "elastic":
        alpha_grid = config.elastic_alpha_grid if sample_count < 200_000 else [0.1, 1.0]
        l1_grid = config.elastic_l1_grid if sample_count < 200_000 else [0.1, 0.5]
        best_params, best_loss = None, np.inf
        for alpha in alpha_grid:
            for l1_ratio in l1_grid:
                loss = embargoed_cv_mse_elastic(X, y, date_array, alpha=alpha, l1_ratio=l1_ratio, embargo=config.embargo_days)
                if loss < best_loss:
                    best_loss, best_params = loss, {"alpha": alpha, "l1_ratio": l1_ratio}
        return best_params
    else:
        return {}

# ======================================================
# β ML Training / Forecast (same as v3)
# ======================================================

def fit_and_forecast_beta_ml(
    features_panel: pd.DataFrame,
    strategy1_stats: pd.DataFrame,
    config: Config,
    horizon_days: int,
    logger: logging.Logger
) -> pd.DataFrame:
    merged = features_panel.merge(
        strategy1_stats[["Date","Ticker","Horizon_D","Beta"]],
        on=["Date","Ticker"], how="inner", validate="many_to_one"
    )
    merged = merged[merged["Horizon_D"] == horizon_days].copy()
    merged["Beta_Future"] = merged.groupby("Ticker")["Beta"].shift(-horizon_days)
    required_columns = ["AR1_20","VOL_20","MOM_5","MOM_20","PRICE_Z20","Beta_Future"]
    merged = merged.dropna(subset=required_columns).copy()

    if merged.empty or merged["Beta_Future"].notna().sum() < 200:
        logger.warning(f"[β ML {horizon_days}d] Not enough data after merge/shift; skipping.")
        return pd.DataFrame(columns=["Date","Ticker","Horizon_D","Beta_Pred","CI_Low","CI_High"])

    merged["sample_weight"] = 1.0 / np.clip(merged["VOL_20"].astype(float).values, 1e-6, np.inf)

    X_matrix = merged[["AR1_20","VOL_20","MOM_5","MOM_20","PRICE_Z20"]].to_numpy(dtype=np.float32)
    y_target = merged["Beta_Future"].to_numpy(dtype=np.float32)
    date_array = pd.to_datetime(merged["Date"]).to_numpy()

    best_params = choose_hyperparameters(X_matrix, y_target, date_array, config)
    model = build_regressor(config.beta_model_name, best_params, config)

    sorted_idx = np.argsort(date_array)
    X_matrix = X_matrix[sorted_idx]; y_target = y_target[sorted_idx]; date_array = date_array[sorted_idx]
    sample_weight = merged["sample_weight"].to_numpy()[sorted_idx]
    n = len(y_target); n_train = int(n*0.80); n_cal = int(n*0.10)
    train_idx = np.arange(0, n_train); cal_idx = np.arange(n_train, n_train+n_cal)

    try:
        model.fit(X_matrix[train_idx], y_target[train_idx], reg__sample_weight=sample_weight[train_idx])
    except TypeError:
        try:
            model.named_steps["reg"].fit(
                model.named_steps["scale"].fit_transform(X_matrix[train_idx]),
                y_target[train_idx],
                sample_weight=sample_weight[train_idx]
            )
        except Exception:
            model.fit(X_matrix[train_idx], y_target[train_idx])

    y_cal = y_target[cal_idx]
    yhat_cal = model.predict(X_matrix[cal_idx])
    residuals = y_cal - yhat_cal
    q_lo, q_hi = conformal_interval_from_residuals(residuals, alpha=config.conformal_alpha)

    latest_date = pd.to_datetime(merged["Date"]).max()
    latest_rows = merged[merged["Date"] == latest_date].copy()
    if latest_rows.empty:
        latest_rows = merged.sort_values("Date").groupby("Ticker").tail(1).copy()

    X_latest = latest_rows[["AR1_20","VOL_20","MOM_5","MOM_20","PRICE_Z20"]].to_numpy(dtype=np.float32)
    beta_pred = model.predict(X_latest).astype(np.float32)
    ci_low = (beta_pred + q_lo).astype(np.float32)
    ci_high = (beta_pred + q_hi).astype(np.float32)

    return pd.DataFrame({
        "Date": latest_rows["Date"].values,
        "Ticker": latest_rows["Ticker"].values,
        "Horizon_D": horizon_days,
        "Beta_Pred": beta_pred,
        "CI_Low": ci_low,
        "CI_High": ci_high,
    })

# ======================================================
# Orchestration
# ======================================================

def run_pipeline(config: Config) -> None:
    logger = setup_logger(config.output_directory)
    logger.info("Starting β Strategy‑1 + ML pipeline (FAST variant)")

    logger.info("Resolving input Excel + sheet…")
    if config.input_csv_path:
        logger.info(f"Loading returns from CSV: {config.input_csv_path}")
        returns_wide = pd.read_csv(config.input_csv_path)
    else:
        excel_path, sheet_name = autodiscover_excel_and_sheet(
            str(config.excel_path) if config.excel_path else None, 
            config.sheet_name, 
            logger
        )
        config.excel_path, config.sheet_name = excel_path, sheet_name
        logger.info(f"Loading returns from Excel: {excel_path.name}, sheet: {sheet_name}")
        returns_wide = load_returns_wide(excel_path, sheet_name)

    returns_wide[config.date_column] = pd.to_datetime(returns_wide[config.date_column])
    returns_wide = returns_wide.sort_values(config.date_column).reset_index(drop=True)

    return_cols = [c for c in returns_wide.columns if c != config.date_column]
    if config.market_column not in returns_wide.columns:
        market_candidates = [c for c in return_cols if any(x in c.upper() for x in ['SPX', 'SPY', 'SP500', 'MARKET'])]
        if market_candidates:
            logger.info(f"Market column '{config.market_column}' not found, using '{market_candidates[0]}'")
            config.market_column = market_candidates[0]
        else:
            config.market_column = return_cols[0]
            logger.warning(f"No clear market column found, using '{config.market_column}'")

    for col in return_cols:
        returns_wide[col] = pd.to_numeric(returns_wide[col], errors="coerce")
        if col != config.market_column:
            returns_wide[col] = winsorize_simple_returns(returns_wide[col])

    ticker_list = [c for c in returns_wide.columns if c not in (config.date_column, config.market_column)]
    if config.float_downcast:
        for c in ticker_list + [config.market_column]:
            returns_wide[c] = returns_wide[c].astype("float32", copy=False)

    logger.info(f"Data loaded: {len(returns_wide):,} rows × {len(returns_wide.columns)} columns")
    logger.info(f"Date range: {returns_wide[config.date_column].min().date()} to {returns_wide[config.date_column].max().date()}")
    logger.info(f"Market column: {config.market_column}")
    logger.info(f"Tickers: {len(ticker_list)} ({', '.join(ticker_list[:5])}{'...' if len(ticker_list) > 5 else ''})")

    # ------- FAST Strategy‑1 (Rolling OLS) -------
    logger.info("Running FAST Strategy‑1 (vectorized rolling OLS)…")
    strategy1_outputs = run_strategy1_rolling_ols_fast(returns_wide[[config.date_column, config.market_column] + ticker_list], config, ticker_list, logger)
    for horizon_days, frame in strategy1_outputs.items():
        output_path = config.output_directory / f"strategy1_betas_{horizon_days}d.csv"
        frame.to_csv(output_path, index=False)
        logger.info(f"Saved Strategy‑1: {output_path} ({len(frame):,} rows)")

    # ------- OLS signal-quality gate -------
    gate_summary = summarize_beta_signal_quality(strategy1_outputs, config, logger=logger)

    # ------- Feature panel -------
    logger.info("Building features (leak-safe, downcast)…")
    features_panel = build_leak_safe_features(returns_wide[[config.date_column] + ticker_list], config, ticker_list)

    # ------- ML β head per horizon (only where OLS shows structure) -------
    for horizon_days in config.beta_horizons_days:
        ok_tickers = set(gate_summary.loc[(gate_summary["Horizon_D"] == horizon_days) & (gate_summary["ok"]), "Ticker"])
        if not ok_tickers:
            logger.warning(f"[β ML {horizon_days}d] No tickers pass OLS gate; fallback = {config.fallback_mode}")
            if config.fallback_mode == "median":
                last_stats = strategy1_outputs[horizon_days].sort_values(config.date_column).groupby("Ticker").tail(1)
                med = last_stats.groupby("Ticker")["Beta"].median().rename("Beta_Pred").reset_index()
                med["Date"] = last_stats[config.date_column].max()
                med["Horizon_D"] = horizon_days
                med["CI_Low"] = med["Beta_Pred"]; med["CI_High"] = med["Beta_Pred"]
                out_path = config.output_directory / f"bpred_{horizon_days}d_forecast.csv"
                med[["Date","Ticker","Horizon_D","Beta_Pred","CI_Low","CI_High"]].to_csv(out_path, index=False)
                logger.info(f"Saved fallback median β forecast: {out_path} ({len(med):,} rows)")
            continue

        stats_ok = strategy1_outputs[horizon_days][strategy1_outputs[horizon_days]["Ticker"].isin(ok_tickers)].copy()
        forecast_frame = fit_and_forecast_beta_ml(features_panel, stats_ok, config, horizon_days, logger)
        if forecast_frame.empty:
            logger.warning(f"[β ML {horizon_days}d] Empty forecast; check merged data.")
            continue
        out_path = config.output_directory / f"bpred_{horizon_days}d_forecast.csv"
        forecast_frame.to_csv(out_path, index=False)
        logger.info(f"Saved β ML forecast: {out_path} ({len(forecast_frame):,} rows)")

    logger.info("Done. ✅")

def main():
    config = parse_cli_arguments()
    run_pipeline(config)

if __name__ == "__main__":
    main()
