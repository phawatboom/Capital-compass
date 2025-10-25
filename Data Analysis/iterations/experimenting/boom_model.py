#!/usr/bin/env python3
"""
Mean-Reversion Likelihood via Serial Correlation — Multi-Horizon (1d/5d/20d)

What this does (aligned to client ask)
--------------------------------------
- Builds **serial-correlation features** (rolling AR(1) corr, sign-persistence) that capture
  whether returns tend to flip sign (mean-revert) or persist (trend).
- Trains **three separate classifiers** to estimate mean-reversion probability for:
  - **Tomorrow** (1 trading day)
  - **Next week** (~5 trading days)
  - **Next month** (~20 trading days)
- Label definition focuses on **reversion vs recent momentum**:
  label_h = 1  if  sign( future_return_over_h ) == - sign( recent_momentum_over_h )
           0  otherwise
  We also ignore tiny future moves: keep rows where |future_return_over_h| > 0.5% (tunable).

Why this maps to “serial correlation → mean-reversion”
------------------------------------------------------
- If **serial correlation** is negative, the chance that the next move flips sign rises →
  higher mean-reversion likelihood. Rolling AR(1) corr and sign-persistence directly encode this.
- We add a few simple controls (volatility, recent returns) but keep the model interpretable.

Outputs
-------
- CSVs with validation predictions & window summaries for each horizon:
    mr_tomorrow_val_predictions.csv, mr_next_week_val_predictions.csv, mr_next_month_val_predictions.csv
    mr_*_window_results.csv
- Console summary of scores and chosen hyperparameters per window.

Dependencies
------------
pip install pandas numpy scikit-learn openpyxl
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, f1_score, precision_recall_fscore_support, balanced_accuracy_score
from sklearn.model_selection import TimeSeriesSplit, GridSearchCV
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from pathlib import Path

# =========================
# Config
# =========================
THIS_DIR = Path(__file__).resolve().parent
EXCEL_PATH: str = str(THIS_DIR / "MXUS_Data.xlsx")  # <— use path next to this script
SHEET_NAME: str = "Returns"


# =========================
# Config
# =========================
# EXCEL_PATH: str        = "MXUS_Data.xlsx"
# SHEET_NAME: str        = "Returns"
LABEL_MOVE_THRESHOLD   = 0.005  # 0.5%
TRAIN_YEARS            = 3
VALIDATION_YEARS       = 1
INNER_NFOLDS_CV        = 5
ALPHA_GRID: List[float] = [0.0, 0.5, 1.0]
THRESHOLD_GRID: List[float] = list(np.round(np.arange(0.45, 0.551, 0.01), 2))
REG_STRENGTHS_C        = list(np.logspace(-2, 1, 7))  # 0.01 … 10
RANDOM_STATE           = 42

# Horizons and their matching "recent momentum" lookback (k)
HORIZONS = [
    ("tomorrow",   1,  1),
    ("next_week",  5,  5),
    ("next_month", 20, 20),
]

# Serial-corr feature windows
AR_WINDOWS = [10, 20, 60]
SIGN_PERSIST_WINDOWS = [20, 60]
VOL_WINDOWS = [10, 20]

@dataclass
class WindowResult:
    window_index: int
    horizon_name: str
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    val_start: pd.Timestamp
    val_end: pd.Timestamp
    alpha: float
    chosen_C: float
    chosen_threshold: float
    auc_val: float
    f1_val: float
    bal_acc_val: float
    n_train: int
    n_val: int

def read_returns_excel(file_path: str, sheet: str) -> pd.DataFrame:
    df = pd.read_excel(file_path, sheet_name=sheet, engine="openpyxl")
    if df.shape[1] < 2:
        raise ValueError("Expect at least 2 columns: Date + one stock.")
    date_col = df.columns[0]
    df = df.rename(columns={date_col: "date"})
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df

def compound_forward(series: pd.Series, horizon: int) -> pd.Series:
    cp = (1.0 + series).cumprod()
    fwd = cp.shift(-horizon) / cp - 1.0
    fwd.iloc[-horizon:] = np.nan
    return fwd

def compound_past(series: pd.Series, window: int) -> pd.Series:
    """Compound return over the **past** `window` days up to t-1."""
    past = (1.0 + series).rolling(window).apply(np.prod, raw=True) - 1.0
    return past.shift(1)  # ensure only info up to t-1

def rolling_ar1_corr(series: pd.Series, window: int) -> pd.Series:
    """Rolling correlation between r_t and r_{t-1} computed *ending at t-1* (shifted)."""
    # Create aligned pairs: x = r_{t-1}, y = r_t
    x = series.shift(1)
    y = series
    # Rolling corr over window ending at t (uses values up to t)
    corr = y.rolling(window).corr(x)
    # Shift by 1 so at time t we only use info through t-1
    return corr.shift(1)

def rolling_sign_persistence(series: pd.Series, window: int) -> pd.Series:
    """Share of times sign(r_t) == sign(r_{t-1}) over the past `window` days, using info up to t-1."""
    same_sign = np.sign(series) * np.sign(series.shift(1)) > 0
    rate = same_sign.rolling(window).mean()
    return rate.shift(1)

def build_panel(returns_wide: pd.DataFrame) -> pd.DataFrame:
    tickers = [c for c in returns_wide.columns if c != "date"]
    frames: List[pd.DataFrame] = []

    for ticker in tickers:
        r = returns_wide[ticker].astype(float)

        feats = {}

        # Serial-correlation features
        for w in AR_WINDOWS:
            feats[f"ar1_corr_{w}d"] = rolling_ar1_corr(r, w)

        for w in SIGN_PERSIST_WINDOWS:
            feats[f"sign_persist_{w}d"] = rolling_sign_persistence(r, w)

        # Volatility controls
        for w in VOL_WINDOWS:
            feats[f"vol_{w}d"] = r.rolling(w).std().shift(1)

        # Recent returns (direction/size controls)
        feats["ret_1d"] = r.shift(1)
        feats["ret_5d"] = compound_past(r, 5)
        feats["ret_20d"] = compound_past(r, 20)

        base = pd.DataFrame({"date": returns_wide["date"], "ticker": ticker})
        feat_df = pd.DataFrame(feats)

        # Forward returns for each horizon
        fwd = {f"fwd_{h}d": compound_forward(r, h) for _, h, _ in HORIZONS}
        fwd_df = pd.DataFrame(fwd)

        # Recent momentum for each horizon (k)
        mom = {f"mom_{k}d": compound_past(r, k) for _, _, k in HORIZONS}
        mom_df = pd.DataFrame(mom)

        frames.append(pd.concat([base, feat_df, fwd_df, mom_df], axis=1))

    panel = pd.concat(frames, ignore_index=True)

    # Build labels for each horizon: mean-reversion = future moves opposite to recent momentum
    for name, h, k in HORIZONS:
        fwd_col = f"fwd_{h}d"
        mom_col = f"mom_{k}d"
        # Only keep rows with a decisive future move (|fwd|>thr), and non-zero momentum sign
        mask = panel[fwd_col].abs() > LABEL_MOVE_THRESHOLD
        sign_future = np.sign(panel[fwd_col])
        sign_mom = np.sign(panel[mom_col])
        label = np.where((mask) & (sign_mom != 0) & (sign_future == -sign_mom), 1,
                         np.where((mask) & (sign_mom != 0), 0, np.nan))
        panel[f"label_{name}"] = label

    # Drop rows with missing features
    feature_cols = [c for c in panel.columns if c not in ("date", "ticker") and not c.startswith("fwd_") and not c.startswith("mom_") and not c.startswith("label_")]
    panel = panel.dropna(subset=feature_cols).reset_index(drop=True)
    return panel

def generate_rolling_windows(dates: pd.Series, train_years: int, val_years: int):
    unique_dates = pd.to_datetime(pd.Series(dates.unique())).sort_values().reset_index(drop=True)
    min_date = unique_dates.min()
    max_date = unique_dates.max()
    windows = []
    start = min_date
    while True:
        train_start = start
        train_end = train_start + pd.DateOffset(years=train_years)
        val_start = train_end + pd.DateOffset(days=1)
        val_end = train_end + pd.DateOffset(years=val_years)
        if val_end > max_date:
            break
        windows.append((train_start, train_end, val_start, val_end))
        start = val_start
    return windows

def fit_enet_logit_with_cv(X_tr, y_tr, alpha: float) -> GridSearchCV:
    pipe = Pipeline([
        ("scale", StandardScaler()),
        ("logit", LogisticRegression(
            penalty="elasticnet",
            solver="saga",
            l1_ratio=alpha,
            max_iter=5000,
            n_jobs=-1,
            class_weight="balanced",
            random_state=RANDOM_STATE,
        ))
    ])
    param_grid = {"logit__C": REG_STRENGTHS_C}
    tscv = TimeSeriesSplit(n_splits=INNER_NFOLDS_CV)
    gs = GridSearchCV(pipe, param_grid=param_grid, scoring="roc_auc", cv=tscv, n_jobs=-1, refit=True, verbose=0)
    gs.fit(X_tr, y_tr)
    return gs

def choose_threshold(y_true: np.ndarray, y_prob: np.ndarray, thresholds: List[float]):
    best_thr, best = thresholds[0], {"f1": -np.inf, "bal_acc": np.nan}
    for thr in thresholds:
        y_pred = (y_prob >= thr).astype(int)
        f1 = f1_score(y_true, y_pred, zero_division=0)
        bal = balanced_accuracy_score(y_true, y_pred)
        if f1 > best["f1"]:
            best_thr, best = thr, {"f1": f1, "bal_acc": bal}
    return best_thr, best

def run_for_horizon(panel: pd.DataFrame, horizon_name: str):
    label_col = f"label_{horizon_name}"
    # Features are the same across horizons
    feature_cols = [c for c in panel.columns if c not in ("date","ticker") and not c.startswith("fwd_") and not c.startswith("mom_") and not c.startswith("label_")]
    df = panel.dropna(subset=[label_col]).copy()
    X_all = df[feature_cols].values
    y_all = df[label_col].astype(int).values
    dates_all = df["date"]

    windows = generate_rolling_windows(dates_all, TRAIN_YEARS, VALIDATION_YEARS)

    results: List[WindowResult] = []
    all_val_preds = []

    for w_idx, (tr_start, tr_end, va_start, va_end) in enumerate(windows, start=1):
        in_tr = (dates_all >= tr_start) & (dates_all <= tr_end)
        in_va = (dates_all >= va_start) & (dates_all <= va_end)
        X_tr, y_tr = X_all[in_tr], y_all[in_tr]
        X_va, y_va = X_all[in_va], y_all[in_va]

        if len(np.unique(y_tr)) < 2 or len(np.unique(y_va)) < 2:
            continue

        best_auc = -np.inf
        best_alpha = None
        best_model = None
        best_C = None
        best_thr = None
        best_f1 = -np.inf
        best_bal = None

        for alpha in ALPHA_GRID:
            gs = fit_enet_logit_with_cv(X_tr, y_tr, alpha=alpha)
            model = gs.best_estimator_
            y_prob = model.predict_proba(X_va)[:, 1]
            auc = roc_auc_score(y_va, y_prob)
            thr, stats = choose_threshold(y_va, y_prob, THRESHOLD_GRID)
            if auc > best_auc or (math.isclose(auc, best_auc) and stats["f1"] > best_f1):
                best_auc = auc
                best_alpha = alpha
                best_model = model
                best_C = float(gs.best_params_["logit__C"])
                best_thr = thr
                best_f1 = stats["f1"]
                best_bal = stats["bal_acc"]

        # store predictions
        y_prob = best_model.predict_proba(X_va)[:, 1]
        all_val_preds.append(pd.DataFrame({
            "date": df.loc[in_va, "date"].values,
            "ticker": df.loc[in_va, "ticker"].values,
            "y_true": y_va,
            "y_prob": y_prob,
            "y_pred": (y_prob >= best_thr).astype(int),
            "window": w_idx,
        }))

        results.append(WindowResult(
            window_index=w_idx,
            horizon_name=horizon_name,
            train_start=tr_start, train_end=tr_end,
            val_start=va_start, val_end=va_end,
            alpha=float(best_alpha),
            chosen_C=float(best_C),
            chosen_threshold=float(best_thr),
            auc_val=float(best_auc),
            f1_val=float(best_f1),
            bal_acc_val=float(best_bal),
            n_train=int(in_tr.sum()),
            n_val=int(in_va.sum()),
        ))

    preds_df = pd.concat(all_val_preds, ignore_index=True) if all_val_preds else pd.DataFrame()
    return preds_df, results

def main():
    print("=== Mean-Reversion via Serial Correlation — Multi-Horizon ===")
    print(f"Reading: {EXCEL_PATH} [sheet={SHEET_NAME}]")

    returns_wide = read_returns_excel(EXCEL_PATH, SHEET_NAME)
    panel = build_panel(returns_wide)

    for horizon_name, _, _ in HORIZONS:
        print(f"\n--- Horizon: {horizon_name} ---")
        preds_df, results = run_for_horizon(panel, horizon_name)

        if preds_df.empty:
            print("  No validation predictions for this horizon (class imbalance or date coverage).")
            continue

        overall_auc = roc_auc_score(preds_df["y_true"], preds_df["y_prob"])
        overall_f1 = f1_score(preds_df["y_true"], preds_df["y_pred"])
        pr, rc, f1, _ = precision_recall_fscore_support(
            preds_df["y_true"], preds_df["y_pred"], average="binary", zero_division=0
        )
        print(f"  AUC={overall_auc:0.4f} | F1={overall_f1:0.4f} | Precision={pr:0.4f} | Recall={rc:0.4f}")

        print("  Per-window choices:")
        for r in results:
            print(
                f"    W{r.window_index}  Train {r.train_start.date()}→{r.train_end.date()}  "
                f"Val {r.val_start.date()}→{r.val_end.date()}  "
                f"alpha={r.alpha} C={r.chosen_C} thr={r.chosen_threshold}  "
                f"AUC={r.auc_val:0.4f} F1={r.f1_val:0.4f} BalAcc={r.bal_acc_val:0.4f}  "
                f"n_train={r.n_train} n_val={r.n_val}"
            )

        # Save
        preds_path = f"mr_{horizon_name}_val_predictions.csv"
        wins_path  = f"mr_{horizon_name}_window_results.csv"
        preds_df.to_csv(preds_path, index=False)
        pd.DataFrame([r.__dict__ for r in results]).to_csv(wins_path, index=False)
        print(f"  Saved → {preds_path} and {wins_path}")

if __name__ == "__main__":
    main()
