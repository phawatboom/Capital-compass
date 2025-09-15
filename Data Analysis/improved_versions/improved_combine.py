#!/usr/bin/env python3
"""
Mean-Reversion Likelihood Model — Improved (returns-as-percent support)
----------------------------------------------------------------------
Focus: modeling only (no web). Expects an Excel sheet of *daily simple returns*
formatted as percentages (e.g., "0.56%").

Key features
• Robust Excel loader for percent strings → decimal returns
• Returns hygiene: winsorization (±10% default), NaN guards
• Features from returns only (serial corr, sign persistence, momentum, vol, z-score over price index)
• Labels: mean-reversion vs recent momentum, with abs-move gate
• Walk-forward by trading-day counts with horizon-aware purge (+ optional embargo)
• Inner CV scoring = neg_log_loss; class_weight="balanced"
• Two-sided abstain band with τ>0.5, coverage-weighted F1 for threshold choice
• Per-window metrics + CSV/plots/models (optional)

Run
  python mean_reversion_model_improved.py --excel "MXUS_Data_%.xlsx" --sheet "Returns"

Requirements
  pip install pandas numpy scikit-learn openpyxl matplotlib seaborn joblib
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple, Iterable, Optional, Union

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from pandas.tseries.offsets import BDay

from sklearn.linear_model import LogisticRegression, LogisticRegressionCV
from sklearn.metrics import (
    roc_auc_score, f1_score, precision_recall_fscore_support,
    balanced_accuracy_score, roc_curve, brier_score_loss, accuracy_score,
    mean_absolute_error, mean_squared_error
)
from sklearn.model_selection import TimeSeriesSplit, GridSearchCV
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from joblib import dump

from pathlib import Path

# Progress bars (safe fallback if tqdm not installed)
try:
    from tqdm.auto import tqdm
except Exception:  # pragma: no cover
    def tqdm(iterable=None, **kwargs):
        return iterable

# =========================
# Configuration
# =========================
THIS_DIR = Path(__file__).resolve().parent
@dataclass
class MeanReversionConfig:
    # I/O
    excel_path: str | Path = field(default=str(THIS_DIR / "MXUS_Data.xlsx"))
    sheet_name: str = field(default="Returns")
    output_dir: str | Path = field(default="results")
  
    # Labeling
    abs_move_threshold: float = 0.005   # 0.5% min magnitude for a "real" move

    # Windows
    train_years: int = 3
    validation_years: int = 1
    trading_days_per_year: int = 252
    embargo_days: int = 5               # optional extra gap between train and validation

    # Regularization search
    alpha_grid: List[float] = field(default_factory=lambda: [0.0, 0.5, 1.0])  # 0=ridge,0.5=elastic,1=lasso
    inner_cv_folds: int = 5
    reg_strengths_C: List[float] = field(default_factory=lambda: list(np.logspace(-4, 4, 30)))

    # Threshold sweep (two-sided abstain uses τ > 0.5)
    threshold_grid: List[float] = field(default_factory=lambda: [round(x, 2) for x in np.arange(0.55, 0.86, 0.01)])

    # Horizons: (name, forward_horizon_days, momentum_lookback_days)
    horizons: List[Tuple[str, int, int]] = field(default_factory=lambda: [
        ("tomorrow",   1,  1),
        ("next_week",  5,  5),
        ("next_month", 20, 20),
    ])

    # Feature windows
    ar_windows: List[int] = field(default_factory=lambda: [10, 20, 60])
    sign_persist_windows: List[int] = field(default_factory=lambda: [20, 60])
    vol_windows: List[int] = field(default_factory=lambda: [10, 20])
    z_score_windows: List[int] = field(default_factory=lambda: [20])

    # Returns hygiene
    winsor_limit_abs: float = 0.10      # clamp simple daily returns to ±10%

    # Randomness
    random_state: int = 42

    # Output toggles
    save_predictions: bool = True
    create_plots: bool = True
    save_models: bool = True
    verbose: bool = True

    show_progress: bool = True

def _pb_disabled(cfg: MeanReversionConfig) -> bool:
    # Show bars only if both verbose and show_progress are True
    return not (getattr(cfg, "verbose", True) and getattr(cfg, "show_progress", True))


# =========================
# Data loading (handles percent strings)
# =========================

def _parse_percentish(series: pd.Series) -> pd.Series:
    """
    Convert a column that may contain:
      • '0.56%' strings
      • numeric percents like 0.56 (meaning 0.56%) or 56 (meaning 56%)
      • decimal simple returns like 0.0056
    into *decimal simple returns* (e.g., 0.0056).
    """
    s = series.astype(str).str.strip()

    # If it has '%', remove and divide by 100
    has_percent = s.str.contains(r"%").any()
    if has_percent:
        s = s.str.replace("%", "", regex=False)
        s = pd.to_numeric(s, errors="coerce") / 100.0
        return s

    # Otherwise coerce to numeric
    s = pd.to_numeric(s, errors="coerce")

    # Heuristic: if many values are > 1.0 (e.g., 2.5 meaning 2.5%), divide by 100
    if s.abs().quantile(0.95) > 1.0 and s.abs().quantile(0.99) <= 100.0:
        s = s / 100.0

    # Now s should be decimal returns
    return s


def load_returns_wide(excel_path: str | Path, sheet_name: str) -> pd.DataFrame:
    """
    Load a "Returns" sheet with the first column as Date and remaining as tickers.
    Cells can be percent-formatted strings (e.g., '0.56%').
    Returns DataFrame with columns: Date, <ticker1>, <ticker2>, ...
    """
    df = pd.read_excel(excel_path, sheet_name=sheet_name, engine="openpyxl")
    # Normalize the date column name
    first_col = df.columns[0]
    df = df.rename(columns={first_col: "Date"})
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df[df["Date"].notna()].sort_values("Date").reset_index(drop=True)

    # Convert every ticker column to decimal simple returns
    for col in [c for c in df.columns if c != "Date"]:
        df[col] = _parse_percentish(df[col])

    return df


# =========================
# Returns hygiene, features, labels
# =========================

def winsorize_simple_returns(series: pd.Series, limit_abs: float) -> pd.Series:
    """Clamp simple daily returns to ±limit_abs (e.g., ±10%)."""
    return series.clip(lower=-limit_abs, upper=limit_abs)

def compound_forward_simple(simple_ret: pd.Series, horizon: int) -> pd.Series:
    """Forward compounded simple return over next horizon days."""
    cp = (1.0 + simple_ret).cumprod()
    out = cp.shift(-horizon) / cp - 1.0
    if horizon > 0:
        out.iloc[-horizon:] = np.nan
    return out

def compound_past_simple(simple_ret: pd.Series, window: int) -> pd.Series:
    """Past compounded simple return over prior window days (ending t-1)."""
    past = (1.0 + simple_ret).rolling(window).apply(np.prod, raw=True) - 1.0
    return past.shift(1)

def rolling_autocorr(series: pd.Series, lag: int, window: int) -> pd.Series:
    """Rolling correlation corr(r_t, r_{t-1}) over 'window', reported at t-1."""
    x = series.shift(1)
    y = series
    corr = y.rolling(window).corr(x)
    return corr.shift(1)

def rolling_sign_persistence(series: pd.Series, window: int) -> pd.Series:
    """Share of same-sign days over the last 'window' (through t-1)."""
    same = (np.sign(series) * np.sign(series.shift(1))) > 0
    rate = same.rolling(window).mean()
    return rate.shift(1)

def build_feature_panel(returns_wide: pd.DataFrame, cfg: MeanReversionConfig) -> pd.DataFrame:
    tickers = [c for c in returns_wide.columns if c != "Date"]
    frames: List[pd.DataFrame] = []

    for ticker in tqdm(tickers, desc="Building features (tickers)", disable=_pb_disabled(cfg)):
        r = returns_wide[ticker].astype(float)

        if r.notna().mean() < 0.7:
            continue

        # Winsorize for robustness
        r = winsorize_simple_returns(r, cfg.winsor_limit_abs)

        base = pd.DataFrame({"Date": returns_wide["Date"], "ticker": ticker})
        features: Dict[str, pd.Series] = {}

        # Serial correlation features
        for w in cfg.ar_windows:
            features[f"ar1_corr_{w}d"] = rolling_autocorr(r, lag=1, window=w)

        for w in cfg.sign_persist_windows:
            features[f"sign_persist_{w}d"] = rolling_sign_persistence(r, window=w)

        # Momentum controls
        features["ret_1d"]   = r.shift(1)
        features["ret_5d"]   = compound_past_simple(r, 5)
        features["ret_20d"]  = compound_past_simple(r, 20)

        # Volatility
        for w in cfg.vol_windows:
            features[f"vol_{w}d"] = r.rolling(w).std().shift(1)

        # Z-score vs MA of price index (scale-free)
        price_index = (1.0 + r.fillna(0)).cumprod()
        for w in cfg.z_score_windows:
            ma = price_index.rolling(w, min_periods=w).mean()
            sd = price_index.rolling(w, min_periods=w).std()
            features[f"z_ma_{w}d"] = ((price_index - ma) / sd).shift(1)

        feat_df = pd.DataFrame(features)

        # Forward returns for horizons
        fwd = {f"fwd_{h}d": compound_forward_simple(r, h) for _, h, _ in cfg.horizons}
        fwd_df = pd.DataFrame(fwd)

        # Recent momentum baselines for labels
        mom = {f"mom_{k}d": compound_past_simple(r, k) for _, _, k in cfg.horizons}
        mom_df = pd.DataFrame(mom)

        frames.append(pd.concat([base, feat_df, fwd_df, mom_df], axis=1))

    if not frames:
        raise RuntimeError("No usable tickers (too sparse after cleaning).")

    panel = pd.concat(frames, ignore_index=True)

    # Build labels per horizon: mean reversion = future move opposes recent momentum (with abs-move gate)
    for name, h, k in cfg.horizons:
        fwd_col = f"fwd_{h}d"
        mom_col = f"mom_{k}d"

        mask_big = panel[fwd_col].abs() > cfg.abs_move_threshold
        sign_future = np.sign(panel[fwd_col])
        sign_mom = np.sign(panel[mom_col])

        label_mr = np.where(
            (mask_big) & (sign_mom != 0) & (sign_future == -sign_mom), 1,
            np.where((mask_big) & (sign_mom != 0), 0, np.nan)
        )
        panel[f"label_mr_{name}"] = label_mr

        # Optional up/down direction (not used by default here)
        updown = np.where(panel[fwd_col] > cfg.abs_move_threshold, 1,
                   np.where(panel[fwd_col] < -cfg.abs_move_threshold, 0, np.nan))
        panel[f"label_updown_{name}"] = updown

    # Keep rows with all features present; labels can still be NaN (filtered later)
    feature_cols = [c for c in panel.columns
                    if c not in ("Date", "ticker")
                    and not c.startswith("fwd_")
                    and not c.startswith("mom_")
                    and not c.startswith("label_")]
    panel = panel.dropna(subset=feature_cols).reset_index(drop=True)
    return panel


# =========================
# Walk-forward windows (with horizon purge + embargo)
# =========================

def generate_windows_by_counts(dates: pd.Series, train_years: int, val_years: int, td_per_year: int) -> List[Tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
    unique_dates = pd.to_datetime(pd.Series(dates.unique())).sort_values().to_numpy()
    n_train = int(train_years * td_per_year)
    n_val   = int(val_years * td_per_year)

    starts = np.arange(0, len(unique_dates) - (n_train + n_val) + 1, n_val, dtype=int)
    windows = []
    for s in starts:
        train_dates = unique_dates[s:s+n_train]
        val_dates   = unique_dates[s+n_train:s+n_train+n_val]
        if train_dates.size == 0 or val_dates.size == 0:
            continue
        windows.append((pd.Timestamp(train_dates[0]), pd.Timestamp(train_dates[-1]),
                        pd.Timestamp(val_dates[0]), pd.Timestamp(val_dates[-1])))
    return windows


# =========================
# Modeling helpers
# =========================

def build_logit_cv(alpha: float, cfg: MeanReversionConfig) -> Union[Pipeline, GridSearchCV]:
    """
    alpha: 0.0=ridge, 1.0=lasso, 0<alpha<1 elastic-net via GridSearchCV
    All use class_weight="balanced" and scoring='neg_log_loss'.
    """
    if 0 < alpha < 1:
        pipe = Pipeline([
            ("scale", StandardScaler()),
            ("logit", LogisticRegression(
                penalty="elasticnet", solver="saga", l1_ratio=alpha,
                max_iter=10000, class_weight="balanced", random_state=cfg.random_state
            ))
        ])
        grid = {"logit__C": cfg.reg_strengths_C}
        cv = TimeSeriesSplit(n_splits=cfg.inner_cv_folds)
        return GridSearchCV(pipe, grid, scoring="neg_log_loss", cv=cv, n_jobs=-1, refit=True, verbose=0)

    if alpha == 0.0:  # ridge
        return Pipeline([
            ("scale", StandardScaler()),
            ("logit_cv", LogisticRegressionCV(
                penalty="l2", solver="lbfgs",
                Cs=cfg.reg_strengths_C, cv=cfg.inner_cv_folds, scoring="neg_log_loss",
                class_weight="balanced", max_iter=10000, n_jobs=-1, refit=True,
                random_state=cfg.random_state
            ))
        ])

    if alpha == 1.0:  # lasso
        return Pipeline([
            ("scale", StandardScaler()),
            ("logit_cv", LogisticRegressionCV(
                penalty="l1", solver="saga",
                Cs=cfg.reg_strengths_C, cv=cfg.inner_cv_folds, scoring="neg_log_loss",
                class_weight="balanced", max_iter=10000, n_jobs=-1, refit=True,
                random_state=cfg.random_state
            ))
        ])

    raise ValueError("alpha must be in [0,1].")


def auc_safe(y_true: np.ndarray, y_prob: np.ndarray) -> float:
    y = np.asarray(y_true)
    p = np.asarray(y_prob, dtype=float)
    keep = np.isin(y, [0, 1]) & np.isfinite(p)
    y = y[keep]; p = p[keep]
    if y.size == 0 or np.unique(y).size < 2 or np.allclose(p.std(ddof=0), 0.0):
        return 0.5
    try:
        return float(roc_auc_score(y, p))
    except Exception:
        return 0.5


def choose_best_threshold(y_true: np.ndarray, y_prob: np.ndarray, thresholds: List[float], use_abstain: bool) -> Tuple[float, Dict]:
    best_thr, best = None, {"score": -np.inf}
    for thr in thresholds:
        if use_abstain and thr <= 0.5:
            continue
        if use_abstain:
            pred = np.full_like(y_true, -1)
            hi = y_prob >= thr
            lo = y_prob <= (1.0 - thr)
            pred[hi] = 1
            pred[lo] = 0
            covered = (pred != -1)
            if not np.any(covered):
                continue
            yt = y_true[covered]; yp = pred[covered]
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
        best_thr = 0.7 if use_abstain else 0.5
        best = {"f1": 0.0, "bal_acc": 0.5, "precision": 0.0, "recall": 0.0, "coverage": 0.0, "score": 0.0}
    return best_thr, best


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
    alpha: float
    chosen_C: float
    chosen_threshold: float
    auc_val: float
    f1_val: float
    bal_acc_val: float
    precision_val: float
    recall_val: float
    n_train: int
    n_val: int
    coverage: float

def run_for_horizon(panel: pd.DataFrame, horizon_name: str, cfg: MeanReversionConfig, label_type: str = "mr") -> Tuple[pd.DataFrame, List[WindowResult]]:
    label_col = f"label_{label_type}_{horizon_name}"
    feature_cols = [c for c in panel.columns
                    if c not in ("Date", "ticker")
                    and not c.startswith("fwd_")
                    and not c.startswith("mom_")
                    and not c.startswith("label_")]

    df = panel.dropna(subset=[label_col]).copy()
    X_all = df[feature_cols].values
    y_all = df[label_col].astype(int).values
    dates_all = df["Date"].to_numpy()

    windows = generate_windows_by_counts(df["Date"], cfg.train_years, cfg.validation_years, cfg.trading_days_per_year)

    # horizon-specific purge
    horizon_days = next(h for name, h, _ in cfg.horizons if name == horizon_name)

    results: List[WindowResult] = []
    all_val_preds = []

    # NEW: progress over windows
    for w_idx, (tr_start, tr_end, va_start, va_end) in enumerate(
        tqdm(windows, desc=f"{horizon_name}: walk-forward windows", disable=_pb_disabled(cfg)),
        start=1
    ):
        # purge + embargo
        train_cutoff = tr_end - BDay(horizon_days)
        val_start_adj = va_start + BDay(cfg.embargo_days)
        val_cutoff = va_end - BDay(horizon_days)

        in_tr = (dates_all >= tr_start) & (dates_all <= train_cutoff)
        in_va = (dates_all >= val_start_adj) & (dates_all <= val_cutoff)

        X_tr, y_tr = X_all[in_tr], y_all[in_tr]
        X_va, y_va = X_all[in_va], y_all[in_va]

        # need both classes in train and val
        if len(np.unique(y_tr)) < 2 or len(np.unique(y_va)) < 2:
            if cfg.verbose:
                print(f"  W{w_idx:02d}: skipped (need both classes in train & val).")
            continue

        best_auc = -np.inf
        best_alpha = None
        best_model = None
        best_C = None
        best_thr = None
        best_metrics = None

        # NEW: progress over alpha grid (nested bar)
        for alpha in tqdm(cfg.alpha_grid, desc=f"W{w_idx}: alpha sweep", leave=False, disable=_pb_disabled(cfg)):
            model = build_logit_cv(alpha, cfg)
            model.fit(X_tr, y_tr)
            y_prob = model.predict_proba(X_va)[:, 1]
            auc = auc_safe(y_va, y_prob)

            use_abstain = (label_type == "mr")
            thr, metrics = choose_best_threshold(y_va, y_prob, cfg.threshold_grid, use_abstain)

            if (auc > best_auc) or (math.isclose(auc, best_auc) and (best_metrics is None or metrics["score"] > best_metrics["score"])):
                best_auc = auc
                best_alpha = alpha
                best_model = model
                if hasattr(model, "best_params_"):
                    best_C = float(model.best_params_["logit__C"])
                elif hasattr(model, "named_steps") and "logit_cv" in model.named_steps and hasattr(model.named_steps["logit_cv"], "C_"):
                    best_C = float(model.named_steps["logit_cv"].C_[0])
                else:
                    best_C = 1.0
                best_thr = thr
                best_metrics = metrics

        # predict with best model
        y_prob = best_model.predict_proba(X_va)[:, 1]
        if label_type == "mr":
            y_pred = np.full_like(y_va, -1)
            hi = y_prob >= best_thr
            lo = y_prob <= (1.0 - best_thr)
            y_pred[hi] = 1
            y_pred[lo] = 0
            abstained = (y_pred == -1)
        else:
            y_pred = (y_prob >= best_thr).astype(int)
            abstained = np.zeros_like(y_pred, dtype=bool)

        all_val_preds.append(pd.DataFrame({
            "Date": df.loc[in_va, "Date"].values,
            "ticker": df.loc[in_va, "ticker"].values,
            "y_true": y_va,
            "y_prob": y_prob,
            "y_pred": y_pred,
            "abstained": abstained,
            "window": w_idx
        }))

        if cfg.save_models:
            out_dir = Path(cfg.output_dir); out_dir.mkdir(parents=True, exist_ok=True)
            model_path = out_dir / f"{label_type}_{horizon_name}_W{w_idx}_alpha{best_alpha:.2f}_C{best_C:.4g}.joblib"
            try:
                dump(best_model, model_path)
            except Exception:
                pass

        results.append(WindowResult(
            window_index=w_idx, horizon_name=horizon_name,
            train_start=tr_start, train_end=tr_end,
            val_start=va_start, val_end=va_end,
            alpha=float(best_alpha), chosen_C=float(best_C),
            chosen_threshold=float(best_thr), auc_val=float(best_auc),
            f1_val=float(best_metrics["f1"]), bal_acc_val=float(best_metrics["bal_acc"]),
            precision_val=float(best_metrics["precision"]), recall_val=float(best_metrics["recall"]),
            n_train=int(in_tr.sum()), n_val=int(in_va.sum()), coverage=float(best_metrics["coverage"]),
        ))

    preds_df = pd.concat(all_val_preds, ignore_index=True) if all_val_preds else pd.DataFrame()
    return preds_df, results


# =========================
# Plots
# =========================

def plot_performance(preds_df: pd.DataFrame, results: List[WindowResult], horizon_name: str, label_type: str, cfg: MeanReversionConfig):
    if preds_df.empty:
        return
    out_dir = Path(cfg.output_dir); out_dir.mkdir(parents=True, exist_ok=True)

    # ROC on non-abstained
    if "abstained" in preds_df.columns:
        mask = ~preds_df["abstained"]
        y_true = preds_df.loc[mask, "y_true"]
        y_prob = preds_df.loc[mask, "y_prob"]
    else:
        y_true = preds_df["y_true"]
        y_prob = preds_df["y_prob"]

    if len(y_true) > 0:
        fpr, tpr, _ = roc_curve(y_true, y_prob)
        auc = auc_safe(y_true.to_numpy(), y_prob.to_numpy())
        plt.figure(figsize=(9, 6))
        plt.plot(fpr, tpr, lw=2, label=f"AUC = {auc:.3f}")
        plt.plot([0, 1], [0, 1], "k--", lw=1)
        plt.xlabel("False Positive Rate"); plt.ylabel("True Positive Rate")
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
        width = 0.22
        plt.bar(x - 1.5*width, r["auc_val"], width, label="AUC")
        plt.bar(x - 0.5*width, r["f1_val"], width, label="F1")
        plt.bar(x + 0.5*width, r["precision_val"], width, label="Precision")
        plt.bar(x + 1.5*width, r["recall_val"], width, label="Recall")
        plt.axhline(0.5, color="r", ls="--", alpha=0.25)
        plt.xticks(x, [f"W{i}" for i in r["window_index"]])
        plt.ylabel("Score"); plt.title(f"Validation by Window — {label_type.upper()} {horizon_name}")
        plt.legend(); plt.tight_layout()
        plt.savefig(out_dir / f"{label_type}_{horizon_name}_by_window.png", dpi=300)
        plt.close()

        # Params & coverage
        fig, ax = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
        ax[0].plot(x, r["alpha"], "o-", label="Alpha")
        ax[0].plot(x, r["chosen_C"], "o-", label="C")
        ax[0].set_ylabel("Value"); ax[0].set_title(f"Params — {label_type.upper()} {horizon_name}")
        ax[0].legend()
        ax[1].plot(x, r["chosen_threshold"], "o-", label="Threshold")
        ax[1].plot(x, r["coverage"], "o--", label="Coverage")
        ax[1].set_ylabel("Value"); ax[1].set_xlabel("Window")
        ax[1].legend(); plt.tight_layout()
        plt.savefig(out_dir / f"{label_type}_{horizon_name}_params_coverage.png", dpi=300)
        plt.close()


# =========================
# Main
# =========================

def find_default_excel() -> Optional[Path]:
    candidates = ["MXUS_Data.xlsx"]
    for name in candidates:
        p = Path(name)
        if p.exists():
            return p
    return None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--excel", type=str, default="")
    parser.add_argument("--sheet", type=str, default="Returns")
    parser.add_argument("--out", type=str, default="results")
    args = parser.parse_args()

    cfg = MeanReversionConfig(
        excel_path=args.excel or (str(find_default_excel()) if find_default_excel() else ""),
        sheet_name=args.sheet,
        output_dir=args.out,
    )

    if not cfg.excel_path:
        raise SystemExit("Excel file not specified and not found (tried MXUS_Data_%.xlsx, MXUS_Data.xlsx).")

    print("=== Mean-Reversion Likelihood Model — Improved ===")
    print(f"Reading: {cfg.excel_path} [sheet={cfg.sheet_name}]")

    # 1) Load returns (percent → decimal)
    returns_wide = load_returns_wide(cfg.excel_path, cfg.sheet_name)
    print(f"Loaded: {len(returns_wide):,} dates, {len(returns_wide.columns)-1} tickers")

    # 2) Build features + labels
    panel = build_feature_panel(returns_wide, cfg)
    print(f"Panel: {panel.shape[0]:,} rows × {panel.shape[1]} cols  "
          f"({panel['Date'].min().date()} → {panel['Date'].max().date()})")

    out_dir = Path(cfg.output_dir); out_dir.mkdir(parents=True, exist_ok=True)

    # 3) Run per horizon (mean-reversion label only)
    for horizon_name, _, _ in tqdm(cfg.horizons, desc="Horizons", disable=_pb_disabled(cfg)):
        print(f"\n--- Horizon: {horizon_name} (mean-reversion) ---")
        preds, results = run_for_horizon(panel, horizon_name, cfg, label_type="mr")

        if preds.empty:
            print("No validation predictions (possibly class imbalance or not enough dates).")
            continue

        active = preds[~preds["abstained"]]
        if not active.empty:
            auc = auc_safe(active["y_true"].to_numpy(), active["y_prob"].to_numpy())
            pred_bin = (active["y_prob"] >= 0.5).astype(int)  # neutral reference
            f1 = f1_score(active["y_true"], pred_bin, zero_division=0)
            prc, rec, _, _ = precision_recall_fscore_support(active["y_true"], pred_bin, average="binary", zero_division=0)
            coverage = 1 - preds["abstained"].mean()
            print(f"AUC={auc:.4f} | F1@0.50={f1:.4f} | Precision={prc:.4f} | Recall={rec:.4f} | Coverage={coverage:.2f}")

        # Per-window summary
        print("Per-window choices:")
        for r in results:
            print(f" W{r.window_index:02d}  Train {r.train_start.date()}→{r.train_end.date()}  "
                  f"Val {r.val_start.date()}→{r.val_end.date()} | "
                  f"alpha={r.alpha:.1f}  C={r.chosen_C:.4g}  thr={r.chosen_threshold:.2f} | "
                  f"AUC={r.auc_val:.4f}  F1={r.f1_val:.4f}  cov={r.coverage:.2f}  "
                  f"n_train={r.n_train:,}  n_val={r.n_val:,}")

        # Save outputs
        if cfg.save_predictions:
            preds.to_csv(out_dir / f"mr_{horizon_name}_predictions.csv", index=False)
            pd.DataFrame([w.__dict__ for w in results]).to_csv(out_dir / f"mr_{horizon_name}_results.csv", index=False)
            print(f"Saved CSVs → mr_{horizon_name}_predictions.csv, mr_{horizon_name}_results.csv")

        if cfg.create_plots:
            plot_performance(preds, results, horizon_name, "mr", cfg)

    print("\nDone.")


if __name__ == "__main__":
    main()
