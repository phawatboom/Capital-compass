#!/usr/bin/env python3
"""
Mean-Reversion: R→Python conversion (glmnet→sklearn)
- Reads Excel with a 'Date' header row (even if there are preambles)
- Long format, per-stock feature engineering
- Walk-forward outer CV by *trading years*
- Inner CV (log-loss) to pick lambda (≈ C) per alpha (≈ l1_ratio)
- Threshold sweep with abstention to select (alpha*, τ*) by accuracy×coverage
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import List, Dict, Tuple
from sklearn.linear_model import LogisticRegressionCV, LogisticRegression
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import log_loss
from sklearn.preprocessing import StandardScaler

# =========================
# Config
# =========================
PATH = "MXUS_Data.xlsx"
SHEET = "Returns"
FWD_H = 5           # forward horizon (days)
THR_LABEL = 0.005   # 0.5% future move threshold: learn only when |fwd_ret| > THR_LABEL
YEARS_TR = 3        # train window (years)
YEARS_VAL = 1       # validation window (years)
ALPHA_GRID = [0.0, 0.5, 1.0]                 # ridge, elastic, lasso (→ l1_ratio)
THR_GRID = np.round(np.arange(0.55, 0.85 + 1e-12, 0.01), 2)  # probability cutoffs
INNER_NFOLDS = 5                             # folds for inner CV
CS_GRID = np.logspace(-4, 4, 15)             # ≈ glmnet lambda grid inverse

TRADING_DAYS_PER_YEAR = 252


# =========================
# Helpers
# =========================
def read_returns_clean(path: str, sheet: str) -> pd.DataFrame:
    """Read Excel, find the row where col0 == 'Date', use it as header; coerce numerics."""
    raw = pd.read_excel(path, sheet_name=sheet, header=None, dtype=str)
    col0 = raw.iloc[:, 0].astype(str).str.strip()
    date_row_index = np.where(col0 == "Date")[0]
    if len(date_row_index) != 1:
        raise ValueError("Could not uniquely locate a 'Date' header row.")
    date_row = date_row_index[0]

    header = raw.iloc[date_row].tolist()
    data = raw.iloc[date_row + 1:].copy()
    data.columns = header

    # Excel serial dates or already datelike → normalize
    # Try numeric → serial; else parse
    date_series = pd.to_numeric(data["Date"], errors="coerce")
    is_serial = date_series.notna().all()
    if is_serial:
        data["Date"] = pd.to_datetime(date_series, unit="d", origin="1899-12-30")
    else:
        data["Date"] = pd.to_datetime(data["Date"], errors="coerce")

    data = data.loc[data["Date"].notna()].reset_index(drop=True)

    # Coerce all non-Date to numeric
    num_cols = [c for c in data.columns if c != "Date"]
    for c in num_cols:
        data[c] = pd.to_numeric(data[c], errors="coerce")

    return data


def auc_safe(p: np.ndarray, y: np.ndarray) -> float:
    """Robust AUC from ranks (like the R version), clamped to [0,1]."""
    keep = np.isfinite(p) & pd.notna(y)
    if not np.any(keep):
        return 0.5
    p = p[keep].astype(float)
    y = y[keep].astype(int)
    n1 = np.sum(y == 1)
    n0 = np.sum(y == 0)
    if n1 == 0 or n0 == 0:
        return 0.5
    if np.isclose(np.std(p), 0.0):
        return 0.5

    r = pd.Series(p).rank(method="average").to_numpy()
    num = np.sum(r[y == 1]) - n1 * (n1 + 1) / 2.0
    den = n1 * n0
    if not np.isfinite(num) or not np.isfinite(den) or den == 0:
        return 0.5
    auc = num / den
    if not np.isfinite(auc):
        return 0.5
    return float(max(0.0, min(1.0, auc)))


def make_folds(all_dates: np.ndarray, years_tr: int, years_val: int) -> List[Dict[str, np.ndarray]]:
    """Walk-forward folds over unique sorted dates using trading-day counts."""
    tr = years_tr * TRADING_DAYS_PER_YEAR
    va = years_val * TRADING_DAYS_PER_YEAR
    n = len(all_dates)
    starts = np.arange(0, n - (tr + va) + 1, va)
    folds = []
    for s in starts:
        tr_idx = np.arange(s, s + tr)
        va_idx = np.arange(s + tr, s + tr + va)
        folds.append({
            "train_dates": all_dates[tr_idx],
            "val_dates": all_dates[va_idx],
        })
    return folds


# =========================
# Data prep
# =========================
rets = read_returns_clean(PATH, SHEET)

# Long format: (Date, stock, ret)
long = rets.melt(id_vars="Date", var_name="stock", value_name="ret").sort_values(["stock", "Date"])
long["ret"] = long["ret"].astype(float)

# =========================
# Feature engineering (by stock)
# =========================
# price index px (treat NA returns as 0 ONLY for cumprod stability)
long["_ret_no_na"] = long["ret"].fillna(0.0)
long["px"] = long.groupby("stock")["_ret_no_na"].transform(lambda r: (1 + r).cumprod())
long.drop(columns=["_ret_no_na"], inplace=True)

# simple AR proxy
long["ret_lag1"] = long.groupby("stock")["ret"].shift(1)

# momentum on price
long["ret_5"] = long.groupby("stock")["px"].transform(lambda s: s / s.shift(5) - 1)
long["ret_20"] = long.groupby("stock")["px"].transform(lambda s: s / s.shift(20) - 1)

# rolling mean/sd on price for z-score (20d)
long["ma_20"] = long.groupby("stock")["px"].transform(lambda s: s.rolling(20, min_periods=20).mean())
long["sd_20"] = long.groupby("stock")["px"].transform(lambda s: s.rolling(20, min_periods=20).std())
long["z_ma_20"] = (long["px"] - long["ma_20"]) / np.maximum(long["sd_20"].fillna(0.0), 1e-8)

# volatility (SD of returns) over 20d
long["vol_20"] = long.groupby("stock")["ret"].transform(lambda s: s.rolling(20, min_periods=20).std())

# Forward return for label (from price)
long["fwd_ret"] = long.groupby("stock")["px"].transform(lambda s: s.shift(-FWD_H) / s - 1)

# Thresholded label: (1 = up, 0 = down, NA = small/weak move)
y_series = np.where(long["fwd_ret"] > THR_LABEL, 1,
           np.where(long["fwd_ret"] < -THR_LABEL, 0, np.nan))
long["y"] = y_series

# Keep rows with all features and labels
feat_cols = ["ret_lag1", "ret_5", "ret_20", "vol_20", "z_ma_20"]
feat = long[["Date", "stock", "y"] + feat_cols].dropna().reset_index(drop=True)

X_raw = feat[feat_cols].to_numpy(dtype=float)
y = feat["y"].to_numpy(dtype=int)
dates = pd.to_datetime(feat["Date"]).to_numpy()
stocks = feat["stock"].astype(str).to_numpy()

# Standardize features (glmnet standardizes internally)
scaler = StandardScaler()
X = scaler.fit_transform(X_raw)

# =========================
# Walk-forward CV (outer)
# =========================
all_dates = np.unique(np.sort(dates))
folds = make_folds(all_dates, YEARS_TR, YEARS_VAL)

# For each alpha (l1_ratio), we store OOS probabilities aligned with feat rows
cv_prob_store: Dict[str, np.ndarray] = {}

for alpha in ALPHA_GRID:
    p_all = np.full(shape=(len(feat),), fill_value=np.nan, dtype=float)

    for fold_id, fold in enumerate(folds, start=1):
        tr_mask = np.isin(dates, fold["train_dates"])
        va_mask = np.isin(dates, fold["val_dates"])
        if tr_mask.sum() == 0 or va_mask.sum() == 0:
            continue

        y_tr = y[tr_mask]
        # need both classes
        if np.unique(y_tr).size < 2:
            continue

        X_tr = X[tr_mask]
        X_va = X[va_mask]

        # Inner CV: deviance (log loss). For alpha=0 (ridge), use l2; alpha=1 (lasso) use l1; middle use elasticnet
        if alpha == 0.0:
            penalty = "l2"
            l1_ratio = None
        elif alpha == 1.0:
            penalty = "l1"
            l1_ratio = None
        else:
            penalty = "elasticnet"
            l1_ratio = alpha

        # Use LogisticRegressionCV to mimic cv.glmnet's lambda search
        # saga supports l1/l2/elasticnet; mult classes ok; here binary.
        # TimeSeriesSplit inside TRAIN ONLY (like inner CV)
        inner_cv = TimeSeriesSplit(n_splits=INNER_NFOLDS)
        clf_cv = LogisticRegressionCV(
            Cs=CS_GRID,
            cv=inner_cv,
            penalty=penalty,
            solver="saga",
            l1_ratios=(l1_ratio,) if l1_ratio is not None else None,
            scoring="neg_log_loss",
            class_weight=None,         # keep parity with glmnet (no balancing)
            fit_intercept=True,
            max_iter=100_000,
            n_jobs=None,
            refit=True,
        )
        clf_cv.fit(X_tr, y_tr)

        # Predict probabilities on validation
        p_va = clf_cv.predict_proba(X_va)[:, 1]
        p_all[va_mask] = p_va

    cv_prob_store[str(alpha)] = p_all

# =========================
# Evaluate thresholds & collect metrics (per fold)
# =========================
eval_rows: List[Dict] = []

for alpha_str, p_all in cv_prob_store.items():
    alpha_val = float(alpha_str)

    for f_idx, fold in enumerate(folds, start=1):
        va_mask = np.isin(dates, fold["val_dates"])
        if va_mask.sum() == 0:
            continue

        p = p_all[va_mask]
        y_sub = y[va_mask]
        keep = np.isfinite(p) & pd.notna(y_sub)
        if not np.any(keep):
            continue

        y_keep = y_sub[keep].astype(int)
        p_keep = p[keep].astype(float)

        stocks_keep = stocks[va_mask][keep]
        dates_keep = dates[va_mask][keep]

        fold_auc = auc_safe(p_keep, y_keep)

        for thr in THR_GRID:
            # Two-sided decision rule with abstention
            pred = np.full_like(y_keep, fill_value=-1, dtype=int)  # -1 = abstain
            pred[p_keep >= thr] = 1
            pred[p_keep <= (1.0 - thr)] = 0
            has_pred = pred != -1

            coverage = float(np.mean(has_pred)) if has_pred.size > 0 else 0.0
            accuracy = (float(np.mean(pred[has_pred] == y_keep[has_pred]))
                        if np.any(has_pred) else np.nan)

            # stock-count metrics
            if np.any(has_pred):
                n_unique_stocks = int(pd.unique(stocks_keep[has_pred]).size)
                # avg stocks per day among covered rows
                df_day = pd.DataFrame({"date": dates_keep[has_pred], "stock": stocks_keep[has_pred]})
                stocks_per_day = df_day.groupby("date")["stock"].count().to_numpy()
                avg_stocks_per_day = float(np.mean(stocks_per_day)) if len(stocks_per_day) else 0.0
            else:
                n_unique_stocks = 0
                avg_stocks_per_day = 0.0

            eval_rows.append({
                "alpha": alpha_val,
                "fold": f_idx,
                "threshold": float(thr),
                "accuracy": accuracy,
                "auc": fold_auc,
                "coverage": coverage,
                "n_unique_stocks": n_unique_stocks,
                "avg_stocks_per_day": avg_stocks_per_day,
            })

# =========================
# Aggregate across folds and rank
# =========================
results_df = (pd.DataFrame(eval_rows)
              .groupby(["alpha", "threshold"], as_index=False)
              .agg(mean_acc=("accuracy", "mean"),
                   mean_auc=("auc", "mean"),
                   mean_cov=("coverage", "mean"),
                   mean_n_stocks=("n_unique_stocks", "mean"),
                   mean_stocks_per_day=("avg_stocks_per_day", "mean"),
                   n_folds=("fold", "count"))
              .assign(score_prod=lambda d: d["mean_acc"] * d["mean_cov"])
              .sort_values(["score_prod", "mean_acc"], ascending=[False, False])
              .reset_index(drop=True))

print(results_df.head(12).to_string(index=False))

best = results_df.iloc[0]
print(
    f"\nBest (by accuracy*coverage): alpha={best.alpha:.2f}, thr={best.threshold:.2f} | "
    f"acc={best.mean_acc:.3f}, AUC={best.mean_auc:.3f}, cov={best.mean_cov:.2f} | "
    f"mean_n_stocks={best.mean_n_stocks:.1f}, mean_stocks_per_day={best.mean_stocks_per_day:.1f}"
)

# =========================
# Refit on ALL data with chosen alpha (keep for live use)
# =========================
alpha_star = float(best.alpha)
thr_star = float(best.threshold)

if alpha_star == 0.0:
    penalty = "l2"; l1_ratio = None
elif alpha_star == 1.0:
    penalty = "l1"; l1_ratio = None
else:
    penalty = "elasticnet"; l1_ratio = alpha_star

# Fit a final LogisticRegressionCV on ALL rows to emulate cv.glmnet(lambda.min)
final_inner_cv = TimeSeriesSplit(n_splits=INNER_NFOLDS)
cvfit_all = LogisticRegressionCV(
    Cs=CS_GRID,
    cv=final_inner_cv,
    penalty=penalty,
    solver="saga",
    l1_ratios=(l1_ratio,) if l1_ratio is not None else None,
    scoring="neg_log_loss",
    fit_intercept=True,
    max_iter=100_000,
    n_jobs=None,
    refit=True,
)
cvfit_all.fit(X, y)

print("\nRefit complete. Use `cvfit_all.predict_proba(scaled_X)[:, 1]` for probabilities.")
print(f"Locked alpha (l1_ratio): {alpha_star:.2f} | Locked classification threshold (τ): {thr_star:.2f}")
