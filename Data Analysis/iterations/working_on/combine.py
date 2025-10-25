#!/usr/bin/env python3
"""
Combined Mean-Reversion Likelihood Model
---------------------------------------
This model combines the best approaches from multiple implementations to predict
mean-reversion likelihood across multiple time horizons (1-day, 5-day, 20-day).

Key features:
1. Robust Excel data loading that handles various formats
2. Rich feature engineering:
   - Serial correlation features (AR(1), sign persistence)
   - Price momentum features at multiple horizons
   - Price z-scores vs moving averages
   - Volatility controls
3. Walk-forward cross-validation with proper time series splits
4. Multiple regularization approaches (ridge, elastic-net, lasso)
5. Probability threshold tuning with abstain bands
6. Performance evaluation via multiple metrics (AUC, F1, precision/recall)

The model outputs:
- OOS predictions for each horizon
- Summary statistics on model performance
- Visualizations of feature importance and model performance
- Selected hyperparameters for each time window

Requirements:
  pip install pandas numpy scikit-learn matplotlib seaborn openpyxl joblib
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional, Union

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path

from sklearn.linear_model import LogisticRegression, LogisticRegressionCV
from sklearn.metrics import (
    roc_auc_score, f1_score, precision_recall_fscore_support, 
    balanced_accuracy_score, confusion_matrix, roc_curve
)
from sklearn.model_selection import TimeSeriesSplit, GridSearchCV
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


# =========================
# Configuration
# =========================
from pathlib import Path

# =========================
# Config
# =========================
# THIS_DIR = Path(__file__).resolve().parent
# EXCEL_PATH: str = str(THIS_DIR / "MXUS_Data.xlsx")  # <— use path next to this script
# SHEET_NAME: str = "Returns"

@dataclass
class MeanReversionConfig:
    # File paths
    THIS_DIR = Path(__file__).resolve().parent
    excel_path: str = str(THIS_DIR / "MXUS_Data.xlsx") 
    sheet_name: str = "Returns"
    output_dir: str | Path = field(default="results")
    
    # Label construction
    label_threshold_abs_ret: float = field(default=0.005)  # 0.5% minimum move
    
    # Walk-forward split (≈252 trading days per calendar year)
    train_years: int = field(default=3)
    validation_years: int = field(default=1)
    
    # Model search
    alpha_grid: List[float] = field(default_factory=lambda: [0.0, 0.5, 1.0])  # 0=ridge, 0.5=elastic-net, 1=lasso
    inner_cv_folds: int = field(default=5)
    reg_strengths_C: List[float] = field(default_factory=lambda: list(np.logspace(-2, 1, 10)))  # Inverse regularization
    
    # Threshold sweep
    threshold_grid: List[float] = field(default_factory=lambda: list(np.round(np.arange(0.45, 0.76, 0.01), 2)))
    
    # Horizons (name, forward horizon days, momentum lookback days)
    horizons: List[Tuple[str, int, int]] = field(default_factory=lambda: [
        ("tomorrow", 1, 1),
        ("next_week", 5, 5),
        ("next_month", 20, 20)
    ])
    
    # Feature engineering windows
    ar_windows: List[int] = field(default_factory=lambda: [10, 20, 60])
    sign_persist_windows: List[int] = field(default_factory=lambda: [20, 60])
    vol_windows: List[int] = field(default_factory=lambda: [10, 20])
    z_score_windows: List[int] = field(default_factory=lambda: [20])
    
    # Reproducibility
    random_state: int = field(default=42)
    
    # Output control
    save_predictions: bool = field(default=True)
    create_plots: bool = field(default=True)
    save_models: bool = field(default=True)
    verbose: bool = field(default=True)


@dataclass
class WindowResult:
    """Results for a single validation window."""
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
    coverage: float  # Fraction of predictions not abstained (if using abstain bands)


# =========================
# Data I/O + Cleaning
# =========================

def load_returns_from_excel(excel_path: str | Path, sheet_name: str) -> pd.DataFrame:
    """
    Reads an Excel sheet with robust handling of various formats.
    Detects headers, converts dates, and ensures numeric returns.
    Returns a DataFrame with columns: Date, <stock_1>, <stock_2>, ...
    """
    try:
        # First try to read with automatic header detection
        raw = pd.read_excel(excel_path, sheet_name=sheet_name, header=None, engine="openpyxl")
        
        # Look for "Date" in the first column
        first_col_str = raw.iloc[:, 0].astype(str).str.strip()
        header_row_idx = np.where(first_col_str.values == "Date")[0]
        
        if len(header_row_idx) == 1:
            # Found "Date" as a header
            header_row = int(header_row_idx[0])
            header = raw.iloc[header_row].astype(str).tolist()
            data = raw.iloc[header_row + 1:].copy()
            data.columns = header
            
            # Excel serial dates to datetime
            data["Date"] = pd.to_datetime(
                pd.to_numeric(data["Date"], errors="coerce"), 
                unit="D", 
                origin="1899-12-30"
            )
            
        else:
            # Try standard pandas read with inferred header
            data = pd.read_excel(excel_path, sheet_name=sheet_name, engine="openpyxl")
            date_col = data.columns[0]
            data = data.rename(columns={date_col: "Date"})
            data["Date"] = pd.to_datetime(data["Date"])
        
        # Clean up the data
        data = data[data["Date"].notna()].reset_index(drop=True)
        
        # Ensure all non-date columns are numeric
        for col in [c for c in data.columns if c != "Date"]:
            data[col] = pd.to_numeric(data[col], errors="coerce")
            
        # Sort by date
        data = data.sort_values("Date").reset_index(drop=True)
        return data
        
    except Exception as e:
        print(f"Error loading data: {str(e)}")
        raise


# =========================
# Feature Engineering
# =========================

def compound_forward(series: pd.Series, horizon: int) -> pd.Series:
    """Compound return over the next `horizon` days from t."""
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


def build_feature_panel(returns_wide: pd.DataFrame, config: MeanReversionConfig) -> pd.DataFrame:
    """
    Build a panel of features for all stocks with both approaches:
    1. Serial correlation features (AR(1), sign persistence)
    2. Price momentum and technical features
    """
    tickers = [c for c in returns_wide.columns if c != "Date"]
    frames: List[pd.DataFrame] = []

    for ticker in tickers:
        # Skip columns with too many NaNs
        if returns_wide[ticker].isna().mean() > 0.3:  # Skip if >30% missing
            continue
            
        r = returns_wide[ticker].astype(float)
        
        # Base dataframe with date and ticker
        base = pd.DataFrame({"Date": returns_wide["Date"], "ticker": ticker})
        
        # --- Feature Engineering ---
        feats = {}
        
        # 1. Serial-correlation features
        for w in config.ar_windows:
            feats[f"ar1_corr_{w}d"] = rolling_ar1_corr(r, w)

        for w in config.sign_persist_windows:
            feats[f"sign_persist_{w}d"] = rolling_sign_persistence(r, w)
            
        # 2. Recent returns (direction/size controls)
        feats["ret_1d"] = r.shift(1)  # Prior day return
        feats["ret_5d"] = compound_past(r, 5)   # ~1 week
        feats["ret_20d"] = compound_past(r, 20)  # ~1 month
            
        # 3. Volatility
        for w in config.vol_windows:
            feats[f"vol_{w}d"] = r.rolling(w).std().shift(1)
            
        # 4. Price index and z-scores
        # Construct price series from returns
        px = (1.0 + r.fillna(0)).cumprod()
        
        # Z-scores vs moving averages
        for w in config.z_score_windows:
            ma = px.rolling(window=w, min_periods=w).mean()
            sd = px.rolling(window=w, min_periods=w).std()
            feats[f"z_ma_{w}d"] = ((px - ma) / sd).shift(1)  # Shift to avoid lookahead
        
        feat_df = pd.DataFrame(feats)

        # --- Forward returns for each horizon ---
        fwd = {f"fwd_{h}d": compound_forward(r, h) for _, h, _ in config.horizons}
        fwd_df = pd.DataFrame(fwd)

        # --- Recent momentum for each horizon ---
        mom = {f"mom_{k}d": compound_past(r, k) for _, _, k in config.horizons}
        mom_df = pd.DataFrame(mom)

        # Combine all features
        frames.append(pd.concat([base, feat_df, fwd_df, mom_df], axis=1))

    # Combine all stocks into one panel
    panel = pd.concat(frames, ignore_index=True)
    
    # Build labels for each horizon with both definitions
    for name, h, k in config.horizons:
        fwd_col = f"fwd_{h}d"
        mom_col = f"mom_{k}d"
        
        # --- Definition 1: Mean-reversion vs recent momentum ---
        # True if future return sign is opposite of momentum sign
        mask = panel[fwd_col].abs() > config.label_threshold_abs_ret
        sign_future = np.sign(panel[fwd_col])
        sign_mom = np.sign(panel[mom_col])
        
        # Mean reversion = future move is opposite to recent momentum
        # Only when momentum is non-zero and future move exceeds threshold
        label_mr = np.where(
            (mask) & (sign_mom != 0) & (sign_future == -sign_mom), 
            1,  # Mean reversion
            np.where((mask) & (sign_mom != 0), 0, np.nan)  # Trend continuation or abstain
        )
        panel[f"label_mr_{name}"] = label_mr
        
        # --- Definition 2: Simple up/down with threshold ---
        # 1=up, 0=down, but only when move exceeds threshold
        up_down = np.where(
            panel[fwd_col] > config.label_threshold_abs_ret, 
            1,  # Up
            np.where(panel[fwd_col] < -config.label_threshold_abs_ret, 0, np.nan)  # Down or abstain
        )
        panel[f"label_updown_{name}"] = up_down

    # Drop rows with missing features or labels
    feature_cols = [c for c in panel.columns 
                    if c not in ("Date", "ticker") 
                    and not c.startswith("fwd_") 
                    and not c.startswith("mom_") 
                    and not c.startswith("label_")]
    
    panel = panel.dropna(subset=feature_cols).reset_index(drop=True)
    return panel


# =========================
# Walk-Forward Split
# =========================

def generate_rolling_windows(dates: pd.Series, train_years: int, val_years: int):
    """
    Generate rolling walk-forward windows for time series cross-validation.
    Each window trains on train_years and validates on the next val_years.
    """
    unique_dates = pd.to_datetime(pd.Series(dates.unique())).sort_values().reset_index(drop=True)
    min_date = unique_dates.min()
    max_date = unique_dates.max()
    windows = []
    
    # Step through time creating windows
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


# =========================
# Modeling Utilities
# =========================

def build_logistic_regression_cv(alpha: float, config: MeanReversionConfig) -> Union[Pipeline, GridSearchCV]:
    """
    Create a logistic regression pipeline with appropriate regularization.
    Can return either a Pipeline or GridSearchCV object based on config.
    
    Parameters:
        alpha: 0.0=ridge (L2), 1.0=lasso (L1), in-between=elastic-net
    """
    # For elastic-net, we use saga solver and explicitly set l1_ratio=alpha
    if 0 < alpha < 1:
        pipe = Pipeline([
            ("scale", StandardScaler()),
            ("logit", LogisticRegression(
                penalty="elasticnet",
                solver="saga",
                l1_ratio=alpha,
                max_iter=10000,
                class_weight="balanced",
                random_state=config.random_state,
                n_jobs=-1
            ))
        ])
        param_grid = {"logit__C": config.reg_strengths_C}
        tscv = TimeSeriesSplit(n_splits=config.inner_cv_folds)
        return GridSearchCV(
            pipe, param_grid=param_grid, scoring="roc_auc", 
            cv=tscv, n_jobs=-1, refit=True, verbose=0
        )
    
    # For ridge, we can use the more efficient LogisticRegressionCV
    elif alpha == 0.0:
        return Pipeline([
            ("scale", StandardScaler()),
            ("logit_cv", LogisticRegressionCV(
                penalty="l2",
                solver="lbfgs",
                Cs=config.reg_strengths_C,
                cv=config.inner_cv_folds,
                scoring="neg_log_loss",
                max_iter=10000,
                n_jobs=-1,
                refit=True,
                class_weight="balanced",
                random_state=config.random_state
            ))
        ])
    
    # For lasso, we can use the LogisticRegressionCV as well
    elif alpha == 1.0:
        return Pipeline([
            ("scale", StandardScaler()),
            ("logit_cv", LogisticRegressionCV(
                penalty="l1",
                solver="saga",
                Cs=config.reg_strengths_C,
                cv=config.inner_cv_folds,
                scoring="neg_log_loss",
                max_iter=10000,
                n_jobs=-1,
                refit=True,
                class_weight="balanced",
                random_state=config.random_state
            ))
        ])


def choose_best_threshold(y_true: np.ndarray, y_prob: np.ndarray, 
                         thresholds: List[float], 
                         use_abstain_band: bool = False) -> Tuple[float, Dict]:
    """
    Choose the best classification threshold based on F1 score.
    
    Parameters:
        y_true: True labels (0/1)
        y_prob: Predicted probabilities
        thresholds: List of thresholds to try
        use_abstain_band: If True, use two-sided thresholds with abstention
        
    Returns:
        Tuple of (best_threshold, performance_metrics)
    """
    best_thr, best_metrics = thresholds[0], {"f1": -np.inf}
    
    for thr in thresholds:
        if use_abstain_band:
            # Two-sided with abstention (predict 1 if p>=thr, 0 if p<=1-thr)
            y_pred = np.full_like(y_true, fill_value=-1)  # -1 = abstain
            y_pred[y_prob >= thr] = 1
            y_pred[y_prob <= (1.0 - thr)] = 0
            
            # Calculate metrics only on non-abstained predictions
            mask = y_pred != -1
            if not np.any(mask):
                continue  # Skip if all abstained
                
            # Subset to non-abstained
            y_pred_covered = y_pred[mask]
            y_true_covered = y_true[mask]
            
            # Calculate metrics
            coverage = np.mean(mask)
            f1 = f1_score(y_true_covered, y_pred_covered, zero_division=0)
            bal_acc = balanced_accuracy_score(y_true_covered, y_pred_covered)
            pr, rc, _, _ = precision_recall_fscore_support(
                y_true_covered, y_pred_covered, 
                average="binary", zero_division=0
            )
            
            # Incorporate coverage into scoring (accuracy * coverage)
            score = f1 * coverage
        
        else:
            # Standard threshold (predict 1 if p>=thr)
            y_pred = (y_prob >= thr).astype(int)
            
            f1 = f1_score(y_true, y_pred, zero_division=0)
            bal_acc = balanced_accuracy_score(y_true, y_pred)
            pr, rc, _, _ = precision_recall_fscore_support(
                y_true, y_pred, average="binary", zero_division=0
            )
            coverage = 1.0  # No abstention
            score = f1  # Just use F1
        
        metrics = {
            "f1": f1, 
            "bal_acc": bal_acc, 
            "precision": pr, 
            "recall": rc,
            "coverage": coverage,
            "score": score
        }
        
        if score > best_metrics["score"]:
            best_thr, best_metrics = thr, metrics
            
    return best_thr, best_metrics


def run_for_horizon(panel: pd.DataFrame, horizon_name: str, 
                   config: MeanReversionConfig, 
                   label_type: str = "mr") -> Tuple[pd.DataFrame, List[WindowResult]]:
    """
    Run walk-forward validation for a specific horizon.
    
    Parameters:
        panel: Feature panel from build_feature_panel
        horizon_name: Name of the horizon (e.g., 'tomorrow')
        config: Configuration parameters
        label_type: Type of label to use ('mr' for mean-reversion or 'updown' for direction)
        
    Returns:
        Tuple of (predictions_df, window_results)
    """
    label_col = f"label_{label_type}_{horizon_name}"
    
    # Get features and prepare data
    feature_cols = [c for c in panel.columns 
                    if c not in ("Date", "ticker") 
                    and not c.startswith("fwd_") 
                    and not c.startswith("mom_") 
                    and not c.startswith("label_")]
    
    df = panel.dropna(subset=[label_col]).copy()
    X_all = df[feature_cols].values
    y_all = df[label_col].astype(int).values
    dates_all = df["Date"]

    # Generate time windows
    windows = generate_rolling_windows(dates_all, config.train_years, config.validation_years)

    results: List[WindowResult] = []
    all_val_preds = []
    
    # For each time window, fit and evaluate models
    for w_idx, (tr_start, tr_end, va_start, va_end) in enumerate(windows, start=1):
        # Get indices for train/val
        in_tr = (dates_all >= tr_start) & (dates_all <= tr_end)
        in_va = (dates_all >= va_start) & (dates_all <= va_end)
        X_tr, y_tr = X_all[in_tr], y_all[in_tr]
        X_va, y_va = X_all[in_va], y_all[in_va]

        # Ensure we have both classes in train and val
        if len(np.unique(y_tr)) < 2 or len(np.unique(y_va)) < 2:
            if config.verbose:
                print(f"  Window {w_idx}: Skipping due to class imbalance")
            continue

        # Try each alpha (regularization mix)
        best_auc = -np.inf
        best_alpha = None
        best_model = None
        best_C = None
        best_thr = None
        best_f1 = -np.inf
        best_metrics = None

        for alpha in config.alpha_grid:
            # Build and fit model
            model = build_logistic_regression_cv(alpha, config)
            model.fit(X_tr, y_tr)
            
            # Get predictions
            y_prob = model.predict_proba(X_va)[:, 1]
            auc = roc_auc_score(y_va, y_prob)
            
            # Choose best threshold
            use_abstain = label_type == "mr"  # Use abstain bands for mean-reversion
            thr, metrics = choose_best_threshold(
                y_va, y_prob, config.threshold_grid, use_abstain_band=use_abstain
            )
            
            # Update if better
            if auc > best_auc or (math.isclose(auc, best_auc) and metrics["score"] > best_metrics["score"] if best_metrics else 0):
                best_auc = auc
                best_alpha = alpha
                best_model = model
                
                # Extract C (regularization strength)
                if hasattr(model, "best_params_"):
                    best_C = float(model.best_params_["logit__C"])
                elif hasattr(model, "named_steps") and hasattr(model.named_steps["logit_cv"], "C_"):
                    best_C = float(model.named_steps["logit_cv"].C_[0])
                else:
                    best_C = 1.0
                    
                best_thr = thr
                best_metrics = metrics

        # Store predictions
        y_prob = best_model.predict_proba(X_va)[:, 1]
        
        # For mean-reversion, use two-sided threshold
        if label_type == "mr":
            y_pred = np.full_like(y_va, fill_value=-1)  # -1 = abstain
            y_pred[y_prob >= best_thr] = 1
            y_pred[y_prob <= (1.0 - best_thr)] = 0
            is_abstain = y_pred == -1
        else:
            # For up/down, use standard threshold
            y_pred = (y_prob >= best_thr).astype(int)
            is_abstain = np.zeros_like(y_pred, dtype=bool)
        
        all_val_preds.append(pd.DataFrame({
            "Date": df.loc[in_va, "Date"].values,
            "ticker": df.loc[in_va, "ticker"].values,
            "y_true": y_va,
            "y_prob": y_prob,
            "y_pred": y_pred,
            "abstained": is_abstain,
            "window": w_idx,
        }))

        # Store window result
        results.append(WindowResult(
            window_index=w_idx,
            horizon_name=horizon_name,
            train_start=tr_start, 
            train_end=tr_end,
            val_start=va_start, 
            val_end=va_end,
            alpha=float(best_alpha),
            chosen_C=float(best_C),
            chosen_threshold=float(best_thr),
            auc_val=float(best_auc),
            f1_val=float(best_metrics["f1"]),
            bal_acc_val=float(best_metrics["bal_acc"]),
            precision_val=float(best_metrics["precision"]),
            recall_val=float(best_metrics["recall"]),
            n_train=int(in_tr.sum()),
            n_val=int(in_va.sum()),
            coverage=float(best_metrics["coverage"])
        ))

    # Combine all predictions
    preds_df = pd.concat(all_val_preds, ignore_index=True) if all_val_preds else pd.DataFrame()
    return preds_df, results


# =========================
# Visualization Utilities
# =========================

def plot_model_performance(preds_df: pd.DataFrame, results: List[WindowResult], 
                          horizon_name: str, label_type: str, config: MeanReversionConfig):
    """Create performance visualizations for a model."""
    if preds_df.empty:
        return
        
    # Create output directory if it doesn't exist
    output_dir = Path(config.output_dir)
    output_dir.mkdir(exist_ok=True, parents=True)
        
    # 1. ROC curve
    plt.figure(figsize=(10, 6))
    
    # Only use non-abstained predictions if applicable
    if "abstained" in preds_df.columns:
        mask = ~preds_df["abstained"]
        y_true = preds_df.loc[mask, "y_true"]
        y_prob = preds_df.loc[mask, "y_prob"]
    else:
        y_true = preds_df["y_true"]
        y_prob = preds_df["y_prob"]
    
    if len(y_true) > 0:
        fpr, tpr, _ = roc_curve(y_true, y_prob)
        auc = roc_auc_score(y_true, y_prob)
        
        plt.plot(fpr, tpr, lw=2, label=f'ROC curve (AUC = {auc:.3f})')
        plt.plot([0, 1], [0, 1], 'k--', lw=1)
        plt.xlim([0.0, 1.0])
        plt.ylim([0.0, 1.05])
        plt.xlabel('False Positive Rate')
        plt.ylabel('True Positive Rate')
        plt.title(f'ROC Curve - {label_type.upper()} {horizon_name}')
        plt.legend(loc="lower right")
        plt.savefig(output_dir / f"{label_type}_{horizon_name}_roc_curve.png", dpi=300, bbox_inches='tight')
        plt.close()
    
    # 2. Performance by window
    if results:
        results_df = pd.DataFrame([r.__dict__ for r in results])
        
        plt.figure(figsize=(12, 6))
        x = np.arange(len(results))
        width = 0.2
        
        plt.bar(x - 1.5*width, results_df["auc_val"], width, label='AUC')
        plt.bar(x - 0.5*width, results_df["f1_val"], width, label='F1')
        plt.bar(x + 0.5*width, results_df["precision_val"], width, label='Precision')
        plt.bar(x + 1.5*width, results_df["recall_val"], width, label='Recall')
        
        plt.axhline(y=0.5, color='r', linestyle='--', alpha=0.3)
        plt.xlabel('Window')
        plt.ylabel('Score')
        plt.title(f'Performance by Window - {label_type.upper()} {horizon_name}')
        plt.xticks(x, [f"{i+1}" for i in range(len(results))])
        plt.legend()
        plt.tight_layout()
        plt.savefig(output_dir / f"{label_type}_{horizon_name}_window_performance.png", dpi=300, bbox_inches='tight')
        plt.close()
        
        # 3. Model choices by window
        plt.figure(figsize=(12, 6))
        
        plt.subplot(2, 1, 1)
        plt.bar(x, results_df["alpha"], label='Alpha')
        plt.bar(x, results_df["chosen_C"], bottom=results_df["alpha"], label='C')
        plt.ylabel('Parameter Value')
        plt.title(f'Model Parameters by Window - {label_type.upper()} {horizon_name}')
        plt.legend()
        
        plt.subplot(2, 1, 2)
        plt.plot(x, results_df["chosen_threshold"], 'o-', label='Threshold')
        plt.plot(x, results_df["coverage"], 'o--', label='Coverage')
        plt.xlabel('Window')
        plt.ylabel('Value')
        plt.legend()
        
        plt.tight_layout()
        plt.savefig(output_dir / f"{label_type}_{horizon_name}_model_params.png", dpi=300, bbox_inches='tight')
        plt.close()


# =========================
# Main Execution
# =========================

def main():
    """Main execution function."""
    config = MeanReversionConfig()
    
    print(f"=== Combined Mean-Reversion Likelihood Model ===")
    print(f"Reading data from: {config.excel_path} [sheet={config.sheet_name}]")
    
    # 1. Load and prepare data
    try:
        returns_wide = load_returns_from_excel(config.excel_path, config.sheet_name)
        print(f"Data loaded successfully: {len(returns_wide):,} dates, {len(returns_wide.columns)-1} stocks")
        
        # Convert 'Date' to 'Date' if it's not already
        if "date" in returns_wide.columns and "Date" not in returns_wide.columns:
            returns_wide = returns_wide.rename(columns={"date": "Date"})
            
        # 2. Build feature panel
        panel = build_feature_panel(returns_wide, config)
        print(f"Feature panel created: {panel.shape[0]:,} rows, {panel.shape[1]} columns")
        print(f"Date range: {panel['Date'].min().date()} to {panel['Date'].max().date()}")
        
        # 3. For each horizon, run both model types
        for horizon_name, _, _ in config.horizons:
            # First run mean-reversion model
            print(f"\n--- Horizon: {horizon_name} (Mean-Reversion) ---")
            mr_preds, mr_results = run_for_horizon(panel, horizon_name, config, label_type="mr")
            
            if not mr_preds.empty:
                # Get non-abstained predictions
                active_preds = mr_preds[~mr_preds["abstained"]]
                overall_metrics = {}
                
                if not active_preds.empty:
                    # Calculate overall metrics
                    overall_metrics["auc"] = roc_auc_score(active_preds["y_true"], active_preds["y_prob"])
                    overall_metrics["f1"] = f1_score(active_preds["y_true"], active_preds["y_pred"])
                    pr, rc, _, _ = precision_recall_fscore_support(
                        active_preds["y_true"], active_preds["y_pred"], 
                        average="binary", zero_division=0
                    )
                    overall_metrics["precision"] = pr
                    overall_metrics["recall"] = rc
                    overall_metrics["coverage"] = 1 - mr_preds["abstained"].mean()
                
                    print(f"  AUC={overall_metrics['auc']:.4f} | F1={overall_metrics['f1']:.4f} | "
                          f"Precision={overall_metrics['precision']:.4f} | Recall={overall_metrics['recall']:.4f} | "
                          f"Coverage={overall_metrics['coverage']:.2f}")
                
                # Print window results
                print("  Per-window choices:")
                for r in mr_results:
                    print(f"    W{r.window_index}  Train {r.train_start.date()}→{r.train_end.date()}  "
                          f"Val {r.val_start.date()}→{r.val_end.date()}  "
                          f"alpha={r.alpha:.1f} C={r.chosen_C:.4f} thr={r.chosen_threshold:.2f}  "
                          f"AUC={r.auc_val:.4f} F1={r.f1_val:.4f}  "
                          f"n_train={r.n_train:,} n_val={r.n_val:,} cov={r.coverage:.2f}")
                
                # Save results
                if config.save_predictions:
                    # Create output directory
                    output_dir = Path(config.output_dir)
                    output_dir.mkdir(exist_ok=True, parents=True)
                    
                    # Save prediction files
                    preds_path = output_dir / f"mr_{horizon_name}_predictions.csv"
                    wins_path = output_dir / f"mr_{horizon_name}_results.csv"
                    
                    mr_preds.to_csv(preds_path, index=False)
                    pd.DataFrame([r.__dict__ for r in mr_results]).to_csv(wins_path, index=False)
                    print(f"  Saved → {preds_path.name} and {wins_path.name}")
                
                # Create visualizations
                if config.create_plots:
                    plot_model_performance(mr_preds, mr_results, horizon_name, "mr", config)
            else:
                print("  No validation predictions for this horizon (class imbalance or date coverage).")
                
            # Optional: Run up/down directional model (uncomment if needed)
            """
            print(f"\n--- Horizon: {horizon_name} (Direction) ---")
            updown_preds, updown_results = run_for_horizon(panel, horizon_name, config, label_type="updown")
            
            if not updown_preds.empty:
                # Similar processing as above for the up/down model
                # ...
            """
        
        print("\nModel runs completed successfully.")
        
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()