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
  python mr_prod_core.py \
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

from joblib import dump

from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, f1_score, precision_score, recall_score
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.isotonic import IsotonicRegression
from sklearn.ensemble import HistGradientBoostingRegressor

# Optional tqdm
try:
    from tqdm.auto import tqdm
except Exception:  # pragma: no cover
    def tqdm(iterable=None, **kwargs):
        return iterable

ABSTAIN = -1
THIS_DIR = Path(__file__).resolve().parent


# =========================
# Config
# =========================
@dataclass
class Config:
    # I/O
    excel_path: str | Path = "MXUS_Data.xlsx"
    sheet_name: str = "Returns"
    output_dir: str | Path = "results"

    # Labeling (vol-scaled gate)
    vol_window: int = 20
    vol_k: float = 0.5  # gate = vol_k * rolling_std * sqrt(h)

    # Walk-forward
    train_years: int = 3
    validation_years: int = 1
    trading_days_per_year: int = 252
    embargo_days: int = 5

    # Model grids (logit by default)
    alpha_grid: List[float] = field(default_factory=lambda: [0.0, 1.0])
    reg_strengths_C: List[float] = field(default_factory=lambda: [0.1, 1.0, 10.0])
    inner_cv_folds: int = 3

    # Optional tree grids
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

    # Trading-day horizons: (name, forward_h, momentum_lookback_k)
    horizons: List[Tuple[str, int, int]] = field(
        default_factory=lambda: [
            ("d1", 1, 1),
            ("d3", 3, 3),
            ("d7", 7, 7),
            ("d15", 15, 15),
            ("d30", 30, 30),
        ]
    )

    # Feature windows
    ar_windows: List[int] = field(default_factory=lambda: [10, 20, 60])
    sign_persist_windows: List[int] = field(default_factory=lambda: [20, 60])
    vol_feat_windows: List[int] = field(default_factory=lambda: [10, 20])
    z_score_windows: List[int] = field(default_factory=lambda: [20])

    winsor_abs_limit: float = 0.10
    random_state: int = 42

    # Calibration & magnitude
    calib_frac: float = 0.20  # held-out slice inside outer-train (by date)
    conformal_alpha: float = 0.10

    # Magnitude model (fast, stable defaults)
    hgb_max_depth: int = 3
    hgb_max_iter: int = 300
    hgb_lr: float = 0.05
    hgb_l2: float = 1.0

    # Verbosity
    verbose: bool = True
    show_progress: bool = True


# =========================
# Logging
# =========================

def setup_logging(out_dir: Path) -> logging.Logger:
    out_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("mr_prod")
    logger.setLevel(logging.INFO)
    # Clear old handlers
    for h in list(logger.handlers):
        logger.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    fh = logging.FileHandler(out_dir / "run.log", mode="w")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


# =========================
# Data utils
# =========================

def _parse_percentish(series: pd.Series) -> pd.Series:
    """Convert strings like '0.56%' or '0.56' to decimals; robust to mixed cells.
    Heuristic: if 90th abs-quantile suggests values are in [0, 100], divide by 100.
    """
    s = pd.to_numeric(series.astype(str).str.replace("%", "", regex=False).str.strip(), errors="coerce")
    abs_q90 = s.abs().quantile(0.90)
    abs_q95 = s.abs().quantile(0.95)
    abs_q99 = s.abs().quantile(0.99)
    if (0.20 < abs_q90 <= 100) or (abs_q95 > 1.0 and abs_q99 <= 100):
        s = s / 100.0
    return s


def load_returns_wide(excel_path: str | Path, sheet_name: str) -> pd.DataFrame:
    if not Path(excel_path).exists():
        raise FileNotFoundError(f"Excel file not found: {excel_path}")
    df = pd.read_excel(excel_path, sheet_name=sheet_name, engine="openpyxl")
    if df.shape[1] < 2:
        raise ValueError("Expected 'Date' + ≥1 ticker columns in the Returns sheet.")
    first_col = df.columns[0]
    df = df.rename(columns={first_col: "Date"})
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df[df["Date"].notna()].sort_values("Date").reset_index(drop=True)
    for col in [c for c in df.columns if c != "Date"]:
        df[col] = _parse_percentish(df[col])
    return df


def winsorize_simple_returns(series: pd.Series, limit_abs: float) -> pd.Series:
    return series.clip(lower=-limit_abs, upper=limit_abs)


def compound_forward_simple(simple_returns: pd.Series, horizon: int) -> pd.Series:
    cp = (1.0 + simple_returns).cumprod()
    out = cp.shift(-horizon) / cp - 1.0
    if horizon > 0:
        out.iloc[-horizon:] = np.nan
    return out


def compound_past_simple(simple_returns: pd.Series, window: int) -> pd.Series:
    past = (1.0 + simple_returns).rolling(window).apply(np.prod, raw=True) - 1.0
    return past.shift(1)


def rolling_autocorr(series: pd.Series, window: int, lag: int = 1) -> pd.Series:
    x_prev = series.shift(lag)
    corr = series.rolling(window).corr(x_prev)
    return corr.shift(1)


def rolling_sign_persistence(series: pd.Series, window: int) -> pd.Series:
    same_sign = (np.sign(series) * np.sign(series.shift(1))) > 0
    rate = same_sign.rolling(window).mean()
    return rate.shift(1)


# =========================
# Feature panel + labels (vol-scaled gate)
# =========================

def build_feature_panel(returns_wide: pd.DataFrame, cfg: Config, logger: logging.Logger) -> pd.DataFrame:
    tickers = [c for c in returns_wide.columns if c != "Date"]
    frames: List[pd.DataFrame] = []
    for ticker in tqdm(tickers, desc="Building features (tickers)", disable=not (cfg.verbose and cfg.show_progress)):
        r = returns_wide[ticker].astype(float)
        if r.notna().mean() < 0.7:  # drop sparse series
            continue
        r = winsorize_simple_returns(r, cfg.winsor_abs_limit)
        base = pd.DataFrame({"Date": returns_wide["Date"], "ticker": ticker})
        feats: Dict[str, pd.Series] = {}
        # AR(1)
        for w in cfg.ar_windows:
            feats[f"ar1_corr_{w}d"] = rolling_autocorr(r, window=w)
        # Sign persistence
        for w in cfg.sign_persist_windows:
            feats[f"sign_persist_{w}d"] = rolling_sign_persistence(r, window=w)
        # Momentum & short history returns
        feats["ret_1d"] = r.shift(1)
        feats["ret_5d"] = compound_past_simple(r, 5)
        feats["ret_20d"] = compound_past_simple(r, 20)
        # Volatility features
        for w in cfg.vol_feat_windows:
            feats[f"vol_{w}d"] = r.rolling(w).std().shift(1)
        # Price-index z-score vs rolling MA
        price_index = (1.0 + r.fillna(0)).cumprod()
        for w in cfg.z_score_windows:
            ma = price_index.rolling(w, min_periods=w).mean()
            sd = price_index.rolling(w, min_periods=w).std()
            feats[f"z_ma_{w}d"] = ((price_index - ma) / sd).shift(1)
        feats_df = pd.DataFrame(feats)
        # Forward returns for all horizons
        fwd = {f"fwd_{h}d": compound_forward_simple(r, h) for _, h, _ in cfg.horizons}
        fwd_df = pd.DataFrame(fwd)
        # Recent momentum windows (k per horizon)
        mom = {f"mom_{k}d": compound_past_simple(r, k) for _, _, k in cfg.horizons}
        mom_df = pd.DataFrame(mom)
        frames.append(pd.concat([base, feats_df, fwd_df, mom_df], axis=1))

    if not frames:
        raise RuntimeError("No usable tickers after cleaning.")

    panel = pd.concat(frames, ignore_index=True)

    # Cross-sectional ranks (for interpretability/features)
    for col in ["ret_1d", "ret_5d", "ret_20d"] + [f"z_ma_{w}d" for w in cfg.z_score_windows]:
        if col in panel.columns:
            panel[f"cs_rank_{col}"] = panel.groupby("Date")[col].rank(pct=True)

    # Pre-compute per-ticker daily vol (for gate)
    panel["daily_vol"] = panel.groupby("ticker")["ret_1d"].transform(lambda s: s.rolling(cfg.vol_window).std())

    # Vol-scaled label gate and labels
    for name, h, k in cfg.horizons:
        fwd_col = f"fwd_{h}d"
        mom_col = f"mom_{k}d"
        # Project daily vol to horizon and fill within ticker
        gate = cfg.vol_k * panel["daily_vol"] * np.sqrt(max(h, 1))
        gate = gate.groupby(panel["ticker"]).transform(lambda s: s.fillna(s.median()))
        sign_future = np.sign(panel[fwd_col])
        sign_recent = np.sign(panel[mom_col])
        mask_big = panel[fwd_col].abs() > gate
        label_mr = np.where(
            (mask_big) & (sign_recent != 0) & (sign_future == -sign_recent), 1,
            np.where((mask_big) & (sign_recent != 0), 0, np.nan),
        )
        panel[f"label_mr_{name}"] = label_mr

    # Final feature list: drop targets/labels/mom/fwd/meta
    feature_cols = [
        c for c in panel.columns
        if c not in ("Date", "ticker", "daily_vol")
        and not c.startswith("fwd_") and not c.startswith("mom_") and not c.startswith("label_")
    ]

    # Drop rows with NaN features (model inputs must be clean)
    panel = panel.dropna(subset=feature_cols).reset_index(drop=True)

    logger.info(
        f"Panel: {panel.shape[0]:,} rows × {panel.shape[1]} cols  "
        f"({panel['Date'].min().date()} → {panel['Date'].max().date()})"
    )
    return panel


# =========================
# Splits
# =========================

def walk_forward_windows(dates: pd.Series, train_years: int, val_years: int, tdy: int) -> List[Tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
    unique_dates = pd.to_datetime(pd.Series(dates.unique())).sort_values().to_numpy()
    n_train = int(train_years * tdy)
    n_val = int(val_years * tdy)
    starts = np.arange(0, len(unique_dates) - (n_train + n_val) + 1, n_val, dtype=int)
    windows: List[Tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]] = []
    for s in starts:
        tr = unique_dates[s : s + n_train]
        va = unique_dates[s + n_train : s + n_train + n_val]
        if tr.size == 0 or va.size == 0:
            continue
        windows.append((pd.Timestamp(tr[0]), pd.Timestamp(tr[-1]), pd.Timestamp(va[0]), pd.Timestamp(va[-1])))
    return windows


def purged_inner_splits(dates: np.ndarray, n_splits: int, purge_days: int):
    """TimeSeriesSplit with a *pre-validation purge* of `purge_days` on the train side."""
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
# Models & calibration
# =========================

def make_logit(alpha: float, C: float, cfg: Config) -> Pipeline:
    if alpha == 0.0:
        logit = LogisticRegression(penalty="l2", solver="lbfgs", C=C, class_weight="balanced", max_iter=10_000, random_state=cfg.random_state)
    elif alpha == 1.0:
        logit = LogisticRegression(penalty="l1", solver="saga", C=C, class_weight="balanced", max_iter=10_000, random_state=cfg.random_state)
    else:
        logit = LogisticRegression(penalty="elasticnet", solver="saga", l1_ratio=alpha, C=C, class_weight="balanced", max_iter=10_000, random_state=cfg.random_state)
    return Pipeline([("scale", StandardScaler()), ("logit", logit)])


def make_tree(model_name: str, params: Dict[str, Union[int, float]], cfg: Config):
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
    raise ValueError("Unknown tree model")


def build_model(name: str, params: Dict[str, Union[int, float]], cfg: Config):
    if name == "logit":
        return make_logit(params.get("alpha", 0.0), params.get("C", 1.0), cfg)
    if name in ("xgb", "lgb"):
        return make_tree(name, params, cfg)
    raise ValueError("Unknown model name")


def auc_safe(y_true: np.ndarray, y_prob: np.ndarray) -> float:
    y = np.asarray(y_true)
    p = np.asarray(y_prob, dtype=float)
    keep = np.isin(y, [0, 1]) & np.isfinite(p)
    y = y[keep]
    p = p[keep]
    if y.size == 0 or np.unique(y).size < 2 or np.allclose(np.nanstd(p), 0.0):
        return 0.5
    try:
        return float(roc_auc_score(y, p))
    except Exception:
        return 0.5


def fit_isotonic_safe(probs: np.ndarray, y_true: np.ndarray) -> Optional[IsotonicRegression]:
    p = np.asarray(probs, dtype=float)
    y = np.asarray(y_true)
    keep = np.isfinite(p) & np.isin(y, [0, 1])
    p = p[keep]
    y = y[keep]
    if p.size < 30 or np.unique(y).size < 2:
        return None
    try:
        iso = IsotonicRegression(out_of_bounds="clip").fit(p, y)
        return iso
    except Exception:
        return None


def apply_calibrator(iso: Optional[IsotonicRegression], probs: np.ndarray) -> np.ndarray:
    if iso is None:
        return np.asarray(probs, dtype=float)
    try:
        return iso.predict(np.asarray(probs, dtype=float))
    except Exception:
        return np.asarray(probs, dtype=float)


# =========================
# Magnitude head + conformal
# =========================

def make_hgbr(cfg: Config) -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(
        max_depth=cfg.hgb_max_depth,
        max_iter=cfg.hgb_max_iter,
        learning_rate=cfg.hgb_lr,
        l2_regularization=cfg.hgb_l2,
        random_state=cfg.random_state,
    )


def conformal_q(residuals: np.ndarray, alpha: float) -> float:
    res = np.asarray(residuals, dtype=float)
    res = res[np.isfinite(res)]
    n = res.size
    if n == 0:
        return 0.0
    k = int(np.ceil((n + 1) * (1 - alpha)))
    k = min(max(k, 1), n)
    return float(np.partition(res, k - 1)[k - 1])


# =========================
# Core run (one horizon)
# =========================

def run_one_horizon(panel: pd.DataFrame, horizon_name: str, cfg: Config, model_name: str, logger: logging.Logger) -> Tuple[pd.DataFrame, pd.DataFrame]:
    label_col = f"label_mr_{horizon_name}"
    feat_cols = [c for c in panel.columns if c not in ("Date","ticker","daily_vol") and not c.startswith("fwd_") and not c.startswith("mom_") and not c.startswith("label_")]

    df = panel.dropna(subset=[label_col]).copy()
    X_all = df[feat_cols].values
    y_all = df[label_col].astype(int).values
    dates_all = df["Date"].to_numpy()

    windows = walk_forward_windows(df["Date"], cfg.train_years, cfg.validation_years, cfg.trading_days_per_year)
    h_days, k_days = next((h, k) for n,h,k in cfg.horizons if n==horizon_name)
    fwd_col = f"fwd_{h_days}d"; mom_col = f"mom_{k_days}d"

    all_preds: List[pd.DataFrame] = []
    per_ticker_rows: List[Dict[str, Union[int,float,str,datetime]]] = []

    def iter_param_grid(name: str):
        if name == "logit":
            for a in cfg.alpha_grid:
                for C in cfg.reg_strengths_C:
                    yield {"alpha": a, "C": float(C)}
        elif name == "xgb":
            for p in cfg.xgb_param_grid:
                yield dict(p)
        elif name == "lgb":
            for p in cfg.lgb_param_grid:
                yield dict(p)
        else:
            raise ValueError("Unknown model name")

    for w_idx, (tr_start, tr_end, va_start, va_end) in enumerate(tqdm(windows, desc=f"{horizon_name}: windows", disable=not (cfg.verbose and cfg.show_progress)), start=1):
        # Horizon-aware purge & optional embargo
        train_cutoff = tr_end - BDay(h_days)
        test_start_adj = va_start + BDay(cfg.embargo_days)
        test_cutoff = va_end - BDay(h_days)

        in_tr = (dates_all >= tr_start) & (dates_all <= train_cutoff)
        in_te = (dates_all >= test_start_adj) & (dates_all <= test_cutoff)

        if not in_tr.any() or not in_te.any():
            logger.info(f"{horizon_name} W{w_idx:02d} skipped (empty split).")
            continue

        X_tr, y_tr = X_all[in_tr], y_all[in_tr]
        X_te, y_te = X_all[in_te], y_all[in_te]
        dates_tr = dates_all[in_tr]; dates_te = df.loc[in_te, "Date"].values
        tickers_te = df.loc[in_te, "ticker"].values
        fwd_tr = df.loc[in_tr, fwd_col].values; fwd_te = df.loc[in_te, fwd_col].values
        mom_tr = np.sign(df.loc[in_tr, mom_col].values); mom_te = np.sign(df.loc[in_te, mom_col].values)

        if len(np.unique(y_tr)) < 2 or len(np.unique(y_te)) < 2:
            logger.info(f"{horizon_name} W{w_idx:02d} skipped (need both classes).")
            continue

        # 1) Inner CV to pick params (AUC) using purged folds
        best_params = None; best_auc = -np.inf
        for params in iter_param_grid(model_name):
            y_prob_all = []; y_true_all = []
            for tr_i, va_i in purged_inner_splits(dates_tr, cfg.inner_cv_folds, purge_days=h_days):
                model = build_model(model_name, params, cfg)
                model.fit(X_tr[tr_i], y_tr[tr_i])
                y_prob_all.append(model.predict_proba(X_tr[va_i])[:,1])
                y_true_all.append(y_tr[va_i])
            if not y_true_all:
                continue
            y_prob_cv = np.concatenate(y_prob_all)
            y_true_cv = np.concatenate(y_true_all)
            if y_true_cv.size == 0 or np.unique(y_true_cv).size < 2:
                continue
            auc_cv = auc_safe(y_true_cv, y_prob_cv)
            if auc_cv > best_auc:
                best_auc = auc_cv; best_params = params
        if best_params is None:
            best_params = {"alpha":0.0, "C":1.0} if model_name=="logit" else (cfg.xgb_param_grid[0] if model_name=="xgb" else cfg.lgb_param_grid[0])

        # 2) Build OOS probabilities for OUTER-TRAIN using purged inner folds (no leakage)
        oos_prob = np.full(y_tr.shape[0], np.nan, dtype=float)
        for tr_i, va_i in purged_inner_splits(dates_tr, cfg.inner_cv_folds, purge_days=h_days):
            mdl = build_model(model_name, best_params, cfg)
            mdl.fit(X_tr[tr_i], y_tr[tr_i])
            oos_prob[va_i] = mdl.predict_proba(X_tr[va_i])[:, 1]

        # 3) Isotonic on OOS predictions
        iso = fit_isotonic_safe(oos_prob, y_tr)

        # 4) Temporal calibration split inside OUTER-TRAIN (for magnitude head + reporting)
        d_tr = pd.to_datetime(pd.Series(dates_tr)); uniq = d_tr.drop_duplicates().sort_values()
        n_cal = max(int(len(uniq) * cfg.calib_frac), 30)
        cutoff = uniq.iloc[-n_cal] if len(uniq) > n_cal else uniq.iloc[-1]
        calib_mask = (d_tr >= cutoff).to_numpy(); model_mask = ~calib_mask

        X_tr_model, y_tr_model = X_tr[model_mask], y_tr[model_mask]
        X_tr_calib, y_tr_calib = X_tr[calib_mask], y_tr[calib_mask]
        fwd_tr_calib = fwd_tr[calib_mask]

        # 5) Final classifier fit on FULL OUTER-TRAIN; calibrated probs on TEST
        clf_full = build_model(model_name, best_params, cfg)
        clf_full.fit(X_tr, y_tr)
        p_raw = clf_full.predict_proba(X_te)[:, 1]
        p = apply_calibrator(iso, p_raw)

        # 6) Magnitude head (two regressors on MODEL-SLICE)
        y_abs_model = np.abs(fwd_tr[model_mask])
        mr_mask_model = y_tr_model == 1; mo_mask_model = y_tr_model == 0

        def fit_reg(Xm, ym):
            if Xm.shape[0] < 50 or np.sum(np.isfinite(ym)) < 30 or float(np.nanstd(ym)) == 0.0:
                return None, float(np.nan)
            reg = make_hgbr(cfg); reg.fit(Xm, ym); return reg, float(np.nanmedian(ym))

        reg_mr, med_mr = fit_reg(X_tr_model[mr_mask_model], y_abs_model[mr_mask_model])
        reg_mo, med_mo = fit_reg(X_tr_model[mo_mask_model], y_abs_model[mo_mask_model])

        def predict_or_const(model, X, const):
            if model is None:
                return np.full(X.shape[0], const if np.isfinite(const) else 0.0)
            try:
                return model.predict(X)
            except Exception:
                return np.full(X.shape[0], const if np.isfinite(const) else 0.0)

        pred_mr_abs = predict_or_const(reg_mr, X_te, med_mr)
        pred_mo_abs = predict_or_const(reg_mo, X_te, med_mo)

        # Expected signed move = mixture of regime magnitudes with regime signs
        exp_move = p * (-np.sign(mom_te)) * pred_mr_abs + (1.0-p) * (np.sign(mom_te)) * pred_mo_abs

        # 7) Conformal bands from CALIB slice residuals (conservative)
        res_mr = np.abs(
            np.abs(fwd_tr_calib[y_tr_calib==1]) -
            predict_or_const(reg_mr, X_tr_calib[y_tr_calib==1], med_mr)
        )
        res_mo = np.abs(
            np.abs(fwd_tr_calib[y_tr_calib==0]) -
            predict_or_const(reg_mo, X_tr_calib[y_tr_calib==0], med_mo)
        )
        q_mr = conformal_q(res_mr, cfg.conformal_alpha)
        q_mo = conformal_q(res_mo, cfg.conformal_alpha)

        low_move  = p * (-np.sign(mom_te)) * (pred_mr_abs - q_mr) + (1.0-p) * ( np.sign(mom_te)) * (pred_mo_abs - q_mo)
        high_move = p * (-np.sign(mom_te)) * (pred_mr_abs + q_mr) + (1.0-p) * ( np.sign(mom_te)) * (pred_mo_abs + q_mo)

        # Package predictions for this window
        mr_score = 1.0 - 2.0*p  # [-1,1] (negative implies MR direction expected)
        action_conf = np.maximum(p, 1.0-p)

        preds = pd.DataFrame({
            "Date": dates_te,
            "ticker": tickers_te,
            "horizon": horizon_name,
            "y_true": y_te,
            "fwd_ret": fwd_te,
            "mom_sign": np.sign(mom_te),
            "y_prob": p_raw,
            "y_prob_cal": p,
            "mr_score": mr_score,
            "confidence": action_conf,
            "exp_move": exp_move,
            "pi_low": low_move,
            "pi_high": high_move,
        })
        all_preds.append(preds)

    if not all_preds:
        logger.warning(f"No predictions for horizon {horizon_name} (data/splits insufficient).")
        return pd.DataFrame(), pd.DataFrame()

    preds_all = pd.concat(all_preds, ignore_index=True)

    # Per-ticker metrics (simple classification at 0.5 for reporting)
    rows = []
    for tkr, g in preds_all.groupby("ticker", sort=False):
        yt = g["y_true"].to_numpy()
        pp = g["y_prob_cal"].to_numpy()
        if yt.size == 0 or np.unique(yt).size < 2:
            rows.append(dict(ticker=tkr, support=int(yt.size), accuracy=np.nan, precision=np.nan, recall=np.nan, f1=np.nan, auc=np.nan))
            continue
        yp = (pp >= 0.5).astype(int)
        rows.append(dict(
            ticker=tkr,
            support=int(yt.size),
            accuracy=float((yt == yp).mean()),
            precision=float(precision_score(yt, yp, zero_division=0)),
            recall=float(recall_score(yt, yp, zero_division=0)),
            f1=float(f1_score(yt, yp, zero_division=0)),
            auc=float(auc_safe(yt, pp)),
        ))
    metrics = pd.DataFrame(rows).sort_values("ticker")

    return preds_all, metrics


# =========================
# Pipeline
# =========================

def run_pipeline(cfg: Config, model_name: str) -> None:
    out_dir = Path(cfg.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    logger = setup_logging(out_dir)

    # Deterministic seeds
    np.random.seed(cfg.random_state)

    logger.info("Loading returns (wide)...")
    returns_wide = load_returns_wide(cfg.excel_path, cfg.sheet_name)

    logger.info("Building feature panel + labels...")
    t0 = time.time()
    panel = build_feature_panel(returns_wide, cfg, logger)
    logger.info(f"Feature panel built in {time.time()-t0:.2f}s")

    # Save feature column list for reference
    feat_cols = [
        c for c in panel.columns
        if c not in ("Date","ticker","daily_vol") and not c.startswith("fwd_") and not c.startswith("mom_") and not c.startswith("label_")
    ]
    (out_dir / "feature_columns.txt").write_text("\n".join(feat_cols), encoding="utf-8")

    # Run each horizon
    summary_rows = []
    for name, _, _ in cfg.horizons:
        logger.info(f"=== Horizon: {name} ===")
        preds, metrics = run_one_horizon(panel, name, cfg, model_name, logger)
        if preds.empty:
            logger.warning(f"No results for horizon {name} — skipping saves.")
            continue
        preds_path = out_dir / f"predictions_{name}.csv"
        metrics_path = out_dir / f"metrics_{name}.csv"
        preds.sort_values(["Date","ticker"]).to_csv(preds_path, index=False)
        metrics.to_csv(metrics_path, index=False)
        logger.info(f"Saved: {preds_path.name} ({len(preds):,} rows), {metrics_path.name} ({len(metrics):,} rows)")
        # Quick horizon summary
        auc_all = auc_safe(preds["y_true"].to_numpy(), preds["y_prob_cal"].to_numpy())
        coverage = float(np.mean(np.isfinite(preds["y_prob_cal"].to_numpy())))
        summary_rows.append(dict(horizon=name, rows=int(len(preds)), auc=float(auc_all), coverage=coverage))

    if summary_rows:
        pd.DataFrame(summary_rows).to_csv(out_dir / "summary.csv", index=False)

    # Run meta
    meta = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "excel": str(cfg.excel_path),
        "sheet": cfg.sheet_name,
        "model": model_name,
        "config": {k: (str(v) if isinstance(v, Path) else v) for k, v in cfg.__dict__.items()},
        "versions": {
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "sklearn": __import__("sklearn").__version__,
        },
    }
    with open(out_dir / "run_meta.json", "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2, default=str)
    logger.info("Done. Artifacts: predictions_*.csv, metrics_*.csv, summary.csv, run_meta.json")


# =========================
# Entry
# =========================

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Mean-Reversion production: per-stock probabilities & magnitudes (no GUI)")
    p.add_argument("--excel", dest="excel", required=True, help="Path to Excel file with a 'Returns' sheet (Date + tickers)")
    p.add_argument("--sheet", dest="sheet", default="Returns", help="Sheet name (default: Returns)")
    p.add_argument("--out", dest="out", default="results", help="Output directory (default: results)")
    p.add_argument("--model", dest="model", default="logit", choices=["logit","xgb","lgb"], help="Classifier (default: logit)")
    p.add_argument("--train_years", type=int, default=3, help="Outer train years (default: 3)")
    p.add_argument("--val_years", type=int, default=1, help="Outer validation years (default: 1)")
    p.add_argument("--embargo", type=int, default=5, help="Embargo days after validation start (default: 5)")
    p.add_argument("--random_state", type=int, default=42, help="Random seed (default: 42)")
    return p.parse_args()


def main():
    args = parse_args()
    cfg = Config(
        excel_path=args.excel,
        sheet_name=args.sheet,
        output_dir=args.out,
        train_years=args.train_years,
        validation_years=args.val_years,
        embargo_days=args.embargo,
        random_state=args.random_state,
    )
    run_pipeline(cfg, model_name=args.model)


if __name__ == "__main__":
    main()
