#!/usr/bin/env python3
"""
MR-PROD — Mean-Reversion Research → Production (headless)
=========================================================

Purpose
-------
Produce *per-stock*, *per-date* mean-reversion likelihoods and expected
move sizes for the next 1, 3, 7, 15, and 30 trading days — with leak-aware
validation, probability calibration, and conformal magnitude bands.

No GUI, no portfolio/positions. Outputs CSVs you can hand to a client.

Key features
------------
• Robust Excel loader for daily simple returns (supports strings like "0.56%")
• Returns hygiene: winsorization (±10% default)
• Features from returns only (AR(1), sign persistence, momentum, vol, z-score)
• Labels: mean-reversion vs momentum with a vol-scaled gate per horizon
• Walk-forward by trading-day counts with horizon-aware purge + optional embargo
• Inner CV hyperparameter tuning (AUC); OOS isotonic calibration (no leakage)
• Magnitude head (|move|) per regime + conformal prediction intervals
• Clean per-horizon outputs (predictions & per-ticker metrics) + run_meta.json

CLI
---
Example:
  python stable_2_lastestv3.py \
    --excel "MXUS_Data.xlsx" --sheet "Returns" \
    --out results --model logit --embargo 5

Requirements
------------
  pip install pandas numpy scikit-learn openpyxl joblib matplotlib
(Optional tree models):
  pip install xgboost lightgbm
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Union

import numpy as np
import pandas as pd
from pandas.tseries.offsets import BDay

from joblib import dump, Parallel, delayed

from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, f1_score, precision_score, recall_score, average_precision_score
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.isotonic import IsotonicRegression
from sklearn.ensemble import HistGradientBoostingRegressor

# Optional tqdm for progress bars
try:
    from tqdm.auto import tqdm
except Exception:  # pragma: no cover
    def tqdm(iterable=None, **kwargs):
        return iterable

# --- Constants ---
ABSTAIN = -1  # Label for when the model abstains from making a prediction
THIS_DIR = Path(__file__).resolve().parent


# =============================================================================
# CONFIGURATION
# =============================================================================
@dataclass
class Config:
    """Holds all parameters for a pipeline run."""
    # --- I/O ---
    excel_path: str | Path = "MXUS_Data.xlsx"
    sheet_name: str = "Returns"
    output_dir: str | Path = "results"

    # --- Market Data (Optional) ---
    with_market: bool = True
    market_sheet: str = "Market"
    market_source: str = "yahoo_price"  # ['yahoo_price','yahoo_tr','stooq','fred']
    market_start: str = "1990-01-01"

    # --- Labeling (vol-scaled gate) ---
    vol_window: int = 20
    vol_k: float = 0.5  # Gate threshold = vol_k * rolling_std * sqrt(horizon)

    # --- Walk-Forward Setup ---
    train_years: int = 3
    validation_years: int = 1
    trading_days_per_year: int = 252
    embargo_days: int = 5  # Gap between train and test to prevent lookahead bias

    # --- Model Hyperparameters ---
    # Logistic Regression (default)
    alpha_grid: List[float] = field(default_factory=lambda: [0.0, 1.0])  # L1/L2 ratio
    reg_strengths_C: List[float] = field(default_factory=lambda: [0.1, 1.0, 10.0]) # Inverse of regularization strength
    inner_cv_folds: int = 3 # Folds for inner cross-validation (hyperparameter tuning)

    # XGBoost / LightGBM (optional)
    xgb_param_grid: List[Dict[str, Union[int, float]]] = field(
        default_factory=lambda: [
            {"max_depth": 3, "n_estimators": 400, "learning_rate": 0.05},
        ]
    )
    lgb_param_grid: List[Dict[str, Union[int, float]]] = field(
        default_factory=lambda: [
            {"num_leaves": 31, "n_estimators": 400, "learning_rate": 0.05},
        ]
    )

    # --- Horizons ---
    # Tuples of (name, forward_return_horizon_h, momentum_lookback_k)
    horizons: List[Tuple[str, int, int]] = field(
        default_factory=lambda: [
            ("d1", 1, 1),
            ("d3", 3, 3),
            ("d7", 7, 7),
            ("d15", 15, 15),
            ("d30", 30, 30),
        ]
    )

    # --- Feature Engineering ---
    ar_windows: List[int] = field(default_factory=lambda: [10, 20, 60])
    sign_persist_windows: List[int] = field(default_factory=lambda: [20, 60])
    vol_feat_windows: List[int] = field(default_factory=lambda: [10, 20])
    z_score_windows: List[int] = field(default_factory=lambda: [20, 60])
    winsor_abs_limit: float = 0.10 # Clip daily returns to +/- 10%

    # --- Reproducibility & Parallelism ---
    random_state: int = 42
    n_jobs: int = -1  # Parallelism for hyperparameter scoring: number of CPU cores to use for parallel tasks. A value of -1 means all available cores will be used.

    # --- Thresholding & Coverage Control ---
    threshold_grid: List[float] = field(default_factory=lambda: [round(x, 2) for x in np.arange(0.55, 0.91, 0.01)])
    min_coverage: Optional[float] = 0.40  # e.g., 0.40 for 40% minimum prediction coverage
    fixed_threshold: Optional[float] = None      # Fixed confidence threshold if provided
    threshold_rule: str = "coverage"            # 'coverage' or 'none'
    min_valid_frac: float = 0.70           # Min non-NaN fraction per ticker to be included

    # --- Calibration & Magnitude Prediction ---
    calib_frac: float = 0.20  # Fraction of train set held out for magnitude model calibration
    conformal_alpha: float = 0.10  # For (1 - alpha) * 100% prediction intervals (e.g., 0.10 -> 90% PI)

    # Magnitude model (HistGradientBoostingRegressor) parameters
    hgb_max_depth: int = 3
    hgb_max_iter: int = 300
    hgb_lr: float = 0.05
    hgb_l2: float = 1.0

    # --- Verbosity ---
    verbose: bool = True
    show_progress: bool = True


# =============================================================================
# LOGGING
# =============================================================================
def setup_logging(output_directory: Path) -> logging.Logger:
    """Configures a logger to write to a file and to the console."""
    output_directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("mr_prod")
    logger.setLevel(logging.INFO)
    # Clear any existing handlers to avoid duplicate logs
    if logger.hasHandlers():
        logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    # File handler
    file_handler = logging.FileHandler(output_directory / "run.log", mode="w")
    file_handler.setFormatter(formatter)
    # Console handler
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger


# =============================================================================
# DATA LOADING & PREPARATION UTILITIES
# =============================================================================
def _parse_percentish(series: pd.Series) -> pd.Series:
    """Converts a series of strings like '0.56%' or '0.56' to decimals.
    Robust to mixed types and uses a heuristic to decide if division by 100 is needed.
    """
    numeric_series = pd.to_numeric(series.astype(str).str.replace("%", "", regex=False).str.strip(), errors="coerce")
    # Heuristic: if high quantiles are between 1 and 100, assume they are percentages.
    abs_q90 = numeric_series.abs().quantile(0.90)
    abs_q95 = numeric_series.abs().quantile(0.95)
    abs_q99 = numeric_series.abs().quantile(0.99)
    if (0.20 < abs_q90 <= 100) or (abs_q95 > 1.0 and abs_q99 <= 100):
        numeric_series = numeric_series / 100.0
    return numeric_series


def load_returns_wide(excel_path: str | Path, sheet_name: str) -> pd.DataFrame:
    """Loads returns from an Excel sheet into a wide-format DataFrame."""
    if not Path(excel_path).exists():
        raise FileNotFoundError(f"Excel file not found: {excel_path}")
    dataframe = pd.read_excel(excel_path, sheet_name=sheet_name, engine="openpyxl")
    if dataframe.shape[1] < 2:
        raise ValueError("Expected 'Date' column plus at least one ticker column in the Returns sheet.")
    # Standardize date column name and format
    first_col_name = dataframe.columns[0]
    dataframe = dataframe.rename(columns={first_col_name: "Date"})
    dataframe["Date"] = pd.to_datetime(dataframe["Date"], errors="coerce")
    dataframe = dataframe[dataframe["Date"].notna()].sort_values("Date").reset_index(drop=True)
    # Parse all ticker columns
    for col in [c for c in dataframe.columns if c != "Date"]:
        dataframe[col] = _parse_percentish(dataframe[col])
    return dataframe

def validate_returns_wide(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Performs basic quality checks on the loaded returns data."""
    issues = []
    num_duplicates = int(dataframe["Date"].duplicated().sum())
    if num_duplicates:
        issues.append(dict(issue="duplicate_dates", count=num_duplicates))
    if not dataframe["Date"].is_monotonic_increasing:
        issues.append(dict(issue="non_monotone_dates", count=int(len(dataframe))))
    all_nan_tickers = [c for c in dataframe.columns if c != "Date" and dataframe[c].notna().sum() == 0]
    if all_nan_tickers:
        issues.append(dict(issue="all_nan_tickers", tickers=",".join(all_nan_tickers), count=len(all_nan_tickers)))
    return pd.DataFrame(issues)


# =============================================================================
# FEATURE ENGINEERING UTILITIES
# =============================================================================
def winsorize_simple_returns(series: pd.Series, limit_abs: float) -> pd.Series:
    """Clips returns to a symmetric absolute limit."""
    return series.clip(lower=-limit_abs, upper=limit_abs)


def compound_forward_simple(simple_returns: pd.Series, horizon: int) -> pd.Series:
    """Calculates forward-looking compounded returns."""
    compounded_price = (1.0 + simple_returns).cumprod()
    forward_return = compounded_price.shift(-horizon) / compounded_price - 1.0
    if horizon > 0:
        forward_return.iloc[-horizon:] = np.nan # Set trailing values to NaN
    return forward_return


def compound_past_simple(simple_returns: pd.Series, window: int) -> pd.Series:
    """Calculates past compounded returns over a rolling window, shifted to be a feature."""
    past_return = (1.0 + simple_returns).rolling(window).apply(np.prod, raw=True) - 1.0
    return past_return.shift(1) # Shift to align with the prediction date


def rolling_autocorr(series: pd.Series, window: int, lag: int = 1) -> pd.Series:
    """Calculates rolling autocorrelation, shifted to be a feature."""
    x_previous = series.shift(lag)
    correlation = series.rolling(window).corr(x_previous)
    return correlation.shift(1)


def rolling_sign_persistence(series: pd.Series, window: int) -> pd.Series:
    """Calculates the rate of consecutive returns having the same sign, shifted."""
    same_sign = (np.sign(series) * np.sign(series.shift(1))) > 0
    persistence_rate = same_sign.rolling(window).mean()
    return persistence_rate.shift(1)


# =============================================================================
# MARKET CONTEXT (Optional S&P 500)
# =============================================================================
def load_market_from_excel(excel_path: str | Path, sheet_name: str = "Market", logger: Optional[logging.Logger] = None) -> Optional[pd.DataFrame]:
    """Attempts to load market returns from a dedicated Excel sheet."""
    try:
        dataframe = pd.read_excel(excel_path, sheet_name=sheet_name, engine="openpyxl")
    except Exception:
        return None
    if dataframe.empty or dataframe.shape[1] < 2:
        return None
    # Standardize column names and format
    first_col_name = dataframe.columns[0]
    dataframe = dataframe.rename(columns={first_col_name: "Date"})
    dataframe["Date"] = pd.to_datetime(dataframe["Date"], errors="coerce")
    dataframe = dataframe[dataframe["Date"].notna()].sort_values("Date").reset_index(drop=True)

    column_names = [c for c in dataframe.columns if c != "Date"]
    market_return = None
    if "MKT_RET" in dataframe.columns:
        market_return = pd.to_numeric(dataframe["MKT_RET"], errors="coerce")
    else: # Try to infer returns from a price column
        price_col_candidates = [c for c in column_names if c.lower() in ("mkt_px","px","close","adj close","price","value")]
        if not price_col_candidates and len(column_names) == 1:
            price_col_candidates = [column_names[0]]
        if price_col_candidates:
            price_series = pd.to_numeric(dataframe[price_col_candidates[0]], errors="coerce")
            market_return = price_series.pct_change()

    if market_return is None:
        if logger: logger.warning("Market sheet present but could not infer MKT_RET. Skipping market features.")
        return None
    output_df = pd.DataFrame({"Date": dataframe["Date"], "MKT_RET": market_return})
    return output_df.dropna()


def get_sp500_market(source: str = "yahoo_price", start: str = "1990-01-01", end: Optional[str] = None, logger: Optional[logging.Logger] = None) -> Optional[pd.DataFrame]:
    """Fetches S&P 500 data from an external source as a fallback."""
    try:
        if end is None:
            end = pd.Timestamp.today().normalize().strftime("%Y-%m-%d")
        if source == "yahoo_price":
            import yfinance as yf
            price_series = yf.download("^GSPC", start=start, end=end, progress=False)["Adj Close"].rename("MKT_PX")
        elif source == "yahoo_tr":
            import yfinance as yf
            price_series = yf.download("^SP500TR", start=start, end=end, progress=False)["Adj Close"].rename("MKT_PX")
        elif source == "stooq":
            url = "https://stooq.com/q/d/l/?s=%5Espx&i=d"
            df = pd.read_csv(url)
            df["Date"] = pd.to_datetime(df["Date"])
            price_series = df.set_index("Date")["Close"].rename("MKT_PX").sort_index()
        elif source == "fred":
            from fredapi import Fred
            fred = Fred(api_key=os.getenv("FRED_API_KEY"))
            price_series = fred.get_series("SP500", observation_start=start, observation_end=end).rename("MKT_PX")
            price_series.index = pd.to_datetime(price_series.index)
        else:
            if logger: logger.warning(f"Unknown market source '{source}'. Skipping market features.")
            return None
    except Exception as e:
        if logger: logger.warning(f"Failed to fetch market data via {source}: {e}")
        return None
    market_df = price_series.dropna().to_frame()
    market_df["MKT_RET"] = market_df["MKT_PX"].pct_change()
    output_df = market_df.reset_index().rename(columns={"index": "Date"})
    return output_df.dropna()


def compute_market_features(market_df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Computes a few standard market-wide features."""
    df = market_df.copy().sort_values("Date")
    df["MKT_RET_1D"] = df["MKT_RET"]
    df["MKT_RET_5D"] = (1.0 + df["MKT_RET"]).rolling(5).apply(lambda x: np.prod(x) - 1.0, raw=True)
    df["MKT_VOL_20D"] = df["MKT_RET"].rolling(20).std()
    # Z-score of the price index vs. its 20-day moving average
    price_index = (1.0 + df["MKT_RET"].fillna(0)).cumprod()
    window = 20
    moving_average = price_index.rolling(window, min_periods=window).mean()
    moving_std = price_index.rolling(window, min_periods=window).std()
    df["MKT_Z_MA_20D"] = (price_index - moving_average) / moving_std
    # Shift all features to prevent lookahead bias
    feature_cols = ["MKT_RET_1D","MKT_RET_5D","MKT_VOL_20D","MKT_Z_MA_20D"]
    for col in feature_cols:
        df[col] = df[col].shift(1)
    return df[["Date"] + feature_cols].dropna()


# =============================================================================
# MAIN FEATURE & LABEL CONSTRUCTION
# =============================================================================
def build_feature_panel(returns_wide: pd.DataFrame, cfg: Config, logger: logging.Logger) -> pd.DataFrame:
    """Converts wide returns data into a long-format panel with features and labels."""
    tickers = [c for c in returns_wide.columns if c != "Date"]
    ticker_frames: List[pd.DataFrame] = []

    for ticker in tqdm(tickers, desc="Building features (tickers)", disable=not (cfg.verbose and cfg.show_progress)):
        returns_series = returns_wide[ticker].astype(float)
        # Skip tickers with too much missing data
        if returns_series.notna().mean() < cfg.min_valid_frac:
            continue
        returns_series = winsorize_simple_returns(returns_series, cfg.winsor_abs_limit)
        base_df = pd.DataFrame({"Date": returns_wide["Date"], "ticker": ticker})
        
        # --- Feature Calculation ---
        features: Dict[str, pd.Series] = {}
        # AR(1)
        for w in cfg.ar_windows:
            features[f"ar1_corr_{w}d"] = rolling_autocorr(returns_series, window=w)
        # Sign persistence
        for w in cfg.sign_persist_windows:
            features[f"sign_persist_{w}d"] = rolling_sign_persistence(returns_series, window=w)
        # Momentum & short history returns
        features["ret_1d"] = returns_series.shift(1)
        features["ret_5d"] = compound_past_simple(returns_series, 5)
        features["ret_20d"] = compound_past_simple(returns_series, 20)
        # Volatility features
        for w in cfg.vol_feat_windows:
            features[f"vol_{w}d"] = returns_series.rolling(w).std().shift(1)
        # Price-index z-score vs rolling MA
        price_index = (1.0 + returns_series.fillna(0)).cumprod()
        for w in cfg.z_score_windows:
            moving_average = price_index.rolling(w, min_periods=w).mean()
            moving_std = price_index.rolling(w, min_periods=w).std()
            features[f"z_ma_{w}d"] = ((price_index - moving_average) / moving_std).shift(1)
        
        features_df = pd.DataFrame(features)
        
        # --- Forward Returns (for labels and magnitude) ---
        forward_returns = {f"fwd_{h}d": compound_forward_simple(returns_series, h) for _, h, _ in cfg.horizons}
        forward_returns_df = pd.DataFrame(forward_returns)
        
        # --- Recent Momentum (for labels) ---
        momentum = {f"mom_{k}d": compound_past_simple(returns_series, k) for _, _, k in cfg.horizons}
        momentum_df = pd.DataFrame(momentum)
        
        ticker_frames.append(pd.concat([base_df, features_df, forward_returns_df, momentum_df], axis=1))

    if not ticker_frames:
        raise RuntimeError("No usable tickers after cleaning and feature generation.")

    panel = pd.concat(ticker_frames, ignore_index=True)

    # --- Cross-Sectional Rank Features ---
    rank_cols = ["ret_1d", "ret_5d", "ret_20d"] + [f"z_ma_{w}d" for w in cfg.z_score_windows]
    for col in rank_cols:
        if col in panel.columns:
            panel[f"cs_rank_{col}"] = panel.groupby("Date")[col].rank(pct=True)

    # --- Label Generation ---
    # Pre-compute per-ticker daily vol for the labeling gate
    panel["daily_vol"] = panel.groupby("ticker")["ret_1d"].transform(lambda s: s.rolling(cfg.vol_window).std())

    # Generate labels for each horizon using a volatility-scaled gate
    for name, horizon_h, momentum_k in cfg.horizons:
        fwd_col = f"fwd_{horizon_h}d"
        mom_col = f"mom_{momentum_k}d"
        # Project daily vol to horizon and fill missing values within each ticker
        gate = cfg.vol_k * panel["daily_vol"] * np.sqrt(max(horizon_h, 1))
        gate = gate.groupby(panel["ticker"]).transform(lambda s: s.fillna(s.median()))
        
        sign_future = np.sign(panel[fwd_col])
        sign_recent = np.sign(panel[mom_col])
        
        # A "significant" move is one larger than the gate
        is_significant_move = panel[fwd_col].abs() > gate
        
        # Label is 1 (MR) if move is significant and direction is opposite to recent momentum.
        # Label is 0 (MO) if move is significant and direction is same as recent momentum.
        # Label is NaN otherwise (insignificant move).
        label_mr = np.where(
            (is_significant_move) & (sign_recent != 0) & (sign_future == -sign_recent), 1,
            np.where((is_significant_move) & (sign_recent != 0), 0, np.nan),
        )
        panel[f"label_mr_{name}"] = label_mr

    # --- Final Cleanup ---
    # Define final feature list, excluding metadata, labels, and forward/momentum returns
    feature_cols = [
        c for c in panel.columns
        if c not in ("Date", "ticker", "daily_vol")
        and not c.startswith("fwd_") and not c.startswith("mom_") and not c.startswith("label_")
    ]

    # Drop rows with any NaN features, as models can't handle them
    panel = panel.dropna(subset=feature_cols).reset_index(drop=True)

    logger.info(
        f"Panel built: {panel.shape[0]:,} rows × {panel.shape[1]} cols  "
        f"({panel['Date'].min().date()} → {panel['Date'].max().date()})"
    )
    return panel


# =============================================================================
# TIME SERIES SPLITTING
# =============================================================================
def walk_forward_windows(dates: pd.Series, train_years: int, val_years: int, trading_days_per_year: int) -> List[Tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
    """Creates walk-forward windows for outer cross-validation."""
    unique_dates = pd.to_datetime(pd.Series(dates.unique())).sort_values().to_numpy()
    n_train_days = int(train_years * trading_days_per_year)
    n_val_days = int(val_years * trading_days_per_year)
    
    # Define the start indices for each window, stepping by the validation size
    start_indices = np.arange(0, len(unique_dates) - (n_train_days + n_val_days) + 1, n_val_days, dtype=int)
    
    windows: List[Tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]] = []
    for start_idx in start_indices:
        train_dates = unique_dates[start_idx : start_idx + n_train_days]
        val_dates = unique_dates[start_idx + n_train_days : start_idx + n_train_days + n_val_days]
        if train_dates.size == 0 or val_dates.size == 0:
            continue
        windows.append((pd.Timestamp(train_dates[0]), pd.Timestamp(train_dates[-1]), pd.Timestamp(val_dates[0]), pd.Timestamp(val_dates[-1])))
    return windows


def purged_inner_splits(dates: np.ndarray, n_splits: int, purge_days: int):
    """Generates purged time-series splits for inner cross-validation.
    This prevents leakage by removing training samples that are too close to the validation set.
    """
    time_series_cv = TimeSeriesSplit(n_splits=n_splits)
    dates = pd.to_datetime(dates)
    for train_indices, val_indices in time_series_cv.split(dates):
        if val_indices.size == 0 or train_indices.size == 0:
            continue
        
        # Define the purge boundary
        val_start_date = pd.Timestamp(dates[val_indices].min())
        purge_cutoff_date = val_start_date - BDay(purge_days)
        
        # Filter the training indices to remove purged dates
        train_dates = dates[train_indices]
        keep_mask = (train_dates <= purge_cutoff_date) & (train_dates < val_start_date)
        purged_train_indices = train_indices[keep_mask]
        
        if purged_train_indices.size == 0:
            continue
        yield purged_train_indices, val_indices


# =============================================================================
# MODELS, CALIBRATION, AND THRESHOLDING
# =============================================================================
def make_logit(alpha_l1_ratio: float, regularization_strength_C: float, cfg: Config) -> Pipeline:
    """Builds a logistic regression model pipeline with scaling."""
    if alpha_l1_ratio == 0.0: # L2 regularization
        logit_model = LogisticRegression(penalty="l2", solver="lbfgs", C=regularization_strength_C, class_weight="balanced", max_iter=10_000, random_state=cfg.random_state)
    elif alpha_l1_ratio == 1.0: # L1 regularization
        logit_model = LogisticRegression(penalty="l1", solver="saga", C=regularization_strength_C, class_weight="balanced", max_iter=10_000, random_state=cfg.random_state)
    else: # ElasticNet
        logit_model = LogisticRegression(penalty="elasticnet", solver="saga", l1_ratio=alpha_l1_ratio, C=regularization_strength_C, class_weight="balanced", max_iter=10_000, random_state=cfg.random_state)
    return Pipeline([("scale", StandardScaler()), ("logit", logit_model)])


def make_tree(model_name: str, params: Dict[str, Union[int, float]], cfg: Config):
    """Builds an XGBoost or LightGBM model."""
    if model_name == "xgb":
        import xgboost as xgb
        defaults = dict(objective="binary:logistic", eval_metric="logloss", n_jobs=-1, tree_method="hist", random_state=cfg.random_state, subsample=0.8, colsample_bytree=0.8, reg_lambda=1.0)
        defaults.update(params)
        return xgb.XGBClassifier(**defaults)
    if model_name == "lgb":
        import lightgbm as lgb
        defaults = dict(objective="binary", n_jobs=-1, random_state=cfg.random_state, subsample=0.8, colsample_bytree=0.8, reg_lambda=1.0, learning_rate=0.05, is_unbalance=True)
        defaults.update(params)
        return lgb.LGBMClassifier(**defaults)
    raise ValueError(f"Unknown tree model: {model_name}")


def build_model(name: str, params: Dict[str, Union[int, float]], cfg: Config):
    """Factory function to build any supported model."""
    if name == "logit":
        return make_logit(params.get("alpha", 0.0), params.get("C", 1.0), cfg)
    if name in ("xgb", "lgb"):
        return make_tree(name, params, cfg)
    raise ValueError(f"Unknown model name: {name}")


def auc_safe(y_true: np.ndarray, y_prob: np.ndarray) -> float:
    """Calculates AUC score, safely handling edge cases."""
    y_true_clean = np.asarray(y_true)
    y_prob_clean = np.asarray(y_prob, dtype=float)
    
    keep_mask = np.isin(y_true_clean, [0, 1]) & np.isfinite(y_prob_clean)
    y_true_clean = y_true_clean[keep_mask]
    y_prob_clean = y_prob_clean[keep_mask]
    
    # Return 0.5 if not enough data, only one class, or no variance in predictions
    if y_true_clean.size == 0 or np.unique(y_true_clean).size < 2 or np.allclose(np.nanstd(y_prob_clean), 0.0):
        return 0.5
    try:
        return float(roc_auc_score(y_true_clean, y_prob_clean))
    except Exception:
        return 0.5


def fit_isotonic_safe(probabilities: np.ndarray, y_true: np.ndarray) -> Optional[IsotonicRegression]:
    """Fits an Isotonic Regression model for probability calibration, handling edge cases."""
    probs_clean = np.asarray(probabilities, dtype=float)
    y_true_clean = np.asarray(y_true)
    
    keep_mask = np.isfinite(probs_clean) & np.isin(y_true_clean, [0, 1])
    probs_clean = probs_clean[keep_mask]
    y_true_clean = y_true_clean[keep_mask]
    
    if probs_clean.size < 30 or np.unique(y_true_clean).size < 2:
        return None # Not enough data to fit a reliable calibrator
    try:
        calibrator = IsotonicRegression(out_of_bounds="clip").fit(probs_clean, y_true_clean)
        return calibrator
    except Exception:
        return None


def apply_calibrator(calibrator: Optional[IsotonicRegression], probabilities: np.ndarray) -> np.ndarray:
    """Applies a fitted isotonic calibrator to new probabilities."""
    if calibrator is None:
        return np.asarray(probabilities, dtype=float)
    try:
        return calibrator.predict(np.asarray(probabilities, dtype=float))
    except Exception:
        return np.asarray(probabilities, dtype=float)


def choose_threshold_by_coverage(probabilities: np.ndarray, thresholds: List[float], min_coverage: float) -> Tuple[float, float]:
    """Picks the largest confidence threshold that meets a minimum coverage requirement.
    Coverage(threshold) = mean( p >= threshold or p <= 1-threshold ).
    If none meet the requirement, returns threshold=0.5 (full coverage).
    """
    probs_clean = np.asarray(probabilities, dtype=float)
    # Iterate from highest (strictest) threshold to lowest
    for confidence_threshold in sorted([t for t in thresholds if t > 0.5], reverse=True):
        is_covered = (probs_clean >= confidence_threshold) | (probs_clean <= (1.0 - confidence_threshold))
        coverage = float(np.mean(is_covered))
        if coverage + 1e-12 >= float(min_coverage):
            return float(confidence_threshold), coverage
    return 0.5, 1.0 # Default if no threshold meets coverage


# =============================================================================
# MAGNITUDE PREDICTION & CONFORMAL UNCERTAINTY
# =============================================================================
def make_hgbr(cfg: Config) -> HistGradientBoostingRegressor:
    """Factory function for the magnitude prediction model."""
    return HistGradientBoostingRegressor(
        max_depth=cfg.hgb_max_depth,
        max_iter=cfg.hgb_max_iter,
        learning_rate=cfg.hgb_lr,
        l2_regularization=cfg.hgb_l2,
        random_state=cfg.random_state,
    )


def conformal_q(residuals: np.ndarray, alpha: float) -> float:
    """Calculates the quantile for split conformal prediction.
    This quantile (q-hat) is added/subtracted from predictions to form the interval.
    """
    residuals_clean = np.asarray(residuals, dtype=float)
    residuals_clean = residuals_clean[np.isfinite(residuals_clean)]
    n = residuals_clean.size
    if n == 0:
        return 0.0
    # Calculate the index for the (1-alpha) quantile
    k = int(np.ceil((n + 1) * (1 - alpha)))
    k = min(max(k, 1), n) # Ensure k is a valid index
    # np.partition is an efficient way to find the k-th smallest element
    return float(np.partition(residuals_clean, k - 1)[k - 1])


# =============================================================================
# CORE PIPELINE FOR A SINGLE HORIZON
# =============================================================================
def run_one_horizon(panel: pd.DataFrame, horizon_name: str, cfg: Config, model_name: str, logger: logging.Logger) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Runs the entire walk-forward process for a single prediction horizon."""
    label_col = f"label_mr_{horizon_name}"
    feature_cols = [c for c in panel.columns if c not in ("Date","ticker","daily_vol") and not c.startswith("fwd_") and not c.startswith("mom_") and not c.startswith("label_")]

    # Prepare data for this horizon
    df_horizon = panel.dropna(subset=[label_col]).copy()
    X_all = df_horizon[feature_cols].values
    y_all = df_horizon[label_col].astype(int).values
    dates_all = df_horizon["Date"].to_numpy()

    windows = walk_forward_windows(df_horizon["Date"], cfg.train_years, cfg.validation_years, cfg.trading_days_per_year)
    horizon_h, momentum_k = next((h, k) for name,h,k in cfg.horizons if name==horizon_name)
    fwd_col = f"fwd_{horizon_h}d"; mom_col = f"mom_{momentum_k}d"

    all_window_predictions: List[pd.DataFrame] = []

    def iter_param_grid(name: str):
        """Generator for hyperparameter grids."""
        if name == "logit":
            for alpha_l1_ratio in cfg.alpha_grid:
                for C in cfg.reg_strengths_C:
                    yield {"alpha": alpha_l1_ratio, "C": float(C)}
        elif name == "xgb":
            for p in cfg.xgb_param_grid: yield dict(p)
        elif name == "lgb":
            for p in cfg.lgb_param_grid: yield dict(p)
        else:
            raise ValueError(f"Unknown model name: {name}")

    # --- Main Walk-Forward Loop ---
    for window_index, (train_start, train_end, val_start, val_end) in enumerate(tqdm(windows, desc=f"{horizon_name}: windows", disable=not (cfg.verbose and cfg.show_progress)), start=1):
        # --- 0. Data Splitting & Purging ---
        # Apply horizon-aware purge and embargo to prevent data leakage
        train_cutoff = train_end - BDay(horizon_h)
        test_start_adj = val_start + BDay(cfg.embargo_days)
        test_cutoff = val_end - BDay(horizon_h)

        in_train = (dates_all >= train_start) & (dates_all <= train_cutoff)
        in_test = (dates_all >= test_start_adj) & (dates_all <= test_cutoff)

        if not in_train.any() or not in_test.any():
            logger.info(f"{horizon_name} W{window_index:02d} skipped (empty split after purge/embargo).")
            continue

        X_train, y_train = X_all[in_train], y_all[in_train]
        X_test, y_test = X_all[in_test], y_all[in_test]
        dates_train = dates_all[in_train]; dates_test = df_horizon.loc[in_test, "Date"].values
        tickers_test = df_horizon.loc[in_test, "ticker"].values
        fwd_train = df_horizon.loc[in_train, fwd_col].values; fwd_test = df_horizon.loc[in_test, fwd_col].values
        mom_train_sign = np.sign(df_horizon.loc[in_train, mom_col].values); mom_test_sign = np.sign(df_horizon.loc[in_test, mom_col].values)

        if len(np.unique(y_train)) < 2 or len(np.unique(y_test)) < 2:
            logger.info(f"{horizon_name} W{window_index:02d} skipped (train or test set needs both classes).")
            continue

        # --- 1. Hyperparameter Tuning (Inner CV) ---
        # This version uses a more robust, parallelized scoring method.
        # The simpler sequential search is kept as a fallback.
        best_params = None
        
        def evaluate_params(params):
            """Inner function to evaluate one set of params across CV folds."""
            aucs, pr_aucs, f1s = [], [], []
            for train_indices, val_indices in purged_inner_splits(dates_train, cfg.inner_cv_folds, purge_days=horizon_h):
                model = build_model(model_name, params, cfg)
                model.fit(X_train[train_indices], y_train[train_indices])
                probabilities = model.predict_proba(X_train[val_indices])[:, 1]
                y_validation  = y_train[val_indices]
                
                aucs.append(auc_safe(y_validation, probabilities))
                try:
                    pr_aucs.append(float(average_precision_score(y_validation, probabilities)))
                except Exception:
                    pr_aucs.append(0.0)
                
                # If coverage is used, also calculate F1 score on the covered set
                if cfg.min_coverage is not None:
                    threshold_cv, _ = choose_threshold_by_coverage(probabilities, cfg.threshold_grid, cfg.min_coverage)
                    is_high = probabilities >= threshold_cv; is_low = probabilities <= (1.0 - threshold_cv)
                    covered_mask = (is_high | is_low)
                    if covered_mask.any() and np.unique(y_validation[covered_mask]).size == 2:
                        y_pred_covered = np.full_like(probabilities, ABSTAIN, int)
                        y_pred_covered[is_high], y_pred_covered[is_low] = 1, 0
                        from sklearn.metrics import f1_score as _f1
                        f1s.append(float(_f1(y_validation[covered_mask], y_pred_covered[covered_mask], zero_division=0)))
            
            # Combine metrics into a single score
            if cfg.min_coverage is not None and f1s:
                score = np.nanmean(aucs)*0.5 + np.nanmean(f1s)*0.5
            else:
                score = np.nanmean(aucs)*0.3 + np.nanmean(pr_aucs)*0.7
            return score, params

        param_candidates = list(iter_param_grid(model_name))
        if param_candidates:
            # Run evaluation in parallel
            scored_params = Parallel(n_jobs=cfg.n_jobs, prefer="threads")(delayed(evaluate_params)(p) for p in param_candidates)
            try:
                # Find the params with the highest score
                best_score, best_params = max(scored_params, key=lambda t: (t[0], ))
            except Exception:
                pass # Fallback if scoring fails
        
        # Fallback to a default if parallel search failed
        if best_params is None:
            best_params = {"alpha":0.0, "C":1.0} if model_name=="logit" else (cfg.xgb_param_grid[0] if model_name=="xgb" else cfg.lgb_param_grid[0])

        # --- 2. Generate Out-of-Sample Predictions for Calibration ---
        # This creates unbiased predictions on the training set to train the calibrator.
        oos_probabilities = np.full(y_train.shape[0], np.nan, dtype=float)
        for train_indices, val_indices in purged_inner_splits(dates_train, cfg.inner_cv_folds, purge_days=horizon_h):
            model = build_model(model_name, best_params, cfg)
            model.fit(X_train[train_indices], y_train[train_indices])
            oos_probabilities[val_indices] = model.predict_proba(X_train[val_indices])[:, 1]

        # --- 3. Fit Probability Calibrator ---
        isotonic_calibrator = fit_isotonic_safe(oos_probabilities, y_train)

        # --- 4. Split Train Set for Magnitude Model ---
        # A separate train/calibration split is needed for the conformal prediction step.
        train_dates_series = pd.to_datetime(pd.Series(dates_train)); unique_train_dates = train_dates_series.drop_duplicates().sort_values()
        n_calib_dates = max(int(len(unique_train_dates) * cfg.calib_frac), 30)
        calib_cutoff_date = unique_train_dates.iloc[-n_calib_dates] if len(unique_train_dates) > n_calib_dates else unique_train_dates.iloc[-1]
        
        calib_mask = (train_dates_series >= calib_cutoff_date).to_numpy()
        model_mask = ~calib_mask

        X_train_model, y_train_model = X_train[model_mask], y_train[model_mask]
        X_train_calib, y_train_calib = X_train[calib_mask], y_train[calib_mask]
        fwd_train_calib = fwd_train[calib_mask]

        # --- 5. Fit Final Classifier and Predict on Test Set ---
        final_classifier = build_model(model_name, best_params, cfg)
        final_classifier.fit(X_train, y_train) # Fit on the full (outer) training set
        p_raw = final_classifier.predict_proba(X_test)[:, 1]
        p_calibrated = apply_calibrator(isotonic_calibrator, p_raw)

        # --- 6. Fit Magnitude Head Models ---
        # Two separate models: one for MR regime, one for MO regime.
        y_abs_model = np.abs(fwd_train[model_mask])
        mr_mask_model = y_train_model == 1; mo_mask_model = y_train_model == 0

        def fit_regressor_safe(X, y):
            """Safely fits a regressor, returning median as fallback."""
            if X.shape[0] < 50 or np.sum(np.isfinite(y)) < 30 or float(np.nanstd(y)) == 0.0:
                return None, float(np.nanmedian(y))
            regressor = make_hgbr(cfg); regressor.fit(X, y); return regressor, float(np.nanmedian(y))

        regressor_mr, median_fallback_mr = fit_regressor_safe(X_train_model[mr_mask_model], y_abs_model[mr_mask_model])
        regressor_mo, median_fallback_mo = fit_regressor_safe(X_train_model[mo_mask_model], y_abs_model[mo_mask_model])

        def predict_safe(model, X, fallback_value):
            """Safely predicts, returning fallback on failure."""
            if model is None:
                return np.full(X.shape[0], fallback_value if np.isfinite(fallback_value) else 0.0)
            try:
                return model.predict(X)
            except Exception:
                return np.full(X.shape[0], fallback_value if np.isfinite(fallback_value) else 0.0)

        pred_mr_abs = predict_safe(regressor_mr, X_test, median_fallback_mr)
        pred_mo_abs = predict_safe(regressor_mo, X_test, median_fallback_mo)

        # --- 7. Calculate Expected Move and Conformal Bands ---
        # Expected move is a probability-weighted mixture of the two regime predictions.
        exp_move = p_calibrated * (-mom_test_sign) * pred_mr_abs + (1.0-p_calibrated) * (mom_test_sign) * pred_mo_abs

        # Calculate residuals on the held-out calibration set for conformal intervals.
        residuals_mr = np.abs(
            np.abs(fwd_train_calib[y_train_calib==1]) -
            predict_safe(regressor_mr, X_train_calib[y_train_calib==1], median_fallback_mr)
        )
        residuals_mo = np.abs(
            np.abs(fwd_train_calib[y_train_calib==0]) -
            predict_safe(regressor_mo, X_train_calib[y_train_calib==0], median_fallback_mo)
        )
        # Get the quantile of residuals for the prediction interval.
        quantile_mr = conformal_q(residuals_mr, cfg.conformal_alpha)
        quantile_mo = conformal_q(residuals_mo, cfg.conformal_alpha)

        # Construct the prediction interval, also as a probability-weighted mixture.
        low_move  = p_calibrated * (-mom_test_sign) * (pred_mr_abs - quantile_mr) + (1.0-p_calibrated) * (mom_test_sign) * (pred_mo_abs - quantile_mo)
        high_move = p_calibrated * (-mom_test_sign) * (pred_mr_abs + quantile_mr) + (1.0-p_calibrated) * (mom_test_sign) * (pred_mo_abs + quantile_mo)

        # --- 8. Package Final Predictions for this Window ---
        mr_score = 1.0 - 2.0*p_calibrated  # [-1,1], negative means MR is likely
        action_confidence = np.maximum(p_calibrated, 1.0-p_calibrated)

        # Apply coverage-driven abstention if configured
        threshold_used = np.nan
        y_pred = np.full(p_calibrated.shape[0], ABSTAIN, dtype=int)
        abstained = np.ones(p_calibrated.shape[0], dtype=bool)
        is_high_prob = np.zeros_like(p_calibrated, dtype=bool)
        is_low_prob = np.zeros_like(p_calibrated, dtype=bool)
        
        if cfg.fixed_threshold is not None:
            threshold_used = float(cfg.fixed_threshold)
            is_high_prob = p_calibrated >= threshold_used
            is_low_prob = p_calibrated <= (1.0 - threshold_used)
        elif cfg.min_coverage is not None and cfg.threshold_rule == "coverage":
            threshold_used, _ = choose_threshold_by_coverage(p_calibrated, cfg.threshold_grid, cfg.min_coverage)
            is_high_prob = p_calibrated >= threshold_used
            is_low_prob = p_calibrated <= (1.0 - threshold_used)
        
        if is_high_prob.any() or is_low_prob.any():
            y_pred[is_high_prob] = 1  # Predict MR
            y_pred[is_low_prob] = 0  # Predict Momentum
            abstained = ~(is_high_prob | is_low_prob)

        window_preds = pd.DataFrame({
            "Date": dates_test,
            "ticker": tickers_test,
            "horizon": horizon_name,
            "y_true": y_test,
            "fwd_ret": fwd_test,
            "mom_sign": mom_test_sign,
            "y_prob_raw": p_raw,
            "y_prob_cal": p_calibrated,
            "mr_score": mr_score,
            "confidence": action_confidence,
            "exp_move": exp_move,
            "pi_low": low_move,
            "pi_high": high_move,
            "threshold": threshold_used,
            "y_pred": y_pred,
            "abstained": abstained,
        })
        all_window_predictions.append(window_preds)

    if not all_window_predictions:
        logger.warning(f"No predictions generated for horizon {horizon_name} (data/splits insufficient).")
        return pd.DataFrame(), pd.DataFrame()

    # --- 9. Aggregate Predictions and Calculate Final Metrics ---
    preds_all = pd.concat(all_window_predictions, ignore_index=True)

    metric_rows = []
    for ticker, group in preds_all.groupby("ticker", sort=False):
        y_true = group["y_true"].to_numpy()
        y_prob_cal = group["y_prob_cal"].to_numpy()
        auc_val = float(auc_safe(y_true, y_prob_cal)) if y_true.size > 0 else np.nan
        
        # Calculate metrics on the "covered" set if abstention is used
        if cfg.min_coverage is not None and "abstained" in group.columns:
            filtered_group = group[~group["abstained"]]
            y_true_covered = filtered_group["y_true"].to_numpy()
            y_pred_covered = filtered_group["y_pred"].to_numpy() if not filtered_group.empty else np.array([])
            coverage = 1.0 - float(group["abstained"].mean()) if not group.empty else np.nan
            
            if y_true_covered.size == 0 or np.unique(y_true_covered).size < 2:
                metric_rows.append(dict(ticker=ticker, support=int(y_true.size), covered=int(y_true_covered.size), coverage=coverage, accuracy=np.nan, precision=np.nan, recall=np.nan, f1=np.nan, auc=auc_val))
                continue
            metric_rows.append(dict(
                ticker=ticker, support=int(y_true.size), covered=int(y_true_covered.size), coverage=coverage,
                accuracy=float((y_true_covered == y_pred_covered).mean()),
                precision=float(precision_score(y_true_covered, y_pred_covered, zero_division=0)),
                recall=float(recall_score(y_true_covered, y_pred_covered, zero_division=0)),
                f1=float(f1_score(y_true_covered, y_pred_covered, zero_division=0)),
                auc=auc_val,
            ))
        else: # Calculate metrics on all predictions
            if y_true.size == 0 or np.unique(y_true).size < 2:
                metric_rows.append(dict(ticker=ticker, support=int(y_true.size), accuracy=np.nan, precision=np.nan, recall=np.nan, f1=np.nan, auc=auc_val))
                continue
            y_pred = (y_prob_cal >= 0.5).astype(int)
            metric_rows.append(dict(
                ticker=ticker, support=int(y_true.size),
                accuracy=float((y_true == y_pred).mean()),
                precision=float(precision_score(y_true, y_pred, zero_division=0)),
                recall=float(recall_score(y_true, y_pred, zero_division=0)),
                f1=float(f1_score(y_true, y_pred, zero_division=0)),
                auc=auc_val,
            ))
    metrics = pd.DataFrame(metric_rows).sort_values("ticker")

    return preds_all, metrics


# =============================================================================
# FILE I/O & AUTO-DISCOVERY
# =============================================================================
def autodiscover_excel_and_sheet(excel_arg: Optional[Union[str, Path]], sheet_arg: Optional[str], logger: Optional[logging.Logger] = None) -> Tuple[Path, str]:
    """Intelligently finds the correct Excel file and sheet to use."""
    def choose_sheet(excel_file: pd.ExcelFile, preferred_sheet: Optional[str]) -> str:
        sheet_names = list(excel_file.sheet_names)
        if preferred_sheet and preferred_sheet in sheet_names:
            return preferred_sheet
        if "Returns" in sheet_names:
            return "Returns"
        # Fallback to first sheet containing 'return' (case-insensitive)
        for name in sheet_names:
            if "return" in name.lower():
                return name
        return sheet_names[0] # Final fallback to the very first sheet

    # Case 1: User provided an explicit path
    if excel_arg:
        path = Path(excel_arg)
        if path.exists():
            try:
                excel_file = pd.ExcelFile(path)
                chosen_sheet = choose_sheet(excel_file, sheet_arg)
                if logger: logger.info(f"Using specified Excel: {path.name} | sheet: {chosen_sheet}")
                return path, chosen_sheet
            except Exception as e:
                if logger: logger.warning(f"Failed to open specified Excel file {path}: {e}")
        else:
            if logger: logger.warning(f"Specified Excel path not found: {path}. Will try auto-discovery.")

    # Case 2: Auto-discover in the current working directory
    search_patterns = ["MXUS_Data_*.xlsx", "MXUS_Data.xlsx", "*.xlsx"]
    candidate_paths: List[Path] = []
    for pattern in search_patterns:
        # Sort by modification time to get the most recent file first
        candidate_paths.extend(sorted(Path.cwd().glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True))
        if candidate_paths:
            break # Stop after the first successful pattern match
    
    for path in candidate_paths:
        try:
            excel_file = pd.ExcelFile(path)
            chosen_sheet = choose_sheet(excel_file, sheet_arg)
            if logger: logger.info(f"Auto-discovered Excel: {path.name} | sheet: {chosen_sheet}")
            return path, chosen_sheet
        except Exception:
            continue # Try the next candidate if this one fails

    raise FileNotFoundError("Could not find a suitable Excel file. Please specify with --excel or place one in the current directory (e.g., MXUS_Data.xlsx).")


# =============================================================================
# MAIN PIPELINE EXECUTION
# =============================================================================
def run_pipeline(cfg: Config, model_name: str) -> None:
    """Orchestrates the entire data loading, feature building, and modeling pipeline."""
    output_directory = Path(cfg.output_dir)
    logger = setup_logging(output_directory)

    # Ensure deterministic results
    np.random.seed(cfg.random_state)

    logger.info("--- Starting MR-PROD Pipeline ---")
    logger.info(f"Model: {model_name} | Output directory: {output_directory.resolve()}")

    logger.info("Step 1: Resolving input Excel file and sheet...")
    excel_path, sheet_name = autodiscover_excel_and_sheet(cfg.excel_path, cfg.sheet_name, logger)
    cfg.excel_path, cfg.sheet_name = excel_path, sheet_name

    logger.info("Step 2: Loading and validating returns data...")
    returns_wide = load_returns_wide(cfg.excel_path, cfg.sheet_name)
    quality_check_results = validate_returns_wide(returns_wide)
    if not quality_check_results.empty:
        quality_check_results.to_csv(output_directory / "data_qc_issues.csv", index=False)
    returns_wide = returns_wide.drop_duplicates("Date").sort_values("Date").reset_index(drop=True)

    # Step 3: Load optional market context features
    market_features = None
    if cfg.with_market:
        logger.info("Step 3: Loading market context...")
        market_df = load_market_from_excel(cfg.excel_path, sheet_name=cfg.market_sheet, logger=logger)
        if market_df is None:
            logger.info(f"No usable '{cfg.market_sheet}' sheet found. Fetching S&P 500 via {cfg.market_source}...")
            market_df = get_sp500_market(cfg.market_source, start=cfg.market_start, logger=logger)
        if market_df is not None and not market_df.empty:
            market_features = compute_market_features(market_df, cfg)
            logger.info(f"Market features ready: {list(market_features.columns.drop('Date'))}")
        else:
            logger.warning("Proceeding without market features (load/fetch failed).")

    logger.info("Step 4: Building feature panel and labels...")
    start_time = time.time()
    panel = build_feature_panel(returns_wide, cfg, logger)
    if market_features is not None:
        panel = panel.merge(market_features, on="Date", how="left")
        logger.info("Merged market features into panel.")
    logger.info(f"Feature panel built in {time.time()-start_time:.2f}s")

    # Save the list of features used in the model for reference
    final_feature_cols = [
        c for c in panel.columns
        if c not in ("Date","ticker","daily_vol") and not c.startswith("fwd_") and not c.startswith("mom_") and not c.startswith("label_")
    ]
    (output_directory / "feature_columns.txt").write_text("\n".join(final_feature_cols), encoding="utf-8")

    # Step 5: Run the walk-forward model for each horizon
    horizon_summary_rows = []
    for horizon_name, _, _ in cfg.horizons:
        logger.info(f"--- Running Horizon: {horizon_name} ---")
        predictions, metrics = run_one_horizon(panel, horizon_name, cfg, model_name, logger)
        if predictions.empty:
            logger.warning(f"No results for horizon {horizon_name}. Skipping output files.")
            continue
        
        preds_path = output_directory / f"predictions_{horizon_name}.csv"
        metrics_path = output_directory / f"metrics_{horizon_name}.csv"
        predictions.sort_values(["Date","ticker"]).to_csv(preds_path, index=False, float_format="%.6f")
        metrics.to_csv(metrics_path, index=False, float_format="%.4f")
        logger.info(f"Saved: {preds_path.name} ({len(predictions):,} rows), {metrics_path.name} ({len(metrics):,} rows)")
        
        # Collect summary stats for this horizon
        auc_overall = auc_safe(predictions["y_true"].to_numpy(), predictions["y_prob_cal"].to_numpy())
        if cfg.min_coverage is not None and "abstained" in predictions.columns:
            coverage = float((~predictions["abstained"]).mean())
        else:
            coverage = float(np.mean(np.isfinite(predictions["y_prob_cal"].to_numpy())))
        horizon_summary_rows.append(dict(horizon=horizon_name, rows=int(len(predictions)), auc=float(auc_overall), coverage=coverage))

    if horizon_summary_rows:
        pd.DataFrame(horizon_summary_rows).to_csv(output_directory / "summary.csv", index=False, float_format="%.4f")

    # Step 6: Save run metadata
    meta = {
        "run_timestamp_utc": datetime.utcnow().isoformat() + "Z",
        "input_excel_file": str(cfg.excel_path),
        "input_sheet_name": cfg.sheet_name,
        "model_used": model_name,
        "run_config": {k: (str(v) if isinstance(v, Path) else v) for k, v in cfg.__dict__.items()},
        "environment_versions": {
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "sklearn": __import__("sklearn").__version__,
        },
    }
    with open(output_directory / "run_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, default=str)
    logger.info("--- Pipeline Finished ---")
    logger.info("Outputs: predictions_*.csv, metrics_*.csv, summary.csv, run_meta.json")


# =============================================================================
# COMMAND-LINE INTERFACE & ENTRY POINT
# =============================================================================
def parse_args() -> argparse.Namespace:
    """Parses command-line arguments."""
    parser = argparse.ArgumentParser(description="MR-PROD: A production-style pipeline for mean-reversion modeling.")
    # I/O
    parser.add_argument("--excel", default=None, help="Path to Excel file (default: auto-discover MXUS_Data.xlsx or similar).")
    parser.add_argument("--sheet", default=None, help="Sheet name for returns (default: 'Returns' or auto-discover).")
    parser.add_argument("--out", default="results", help="Output directory (default: results).")
    # Model & Walk-Forward
    parser.add_argument("--model", default="logit", choices=["logit","xgb","lgb"], help="Classifier model to use (default: logit).")
    parser.add_argument("--train_years", type=int, default=3, help="Years of data for outer training window (default: 3).")
    parser.add_argument("--val_years", type=int, default=1, help="Years of data for outer validation/test window (default: 1).")
    parser.add_argument("--embargo", type=int, default=5, help="Embargo days between train and test sets (default: 5).")
    # Technical
    parser.add_argument("--random_state", type=int, default=42, help="Random seed for reproducibility (default: 42).")
    parser.add_argument("--n_jobs", type=int, default=-1, help="Parallel jobs for hyperparameter search (default: -1, use all cores).")
    parser.add_argument("--min_valid_frac", type=float, default=0.70, help="Min non-NaN fraction for a ticker to be included (default: 0.70).")
    # Market Features
    parser.add_argument("--no_market", dest="with_market", action="store_false", help="Disable fetching and merging market features.")
    parser.add_argument("--market_sheet", default="Market", help="Excel sheet for market data (default: Market).")
    parser.add_argument("--market_source", default="yahoo_price", choices=["yahoo_price","yahoo_tr","stooq","fred"], help="Fallback source for S&P 500 (default: yahoo_price).")
    parser.add_argument("--market_start", default="1990-01-01", help="Start date for fetching market series (default: 1990-01-01).")
    # Coverage / Thresholding
    parser.add_argument("--min_coverage", type=float, default=None, help="Minimum decision coverage (0-1). e.g., 0.4 means at least 40%% of predictions will be made (default: None, no abstention).")
    parser.add_argument("--fixed_threshold", type=float, default=None, help="Use a fixed confidence threshold (e.g., 0.75). Overrides coverage rule if set.")
    parser.add_argument("--threshold_rule", default="coverage", choices=["coverage","none"], help="Rule for thresholding when --min_coverage is set (default: coverage).")
    parser.set_defaults(with_market=True)
    return parser.parse_args()


def main():
    """Main entry point of the script."""
    args = parse_args()
    # Create Config object from command-line arguments
    config = Config(
        excel_path=args.excel,
        sheet_name=args.sheet,
        output_dir=args.out,
        with_market=args.with_market,
        market_sheet=args.market_sheet,
        market_source=args.market_source,
        market_start=args.market_start,
        train_years=args.train_years,
        validation_years=args.val_years,
        embargo_days=args.embargo,
        random_state=args.random_state,
        n_jobs=args.n_jobs,
        min_valid_frac=args.min_valid_frac,
        min_coverage=args.min_coverage,
        fixed_threshold=args.fixed_threshold,
        threshold_rule=args.threshold_rule,
    )
    run_pipeline(config, model_name=args.model)


if __name__ == "__main__":
    main()
