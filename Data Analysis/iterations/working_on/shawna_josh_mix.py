#!/usr/bin/env python3
"""
Mean-Reversion (Serial Correlation) — Evaluation Only (No Saving)
=================================================================
What this does
--------------
- Builds serial-correlation features (rolling AR(1), multi-lag autocorr) + light controls.
- Defines "mean-reversion" labels: future move over horizon opposes current z-score sign (and is big enough).
- Trains with walk-forward CV (train 3y → validate 1y → slide), inner CV uses TimeSeriesSplit.
- Chooses a two-sided threshold with an abstain band (optimize mean(accuracy × coverage) across folds).
- Prints **AUC**, **accuracy on covered**, **coverage**, and the chosen **alpha/threshold** for:
    • Tomorrow (1d), Next Week (5d), Next Month (20d)

Run
---
pip install pandas numpy scikit-learn openpyxl
python meanrev_eval_only.py --excel MXUS_Data.xlsx --sheet Returns
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegressionCV
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import TimeSeriesSplit

# =========================
# Configuration
# =========================

@dataclass
class EvalConfig:
    excel_path: str = "MXUS_Data.xlsx"
    sheet_name: str = "Returns"

    # Labeling
    label_threshold_abs_ret: float = 0.005  # |future return| >= 0.5%

    # Walk-forward (≈252 trading days per year)
    train_years: int = 3
    validation_years: int = 1

    # Model search
    alpha_grid: Tuple[float, ...] = (0.0, 0.5, 1.0)   # ridge, elastic, lasso
    inner_cv_folds: int = 5
    C_grid: np.ndarray = np.logspace(-2, 2, 10)       # speed-friendly
    class_weight: str = "balanced"

    # Two-sided threshold (abstain band)
    threshold_grid: np.ndarray = np.round(np.arange(0.55, 0.86, 0.01), 2)

    # Feature timing: 1 means only info up to t-1 (safe for next-day trading)
    shift_features_by_days: int = 1

    random_state: int = 42


FEATURE_COLUMNS: List[str] = [
    "ret_lag1",
    "ret_5",
    "ret_20",
    "vol_20",
    "z_ma_20",
    "ac_l1_w20",
    "ac_l1_w60",
    "ac_l1_w120",
    "ac_l5_w60",
    "ac_l5_w120",
    "ac_l20_w120",
]

# =========================
# Data
# =========================

def load_returns_from_excel(excel_path: str, sheet_name: str) -> pd.DataFrame:
    df = pd.read_excel(excel_path, sheet_name=sheet_name, engine="openpyxl")
    if "Date" not in df.columns:
        raise ValueError("Excel must have a header row with a 'Date' column.")
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df[df["Date"].notna()].sort_values("Date").reset_index(drop=True)
    for c in df.columns:
        if c != "Date":
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

# =========================
# Features
# =========================

def compute_base_technicals(long_returns: pd.DataFrame, shift_features_by_days: int) -> pd.DataFrame:
    df = long_returns.copy()
    df["ret_filled"] = df["ret"].fillna(0.0)
    df["px"] = (1.0 + df["ret_filled"]).groupby(df["stock"]).cumprod()

    df["ret_lag1"] = df.groupby("stock")["ret"].shift(1)
    df["ret_5"] = df["px"] / df.groupby("stock")["px"].shift(5) - 1.0
    df["ret_20"] = df["px"] / df.groupby("stock")["px"].shift(20) - 1.0

    ma_20 = df.groupby("stock")["px"].rolling(20, min_periods=20).mean().reset_index(level=0, drop=True)
    sd_20 = df.groupby("stock")["px"].rolling(20, min_periods=20).std().reset_index(level=0, drop=True)
    df["z_ma_20"] = (df["px"] - ma_20) / sd_20

    vol_20 = df.groupby("stock")["ret"].rolling(20, min_periods=20).std().reset_index(level=0, drop=True)
    df["vol_20"] = vol_20

    if shift_features_by_days > 0:
        for c in ["ret_5", "ret_20", "z_ma_20", "vol_20"]:
            df[c] = df.groupby("stock")[c].shift(shift_features_by_days)

    return df


def add_serial_correlation_features(long_df: pd.DataFrame, shift_features_by_days: int) -> pd.DataFrame:
    df = long_df.copy()

    def rolling_autocorr(series: pd.Series, lag: int, window: int) -> pd.Series:
        s = series
        s_lag = s.shift(lag)
        return s.rolling(window=window, min_periods=window).corr(s_lag)

    for stock, g in df.groupby("stock"):
        idx = g.index
        df.loc[idx, "ac_l1_w20"] = rolling_autocorr(g["ret"], lag=1, window=20)
        df.loc[idx, "ac_l1_w60"] = rolling_autocorr(g["ret"], lag=1, window=60)
        df.loc[idx, "ac_l1_w120"] = rolling_autocorr(g["ret"], lag=1, window=120)
        df.loc[idx, "ac_l5_w60"] = rolling_autocorr(g["ret"], lag=5, window=60)
        df.loc[idx, "ac_l5_w120"] = rolling_autocorr(g["ret"], lag=5, window=120)
        df.loc[idx, "ac_l20_w120"] = rolling_autocorr(g["ret"], lag=20, window=120)

    if shift_features_by_days > 0:
        for c in ["ac_l1_w20","ac_l1_w60","ac_l1_w120","ac_l5_w60","ac_l5_w120","ac_l20_w120"]:
            df[c] = df.groupby("stock")[c].shift(shift_features_by_days)
    return df


def build_reversion_label(df: pd.DataFrame, horizon_days: int, thr_abs: float) -> pd.Series:
    future_px = df.groupby("stock")["px"].shift(-horizon_days)
    future_ret = future_px / df["px"] - 1.0
    z_sign = np.sign(df["z_ma_20"])
    ret_sign = np.sign(future_ret)

    big = np.abs(future_ret) >= thr_abs
    has_dir = z_sign != 0

    y = pd.Series(np.nan, index=df.index, dtype="float")
    y[big & has_dir & (ret_sign == -z_sign)] = 1.0   # reversion
    y[big & has_dir & (ret_sign ==  z_sign)] = 0.0   # continuation
    return y.astype("Int64")


def assemble_features_for_horizon(returns_wide: pd.DataFrame, horizon_days: int, cfg: EvalConfig) -> pd.DataFrame:
    long_ret = returns_wide.melt(id_vars="Date", var_name="stock", value_name="ret") \
                           .sort_values(["stock","Date"]).reset_index(drop=True)
    base = compute_base_technicals(long_ret, shift_features_by_days=cfg.shift_features_by_days)
    ac = add_serial_correlation_features(base, shift_features_by_days=cfg.shift_features_by_days)
    y = build_reversion_label(ac, horizon_days=horizon_days, thr_abs=cfg.label_threshold_abs_ret)
    ac["y"] = y
    feat = ac[["Date","stock","y"] + FEATURE_COLUMNS].dropna().copy()
    feat = feat[feat["y"].notna()].reset_index(drop=True)
    return feat

# =========================
# Walk-Forward & Modeling
# =========================

@dataclass
class Fold:
    train_dates: np.ndarray
    val_dates: np.ndarray

def make_folds(unique_dates: np.ndarray, train_years: int, val_years: int) -> List[Fold]:
    train_days = int(train_years * 252)
    val_days = int(val_years * 252)
    n = len(unique_dates)
    starts = np.arange(0, n - (train_days + val_days) + 1, val_days, dtype=int)
    folds: List[Fold] = []
    for s in starts:
        tr_idx = np.arange(s, s+train_days, dtype=int)
        va_idx = np.arange(s+train_days, s+train_days+val_days, dtype=int)
        folds.append(Fold(unique_dates[tr_idx], unique_dates[va_idx]))
    return folds

def build_logit_cv(alpha: float, cfg: EvalConfig) -> Pipeline:
    inner = TimeSeriesSplit(n_splits=cfg.inner_cv_folds)
    common = dict(
        Cs=cfg.C_grid, cv=inner, scoring="neg_log_loss",
        max_iter=100_000, n_jobs=-1, refit=True,
        class_weight=cfg.class_weight, random_state=cfg.random_state
    )
    if alpha == 0.0:
        lr = LogisticRegressionCV(penalty="l2", solver="lbfgs", **common)
    elif alpha == 1.0:
        lr = LogisticRegressionCV(penalty="l1", solver="saga", **common)
    else:
        lr = LogisticRegressionCV(penalty="elasticnet", solver="saga", l1_ratios=[alpha], **common)
    return Pipeline([("scale", StandardScaler()), ("logit_cv", lr)])

def auc_safe(p: np.ndarray, y: np.ndarray) -> float:
    p = np.asarray(p, float); y = np.asarray(y, int)
    keep = np.isfinite(p) & np.isin(y, [0,1])
    p = p[keep]; y = y[keep]
    if p.size == 0 or np.unique(y).size < 2 or np.allclose(p.std(ddof=0), 0.0):
        return 0.5
    try: return float(roc_auc_score(y, p))
    except Exception: return 0.5

def run_eval(feature_table: pd.DataFrame, cfg: EvalConfig) -> pd.DataFrame:
    X = feature_table[FEATURE_COLUMNS]
    y = feature_table["y"].astype(int).values
    dates = pd.to_datetime(feature_table["Date"]).values
    uniq = np.sort(np.unique(dates))
    folds = make_folds(uniq, cfg.train_years, cfg.validation_years)

    rows = []
    for alpha in cfg.alpha_grid:
        # out-of-sample probabilities across folds
        probs_all = np.full(len(feature_table), np.nan, float)
        for fold_i, f in enumerate(folds, start=1):
            tr_mask = np.isin(dates, f.train_dates)
            va_mask = np.isin(dates, f.val_dates)
            tr_idx = np.where(tr_mask)[0]; va_idx = np.where(va_mask)[0]
            if np.unique(y[tr_idx]).size < 2:  # need both classes
                continue
            model = build_logit_cv(alpha, cfg)
            model.fit(X.iloc[tr_idx], y[tr_idx])
            probs_all[va_idx] = model.predict_proba(X.iloc[va_idx])[:,1]

        # evaluate thresholds
        for thr in cfg.threshold_grid:
            # two-sided with abstain
            p = probs_all.copy()
            keep = np.isfinite(p)
            yk = y[keep]; pk = p[keep]
            pred = np.full_like(yk, -1, int)
            pred[pk >= thr] = 1
            pred[pk <= (1.0 - thr)] = 0
            covered = pred != -1
            coverage = float(np.mean(covered)) if yk.size else np.nan
            acc = float(np.mean(pred[covered] == yk[covered])) if covered.any() else np.nan
            auc = auc_safe(pk, yk)
            score = acc * coverage if (acc==acc and coverage==coverage) else np.nan  # acc*coverage
            rows.append(dict(alpha=alpha, threshold=thr, mean_accuracy=acc, mean_auc=auc, mean_coverage=coverage, score_acc_x_cov=score))
    out = pd.DataFrame(rows).dropna().sort_values(["score_acc_x_cov","mean_accuracy"], ascending=False).reset_index(drop=True)
    return out

# =========================
# CLI
# =========================

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Evaluate serial-corr mean-reversion accuracy (no saving).")
    p.add_argument("--excel", type=str, default="MXUS_Data.xlsx")
    p.add_argument("--sheet", type=str, default="Returns")
    p.add_argument("--shift_features", type=int, default=1)
    p.add_argument("--label_thr", type=float, default=0.005)
    p.add_argument("--train_years", type=int, default=3)
    p.add_argument("--val_years", type=int, default=1)
    return p.parse_args()

def main() -> None:
    args = parse_args()
    cfg = EvalConfig(
        excel_path=args.excel, sheet_name=args.sheet,
        shift_features_by_days=int(args.shift_features),
        label_threshold_abs_ret=float(args.label_thr),
        train_years=int(args.train_years),
        validation_years=int(args.val_years),
    )

    data = load_returns_from_excel(cfg.excel_path, cfg.sheet_name)
    horizons = {"tomorrow":1, "next_week":5, "next_month":20}

    for name, h in horizons.items():
        print(f"\n=== Horizon: {name} ({h}d) ===")
        feat = assemble_features_for_horizon(data, h, cfg)
        if feat.empty:
            print("No rows after feature/label filtering. Try lowering --label_thr or ensure enough history.")
            continue
        summary = run_eval(feat, cfg)
        if summary.empty:
            print("No evaluation rows—check class balance and folds.")
            continue
        best = summary.iloc[0]
        print(f"Best alpha={best['alpha']:.2f} | threshold={best['threshold']:.2f}")
        print(f"  mean_accuracy (on covered): {best['mean_accuracy']:.3f}")
        print(f"  mean_coverage:              {best['mean_coverage']:.2f}")
        print(f"  score (acc×coverage):       {best['score_acc_x_cov']:.3f}")
        print(f"  mean AUC (prob quality):    {best['mean_auc']:.3f}")
        # Show top 5 rows for quick exploration
        print("\nTop 5 settings (alpha, thr, acc, cov, score, AUC):")
        print(summary.head(5).to_string(index=False))

if __name__ == "__main__":
    main()
