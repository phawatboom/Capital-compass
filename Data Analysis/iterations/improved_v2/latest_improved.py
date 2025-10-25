#!/usr/bin/env python3
"""
Mean-Reversion Likelihood Model — No-Leak CV + CS Ranks + Tree Models + Backtest
Production-grade with calibration, accuracy metrics, and rich outputs
-------------------------------------------------------------------------------

What’s new vs your last version:
• Isotonic probability calibration per outer window (confidence you can trust)
• MR score in [-1, 1] (autocorr-like): mr_score = 1 - 2 * p_mr_calibrated
• Overall accuracy (covered set) + per-ticker accuracy/precision/recall/F1/AUC
• Human-friendly trades CSV: columns are self-explanatory for non-quants
• Minor hygiene: clearer logging, safer splits, robust fallbacks

Run
  python latest_improved.py --excel "MXUS_Data.xlsx" --sheet "Returns" \
      --model logit --p_at_k 10 --cost_bps 10

Optional dependencies (for --model xgb / lgb):
  pip install xgboost lightgbm

Core requirements:
  pip install pandas numpy scikit-learn openpyxl matplotlib joblib
"""

from __future__ import annotations

import argparse
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Union

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pandas.tseries.offsets import BDay

from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    roc_auc_score,
    f1_score,
    precision_recall_fscore_support,
    balanced_accuracy_score,
    roc_curve,
    average_precision_score,
    brier_score_loss,
)
from sklearn.metrics import accuracy_score, precision_score, recall_score
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.isotonic import IsotonicRegression
from joblib import dump

# Progress bar (safe fallback if tqdm is unavailable)
try:
    from tqdm.auto import tqdm
except Exception:  # pragma: no cover
    def tqdm(iterable=None, **kwargs):
        return iterable

# =========================
# Configuration
# =========================

THIS_DIR = Path(__file__).resolve().parent
DEFAULT_EXCEL_CANDIDATES: List[str] = ["MXUS_Data.xlsx"]
ABSTAIN = -1  # label used for abstentions in mean-reversion classification


@dataclass
class MeanReversionConfig:
    # I/O
    excel_path: str | Path = field(default=str(THIS_DIR / "MXUS_Data.xlsx"))
    sheet_name: str = "Returns"
    output_dir: str | Path = "results"

    # Labeling
    abs_move_threshold: float = 0.005  # 0.5% min magnitude for a "real" move (consider vol-scaling later)

    # Walk-forward windowing
    train_years: int = 3
    validation_years: int = 1
    trading_days_per_year: int = 252
    embargo_days: int = 5  # additional gap between last train date used and first test date used

    # Logistic regularization search (used when --model=logit)
    alpha_grid: List[float] = field(default_factory=lambda: [0.0, 0.5, 1.0])  # 0=ridge, 1=lasso
    inner_cv_folds: int = 5
    reg_strengths_C: List[float] = field(default_factory=lambda: list(np.logspace(-4, 4, 30)))

    # XGB/LGB small grids (kept tiny for speed)
    xgb_param_grid: List[Dict[str, Union[int, float]]] = field(
        default_factory=lambda: [
            {"max_depth": 3, "n_estimators": 400, "learning_rate": 0.05},
            {"max_depth": 4, "n_estimators": 600, "learning_rate": 0.05},
        ]
    )
    lgb_param_grid: List[Dict[str, Union[int, float]]] = field(
        default_factory=lambda: [
            {"num_leaves": 31, "n_estimators": 400, "learning_rate": 0.05},
            {"num_leaves": 63, "n_estimators": 600, "learning_rate": 0.05},
        ]
    )

    # Threshold sweep (two-sided abstain uses τ > 0.5)
    threshold_grid: List[float] = field(
        default_factory=lambda: [round(x, 2) for x in np.arange(0.55, 0.86, 0.01)]
    )

    # Horizons: (horizon_name, forward_horizon_days, momentum_lookback_days)
    horizons: List[Tuple[str, int, int]] = field(
        default_factory=lambda: [
            ("d1", 1, 1),
            ("d3", 3, 3),
            ("w1", 7, 7),
            ("w2", 15, 15),
            ("m1", 30, 30),
        ]
    )

    # Feature windows
    ar_windows: List[int] = field(default_factory=lambda: [10, 20, 60])
    sign_persist_windows: List[int] = field(default_factory=lambda: [20, 60])
    vol_windows: List[int] = field(default_factory=lambda: [10, 20])
    z_score_windows: List[int] = field(default_factory=lambda: [20])

    # Returns hygiene
    winsor_abs_limit: float = 0.10  # clamp simple daily returns to ±10%

    # Randomness
    random_state: int = 42

    # Outputs
    save_predictions: bool = True
    create_plots: bool = True
    save_models: bool = True
    verbose: bool = True
    show_progress: bool = True


def _progress_disabled(cfg: MeanReversionConfig) -> bool:
    """Progress bars show only if both verbose and show_progress are True."""
    return not (getattr(cfg, "verbose", True) and getattr(cfg, "show_progress", True))

# =========================
# Data loading (handles percent strings)
# =========================

def _parse_percentish(series: pd.Series) -> pd.Series:
    """
    Coerce a column that may contain:
      • '0.56%' strings
      • numeric percents like 0.56 (meaning 0.56%) or 56 (meaning 56%)
      • decimal simple returns like 0.0056
    into decimal simple returns (e.g., 0.0056).
    """
    s = pd.to_numeric(series.astype(str).str.replace("%", "", regex=False).str.strip(),
                      errors="coerce")

    # Heuristic to decide if values are percent-style:
    # - If 90th pct abs value > 0.20 (20%) and <=100 → treat as percent → divide by 100.
    # - Or if many values >1 but not crazy (<=100), also divide by 100.
    abs_q90 = s.abs().quantile(0.90)
    abs_q95 = s.abs().quantile(0.95)
    abs_q99 = s.abs().quantile(0.99)
    if (0.20 < abs_q90 <= 100) or (abs_q95 > 1.0 and abs_q99 <= 100):
        s = s / 100.0
    return s


def load_returns_wide(excel_path: str | Path, sheet_name: str) -> pd.DataFrame:
    """
    Load a "Returns" sheet with the first column as Date and remaining as tickers.
    Cells can be percent-formatted strings (e.g., '0.56%').
    Returns a DataFrame with columns: Date, <ticker1>, <ticker2>, ...
    """
    df = pd.read_excel(excel_path, sheet_name=sheet_name, engine="openpyxl")

    # Normalize the date column name and values.
    first_col = df.columns[0]
    df = df.rename(columns={first_col: "Date"})
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df[df["Date"].notna()].sort_values("Date").reset_index(drop=True)

    # Convert every ticker column to decimal simple returns.
    ticker_columns = [c for c in df.columns if c != "Date"]
    for col in ticker_columns:
        df[col] = _parse_percentish(df[col])

    return df

# =========================
# Returns hygiene, features, labels
# =========================

def winsorize_simple_returns(series: pd.Series, limit_abs: float) -> pd.Series:
    """Clamp simple daily returns to ±limit_abs (e.g., ±10%)."""
    return series.clip(lower=-limit_abs, upper=limit_abs)


def compound_forward_simple(simple_returns: pd.Series, horizon: int) -> pd.Series:
    """Forward compounded simple return over the next `horizon` days."""
    cp = (1.0 + simple_returns).cumprod()
    out = cp.shift(-horizon) / cp - 1.0
    if horizon > 0:
        out.iloc[-horizon:] = np.nan
    return out


def compound_past_simple(simple_returns: pd.Series, window: int) -> pd.Series:
    """Past compounded simple return over the prior `window` days (ending t-1)."""
    past = (1.0 + simple_returns).rolling(window).apply(np.prod, raw=True) - 1.0
    return past.shift(1)


def rolling_autocorr(series: pd.Series, window: int, lag: int = 1) -> pd.Series:
    """Rolling correlation corr(r_t, r_{t-1}) over `window`, reported at t-1."""
    x_prev = series.shift(lag)
    corr = series.rolling(window).corr(x_prev)
    return corr.shift(1)


def rolling_sign_persistence(series: pd.Series, window: int) -> pd.Series:
    """Share of same-sign days over the last `window` (through t-1)."""
    same_sign = (np.sign(series) * np.sign(series.shift(1))) > 0
    rate = same_sign.rolling(window).mean()
    return rate.shift(1)


def build_feature_panel(returns_wide: pd.DataFrame, cfg: MeanReversionConfig) -> pd.DataFrame:
    """Generate per-ticker features, forward returns, recent momentum, and labels."""
    tickers = [c for c in returns_wide.columns if c != "Date"]
    frames: List[pd.DataFrame] = []

    for ticker in tqdm(tickers, desc="Building features (tickers)", disable=_progress_disabled(cfg)):
        returns_series = returns_wide[ticker].astype(float)

        # Drop very sparse tickers.
        if returns_series.notna().mean() < 0.7:
            continue

        # Winsorize for robustness.
        returns_series = winsorize_simple_returns(returns_series, cfg.winsor_abs_limit)

        base = pd.DataFrame({"Date": returns_wide["Date"], "ticker": ticker})
        features: Dict[str, pd.Series] = {}

        # Serial correlation features.
        for w in cfg.ar_windows:
            features[f"ar1_corr_{w}d"] = rolling_autocorr(returns_series, window=w)

        # Sign persistence.
        for w in cfg.sign_persist_windows:
            features[f"sign_persist_{w}d"] = rolling_sign_persistence(returns_series, window=w)

        # Momentum controls.
        features["ret_1d"] = returns_series.shift(1)
        features["ret_5d"] = compound_past_simple(returns_series, 5)
        features["ret_20d"] = compound_past_simple(returns_series, 20)

        # Volatility.
        for w in cfg.vol_windows:
            features[f"vol_{w}d"] = returns_series.rolling(w).std().shift(1)

        # Z-score vs MA of price index (scale-free).
        price_index = (1.0 + returns_series.fillna(0)).cumprod()
        for w in cfg.z_score_windows:
            ma = price_index.rolling(w, min_periods=w).mean()
            sd = price_index.rolling(w, min_periods=w).std()
            features[f"z_ma_{w}d"] = ((price_index - ma) / sd).shift(1)

        features_df = pd.DataFrame(features)

        # Forward returns for horizons.
        fwd = {f"fwd_{h}d": compound_forward_simple(returns_series, h) for _, h, _ in cfg.horizons}
        fwd_df = pd.DataFrame(fwd)

        # Recent momentum baselines for labels.
        mom = {f"mom_{k}d": compound_past_simple(returns_series, k) for _, _, k in cfg.horizons}
        mom_df = pd.DataFrame(mom)

        frames.append(pd.concat([base, features_df, fwd_df, mom_df], axis=1))

    if not frames:
        raise RuntimeError("No usable tickers (too sparse after cleaning).")

    panel = pd.concat(frames, ignore_index=True)

    # === Cross-sectional ranks (market context) ===
    cs_cols = ["ret_1d", "ret_5d", "ret_20d"] + [f"z_ma_{w}d" for w in cfg.z_score_windows]
    for col in cs_cols:
        if col in panel.columns:
            panel[f"cs_rank_{col}"] = panel.groupby("Date")[col].rank(pct=True)

    # Build labels per horizon: mean reversion = future move opposes recent momentum (with abs-move gate).
    for horizon_name, h_forward, k_mom in cfg.horizons:
        fwd_col = f"fwd_{h_forward}d"
        mom_col = f"mom_{k_mom}d"

        mask_big = panel[fwd_col].abs() > cfg.abs_move_threshold
        sign_future = np.sign(panel[fwd_col])
        sign_recent = np.sign(panel[mom_col])

        # Mean-reversion label: 1 if big move and opposite to recent momentum; 0 if big move but same direction; NaN otherwise.
        label_mr = np.where(
            (mask_big) & (sign_recent != 0) & (sign_future == -sign_recent),
            1,
            np.where((mask_big) & (sign_recent != 0), 0, np.nan),
        )
        panel[f"label_mr_{horizon_name}"] = label_mr

        # Optional up/down direction (not used by default here).
        updown = np.where(
            panel[fwd_col] > cfg.abs_move_threshold, 1,
            np.where(panel[fwd_col] < -cfg.abs_move_threshold, 0, np.nan),
        )
        panel[f"label_updown_{horizon_name}"] = updown

    # Keep rows with all features present; labels can still be NaN (filtered later).
    feature_cols = [
        c for c in panel.columns
        if c not in ("Date", "ticker")
        and not c.startswith("fwd_")
        and not c.startswith("mom_")
        and not c.startswith("label_")
    ]
    panel = panel.dropna(subset=feature_cols).reset_index(drop=True)
    return panel

# =========================
# Walk-forward windows (with horizon purge + embargo)
# =========================

def generate_walk_forward_windows(
    dates: pd.Series,
    train_years: int,
    val_years: int,
    td_per_year: int,
) -> List[Tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
    """
    Split unique dates into rolling (train, validation) windows by counts:
    - train: train_years * td_per_year days
    - validation: val_years * td_per_year days
    Step size: move forward by validation length each iteration.
    """
    unique_dates = pd.to_datetime(pd.Series(dates.unique())).sort_values().to_numpy()
    n_train = int(train_years * td_per_year)
    n_val = int(val_years * td_per_year)

    starts = np.arange(0, len(unique_dates) - (n_train + n_val) + 1, n_val, dtype=int)
    windows: List[Tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]] = []

    for s in starts:
        train_dates = unique_dates[s : s + n_train]
        val_dates = unique_dates[s + n_train : s + n_train + n_val]
        if train_dates.size == 0 or val_dates.size == 0:
            continue
        windows.append(
            (pd.Timestamp(train_dates[0]), pd.Timestamp(train_dates[-1]),
             pd.Timestamp(val_dates[0]), pd.Timestamp(val_dates[-1]))
        )
    return windows

# =========================
# Modeling helpers
# =========================

def make_logit_pipeline(alpha: float, C: float, cfg: MeanReversionConfig) -> Pipeline:
    """Standardized logistic regression pipeline with chosen penalty."""
    if alpha == 0.0:
        logit = LogisticRegression(
            penalty="l2", solver="lbfgs", C=C,
            class_weight="balanced", max_iter=10_000, random_state=cfg.random_state
        )
    elif alpha == 1.0:
        logit = LogisticRegression(
            penalty="l1", solver="saga", C=C,
            class_weight="balanced", max_iter=10_000, random_state=cfg.random_state
        )
    else:
        logit = LogisticRegression(
            penalty="elasticnet", solver="saga", l1_ratio=alpha, C=C,
            class_weight="balanced", max_iter=10_000, random_state=cfg.random_state
        )
    return Pipeline([("scale", StandardScaler()), ("logit", logit)])


def make_tree_model(model_name: str, params: Dict[str, Union[int, float]], cfg: MeanReversionConfig):
    """Build an XGBoost or LightGBM classifier from a minimal param dict."""
    if model_name == "xgb":
        try:
            import xgboost as xgb
        except Exception as e:
            raise SystemExit("XGBoost not available. Please `pip install xgboost`.") from e
        defaults = dict(
            objective="binary:logistic",
            eval_metric="logloss",
            n_jobs=-1,
            tree_method="hist",
            random_state=cfg.random_state,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_lambda=1.0,
        )
        defaults.update(params)
        return xgb.XGBClassifier(**defaults)

    if model_name == "lgb":
        try:
            import lightgbm as lgb
        except Exception as e:
            raise SystemExit("LightGBM not available. Please `pip install lightgbm`.") from e
        defaults = dict(
            objective="binary",
            n_jobs=-1,
            random_state=cfg.random_state,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_lambda=1.0,
            learning_rate=0.05,
        )
        defaults.update(params)
        return lgb.LGBMClassifier(**defaults)

    raise ValueError("Unknown tree model.")


def auc_safe(y_true: np.ndarray, y_prob: np.ndarray) -> float:
    """AUC that falls back to 0.5 when degenerate."""
    y = np.asarray(y_true)
    p = np.asarray(y_prob, dtype=float)
    keep = np.isin(y, [0, 1]) & np.isfinite(p)
    y = y[keep]
    p = p[keep]
    if y.size == 0 or np.unique(y).size < 2 or np.allclose(p.std(ddof=0), 0.0):
        return 0.5
    try:
        return float(roc_auc_score(y, p))
    except Exception:
        return 0.5


def choose_best_threshold(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    thresholds: List[float],
    use_abstain: bool,
) -> Tuple[float, Dict[str, float]]:
    """
    If abstain is enabled (mean-reversion), we classify 1 when p >= τ and 0 when p <= 1-τ.
    Otherwise, standard single-sided threshold p >= τ.
    Score = F1 × coverage for abstain; Score = F1 for non-abstain.
    """
    best_thr: Optional[float] = None
    best: Dict[str, float] = {"score": -np.inf}

    for thr in thresholds:
        if use_abstain and thr <= 0.5:
            continue

        if use_abstain:
            pred = np.full_like(y_true, ABSTAIN)
            hi = y_prob >= thr
            lo = y_prob <= (1.0 - thr)
            pred[hi] = 1
            pred[lo] = 0
            covered = (pred != ABSTAIN)
            if not np.any(covered):
                continue
            yt = y_true[covered]
            yp = pred[covered]
            f1 = f1_score(yt, yp, zero_division=0)
            bal = balanced_accuracy_score(yt, yp)
            prc, rec, _, _ = precision_recall_fscore_support(yt, yp, average="binary", zero_division=0)
            cov = float(np.mean(covered))
            score = f1 * cov
        else:
            pred = (y_prob >= thr).astype(int)
            f1 = f1_score(y_true, pred, zero_division=0)
            bal = balanced_accuracy_score(y_true, pred)
            prc, rec, _, _ = precision_recall_fscore_support(y_true, pred, average="binary", zero_division=0)
            cov = 1.0
            score = f1

        metrics = {"f1": f1, "bal_acc": bal, "precision": prc, "recall": rec, "coverage": cov, "score": score}
        if metrics["score"] > best["score"]:
            best_thr, best = thr, metrics

    if best_thr is None:
        # Reasonable fallback
        best_thr = 0.7 if use_abstain else 0.5
        best = {"f1": 0.0, "bal_acc": 0.5, "precision": 0.0, "recall": 0.0, "coverage": 0.0, "score": 0.0}
    return best_thr, best

# =========================
# Purged inner CV (no leakage during tuning)
# =========================

def purged_inner_splits(dates: np.ndarray, n_splits: int, purge_days: int):
    """
    Generate purged splits based on dates.
    Uses TimeSeriesSplit to propose folds, then trims the *train* side:
      - drop samples with dates in (val_start - purge_days, val_start]
      - ensure strictly before val_start
    Note: TimeSeriesSplit ensures train < val chronologically, so post-val embargo
    is not needed inside inner CV.
    """
    tscv = TimeSeriesSplit(n_splits=n_splits)
    dates = pd.to_datetime(dates)
    for tr_idx, val_idx in tscv.split(dates):
        if val_idx.size == 0 or tr_idx.size == 0:
            continue
        val_start = pd.Timestamp(dates[val_idx].min())
        purge_cut = val_start - BDay(purge_days)
        tr_dates = dates[tr_idx]
        keep = (tr_dates <= purge_cut) & (tr_dates < val_start)
        tr_idx_purged = tr_idx[keep]
        if tr_idx_purged.size == 0:
            continue
        yield tr_idx_purged, val_idx

# =========================
# Generic model selection (inner CV)
# =========================

def iter_param_grid(model_name: str, cfg: MeanReversionConfig):
    """Yield parameter dicts depending on model choice."""
    if model_name == "logit":
        for a in cfg.alpha_grid:
            for c in cfg.reg_strengths_C:
                yield {"alpha": a, "C": float(c)}
    elif model_name == "xgb":
        for p in cfg.xgb_param_grid:
            yield dict(p)  # copy
    elif model_name == "lgb":
        for p in cfg.lgb_param_grid:
            yield dict(p)
    else:
        raise ValueError("Unknown model name.")


def build_model(model_name: str, params: Dict[str, Union[int, float]], cfg: MeanReversionConfig):
    if model_name == "logit":
        return make_logit_pipeline(params["alpha"], params["C"], cfg)
    if model_name in ("xgb", "lgb"):
        return make_tree_model(model_name, params, cfg)
    raise ValueError("Unknown model name.")


def param_note(model_name: str, params: Dict[str, Union[int, float]]) -> str:
    if model_name == "logit":
        return f"alpha={params['alpha']}, C={params['C']}"
    return ", ".join(f"{k}={v}" for k, v in params.items())

# =========================
# Calibration helpers & per-ticker metrics
# =========================

def temporal_calibration_split(dates: np.ndarray, frac: float = 0.2, min_cal_days: int = 30):
    """
    Split a training block into (model_train_mask, calib_mask) by time:
    calib = last `frac` of unique dates (min `min_cal_days`). Returns boolean masks.
    """
    d = pd.to_datetime(pd.Series(dates)).reset_index(drop=True)
    uniq = d.drop_duplicates().sort_values()
    if len(uniq) < 5:
        # degenerate, fallback by index fraction
        n = len(d)
        cut = max(int(n * (1 - frac)), n - 200)
        model_mask = np.arange(n) < cut
        calib_mask = ~model_mask
        return model_mask, calib_mask

    n_cal = max(int(len(uniq) * frac), min_cal_days)
    cutoff_date = uniq.iloc[-n_cal]
    calib_mask = (d >= cutoff_date).to_numpy()
    model_mask = ~calib_mask
    # ensure at least one sample in each
    if calib_mask.sum() == 0 or model_mask.sum() == 0:
        n = len(d)
        cut = max(int(n * (1 - frac)), n - 200)
        model_mask = np.arange(n) < cut
        calib_mask = ~model_mask
    return model_mask, calib_mask


def fit_isotonic_safe(y_prob: np.ndarray, y_true: np.ndarray) -> Optional[IsotonicRegression]:
    """Fit isotonic calibrator on validation-like predictions. Returns None if not feasible."""
    y_true = np.asarray(y_true)
    y_prob = np.asarray(y_prob, dtype=float)
    keep = np.isfinite(y_prob) & np.isin(y_true, [0, 1])
    y_prob, y_true = y_prob[keep], y_true[keep]
    # Need both classes and some variation
    if y_true.size < 50 or np.unique(y_true).size < 2 or np.allclose(y_prob.std(ddof=0), 0):
        return None
    try:
        iso = IsotonicRegression(out_of_bounds="clip")
        iso.fit(y_prob, y_true)
        return iso
    except Exception:
        return None


def apply_calibrator(iso: Optional[IsotonicRegression], p: np.ndarray) -> np.ndarray:
    """Apply isotonic if available, else return original probs clipped to [0,1]."""
    p = np.asarray(p, dtype=float)
    if iso is None:
        return np.clip(p, 0.0, 1.0)
    try:
        return np.clip(iso.predict(p), 0.0, 1.0)
    except Exception:
        return np.clip(p, 0.0, 1.0)


def per_ticker_classification_metrics(active_df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute per-ticker accuracy, precision, recall, F1, AUC, support on the covered (non-abstained) set.
    """
    rows = []
    for tkr, g in active_df.groupby("ticker", sort=False):
        yt = g["y_true"].to_numpy()
        yp = g["y_pred"].to_numpy()
        pp = g["y_prob_cal"].to_numpy() if "y_prob_cal" in g else g["y_prob"].to_numpy()
        if yt.size == 0 or np.unique(yt).size < 2:
            rows.append(dict(
                ticker=tkr, support=int(yt.size), accuracy=float("nan"),
                precision=float("nan"), recall=float("nan"), f1=float("nan"),
                auc=float("nan")
            ))
            continue
        acc = float((yt == yp).mean())
        prc = float(precision_score(yt, yp, zero_division=0))
        rec = float(recall_score(yt, yp, zero_division=0))
        f1  = float(f1_score(yt, yp, zero_division=0))
        auc = float(auc_safe(yt, pp))
        rows.append(dict(ticker=tkr, support=int(yt.size), accuracy=acc,
                         precision=prc, recall=rec, f1=f1, auc=auc))
    return pd.DataFrame(rows).sort_values("ticker")

# =========================
# One horizon run
# =========================

@dataclass
class WindowResult:
    window_index: int
    horizon_name: str
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    val_start: pd.Timestamp
    val_end: pd.Timestamp
    model: str
    param_note: str
    alpha: float
    chosen_C: float
    chosen_threshold: float
    auc_val: float
    f1_val: float
    bal_acc_val: float
    precision_val: float
    recall_val: float
    accuracy_val: float
    n_train: int
    n_val: int
    coverage: float


def nested_cv_select_model_and_threshold(
    X_train: np.ndarray,
    y_train: np.ndarray,
    dates_train: np.ndarray,
    cfg: MeanReversionConfig,
    label_type: str,
    horizon_days: int,
    model_name: str,
) -> Tuple[Dict[str, Union[int, float]], float, float, Dict[str, float]]:
    """
    Inner time-series CV to pick (model params, tau) with purge to avoid label overlap leakage.
    Returns: best_params, best_tau, best_auc, best_metrics
    """
    use_abstain = (label_type == "mr")

    best_params: Optional[Dict[str, Union[int, float]]] = None
    best_tau = 0.7 if use_abstain else 0.5
    best_auc = -np.inf
    best_metrics: Dict[str, float] = {"score": -np.inf}

    for params in tqdm(list(iter_param_grid(model_name, cfg)),
                       desc=f"  innerCV: {model_name}", leave=False, disable=_progress_disabled(cfg)):
        y_prob_all: List[np.ndarray] = []
        y_true_all: List[np.ndarray] = []

        for inner_train_idx, inner_val_idx in purged_inner_splits(
            dates_train, cfg.inner_cv_folds, purge_days=horizon_days
        ):
            model = build_model(model_name, params, cfg)
            model.fit(X_train[inner_train_idx], y_train[inner_train_idx])

            y_prob_fold = model.predict_proba(X_train[inner_val_idx])[:, 1]
            y_prob_all.append(y_prob_fold)
            y_true_all.append(y_train[inner_val_idx])

        if not y_true_all:
            continue

        y_prob_concat = np.concatenate(y_prob_all)
        y_true_concat = np.concatenate(y_true_all)

        if y_true_concat.size == 0 or np.unique(y_true_concat).size < 2:
            continue

        auc_inner = auc_safe(y_true_concat, y_prob_concat)
        tau_candidate, inner_metrics = choose_best_threshold(
            y_true_concat, y_prob_concat, cfg.threshold_grid, use_abstain
        )

        is_better_auc = auc_inner > best_auc
        is_tie_better_score = math.isclose(auc_inner, best_auc) and inner_metrics["score"] > best_metrics["score"]

        if is_better_auc or is_tie_better_score:
            best_auc = auc_inner
            best_params = params
            best_tau = float(tau_candidate)
            best_metrics = inner_metrics

    if best_params is None:
        # sane fallback
        if model_name == "logit":
            best_params = {"alpha": 0.0, "C": 1.0}
        elif model_name == "xgb":
            best_params = {"max_depth": 3, "n_estimators": 400, "learning_rate": 0.05}
        else:
            best_params = {"num_leaves": 31, "n_estimators": 400, "learning_rate": 0.05}

    return best_params, best_tau, best_auc, best_metrics


def run_for_horizon(
    panel: pd.DataFrame,
    horizon_name: str,
    cfg: MeanReversionConfig,
    model_name: str,
    label_type: str = "mr",
) -> Tuple[pd.DataFrame, List[WindowResult]]:
    """
    Nested CV per outer window:
      • OUTER: walk-forward windows → unbiased outer test
      • INNER (TimeSeriesSplit + purge on outer-train): tune model params and tau
      • Refit on full outer-train with chosen params; evaluate once on outer test using chosen tau
      • Isotonic calibration on a temporal split of the outer-train block
    """
    label_col = f"label_{label_type}_{horizon_name}"
    feature_cols = [
        c for c in panel.columns
        if c not in ("Date", "ticker")
        and not c.startswith("fwd_")
        and not c.startswith("mom_")
        and not c.startswith("label_")
    ]

    df = panel.dropna(subset=[label_col]).copy()
    X_all = df[feature_cols].values
    y_all = df[label_col].astype(int).values
    dates_all = df["Date"].to_numpy()

    outer_windows = generate_walk_forward_windows(
        df["Date"], cfg.train_years, cfg.validation_years, cfg.trading_days_per_year
    )
    # Get horizon in days for this named horizon
    horizon_days = next(h for name, h, _ in cfg.horizons if name == horizon_name)
    fwd_col = f"fwd_{horizon_days}d"
    mom_col = f"mom_{horizon_days}d"

    results: List[WindowResult] = []
    all_val_preds: List[pd.DataFrame] = []

    for w_idx, (outer_train_start, outer_train_end, outer_test_start, outer_test_end) in enumerate(
        tqdm(outer_windows, desc=f"{horizon_name}: walk-forward windows", disable=_progress_disabled(cfg)),
        start=1
    ):
        # Purge + embargo relative to horizon
        train_cutoff = outer_train_end - BDay(horizon_days)
        test_start_adj = outer_test_start + BDay(cfg.embargo_days)
        test_cutoff = outer_test_end - BDay(horizon_days)

        in_outer_train = (dates_all >= outer_train_start) & (dates_all <= train_cutoff)
        in_outer_test  = (dates_all >= test_start_adj)   & (dates_all <= test_cutoff)

        X_tr, y_tr = X_all[in_outer_train], y_all[in_outer_train]
        X_te, y_te = X_all[in_outer_test],  y_all[in_outer_test]
        dates_tr = dates_all[in_outer_train]
        dates_te = df.loc[in_outer_test, "Date"].values
        tickers_te = df.loc[in_outer_test, "ticker"].values

        fwd_ret_te = df.loc[in_outer_test, fwd_col].values
        mom_sign_te = np.sign(df.loc[in_outer_test, mom_col].values)

        # Need both classes in outer train and test to compute metrics cleanly
        if len(np.unique(y_tr)) < 2 or len(np.unique(y_te)) < 2:
            if cfg.verbose:
                print(f"  W{w_idx:02d}: skipped (need both classes in outer train & test).")
            continue

        # === INNER CV: tune params + tau on outer-train only, with purge ===
        best_params, _best_tau_inner, _, _ = nested_cv_select_model_and_threshold(
            X_tr, y_tr, dates_tr, cfg, label_type, horizon_days, model_name
        )

        # === CALIBRATION SPLIT inside OUTER TRAIN ===
        model_mask, calib_mask = temporal_calibration_split(dates_tr, frac=0.2, min_cal_days=30)

        X_tr_model, y_tr_model = X_tr[model_mask], y_tr[model_mask]
        X_tr_calib, y_tr_calib = X_tr[calib_mask], y_tr[calib_mask]

        # 1) Fit model on model-slice
        final_model = build_model(model_name, best_params, cfg)
        final_model.fit(X_tr_model, y_tr_model)

        # 2) Calibrate on calib-slice
        y_prob_calib_raw = final_model.predict_proba(X_tr_calib)[:, 1]
        iso = fit_isotonic_safe(y_prob_calib_raw, y_tr_calib)
        y_prob_calib = apply_calibrator(iso, y_prob_calib_raw)

        # 3) Choose tau on calib set (no leakage to outer test)
        use_abstain = (label_type == "mr")
        tau_on_calib, _cal_metrics = choose_best_threshold(
            y_tr_calib, y_prob_calib, cfg.threshold_grid, use_abstain
        )

        # 4) Refit model on full outer-train for final scoring
        final_model = build_model(model_name, best_params, cfg)
        final_model.fit(X_tr, y_tr)

        # === OUTER TEST PREDICTIONS ===
        y_prob_raw = final_model.predict_proba(X_te)[:, 1]
        y_prob = apply_calibrator(iso, y_prob_raw)  # calibrated probability of MR

        # Probability → MR score (ACF-like) and confidence
        mr_score_raw = 1.0 - 2.0 * y_prob_raw
        mr_score_cal = 1.0 - 2.0 * y_prob
        confidence = np.abs(mr_score_cal)          # 0..1 distance from neutral
        entropy = -(y_prob * np.log(np.clip(y_prob,1e-12,1.0)) + (1-y_prob)*np.log(np.clip(1-y_prob,1e-12,1.0)))

        # Classification with abstain on calibrated probability
        if label_type == "mr":
            thr = float(tau_on_calib)
            y_pred = np.full_like(y_te, ABSTAIN)
            hi = y_prob >= thr
            lo = y_prob <= (1.0 - thr)
            y_pred[hi] = 1
            y_pred[lo] = 0
            covered_mask = (y_pred != ABSTAIN)

            if np.any(covered_mask):
                yt_cov = y_te[covered_mask]
                yp_cov = y_pred[covered_mask]
                pr_cov = y_prob[covered_mask]

                auc_outer = auc_safe(yt_cov, pr_cov)
                f1_outer = f1_score(yt_cov, yp_cov, zero_division=0)
                precision_outer, recall_outer, _, _ = precision_recall_fscore_support(
                    yt_cov, yp_cov, average="binary", zero_division=0
                )
                bal_outer = balanced_accuracy_score(yt_cov, yp_cov)
                coverage = float(np.mean(covered_mask))
                accuracy_outer = float((yt_cov == yp_cov).mean())
            else:
                auc_outer = 0.5
                f1_outer = 0.0
                precision_outer = 0.0
                recall_outer = 0.0
                bal_outer = 0.5
                coverage = 0.0
                accuracy_outer = float("nan")

            abstained = (y_pred == ABSTAIN)
        else:
            thr = 0.5
            y_pred = (y_prob >= thr).astype(int)
            abstained = np.zeros_like(y_pred, dtype=bool)
            auc_outer = auc_safe(y_te, y_prob)
            f1_outer = f1_score(y_te, y_pred, zero_division=0)
            precision_outer, recall_outer, _, _ = precision_recall_fscore_support(
                y_te, y_pred, average="binary", zero_division=0
            )
            bal_outer = balanced_accuracy_score(y_te, y_pred)
            coverage = 1.0
            accuracy_outer = float((y_te == y_pred).mean())

        # Collect predictions for this outer test slice (plus fwd return & momentum sign for backtest)
        all_val_preds.append(pd.DataFrame({
            "Date": dates_te,
            "ticker": tickers_te,
            "y_true": y_te,
            "y_prob_raw": y_prob_raw,          # uncalibrated
            "y_prob_cal": y_prob,              # calibrated probability of MR (confidence)
            "mr_score_raw": mr_score_raw,      # [-1,1], uncalibrated
            "mr_score": mr_score_cal,          # [-1,1], calibrated (recommended for client)
            "confidence": confidence,          # 0..1 (|mr_score|)
            "entropy": entropy,                # uncertainty measure
            "y_pred": y_pred,
            "abstained": abstained,
            "fwd_ret": fwd_ret_te,
            "mom_sign": mom_sign_te,
            "horizon_days": horizon_days,
            "window": w_idx,
            "threshold_tau": thr,
            "param_note": param_note(model_name, best_params),
        }))

        # Optionally save model (per window, per horizon)
        if cfg.save_models:
            out_dir = Path(cfg.output_dir); out_dir.mkdir(parents=True, exist_ok=True)
            model_path = out_dir / f"{label_type}_{horizon_name}_W{w_idx}_{model_name}_{param_note(model_name, best_params).replace(', ','_').replace('=','')}_tau{thr:.2f}.joblib"
            try:
                dump(final_model, model_path)
            except Exception:
                pass

        results.append(WindowResult(
            window_index=w_idx,
            horizon_name=horizon_name,
            train_start=outer_train_start, train_end=outer_train_end,
            val_start=outer_test_start,   val_end=outer_test_end,
            model=model_name,
            param_note=param_note(model_name, best_params),
            alpha=float(best_params["alpha"]) if model_name == "logit" else float("nan"),
            chosen_C=float(best_params["C"]) if model_name == "logit" else float("nan"),
            chosen_threshold=float(thr), auc_val=float(auc_outer),
            f1_val=float(f1_outer), bal_acc_val=float(bal_outer),
            precision_val=float(precision_outer), recall_val=float(recall_outer),
            accuracy_val=float(accuracy_outer),
            n_train=int(in_outer_train.sum()), n_val=int(in_outer_test.sum()),
            coverage=float(coverage),
        ))

    preds_df = pd.concat(all_val_preds, ignore_index=True) if all_val_preds else pd.DataFrame()
    return preds_df, results

# =========================
# Plots
# =========================

def plot_performance(
    preds_df: pd.DataFrame,
    results: List[WindowResult],
    horizon_name: str,
    label_type: str,
    cfg: MeanReversionConfig,
) -> None:
    if preds_df.empty:
        return

    out_dir = Path(cfg.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ROC on non-abstained, using calibrated probability when available
    if "abstained" in preds_df.columns:
        mask = ~preds_df["abstained"]
        y_true = preds_df.loc[mask, "y_true"]
        y_prob = preds_df.loc[mask, "y_prob_cal"] if "y_prob_cal" in preds_df.columns else preds_df.loc[mask, "y_prob"]
    else:
        y_true = preds_df["y_true"]
        y_prob = preds_df["y_prob_cal"] if "y_prob_cal" in preds_df.columns else preds_df["y_prob"]

    if len(y_true) > 0:
        fpr, tpr, _ = roc_curve(y_true, y_prob)
        auc = auc_safe(y_true.to_numpy(), y_prob.to_numpy())
        plt.figure(figsize=(9, 6))
        plt.plot(fpr, tpr, lw=2, label=f"AUC = {auc:.3f}")
        plt.plot([0, 1], [0, 1], "k--", lw=1)
        plt.xlabel("False Positive Rate")
        plt.ylabel("True Positive Rate")
        plt.title(f"ROC — {label_type.upper()} {horizon_name}")
        plt.legend(loc="lower right")
        plt.tight_layout()
        plt.savefig(out_dir / f"{label_type}_{horizon_name}_roc.png", dpi=300)
        plt.close()

    # By-window bars
    if results:
        r = pd.DataFrame([w.__dict__ for w in results])
        x = np.arange(len(r))
        plt.figure(figsize=(12, 6))
        width = 0.18
        plt.bar(x - 2*width, r["auc_val"], width, label="AUC")
        plt.bar(x - 1*width, r["f1_val"], width, label="F1")
        plt.bar(x + 0*width, r["precision_val"], width, label="Precision")
        plt.bar(x + 1*width, r["recall_val"], width, label="Recall")
        plt.bar(x + 2*width, r["accuracy_val"], width, label="Accuracy")
        plt.axhline(0.5, color="r", ls="--", alpha=0.25)
        plt.xticks(x, [f"W{i}" for i in r["window_index"]])
        plt.ylabel("Score")
        plt.title(f"Validation by Window — {label_type.upper()} {horizon_name}")
        plt.legend()
        plt.tight_layout()
        plt.savefig(out_dir / f"{label_type}_{horizon_name}_by_window.png", dpi=300)
        plt.close()

        # Params & coverage
        fig, ax = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
        ax[0].plot(x, r["chosen_threshold"], "o-", label="Threshold")
        ax[0].set_ylabel("Value")
        ax[0].set_title(f"Params — {label_type.upper()} {horizon_name} ({r['model'].iloc[0]})")
        ax[0].legend()
        ax[1].plot(x, r["coverage"], "o--", label="Coverage")
        ax[1].set_ylabel("Value")
        ax[1].set_xlabel("Window")
        ax[1].legend()
        plt.tight_layout()
        plt.savefig(out_dir / f"{label_type}_{horizon_name}_params_coverage.png", dpi=300)
        plt.close()

# =========================
# Extra selection metrics
# =========================

def precision_at_k_per_day(df: pd.DataFrame, k: int = 10) -> Tuple[float, int]:
    """
    Compute average Precision@K across days on the non-abstained set.
    Returns (average_precision_at_k, num_days_evaluated).
    """
    day_groups = df[~df["abstained"]].groupby("Date", sort=False)
    precisions: List[float] = []
    for _, g in day_groups:
        g_sorted = g.sort_values("y_prob_cal" if "y_prob_cal" in g else "y_prob", ascending=False).head(k)
        if g_sorted.empty:
            continue
        precisions.append(g_sorted["y_true"].mean())
    if not precisions:
        return 0.0, 0
    return float(np.mean(precisions)), len(precisions)

# =========================
# Simple per-trade backtest
# =========================

def compute_max_drawdown(equity_curve: pd.Series) -> float:
    roll_max = equity_curve.cummax()
    dd = 1.0 - (equity_curve / roll_max)
    return float(dd.max()) if len(dd) else 0.0


def backtest_from_preds(
    preds_df: pd.DataFrame, horizon_days: int, cost_bps: float
) -> Dict[str, float]:
    """
    Per-signal backtest (independent trades):
    - If predict MR (1): trade opposite recent momentum sign
    - If predict momentum (0): trade with recent momentum sign
    - PnL = position * fwd_return - cost
    Returns dict of summary metrics.
    """
    active = preds_df[~preds_df["abstained"]].copy()
    if active.empty:
        return {
            "n_trades": 0, "hit_rate": 0.0, "avg_ret": 0.0, "sharpe_ann": 0.0,
            "max_dd": 0.0, "profit_factor": 0.0
        }

    cost = float(cost_bps) / 1e4
    # position: +1 long, -1 short
    pos = np.where(active["y_pred"] == 1, -np.sign(active["mom_sign"]),
          np.where(active["y_pred"] == 0,  np.sign(active["mom_sign"]), 0.0))
    gross = pos * active["fwd_ret"]
    net = gross - cost * (pos != 0)

    # Metrics
    n_trades = int((pos != 0).sum())
    hit_rate = float((net > 0).mean()) if n_trades else 0.0
    avg_ret = float(net.mean()) if n_trades else 0.0
    std_ret = float(net.std(ddof=1)) if n_trades > 1 else 0.0
    ann_factor = np.sqrt(252.0 / max(horizon_days, 1))
    sharpe_ann = float((avg_ret / std_ret) * ann_factor) if std_ret > 0 else 0.0

    eq = (1.0 + net).cumprod()
    max_dd = compute_max_drawdown(eq)

    gains = net[net > 0].sum()
    losses = -net[net < 0].sum()
    profit_factor = float(gains / losses) if losses > 0 else (float("inf") if gains > 0 else 0.0)

    return {
        "n_trades": n_trades,
        "hit_rate": hit_rate,
        "avg_ret": avg_ret,
        "sharpe_ann": sharpe_ann,
        "max_dd": max_dd,
        "profit_factor": profit_factor,
    }

# =========================
# Main
# =========================

def _find_default_excel() -> Optional[Path]:
    for name in DEFAULT_EXCEL_CANDIDATES:
        p = Path(name)
        if p.exists():
            return p
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mean-Reversion Likelihood Model (no-leak CV, CS ranks, tree models, backtest)."
    )
    parser.add_argument("--excel", type=str, default="", help='Path to Excel file (default: try "MXUS_Data.xlsx").')
    parser.add_argument("--sheet", type=str, default="Returns", help='Worksheet name (default: "Returns").')
    parser.add_argument("--out", type=str, default="results", help='Output directory (default: "results").')
    parser.add_argument("--p_at_k", type=int, default=10, help="K for Precision@K/day (default: 10).")
    parser.add_argument(
        "--model", type=str, default="logit", choices=["logit", "xgb", "lgb"],
        help="Base learner (default: logit)."
    )
    parser.add_argument("--cost_bps", type=float, default=10.0,
                        help="Round-trip cost in bps per trade for backtest (default: 10 bps).")
    args = parser.parse_args()

    cfg = MeanReversionConfig(
        excel_path=args.excel or (str(_find_default_excel()) if _find_default_excel() else ""),
        sheet_name=args.sheet,
        output_dir=args.out,
    )

    if not cfg.excel_path:
        raise SystemExit('Excel file not specified and not found (tried "MXUS_Data.xlsx").')

    print("=== Mean-Reversion Likelihood Model — No-Leak CV + CS Ranks + Backtest (calibrated) ===")
    print(f"Reading: {cfg.excel_path} [sheet={cfg.sheet_name}]  |  Model={args.model}")

    # 1) Load returns (percent → decimal)
    returns_wide = load_returns_wide(cfg.excel_path, cfg.sheet_name)
    n_tickers = len(returns_wide.columns) - 1
    print(f"Loaded: {len(returns_wide):,} dates, {n_tickers} tickers")

    # 2) Build features + labels
    panel = build_feature_panel(returns_wide, cfg)
    print(
        f"Panel: {panel.shape[0]:,} rows × {panel.shape[1]} cols  "
        f"({panel['Date'].min().date()} → {panel['Date'].max().date()})"
    )

    out_dir = Path(cfg.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 3) Run per horizon (mean-reversion label only)
    for horizon_name, horizon_days, _ in tqdm(cfg.horizons, desc="Horizons", disable=_progress_disabled(cfg)):
        print(f"\n--- Horizon: {horizon_name} ({horizon_days}d) — mean-reversion ---")
        preds, results = run_for_horizon(panel, horizon_name, cfg, model_name=args.model, label_type="mr")

        if preds.empty:
            print("No validation predictions (possibly class imbalance or not enough dates).")
            continue

        # Use calibrated prob where available
        prob_col = "y_prob_cal" if "y_prob_cal" in preds.columns else "y_prob"
        active = preds[~preds["abstained"]]
        if not active.empty:
            auc = auc_safe(active["y_true"].to_numpy(), active[prob_col].to_numpy())
            try:
                pr_auc = average_precision_score(active["y_true"], active[prob_col])
            except Exception:
                pr_auc = float("nan")
            try:
                brier = brier_score_loss(active["y_true"], active[prob_col])
            except Exception:
                brier = float("nan")
            p_at_k, days_eval = precision_at_k_per_day(active, k=args.p_at_k)

            pred_bin = (active[prob_col] >= 0.5).astype(int)
            f1 = f1_score(active["y_true"], pred_bin, zero_division=0)
            prc, rec, _, _ = precision_recall_fscore_support(active["y_true"], pred_bin, average="binary", zero_division=0)
            coverage = 1 - preds["abstained"].mean()
            accuracy_overall = float((active["y_true"] == active["y_pred"]).mean())

            print(
                f"AUC={auc:.4f} | PR-AUC={pr_auc:.4f} | Brier={brier:.4f} | "
                f"F1@0.50={f1:.4f} | Precision={prc:.4f} | Recall={rec:.4f} | "
                f"Accuracy(covered)={accuracy_overall:.4f} | Coverage={coverage:.4f} | "
                f"P@{args.p_at_k}/day={p_at_k:.4f} ({days_eval} days)"
            )

        # Per-window summary
        print("Per-window choices:")
        for r in results:
            print(
                f" W{r.window_index:02d}  Train {r.train_start.date()}→{r.train_end.date()}  "
                f"Val {r.val_start.date()}→{r.val_end.date()} | "
                f"{r.model}: {r.param_note}  thr={r.chosen_threshold:.2f} | "
                f"AUC={r.auc_val:.4f}  F1={r.f1_val:.4f}  BalAcc={r.bal_acc_val:.4f}  "
                f"Precision={r.precision_val:.4f}  Recall={r.recall_val:.4f}  "
                f"Accuracy={r.accuracy_val:.4f}  cov={r.coverage:.4f}  "
                f"n_train={r.n_train:,}  n_val={r.n_val:,}"
            )

        # Save predictions with calibrated confidence and MR score
        if cfg.save_predictions:
            preds.to_csv(out_dir / f"mr_{horizon_name}_{args.model}_predictions.csv", index=False)

        # 4) Backtest (per-trade, independent signals)
        bt = backtest_from_preds(preds, horizon_days=horizon_days, cost_bps=args.cost_bps)
        print(
            f"Backtest: n={bt['n_trades']} | hit={bt['hit_rate']:.3f} | avg_ret={bt['avg_ret']:.4f} "
            f"| Sharpe_ann={bt['sharpe_ann']:.2f} | MaxDD={bt['max_dd']:.3f} | PF={bt['profit_factor']:.2f}"
        )

        # Detailed, human-friendly backtest/trades file
        trades = preds[~preds["abstained"]].copy()
        trades["position"] = np.where(trades["y_pred"] == 1, -np.sign(trades["mom_sign"]),
                               np.where(trades["y_pred"] == 0,  np.sign(trades["mom_sign"]), 0.0))
        trades["gross_ret"] = trades["position"] * trades["fwd_ret"]
        trades["cost"] = (args.cost_bps / 1e4) * (trades["position"] != 0)
        trades["net_ret"] = trades["gross_ret"] - trades["cost"]
        trades["correct"] = (trades["y_pred"] == trades["y_true"]).astype(int)  # row-level correctness

        # Helpful presentation columns (what a client needs to read the file)
        trades["horizon"] = f"{horizon_days}d"
        trades["mr_label_meaning"] = np.where(trades["y_pred"]==1, "Mean-Reversion",
                                       np.where(trades["y_pred"]==0, "Momentum/Continuation", "Abstain"))
        trades["explanation"] = (
            "mr_score ∈ [-1,1]: <0=Mean-Reversion, >0=Momentum; "
            "confidence=|mr_score|; "
            "position=−sign(momentum) if MR else +sign(momentum); "
            "net_ret = position*fwd_ret − cost"
        )

        # Keep a concise, documented column order for users
        nice_cols = [
            "Date","ticker","horizon","window",
            "y_true","y_pred","correct",
            "y_prob_cal","mr_score","confidence","threshold_tau",
            "y_prob_raw","mr_score_raw","entropy","param_note",
            "mom_sign","position","fwd_ret","gross_ret","cost","net_ret"
        ]
        for c in nice_cols:
            if c not in trades.columns:  # safety
                trades[c] = np.nan
        trades = trades[nice_cols].sort_values(["Date","ticker"])

        trades_path = out_dir / f"mr_{horizon_name}_{args.model}_trades.csv"
        trades.to_csv(trades_path, index=False)
        print(f"Saved detailed trades → {trades_path.name}")

        # Per-ticker metrics (accuracy etc.) on covered set
        if not trades.empty:
            tkr_metrics = per_ticker_classification_metrics(trades.rename(columns={"y_prob": "y_prob_cal"}))
            tkr_metrics_path = out_dir / f"mr_{horizon_name}_{args.model}_ticker_metrics.csv"
            tkr_metrics.to_csv(tkr_metrics_path, index=False)
            print(f"Saved per-ticker metrics → {tkr_metrics_path.name}")

        # Save by-window CSV (results)
        pd.DataFrame([w.__dict__ for w in results]).to_csv(out_dir / f"mr_{horizon_name}_{args.model}_results.csv", index=False)

        # Plots
        if cfg.create_plots:
            plot_performance(preds, results, horizon_name, "mr", cfg)

    print("\nDone.")


if __name__ == "__main__":
    # Make output deterministic-ish
    np.random.seed(42)
    main()
