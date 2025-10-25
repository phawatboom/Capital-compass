#!/usr/bin/env python3
"""
MR-PROD — Mean-Reversion Research → Production
==============================================

One-file, production-ready pipeline with a simple GUI "Run" button.

What you get
------------
• Leak-aware walk-forward evaluation with inner purged CV (horizon-aware)  
• Per-horizon calibrated MR probability, MR score in [-1,1], and confidence  
• Economic thresholding (τ) chosen to maximize expected net PnL on validation  
• Magnitude forecasting (|move| for MR & Momentum regimes) + conformal PI  
• Volatility-scaled label gate (per ticker & horizon)  
• Overall & per-ticker metrics, human-readable trades CSVs, saved model bundles  
• Optional daily portfolio backtest (top-N long/short, dollar-neutral)  
• **GUI**: Select Excel, horizon set, and click **Run Backtest** (Tkinter)  

Usage
-----
CLI (headless):
  python mr_prod.py --excel "MXUS_Data.xlsx" --sheet "Returns" --out results --model logit

GUI (one-click):
  python mr_prod.py --gui

Requirements
------------
  pip install pandas numpy scikit-learn openpyxl matplotlib joblib
Optional for tree models:  pip install xgboost lightgbm

Notes
-----
• Horizons use trading days: [1, 3, 5, 10, 20] ≈ 1d, 3d, 1w, 2w, 1m  
• We persist a bundle per window: {model, calibrator, tau, feature_cols, meta}
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import math
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Union

import numpy as np
import pandas as pd
from pandas.tseries.offsets import BDay

import matplotlib.pyplot as plt
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    roc_auc_score,
    f1_score,
    precision_recall_fscore_support,
    balanced_accuracy_score,
    roc_curve,
    average_precision_score,
    brier_score_loss,
    precision_score,
    recall_score,
)
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.isotonic import IsotonicRegression
from sklearn.ensemble import HistGradientBoostingRegressor
from joblib import dump

# Optional, safe tqdm fallback
try:
    from tqdm.auto import tqdm
except Exception:  # pragma: no cover
    def tqdm(iterable=None, **kwargs):
        return iterable

# =========================
# Config
# =========================

ABSTAIN = -1
THIS_DIR = Path(__file__).resolve().parent

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

    # Model grids
    alpha_grid: List[float] = field(default_factory=lambda: [0.0, 1.0])
    reg_strengths_C: List[float] = field(default_factory=lambda: [0.1, 1.0, 10.0])
    inner_cv_folds: int = 3

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

    # Economic threshold sweep for τ (two-sided)
    threshold_grid: List[float] = field(
        default_factory=lambda: [round(x, 2) for x in np.arange(0.55, 0.86, 0.01)]
    )

    # Trading-day horizons: (name, forward_h, mom_lookback_h)
    horizons: List[Tuple[str, int, int]] = field(
        default_factory=lambda: [
            ("d1", 1, 1),
            ("d3", 3, 3),
            ("w1", 5, 5),
            ("w2", 10, 10),
            ("m1", 20, 20),
        ]
    )

    # Features
    ar_windows: List[int] = field(default_factory=lambda: [10, 20, 60])
    sign_persist_windows: List[int] = field(default_factory=lambda: [20, 60])
    vol_feat_windows: List[int] = field(default_factory=lambda: [10, 20])
    z_score_windows: List[int] = field(default_factory=lambda: [20])

    winsor_abs_limit: float = 0.10

    random_state: int = 42

    # Outputs
    save_predictions: bool = True
    create_plots: bool = True
    save_models: bool = True
    verbose: bool = True
    show_progress: bool = True

    # Calibration & magnitude
    calib_frac: float = 0.20  # held-out slice inside outer-train
    conformal_alpha: float = 0.10

    # Magnitude model
    hgb_max_depth: int = 3
    hgb_max_iter: int = 300
    hgb_lr: float = 0.05
    hgb_l2: float = 1.0

    # Portfolio backtest
    do_portfolio: bool = True
    top_per_side: int = 10  # long + short picks per day


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
    s = pd.to_numeric(series.astype(str).str.replace("%", "", regex=False).str.strip(), errors="coerce")
    abs_q90 = s.abs().quantile(0.90)
    abs_q95 = s.abs().quantile(0.95)
    abs_q99 = s.abs().quantile(0.99)
    if (0.20 < abs_q90 <= 100) or (abs_q95 > 1.0 and abs_q99 <= 100):
        s = s / 100.0
    return s


def load_returns_wide(excel_path: str | Path, sheet_name: str) -> pd.DataFrame:
    df = pd.read_excel(excel_path, sheet_name=sheet_name, engine="openpyxl")
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
# Features + labels (vol-scaled gate)
# =========================

def build_feature_panel(returns_wide: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    tickers = [c for c in returns_wide.columns if c != "Date"]
    frames: List[pd.DataFrame] = []
    for ticker in tqdm(tickers, desc="Building features (tickers)", disable=not (cfg.verbose and cfg.show_progress)):
        r = returns_wide[ticker].astype(float)
        if r.notna().mean() < 0.7:
            continue
        r = winsorize_simple_returns(r, cfg.winsor_abs_limit)
        base = pd.DataFrame({"Date": returns_wide["Date"], "ticker": ticker})
        feats: Dict[str, pd.Series] = {}
        for w in cfg.ar_windows:
            feats[f"ar1_corr_{w}d"] = rolling_autocorr(r, window=w)
        for w in cfg.sign_persist_windows:
            feats[f"sign_persist_{w}d"] = rolling_sign_persistence(r, window=w)
        feats["ret_1d"] = r.shift(1)
        feats["ret_5d"] = compound_past_simple(r, 5)
        feats["ret_20d"] = compound_past_simple(r, 20)
        for w in cfg.vol_feat_windows:
            feats[f"vol_{w}d"] = r.rolling(w).std().shift(1)
        price_index = (1.0 + r.fillna(0)).cumprod()
        for w in cfg.z_score_windows:
            ma = price_index.rolling(w, min_periods=w).mean()
            sd = price_index.rolling(w, min_periods=w).std()
            feats[f"z_ma_{w}d"] = ((price_index - ma) / sd).shift(1)
        feats_df = pd.DataFrame(feats)
        fwd = {f"fwd_{h}d": compound_forward_simple(r, h) for _, h, _ in cfg.horizons}
        fwd_df = pd.DataFrame(fwd)
        mom = {f"mom_{k}d": compound_past_simple(r, k) for _, _, k in cfg.horizons}
        mom_df = pd.DataFrame(mom)
        frames.append(pd.concat([base, feats_df, fwd_df, mom_df], axis=1))
    if not frames:
        raise RuntimeError("No usable tickers after cleaning.")
    panel = pd.concat(frames, ignore_index=True)
    # Cross-sectional ranks
    for col in ["ret_1d", "ret_5d", "ret_20d"] + [f"z_ma_{w}d" for w in cfg.z_score_windows]:
        if col in panel.columns:
            panel[f"cs_rank_{col}"] = panel.groupby("Date")[col].rank(pct=True)
    # Vol-scaled label gate and labels
    for name, h, k in cfg.horizons:
        fwd_col = f"fwd_{h}d"
        mom_col = f"mom_{k}d"
        # Per-ticker rolling daily vol, projected to horizon
        daily_vol = panel.groupby("ticker")["ret_1d"].transform(lambda s: s.rolling(cfg.vol_window).std())
        gate = cfg.vol_k * daily_vol * np.sqrt(max(h, 1))
        gate = gate.fillna(gate.median())
        sign_future = np.sign(panel[fwd_col])
        sign_recent = np.sign(panel[mom_col])
        mask_big = panel[fwd_col].abs() > gate
        label_mr = np.where(
            (mask_big) & (sign_recent != 0) & (sign_future == -sign_recent), 1,
            np.where((mask_big) & (sign_recent != 0), 0, np.nan),
        )
        panel[f"label_mr_{name}"] = label_mr
    # Final feature list
    feature_cols = [
        c for c in panel.columns
        if c not in ("Date", "ticker") and not c.startswith("fwd_") and not c.startswith("mom_") and not c.startswith("label_")
    ]
    panel = panel.dropna(subset=feature_cols).reset_index(drop=True)
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
# Models
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
        defaults = dict(objective="binary", n_jobs=-1, random_state=cfg.random_state, subsample=0.8, colsample_bytree=0.8, reg_lambda=1.0, learning_rate=0.05)
        defaults.update(params)
        return lgb.LGBMClassifier(**defaults)
    raise ValueError("Unknown tree model")


def build_model(name: str, params: Dict[str, Union[int, float]], cfg: Config):
    if name == "logit":
        return make_logit(params.get("alpha", 0.0), params.get("C", 1.0), cfg)
    if name in ("xgb", "lgb"):
        return make_tree(name, params, cfg)
    raise ValueError("Unknown model name")


# =========================
# Metrics helpers
# =========================

def auc_safe(y_true: np.ndarray, y_prob: np.ndarray) -> float:
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


def choose_tau_by_econ(y_true: np.ndarray, p_mr: np.ndarray, fwd_ret: np.ndarray, mom_sign: np.ndarray, thresholds: List[float], cost_bps: float) -> Tuple[float, Dict[str, float]]:
    """Pick τ that maximizes expected net PnL on the validation slice.
       Decision: MR if p>=τ → position = -sign(mom); MO if p<=1-τ → position = +sign(mom); else abstain.
    """
    best_tau = 0.7
    best = {"exp_pnl": -1e9, "coverage": 0.0}
    cost = float(cost_bps) / 1e4
    y_true = np.asarray(y_true)
    p = np.asarray(p_mr, dtype=float)
    f = np.asarray(fwd_ret, dtype=float)
    m = np.asarray(mom_sign, dtype=float)
    for tau in thresholds:
        if tau <= 0.5:
            continue
        # decisions
        pred = np.full_like(p, ABSTAIN, dtype=int)
        hi = p >= tau
        lo = p <= (1.0 - tau)
        pred[hi] = 1
        pred[lo] = 0
        covered = pred != ABSTAIN
        if not np.any(covered):
            continue
        pos = np.zeros_like(f)
        pos[pred == 1] = -np.sign(m[ pred == 1])
        pos[pred == 0] =  np.sign(m[ pred == 0])
        gross = pos * f
        net = gross - cost * (pos != 0)
        exp_pnl = float(np.nanmean(net))
        cov = float(np.mean(covered))
        # tie-breaker by exp_pnl * cov (optional), otherwise exp_pnl
        score = exp_pnl
        if score > best["exp_pnl"]:
            best_tau = float(tau)
            best = {"exp_pnl": score, "coverage": cov}
    return best_tau, best


def precision_at_k_per_day(df: pd.DataFrame, k: int = 10) -> Tuple[float, int]:
    day_groups = df[~df["abstained"]].groupby("Date", sort=False)
    vals: List[float] = []
    for _, g in day_groups:
        prob_col = "y_prob_cal" if "y_prob_cal" in g else "y_prob"
        g_sorted = g.sort_values(prob_col, ascending=False).head(k)
        if g_sorted.empty:
            continue
        vals.append(g_sorted["y_true"].mean())
    if not vals:
        return 0.0, 0
    return float(np.mean(vals)), len(vals)


def per_ticker_metrics(active_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for tkr, g in active_df.groupby("ticker", sort=False):
        yt = g["y_true"].to_numpy()
        yp = g["y_pred"].to_numpy()
        pp = g.get("y_prob_cal", g["y_prob"]).to_numpy()
        if yt.size == 0 or np.unique(yt).size < 2:
            rows.append(dict(ticker=tkr, support=int(yt.size), accuracy=np.nan, precision=np.nan, recall=np.nan, f1=np.nan, auc=np.nan))
            continue
        rows.append(dict(
            ticker=tkr,
            support=int(yt.size),
            accuracy=float((yt == yp).mean()),
            precision=float(precision_score(yt, yp, zero_division=0)),
            recall=float(recall_score(yt, yp, zero_division=0)),
            f1=float(f1_score(yt, yp, zero_division=0)),
            auc=float(auc_safe(yt, pp)),
        ))
    return pd.DataFrame(rows).sort_values("ticker")


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

def run_one_horizon(panel: pd.DataFrame, horizon_name: str, cfg: Config, model_name: str, cost_bps: float, logger: logging.Logger) -> Tuple[pd.DataFrame, pd.DataFrame]:
    label_col = f"label_mr_{horizon_name}"
    feat_cols = [c for c in panel.columns if c not in ("Date","ticker") and not c.startswith("fwd_") and not c.startswith("mom_") and not c.startswith("label_")]

    df = panel.dropna(subset=[label_col]).copy()
    X_all = df[feat_cols].values
    y_all = df[label_col].astype(int).values
    dates_all = df["Date"].to_numpy()

    windows = walk_forward_windows(df["Date"], cfg.train_years, cfg.validation_years, cfg.trading_days_per_year)
    h_days = next(h for n,h,_ in cfg.horizons if n==horizon_name)
    fwd_col = f"fwd_{h_days}d"; mom_col = f"mom_{h_days}d"

    all_preds: List[pd.DataFrame] = []
    win_rows: List[Dict[str, Union[int,float,str,datetime]]] = []

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
        # Purge & embargo
        train_cutoff = tr_end - BDay(h_days)
        test_start_adj = va_start + BDay(cfg.embargo_days)
        test_cutoff = va_end - BDay(h_days)

        in_tr = (dates_all >= tr_start) & (dates_all <= train_cutoff)
        in_te = (dates_all >= test_start_adj) & (dates_all <= test_cutoff)

        X_tr, y_tr = X_all[in_tr], y_all[in_tr]
        X_te, y_te = X_all[in_te], y_all[in_te]
        dates_tr = dates_all[in_tr]; dates_te = df.loc[in_te, "Date"].values
        tickers_te = df.loc[in_te, "ticker"].values
        fwd_tr = df.loc[in_tr, fwd_col].values; fwd_te = df.loc[in_te, fwd_col].values
        mom_tr = np.sign(df.loc[in_tr, mom_col].values); mom_te = np.sign(df.loc[in_te, mom_col].values)

        if len(np.unique(y_tr)) < 2 or len(np.unique(y_te)) < 2:
            logger.info(f"W{w_idx:02d} skipped (need both classes).")
            continue

        # Inner CV to pick params (AUC) using purged folds
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

        # Temporal calibration split inside OUTER-TRAIN
        d_tr = pd.to_datetime(pd.Series(dates_tr))
        uniq = d_tr.drop_duplicates().sort_values()
        n_cal = max(int(len(uniq)*cfg.calib_frac), 30)
        cutoff = uniq.iloc[-n_cal]
        calib_mask = (d_tr >= cutoff).to_numpy(); model_mask = ~calib_mask
        X_tr_model, y_tr_model = X_tr[model_mask], y_tr[model_mask]
        X_tr_calib, y_tr_calib = X_tr[calib_mask], y_tr[calib_mask]
        fwd_tr_calib = fwd_tr[calib_mask]; mom_tr_calib = mom_tr[calib_mask]

        # 1) Fit classifier on model-slice
        clf = build_model(model_name, best_params, cfg)
        clf.fit(X_tr_model, y_tr_model)

        # 2) Refit classifier on FULL outer-train for final scoring
        clf_full = build_model(model_name, best_params, cfg)
        clf_full.fit(X_tr, y_tr)

        # 3) Calibrator REFIT using predictions from the FULL model on the held-out calib slice
        y_prob_calib_raw = clf_full.predict_proba(X_tr_calib)[:,1]
        iso = fit_isotonic_safe(y_prob_calib_raw, y_tr_calib)
        p_calib = apply_calibrator(iso, y_prob_calib_raw)

        # 4) Choose τ by ECONOMICS on calibration set
        tau, econ = choose_tau_by_econ(y_tr_calib, p_calib, fwd_tr_calib, mom_tr_calib, cfg.threshold_grid, cost_bps)

        # === Magnitude head (two regressors on model-slice) ===
        y_abs_model = np.abs(fwd_tr[model_mask])
        mr_mask_model = y_tr_model == 1; mo_mask_model = y_tr_model == 0
        def fit_reg(Xm, ym):
            if Xm.shape[0] < 50 or np.sum(np.isfinite(ym)) < 30 or np.nanstd(ym)==0:
                return None, float(np.nan)
            reg = make_hgbr(cfg); reg.fit(Xm, ym); return reg, float(np.nanmedian(ym))
        reg_mr, med_mr = fit_reg(X_tr_model[mr_mask_model], y_abs_model[mr_mask_model])
        reg_mo, med_mo = fit_reg(X_tr_model[mo_mask_model], y_abs_model[mo_mask_model])

        # === OUTER TEST ===
        p_raw = clf_full.predict_proba(X_te)[:,1]
        p = apply_calibrator(iso, p_raw)
        mr_score = 1.0 - 2.0*p
        confidence = np.abs(mr_score)
        action_conf = np.maximum(p, 1.0-p)

        def predict_or_const(model, X, const):
            if model is None:
                return np.full(X.shape[0], const if np.isfinite(const) else 0.0)
            try:
                return model.predict(X)
            except Exception:
                return np.full(X.shape[0], const if np.isfinite(const) else 0.0)
        pred_mr_abs = predict_or_const(reg_mr, X_te, med_mr)
        pred_mo_abs = predict_or_const(reg_mo, X_te, med_mo)
        exp_move = p * (-np.sign(mom_te)) * pred_mr_abs + (1.0-p) * (np.sign(mom_te)) * pred_mo_abs

        # simple conformal mix (conservative)
        # Calib residuals per regime using FULL model embeddings
        res_mr = np.abs(np.abs(fwd_tr_calib[y_tr_calib==1]) - predict_or_const(reg_mr, X_tr_calib[y_tr_calib==1], med_mr))
        res_mo = np.abs(np.abs(fwd_tr_calib[y_tr_calib==0]) - predict_or_const(reg_mo, X_tr_calib[y_tr_calib==0], med_mo))
        q_mr = conformal_q(res_mr, cfg.conformal_alpha)
        q_mo = conformal_q(res_mo, cfg.conformal_alpha)
        low_move = p * (-np.sign(mom_te)) * (pred_mr_abs - q_mr) + (1.0-p) * (np.sign(mom_te)) * (pred_mo_abs - q_mo)
        high_move = p * (-np.sign(mom_te)) * (pred_mr_abs + q_mr) + (1.0-p) * (np.sign(mom_te)) * (pred_mo_abs + q_mo)

        # threshold decisions (two-sided with abstain)
        thr = float(tau)
        y_pred = np.full_like(y_te, ABSTAIN)
        y_pred[p >= thr] = 1
        y_pred[p <= (1.0-thr)] = 0
        covered = y_pred != ABSTAIN

        if np.any(covered):
            yt, yp = y_te[covered], y_pred[covered]
            auc = auc_safe(yt, p[covered])
            f1 = f1_score(yt, yp, zero_division=0)
            prc, rec, _, _ = precision_recall_fscore_support(yt, yp, average="binary", zero_division=0)
            bal = balanced_accuracy_score(yt, yp)
            acc = float((yt==yp).mean())
            cov = float(np.mean(covered))
        else:
            auc=f1=prc=rec=bal=acc=cov=np.nan

        all_preds.append(pd.DataFrame({
            "Date": dates_te,
            "ticker": tickers_te,
            "y_true": y_te,
            "y_prob_cal": p,
            "mr_score": mr_score,
            "confidence": confidence,
            "action_confidence": action_conf,
            "y_pred": y_pred,
            "abstained": ~covered,
            "fwd_ret": fwd_te,
            "mom_sign": mom_te,
            "horizon_days": h_days,
            "window": w_idx,
            "threshold_tau": thr,
            # magnitude
            "exp_mr_abs": pred_mr_abs,
            "exp_mo_abs": pred_mo_abs,
            "exp_move": exp_move,
            "pi_low": low_move,
            "pi_high": high_move,
            "exp_mr_abs_bps": pred_mr_abs*1e4,
            "exp_mo_abs_bps": pred_mo_abs*1e4,
            "exp_move_bps": exp_move*1e4,
            "pi_low_bps": low_move*1e4,
            "pi_high_bps": high_move*1e4,
        }))

        # Save bundle
        if cfg.save_models:
            bundle = {
                "model": clf_full,
                "calibrator": iso,
                "tau": thr,
                "feature_cols": feat_cols,
                "horizon_days": h_days,
                "meta": {
                    "params": best_params,
                    "chosen_on": datetime.utcnow().isoformat()+"Z",
                    "econ_val_exp_pnl": econ.get("exp_pnl"),
                    "econ_val_coverage": econ.get("coverage"),
                },
            }
            dump(bundle, Path(cfg.output_dir) / f"mr_{horizon_name}_W{w_idx}_bundle.joblib")

        win_rows.append(dict(
            window=w_idx, horizon=horizon_name, train_start=tr_start, train_end=tr_end, val_start=va_start, val_end=va_end,
            auc=auc, f1=f1, precision=prc, recall=rec, bal_acc=bal, accuracy=acc, coverage=cov,
            tau=thr, params=json.dumps(best_params), exp_val_pnl=econ.get("exp_pnl"), exp_val_cov=econ.get("coverage")
        ))

    preds = pd.concat(all_preds, ignore_index=True) if all_preds else pd.DataFrame()
    results = pd.DataFrame(win_rows)
    return preds, results


# =========================
# Backtests
# =========================

def per_trade_backtest(preds: pd.DataFrame, h_days: int, cost_bps: float) -> Dict[str,float]:
    active = preds[~preds["abstained"]].copy()
    if active.empty:
        return {"n_trades":0, "hit_rate":0.0, "avg_ret":0.0, "sharpe_ann":0.0, "max_dd":0.0, "profit_factor":0.0}
    cost = float(cost_bps)/1e4
    pos = np.where(active["y_pred"]==1, -np.sign(active["mom_sign"]), np.where(active["y_pred"]==0, np.sign(active["mom_sign"]), 0.0))
    gross = pos * active["fwd_ret"]
    net = gross - cost*(pos!=0)
    n = int((pos!=0).sum()); hit=float((net>0).mean()) if n else 0.0
    avg=float(net.mean()) if n else 0.0; std=float(net.std(ddof=1)) if n>1 else 0.0
    ann_factor = np.sqrt(252.0/max(h_days,1)); sharpe=float((avg/std)*ann_factor) if std>0 else 0.0
    eq=(1.0+net).cumprod(); roll=eq.cummax(); dd=1.0 - (eq/roll); maxdd=float(dd.max()) if len(dd) else 0.0
    gains=net[net>0].sum(); losses=-net[net<0].sum(); pf=float(gains/losses) if losses>0 else (float("inf") if gains>0 else 0.0)
    return {"n_trades":n,"hit_rate":hit,"avg_ret":avg,"sharpe_ann":sharpe,"max_dd":maxdd,"profit_factor":pf}


def daily_portfolio_backtest(preds: pd.DataFrame, top_per_side:int, cost_bps: float) -> Dict[str,float]:
    if preds.empty:
        return {"days":0,"avg_daily":0.0,"sharpe_ann":0.0,"max_dd":0.0,"turnover":0.0}
    cost = float(cost_bps)/1e4
    df = preds.copy()
    df = df[~df["abstained"]]
    if df.empty:
        return {"days":0,"avg_daily":0.0,"sharpe_ann":0.0,"max_dd":0.0,"turnover":0.0}
    # score to rank by action confidence
    df["score"] = df["action_confidence"]
    rets=[]; turnovers=[]
    for dt, g in df.groupby("Date", sort=True):
        # desired positions: pick top per side by decision
        longs = g[g["y_pred"]==0].nlargest(top_per_side, "score")  # momentum → +sign(mom)
        shorts= g[g["y_pred"]==1].nlargest(top_per_side, "score")  # MR → -sign(mom)
        picks = pd.concat([longs, shorts])
        if picks.empty:
            rets.append(0.0); turnovers.append(0.0); continue
        # equal-weight dollar-neutral
        n_long = (picks["y_pred"]==0).sum(); n_short = (picks["y_pred"]==1).sum()
        w_long = 0.5/max(n_long,1); w_short = 0.5/max(n_short,1)
        pos = np.zeros(len(picks))
        pos[picks["y_pred"].values==0] =  w_long * np.sign(picks["mom_sign"])  # with momentum
        pos[picks["y_pred"].values==1] = -w_short * np.sign(picks["mom_sign"])  # against momentum
        gross = pos * picks["fwd_ret"].values
        cost_per_trade = cost  # per name; approximated
        net = gross - cost_per_trade * (pos!=0)
        rets.append(net.sum())
        turnovers.append(np.abs(pos).sum())
    if not rets:
        return {"days":0,"avg_daily":0.0,"sharpe_ann":0.0,"max_dd":0.0,"turnover":0.0}
    r = pd.Series(rets)
    avg=float(r.mean()); std=float(r.std(ddof=1)) if len(r)>1 else 0.0
    sharpe=float((avg/std)*np.sqrt(252)) if std>0 else 0.0
    eq=(1.0+r).cumprod(); dd=(1.0 - eq/eq.cummax()).max() if len(eq) else 0.0
    return {"days":len(r),"avg_daily":avg,"sharpe_ann":sharpe,"max_dd":float(dd),"turnover":float(np.mean(turnovers))}


# =========================
# Calibration helpers
# =========================

def fit_isotonic_safe(y_prob: np.ndarray, y_true: np.ndarray) -> Optional[IsotonicRegression]:
    y_true = np.asarray(y_true)
    y_prob = np.asarray(y_prob, dtype=float)
    keep = np.isfinite(y_prob) & np.isin(y_true, [0, 1])
    y_prob, y_true = y_prob[keep], y_true[keep]
    if y_true.size < 50 or np.unique(y_true).size < 2 or np.allclose(y_prob.std(ddof=0), 0):
        return None
    try:
        iso = IsotonicRegression(out_of_bounds="clip")
        iso.fit(y_prob, y_true)
        return iso
    except Exception:
        return None


def apply_calibrator(iso: Optional[IsotonicRegression], p: np.ndarray) -> np.ndarray:
    p = np.asarray(p, dtype=float)
    if iso is None:
        return np.clip(p, 0.0, 1.0)
    try:
        return np.clip(iso.predict(p), 0.0, 1.0)
    except Exception:
        return np.clip(p, 0.0, 1.0)


# =========================
# Orchestrator
# =========================

def run_pipeline(cfg: Config, model_name: str, p_at_k: int, cost_bps: float, logger: logging.Logger):
    logger.info("Starting MR-PROD run …")
    out_dir = Path(cfg.output_dir); out_dir.mkdir(parents=True, exist_ok=True)

    returns_wide = load_returns_wide(cfg.excel_path, cfg.sheet_name)
    logger.info(f"Loaded {len(returns_wide):,} dates, {len(returns_wide.columns)-1} tickers")

    panel = build_feature_panel(returns_wide, cfg)
    logger.info(f"Panel: {panel.shape[0]:,} rows × {panel.shape[1]} cols  ({panel['Date'].min().date()} → {panel['Date'].max().date()})")

    for name, h_days, _ in cfg.horizons:
        logger.info(f"--- Horizon: {name} ({h_days}d) — mean-reversion ---")
        preds, results = run_one_horizon(panel, name, cfg, model_name, cost_bps, logger)
        if preds.empty:
            logger.warning("No validation predictions for this horizon.")
            continue
        # Aggregate metrics (covered set)
        active = preds[~preds["abstained"]]
        prob_col = "y_prob_cal" if "y_prob_cal" in preds.columns else "y_prob"
        if not active.empty:
            auc = auc_safe(active["y_true"].to_numpy(), active[prob_col].to_numpy())
            pr_auc = average_precision_score(active["y_true"], active[prob_col]) if active["y_true"].nunique()>1 else np.nan
            brier = brier_score_loss(active["y_true"], active[prob_col]) if active["y_true"].nunique()>1 else np.nan
            pred_bin = (active[prob_col] >= 0.5).astype(int)
            f1 = f1_score(active["y_true"], pred_bin, zero_division=0)
            prc, rec, _, _ = precision_recall_fscore_support(active["y_true"], pred_bin, average="binary", zero_division=0)
            acc = float((active["y_true"] == active["y_pred"]).mean())
            coverage = 1 - preds["abstained"].mean()
            p_atk, days_eval = precision_at_k_per_day(active, k=p_at_k)
            logger.info(f"AUC={auc:.4f} | PR-AUC={pr_auc:.4f} | Brier={brier:.4f} | F1@0.50={f1:.4f} | Precision={prc:.4f} | Recall={rec:.4f} | Accuracy(covered)={acc:.4f} | Coverage={coverage:.4f} | P@{p_at_k}/day={p_atk:.4f} ({days_eval} days)")
        # Save predictions
        if cfg.save_predictions:
            preds.to_csv(out_dir / f"mr_{name}_{model_name}_predictions.csv", index=False)
            results.to_csv(out_dir / f"mr_{name}_{model_name}_results.csv", index=False)
        # Per-ticker metrics
        if not active.empty:
            tkr = per_ticker_metrics(active)
            tkr.to_csv(out_dir / f"mr_{name}_{model_name}_ticker_metrics.csv", index=False)
        # Backtests
        bt = per_trade_backtest(preds, h_days, cost_bps)
        logger.info(f"Per-trade: n={bt['n_trades']} | hit={bt['hit_rate']:.3f} | avg_ret={bt['avg_ret']:.4f} | Sharpe_ann={bt['sharpe_ann']:.2f} | MaxDD={bt['max_dd']:.3f} | PF={bt['profit_factor']:.2f}")
        if cfg.do_portfolio:
            port = daily_portfolio_backtest(preds, cfg.top_per_side, cost_bps)
            logger.info(f"Portfolio (top±{cfg.top_per_side}/day): days={port['days']} | avg_daily={port['avg_daily']:.5f} | Sharpe_ann={port['sharpe_ann']:.2f} | MaxDD={port['max_dd']:.3f} | Turnover={port['turnover']:.3f}")
        # Human-friendly trades CSV
        trades = preds[~preds["abstained"]].copy()
        trades["position"] = np.where(trades["y_pred"]==1, -np.sign(trades["mom_sign"]), np.where(trades["y_pred"]==0, np.sign(trades["mom_sign"]), 0.0))
        trades["gross_ret"] = trades["position"]*trades["fwd_ret"]
        trades["cost"] = (cost_bps/1e4) * (trades["position"]!=0)
        trades["net_ret"] = trades["gross_ret"] - trades["cost"]
        trades["correct"] = (trades["y_pred"] == trades["y_true"]).astype(int)
        trades["horizon"] = f"{h_days}d"
        trades["mr_label_meaning"] = np.where(trades["y_pred"]==1, "Mean-Reversion", np.where(trades["y_pred"]==0, "Momentum/Continuation", "Abstain"))
        trades["explanation"] = (
            "mr_score[-1,1]: <0=MR, >0=MO; confidence=|mr_score|; position=−sign(momentum) if MR else +sign(momentum); "
            "net_ret = position*fwd_ret − cost; exp_move_bps is an expectation; PI is conservative."
        )
        nice_cols = ["Date","ticker","horizon","window","y_true","y_pred","correct","y_prob_cal","action_confidence","mr_score","confidence","threshold_tau","mom_sign","position","fwd_ret","gross_ret","cost","net_ret","exp_mr_abs","exp_mo_abs","exp_move","pi_low","pi_high","exp_mr_abs_bps","exp_mo_abs_bps","exp_move_bps","pi_low_bps","pi_high_bps"]
        for c in nice_cols:
            if c not in trades.columns:
                trades[c] = np.nan
        trades = trades[nice_cols].sort_values(["Date","ticker"])    
        trades.to_csv(out_dir / f"mr_{name}_{model_name}_trades.csv", index=False)
        logger.info(f"Saved CSVs for {name} → predictions, results, ticker_metrics, trades")

    logger.info("Done.")


# =========================
# Minimal GUI (Tkinter)
# =========================

def launch_gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox

    root = tk.Tk()
    root.title("MR-PROD — Mean Reversion Backtest")
    root.geometry("720x540")

    state = {
        "excel": tk.StringVar(value=str((THIS_DIR/"MXUS_Data.xlsx").resolve())),
        "sheet": tk.StringVar(value="Returns"),
        "out": tk.StringVar(value=str((THIS_DIR/"results").resolve())),
        "model": tk.StringVar(value="logit"),
        "p_at_k": tk.IntVar(value=10),
        "cost": tk.DoubleVar(value=10.0),
    }

    def browse_excel():
        path = filedialog.askopenfilename(title="Select Excel (returns)", filetypes=[("Excel","*.xlsx"), ("All","*.*")])
        if path:
            state["excel"].set(path)

    def browse_out():
        path = filedialog.askdirectory(title="Select output folder")
        if path:
            state["out"].set(path)

    # Layout
    frm = tk.Frame(root); frm.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
    def row(lbl, widget):
        r = tk.Frame(frm); r.pack(fill=tk.X, pady=4)
        tk.Label(r, text=lbl, width=18, anchor="w").pack(side=tk.LEFT)
        widget.pack(side=tk.LEFT, fill=tk.X, expand=True)
        return r

    row("Excel file:", tk.Entry(frm, textvariable=state["excel"]))
    tk.Button(frm, text="Browse…", command=browse_excel).pack(anchor="e")
    row("Sheet name:", tk.Entry(frm, textvariable=state["sheet"]))
    row("Output dir:", tk.Entry(frm, textvariable=state["out"]))
    tk.Button(frm, text="Browse…", command=browse_out).pack(anchor="e")
    row("Model:", tk.OptionMenu(frm, state["model"], "logit", "xgb", "lgb"))
    row("Precision@K (per day):", tk.Entry(frm, textvariable=state["p_at_k"]))
    row("Cost (bps round-trip):", tk.Entry(frm, textvariable=state["cost"]))

    log_box = tk.Text(frm, height=16); log_box.pack(fill=tk.BOTH, expand=True, pady=8)
    log_box.insert(tk.END, "Ready. Configure and click Run Backtest.\n")

    def run_thread():
        try:
            cfg = Config(
                excel_path=state["excel"].get(),
                sheet_name=state["sheet"].get(),
                output_dir=state["out"].get(),
            )
            logger = setup_logging(Path(cfg.output_dir))
            # also stream log messages to the GUI
            class TextHandler(logging.Handler):
                def emit(self, record):
                    msg = self.format(record) + "\n"
                    log_box.insert(tk.END, msg)
                    log_box.see(tk.END)
            th = TextHandler(); th.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
            logger.addHandler(th)
            run_pipeline(cfg, state["model"].get(), state["p_at_k"].get(), state["cost"].get(), logger)
            messagebox.showinfo("MR-PROD", "Run completed. See results folder.")
        except Exception as e:
            messagebox.showerror("MR-PROD", f"Error: {e}")

    def on_run():
        threading.Thread(target=run_thread, daemon=True).start()

    tk.Button(frm, text="Run Backtest", command=on_run, bg="#2e7d32", fg="white", padx=12, pady=6).pack(anchor="e")

    root.mainloop()


# =========================
# CLI
# =========================

def parse_args():
    ap = argparse.ArgumentParser(description="MR-PROD: Mean-Reversion backtest (GUI or CLI).")
    ap.add_argument("--excel", type=str, default=str((THIS_DIR/"MXUS_Data.xlsx").resolve()))
    ap.add_argument("--sheet", type=str, default="Returns")
    ap.add_argument("--out", type=str, default=str((THIS_DIR/"results").resolve()))
    ap.add_argument("--model", type=str, default="logit", choices=["logit","xgb","lgb"])
    ap.add_argument("--p_at_k", type=int, default=10)
    ap.add_argument("--cost_bps", type=float, default=10.0)
    ap.add_argument("--gui", action="store_true", help="Launch GUI with a Run button")
    return ap.parse_args()


def main():
    args = parse_args()
    if args.gui:
        launch_gui(); return
    cfg = Config(excel_path=args.excel, sheet_name=args.sheet, output_dir=args.out)
    logger = setup_logging(Path(cfg.output_dir))
    np.random.seed(cfg.random_state)
    run_pipeline(cfg, args.model, args.p_at_k, args.cost_bps, logger)


if __name__ == "__main__":
    main()
