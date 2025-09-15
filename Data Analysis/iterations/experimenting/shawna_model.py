"""
Walk-forward stock classifier (ridge / elastic net / lasso logistic regression)
-----------------------------------------------------------------------------
Reads an Excel of daily returns, builds intuitive technical features,
does walk-forward cross-validation with an inner CV for regularization,
sweeps two-sided probability thresholds (with an abstain band),
selects (alpha, threshold) by accuracy*coverage, and refits on all data.

Requirements:
  pip install pandas numpy scikit-learn openpyxl
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict, Tuple

import numpy as np
import pandas as pd
from pathlib import Path

from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegressionCV
from sklearn.metrics import roc_auc_score


# =========================
# Configuration
# =========================

@dataclass
class ExperimentConfig:
    excel_path: str | Path = "MXUS_Data.xlsx"
    sheet_name: str = "Returns"

    # Label construction
    forward_horizon_days: int = 5                # fwd_h
    label_threshold_abs_ret: float = 0.005       # thr_label (0.5%)

    # Walk-forward split (≈252 trading days per calendar year)
    train_years: int = 3                         # years_tr
    validation_years: int = 1                    # years_val

    # Model search
    alpha_grid: List[float] = (0.0, 0.5, 1.0)    # 0=ridge, 0.5=elastic-net, 1=lasso
    inner_cv_folds: int = 5
    C_grid: np.ndarray = np.logspace(-4, 4, 30)  # inverse regularization strengths

    # Threshold sweep (two-sided with abstain zone)
    threshold_grid: np.ndarray = np.round(np.arange(0.55, 0.85 + 1e-9, 0.01), 2)

    # Reproducibility
    random_state: int = 42


# =========================
# Data I/O + Cleaning
# =========================

def load_returns_from_excel(excel_path: str | Path, sheet_name: str) -> pd.DataFrame:
    """
    Reads an Excel sheet that contains a header row where the first cell equals 'Date'.
    Converts Excel serial dates to pandas datetime. Non-numeric cells become NaN.
    Returns a DataFrame with columns: Date, <stock_1>, <stock_2>, ...
    """
    raw = pd.read_excel(excel_path, sheet_name=sheet_name, header=None, engine="openpyxl")
    first_col_str = raw.iloc[:, 0].astype(str).str.strip()
    header_row_idx = np.where(first_col_str.values == "Date")[0]
    if len(header_row_idx) != 1:
        raise ValueError("Could not uniquely locate the header row whose first cell is 'Date'.")
    header_row = int(header_row_idx[0])

    header = raw.iloc[header_row].astype(str).tolist()
    data = raw.iloc[header_row + 1 :].copy()
    data.columns = header

    # Excel serial (Windows origin 1899-12-30) -> datetime
    data["Date"] = pd.to_datetime(pd.to_numeric(data["Date"], errors="coerce"), unit="D", origin="1899-12-30")
    data = data[data["Date"].notna()].reset_index(drop=True)

    for col in [c for c in data.columns if c != "Date"]:
        data[col] = pd.to_numeric(data[col], errors="coerce")

    return data


# =========================
# Feature Engineering
# =========================

def build_feature_table(
    returns_wide: pd.DataFrame,
    forward_horizon_days: int,
    label_threshold_abs_ret: float,
) -> pd.DataFrame:
    """
    Transforms wide returns into a long feature table with:
      - ret_lag1: previous day return
      - ret_5, ret_20: price momentum over 5/20 days (from cumulative price index)
      - vol_20: 20-day rolling volatility of returns
      - z_ma_20: price z-score vs 20-day moving average
      - y: binary label (1 up / 0 down) only when |future return| > threshold, else NaN (abstain)
    Returns a DataFrame with columns:
      Date, stock, y, ret_lag1, ret_5, ret_20, vol_20, z_ma_20
    """
    long_df = returns_wide.melt(id_vars="Date", var_name="stock", value_name="ret") \
                          .sort_values(["stock", "Date"]).reset_index(drop=True)

    # Price index (fill NaNs as 0 for compounding)
    long_df["ret_filled"] = long_df["ret"].fillna(0.0)
    long_df["px"] = (1.0 + long_df["ret_filled"]).groupby(long_df["stock"]).cumprod()

    # Simple lags and momentums
    long_df["ret_lag1"] = long_df.groupby("stock")["ret"].shift(1)
    long_df["ret_5"] = long_df["px"] / long_df.groupby("stock")["px"].shift(5) - 1.0
    long_df["ret_20"] = long_df["px"] / long_df.groupby("stock")["px"].shift(20) - 1.0

    # Rolling mean / std on price for z-score
    rolling_ma_20 = long_df.groupby("stock")["px"].rolling(window=20, min_periods=20).mean().reset_index(level=0, drop=True)
    rolling_sd_20 = long_df.groupby("stock")["px"].rolling(window=20, min_periods=20).std().reset_index(level=0, drop=True)
    long_df["z_ma_20"] = (long_df["px"] - rolling_ma_20) / rolling_sd_20

    # Rolling volatility of returns (20-day std)
    long_df["vol_20"] = long_df.groupby("stock")["ret"].rolling(window=20, min_periods=20).std().reset_index(level=0, drop=True)

    # Future return label from price
    future_px = long_df.groupby("stock")["px"].shift(-forward_horizon_days)
    long_df["fwd_ret"] = future_px / long_df["px"] - 1.0

    # Thresholded label: learn only when |future move| is meaningful
    label = pd.Series(np.nan, index=long_df.index)
    label[long_df["fwd_ret"] > +label_threshold_abs_ret] = 1
    label[long_df["fwd_ret"] < -label_threshold_abs_ret] = 0
    long_df["y"] = label.astype("Int64")  # pandas nullable integer (allows NaN)

    # Keep complete rows (no NaNs in features or label)
    feature_cols = ["ret_lag1", "ret_5", "ret_20", "vol_20", "z_ma_20"]
    feature_table = long_df[["Date", "stock", "y"] + feature_cols].dropna().copy()
    feature_table = feature_table[feature_table["y"].notna()].reset_index(drop=True)

    return feature_table


# =========================
# Walk-Forward Split
# =========================

@dataclass
class WalkForwardFold:
    train_dates: np.ndarray
    validation_dates: np.ndarray

def make_walk_forward_folds(unique_dates: np.ndarray, train_years: int, validation_years: int) -> List[WalkForwardFold]:
    """
    Creates walk-forward folds over unique dates.
    Each fold trains on `train_years`*252 days and validates on the next `validation_years`*252 days.
    """
    train_days = train_years * 252
    validation_days = validation_years * 252
    date_count = len(unique_dates)

    start_indices = np.arange(0, date_count - (train_days + validation_days) + 1, validation_days, dtype=int)
    folds: List[WalkForwardFold] = []
    for start in start_indices:
        train_idx = np.arange(start, start + train_days, dtype=int)
        val_idx = np.arange(start + train_days, start + train_days + validation_days, dtype=int)
        folds.append(
            WalkForwardFold(
                train_dates=unique_dates[train_idx],
                validation_dates=unique_dates[val_idx],
            )
        )
    return folds


# =========================
# Modeling utilities
# =========================

def build_logistic_regression_cv(alpha: float, config: ExperimentConfig) -> Pipeline:
    """
    Maps glmnet alpha to scikit-learn:
      alpha = 0.0 → ridge (L2, solver='lbfgs')
      alpha = 1.0 → lasso (L1, solver='saga')
      0 < alpha < 1 → elastic-net (solver='saga', l1_ratio=alpha)
    Wrapped in a pipeline with StandardScaler to match glmnet standardization.
    """
    if alpha == 0.0:
        lr = LogisticRegressionCV(
            penalty="l2",
            solver="lbfgs",
            Cs=config.C_grid,
            cv=config.inner_cv_folds,
            scoring="neg_log_loss",
            max_iter=100_000,
            n_jobs=-1,
            refit=True,
            random_state=config.random_state,
        )
    elif alpha == 1.0:
        lr = LogisticRegressionCV(
            penalty="l1",
            solver="saga",
            Cs=config.C_grid,
            cv=config.inner_cv_folds,
            scoring="neg_log_loss",
            max_iter=100_000,
            n_jobs=-1,
            refit=True,
            random_state=config.random_state,
        )
    else:
        lr = LogisticRegressionCV(
            penalty="elasticnet",
            solver="saga",
            l1_ratios=[alpha],
            Cs=config.C_grid,
            cv=config.inner_cv_folds,
            scoring="neg_log_loss",
            max_iter=100_000,
            n_jobs=-1,
            refit=True,
            random_state=config.random_state,
        )

    return Pipeline([
        ("standardize", StandardScaler(with_mean=True, with_std=True)),
        ("logit_cv", lr),
    ])


def auc_safe(probabilities: np.ndarray, labels: np.ndarray) -> float:
    """
    Safe AUC: returns 0.5 if degenerate (single class, constant probabilities, etc.).
    Matches the robustness of the R version.
    """
    if probabilities is None or labels is None:
        return 0.5
    probabilities = np.asarray(probabilities, dtype=float)
    labels = np.asarray(labels, dtype=int)

    valid_mask = np.isfinite(probabilities) & np.isin(labels, [0, 1])
    probabilities = probabilities[valid_mask]
    labels = labels[valid_mask]

    if probabilities.size == 0 or np.unique(labels).size < 2 or np.allclose(probabilities.std(ddof=0), 0.0):
        return 0.5

    try:
        return float(roc_auc_score(labels, probabilities))
    except Exception:
        return 0.5


# =========================
# Training / Validation Loop
# =========================

def run_walk_forward_cv(
    feature_table: pd.DataFrame,
    alpha_grid: List[float],
    threshold_grid: np.ndarray,
    config: ExperimentConfig,
) -> Tuple[pd.DataFrame, Dict[str, np.ndarray]]:
    """
    Runs walk-forward CV for each alpha, collects out-of-sample probabilities,
    evaluates thresholds with an abstain band, and returns:
      - summary_table: mean accuracy, AUC, coverage, and score (accuracy*coverage) by alpha & threshold
      - oos_probabilities_by_alpha: dict of alpha → vector of OOS probabilities aligned to feature_table rows
    """
    feature_columns = ["ret_lag1", "ret_5", "ret_20", "vol_20", "z_ma_20"]
    X_frame = feature_table[feature_columns]
    y_vector = feature_table["y"].astype(int).values
    date_array = pd.to_datetime(feature_table["Date"]).values

    unique_dates = np.sort(np.unique(date_array))
    folds = make_walk_forward_folds(unique_dates, config.train_years, config.validation_years)

    # 1) Collect OOS probabilities per alpha
    oos_probabilities_by_alpha: Dict[str, np.ndarray] = {}

    for alpha in alpha_grid:
        probabilities_all_rows = np.full(len(feature_table), np.nan, dtype=float)

        for fold_idx, fold in enumerate(folds, start=1):
            train_mask = np.isin(date_array, fold.train_dates)
            val_mask = np.isin(date_array, fold.validation_dates)

            train_idx = np.where(train_mask)[0]
            val_idx = np.where(val_mask)[0]

            # Need both classes in training
            if np.unique(y_vector[train_idx]).size < 2:
                continue

            model = build_logistic_regression_cv(alpha, config)
            model.fit(X_frame.iloc[train_idx], y_vector[train_idx])

            proba_val = model.predict_proba(X_frame.iloc[val_idx])[:, 1]
            probabilities_all_rows[val_idx] = proba_val

        oos_probabilities_by_alpha[str(alpha)] = probabilities_all_rows

    # 2) Evaluate thresholds (two-sided with abstain)
    evaluation_records: List[Dict] = []

    for alpha_str, all_probabilities in oos_probabilities_by_alpha.items():
        alpha_value = float(alpha_str)

        for fold_idx, fold in enumerate(folds, start=1):
            val_mask = np.isin(date_array, fold.validation_dates)
            val_idx = np.where(val_mask)[0]

            probs_slice = all_probabilities[val_idx]
            labels_slice = y_vector[val_idx]

            keep = np.isfinite(probs_slice) & np.isin(labels_slice, [0, 1])
            if not np.any(keep):
                continue

            y_keep = labels_slice[keep]
            p_keep = probs_slice[keep]
            fold_auc = auc_safe(p_keep, y_keep)

            for threshold in threshold_grid:
                # Decision rule:
                #  - predict 1 if p >= threshold
                #  - predict 0 if p <= 1 - threshold
                #  - otherwise abstain (no prediction)
                predictions = np.full_like(y_keep, fill_value=-1, dtype=int)  # -1 = abstain
                predictions[p_keep >= threshold] = 1
                predictions[p_keep <= (1.0 - threshold)] = 0

                is_covered = predictions != -1
                coverage = float(np.mean(is_covered))
                accuracy = float(np.mean(predictions[is_covered] == y_keep[is_covered])) if is_covered.any() else np.nan

                evaluation_records.append(
                    dict(
                        alpha=alpha_value,
                        fold=fold_idx,
                        threshold=float(threshold),
                        accuracy=accuracy,
                        auc=fold_auc,
                        coverage=coverage,
                    )
                )

    evaluation_table = pd.DataFrame.from_records(evaluation_records)
    if evaluation_table.empty:
        raise RuntimeError("No validation results—check your data and label threshold settings.")

    summary_table = (
        evaluation_table.groupby(["alpha", "threshold"], as_index=False)
        .agg(
            mean_accuracy=("accuracy", "mean"),
            mean_auc=("auc", "mean"),
            mean_coverage=("coverage", "mean"),
            folds_evaluated=("fold", "count"),
        )
    )
    summary_table["score_accuracy_x_coverage"] = summary_table["mean_accuracy"] * summary_table["mean_coverage"]
    summary_table = summary_table.sort_values(
        ["score_accuracy_x_coverage", "mean_accuracy"], ascending=False
    ).reset_index(drop=True)

    return summary_table, oos_probabilities_by_alpha


# =========================
# Final refit
# =========================

def refit_final_model(
    feature_table: pd.DataFrame, chosen_alpha: float, config: ExperimentConfig
) -> Pipeline:
    """
    Refit the chosen logistic model (by alpha) on all rows (no walk-forward split).
    Returns a sklearn Pipeline (StandardScaler → LogisticRegressionCV).
    """
    feature_columns = ["ret_lag1", "ret_5", "ret_20", "vol_20", "z_ma_20"]
    X_frame = feature_table[feature_columns]
    y_vector = feature_table["y"].astype(int).values

    model = build_logistic_regression_cv(chosen_alpha, config)
    model.fit(X_frame, y_vector)
    return model


# =========================
# Script entry point
# =========================

def main() -> None:
    config = ExperimentConfig()

    # 1) Load data and build features
    returns_wide = load_returns_from_excel(config.excel_path, config.sheet_name)
    feature_table = build_feature_table(
        returns_wide=returns_wide,
        forward_horizon_days=config.forward_horizon_days,
        label_threshold_abs_ret=config.label_threshold_abs_ret,
    )

    # 2) Walk-forward CV over alpha + threshold grid
    summary_table, _ = run_walk_forward_cv(
        feature_table=feature_table,
        alpha_grid=list(config.alpha_grid),
        threshold_grid=config.threshold_grid,
        config=config,
    )

    # 3) Report top settings
    print("\nTop hyperparameter / threshold combos (by accuracy × coverage):")
    print(summary_table.head(12).to_string(index=False))

    best_row = summary_table.iloc[0]
    chosen_alpha = float(best_row["alpha"])
    chosen_threshold = float(best_row["threshold"])
    print(
        f"\nBest choice → alpha={chosen_alpha:.2f}, threshold={chosen_threshold:.2f} "
        f"| mean_acc={best_row['mean_accuracy']:.3f}, "
        f"mean_AUC={best_row['mean_auc']:.3f}, "
        f"mean_cov={best_row['mean_coverage']:.2f}"
    )

    # 4) Refit on all data with chosen alpha
    final_model = refit_final_model(feature_table, chosen_alpha, config)
    print("\nRefit complete. Use:  final_model.predict_proba(X)[:, 1]  for probabilities.")
    print(f"Chosen classification threshold (two-sided with abstain band): {chosen_threshold:.2f}")

    # (Optional) You could persist the model with joblib if you like:
    # from joblib import dump
    # dump(final_model, "final_logistic_model.joblib")


if __name__ == "__main__":
    main()
