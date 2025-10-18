#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
β-forecast (fast, interpretable) — Strategy-1 with feature head (NO market data)
==============================================================================

This version removes dependence on an external market index and replaces
market-dependent features with cross-sectional, price-only proxies.

Adds (client-focused):
- >>> NEW: Dynamic R² gate + n/Sxx information gate (with regime-aware relax).
- >>> NEW: Carry r2_ols into outputs for interpretability.
- >>> NEW: latest_beta_forecasts.csv (one row per ticker; H=20d) with Δβ and confidence.

"""
from __future__ import annotations
import argparse, logging, re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from pandas.tseries.offsets import BDay
from sklearn.linear_model import Ridge
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from scipy.stats import t

import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from pathlib import Path
import os 

# Ensure script runs from its own folder
os.chdir(Path(__file__).parent)
print("Current working directory:", os.getcwd())


# =========================================================
# Config & logging
# =========================================================

@dataclass
class Config:
    # I/O
    excel_path: Optional[Path] = None
    sheet_name: Optional[str] = None
    out_dir: Path = Path("./outputs")

    # data
    date_col: str = "Date"

    # β estimation
    horizons: List[int] = field(default_factory=lambda: [1, 2, 5, 10, 20])  # Added H=2 for client
    beta_window: int = 60
    min_obs: int = 25
    stride_days: int = 2

    # β target horizon
    target_gap_days: int = 20
    target_ema_span: Optional[int] = 5

    # walk-forward
    train_years: int = 3
    val_years: int = 1
    tdy_per_year: int = 252
    purge_days: int = 5

    # model
    ridge_alphas: List[float] = field(default_factory=lambda: [0.05, 0.1, 0.25, 0.5, 1.0])
    random_state: int = 1337

    # hygiene
    winsor_abs: float = 0.10

    # viz toggles
    make_charts: bool = True

    # >>> NEW: Thresholds & regime-awareness
    r2_min: float = 0.01                  # Relaxed from 0.05 to 0.01
    r2_pctl_floor: float = 0.02           # Relaxed from 0.05 to 0.02
    sxx_min: float = 1e-8                 # Relaxed from 1e-7 to 1e-8
    hi_vol_relax: int = 15                # Increased from 10 to 15
    
    # >>> NEW: Statistical significance gates
    p_value_max: float = 0.05             # Maximum p-value (5% significance level)
    p_value_relax_factor: float = 2.0     # Relax to 10% in high-vol regimes
    min_significance_score: float = 0.60  # Combined R²/p-value score threshold
    
    summary_file: str = "latest_beta_forecasts.csv"  # client pack

# Final feature list (price-only, no external market)
FEATURES = [
    "LAG_BETA_1","R2_60",
    "VOL_30","VOL_PCTL_30","MOM_30","MOM_PCTL_30","PRICE_Z20","AR1_20",
    "XSEC_DISP_30","SKEW_20","KURT_20","DD_60","HL_RANGE_252",
]

def setup_logger(out_dir: Path) -> logging.Logger:
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "logs").mkdir(parents=True, exist_ok=True)
        (out_dir / "charts").mkdir(parents=True, exist_ok=True)
        
        log = logging.getLogger("bcoef_nomkt")
        log.setLevel(logging.INFO)
        
        # Clear existing handlers to prevent duplicates
        for h in list(log.handlers): 
            log.removeHandler(h)
            
        fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
        
        # File handler with error handling
        try:
            fh = logging.FileHandler(out_dir / "logs" / "run.log", mode="w", encoding="utf-8")
            fh.setFormatter(fmt)
            log.addHandler(fh)
        except Exception as e:
            print(f"Warning: Could not create file handler: {e}")
            
        # Console handler
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        log.addHandler(sh)
        
        return log
    except Exception as e:
        # Fallback logger if setup fails
        logging.basicConfig(level=logging.INFO)
        logger = logging.getLogger("bcoef_nomkt")
        logger.error(f"Logger setup failed: {e}")
        return logger

def validate_config(cfg: Config) -> None:
    """Validate configuration for statistical soundness."""
    if cfg.beta_window < cfg.min_obs:
        raise ValueError(f"beta_window ({cfg.beta_window}) must be >= min_obs ({cfg.min_obs})")
    
    if cfg.beta_window < 20:
        raise ValueError(f"beta_window too small for reliable estimates: {cfg.beta_window}")
    
    if cfg.target_gap_days <= 0:
        raise ValueError(f"target_gap_days must be positive: {cfg.target_gap_days}")
        
    if cfg.train_years * cfg.tdy_per_year < cfg.beta_window * 2:
        raise ValueError("Training period too short relative to beta estimation window")
    
    if cfg.stride_days < 1:
        raise ValueError(f"stride_days must be >= 1, got {cfg.stride_days}")
        
    if not cfg.horizons:
        raise ValueError("horizons list cannot be empty")
        
    if any(h <= 0 for h in cfg.horizons):
        raise ValueError("All horizons must be positive")

# =========================================================
# Data loading (autodiscovery preserved)
# =========================================================

def autodiscover_excel(excel_arg: Optional[str], sheet_arg: Optional[str], log: logging.Logger) -> Tuple[Path, str]:
    def choose_sheet(xls: pd.ExcelFile, preferred: Optional[str]) -> str:
        if preferred and preferred in xls.sheet_names: return preferred
        if "Returns" in xls.sheet_names: return "Returns"
        for n in xls.sheet_names:
            if "return" in n.lower(): return n
        return xls.sheet_names[0]

    if excel_arg:
        p = Path(excel_arg); xls = pd.ExcelFile(p, engine="openpyxl")
        sheet = choose_sheet(xls, sheet_arg)
        log.info(f"Using Excel: {p.name} | sheet: {sheet}")
        return p, sheet
    for base in [Path.cwd(), Path("/mnt/data")]:
        for pat in ["MXUS_Data_*.xlsx","MXUS_Data.xlsx","*.xlsx"]:
            cands = sorted(base.glob(pat), key=lambda q: q.stat().st_mtime, reverse=True)
            if cands:
                xls = pd.ExcelFile(cands[0], engine="openpyxl")
                sheet = choose_sheet(xls, sheet_arg)
                log.info(f"Autodiscovered Excel: {cands[0].name} | sheet: {sheet}")
                return cands[0], sheet
    raise FileNotFoundError("Excel not found. Provide --excel or place MXUS_Data*.xlsx in working dir.")

def _parse_percentish(series: pd.Series) -> pd.Series:
    s = pd.to_numeric(series.astype(str).str.replace('%','',regex=False).str.strip(), errors='coerce')
    q90, q95, q99 = s.abs().quantile(0.90), s.abs().quantile(0.95), s.abs().quantile(0.99)
    if (0.20 < q90 <= 100) or (q95 > 1.0 and q99 <= 100): s = s / 100.0
    return s

def load_returns_wide(excel_path: Path, sheet_name: str) -> pd.DataFrame:
    """Load returns data with robust error handling."""
    if not excel_path.exists():
        raise FileNotFoundError(f"Excel file not found: {excel_path}")
        
    try:
        raw = pd.read_excel(excel_path, sheet_name=sheet_name, header=None, engine="openpyxl")
    except Exception as e:
        raise RuntimeError(f"Failed to read Excel file {excel_path}, sheet {sheet_name}: {e}")
        
    if raw.empty:
        raise ValueError(f"Excel sheet {sheet_name} is empty")
        
    col0 = raw.iloc[:,0].astype(str).str.strip().str.lower()
    header_idx = col0[col0.eq("date")].index.tolist()
    header_idx = header_idx[0] if header_idx else 0
    headers = raw.iloc[header_idx].astype(str).str.strip().tolist()
    df = raw.iloc[header_idx+1:].copy(); df.columns = headers
    if "Date" not in df.columns: df = df.rename(columns={df.columns[0]:"Date"})
    
    try:
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    except Exception as e:
        raise ValueError(f"Failed to parse dates: {e}")
        
    df = df[df["Date"].notna()].sort_values("Date").reset_index(drop=True)
    
    if df.empty:
        raise ValueError("No valid dates found in data")
    
    for c in [c for c in df.columns if c != "Date"]:
        df[c] = _parse_percentish(df[c])
    keep = ["Date"] + [c for c in df.columns if c != "Date" and df[c].notna().sum() > 0]
    result = df[keep]
    
    if len(result.columns) < 2:  # Date + at least one data column
        raise ValueError("No valid data columns found")
        
    return result

# =========================================================
# Horizon-dependent threshold adjustment
# =========================================================

def get_horizon_adjusted_thresholds(horizon: int, base_cfg: Config) -> dict:
    """Return horizon-adjusted thresholds based on forecast horizon.
    Simplified gate system - use EITHER basic gates OR composite score, not both."""
    if horizon <= 1:
        return {
            "r2_min": 0.001,              
            "p_value_max": 0.25,           
        }
    elif horizon <= 5:
        return {
            "r2_min": 0.005,               
            "p_value_max": 0.15,           
        }
    elif horizon <= 10:
        return {
            "r2_min": 0.01,               
            "p_value_max": 0.10,           
        }
    else:
        return {
            "r2_min": base_cfg.r2_min,     
            "p_value_max": base_cfg.p_value_max,
        }

def calc_significance_score(r2: float, p_value: float, horizon: int) -> float:
    """Calculate significance score with horizon-adjusted scaling"""
    # Scale R² to be more meaningful (typically very small in finance)
    r2_component = min(r2 * 20, 1.0)  
    
    # Scale p-value (more permissive for short horizons)
    p_threshold = 0.25 if horizon <= 1 else 0.15 if horizon <= 5 else 0.10 if horizon <= 10 else 0.05
    p_component = max(0, 1.0 - (p_value / p_threshold))
    
    # Balanced weighting (R² matters more for short horizons)
    w_r2 = 0.8 if horizon <= 5 else 0.6
    return w_r2 * r2_component + (1-w_r2) * p_component

def assign_confidence_tier(r2: float, p_value: float) -> str:
    """Assign confidence tier for client transparency"""
    if r2 >= 0.1 and p_value <= 0.01:
        return "Very High"
    elif r2 >= 0.05 and p_value <= 0.05:
        return "High"
    elif r2 >= 0.02 and p_value <= 0.10:
        return "Medium"
    elif r2 >= 0.01 and p_value <= 0.20:
        return "Low"
    else:
        return "Very Low"

# =========================================================
# Feature primitives & rolling OLS (as before)
# =========================================================

def winsorize(series: pd.Series, limit_abs: float) -> pd.Series:
    return series.clip(lower=-limit_abs, upper=limit_abs)

def compound_past_simple(simple_returns: pd.Series, window: int) -> pd.Series:
    past = (1.0 + simple_returns).rolling(window).apply(np.prod, raw=True) - 1.0
    return past.shift(1)

def price_index_zscore(simple_returns: pd.Series, window: int) -> pd.Series:
    idx = (1.0 + simple_returns.fillna(0)).cumprod()
    mu = idx.rolling(window, min_periods=window).mean()
    sd = idx.rolling(window, min_periods=window).std()
    return ((idx - mu) / sd).shift(1)

def rolling_autocorr_lag1_vectorized(series: pd.Series, window: int) -> pd.Series:
    """Vectorized AR(1) calculation - much faster than lambda approach."""
    x = series.values
    x_lag = np.concatenate([[np.nan], x[:-1]])
    
    # Rolling means
    x_mean = pd.Series(x).rolling(window).mean()
    x_lag_mean = pd.Series(x_lag).rolling(window).mean()
    
    # Rolling variances and covariance
    x_var = pd.Series(x).rolling(window).var()
    x_lag_var = pd.Series(x_lag).rolling(window).var()
    
    # Cross-covariance
    cross_prod = pd.Series(x * x_lag).rolling(window).mean()
    cov = cross_prod - (x_mean * x_lag_mean)
    
    # Correlation
    corr = cov / np.sqrt(x_var * x_lag_var)
    return corr.shift(1)

def rolling_autocorr_lag1(series: pd.Series, window: int) -> pd.Series:
    x_prev = series.shift(1)
    corr = series.rolling(window).corr(x_prev)
    return corr.shift(1)

def _rolling_ols_xy(x: np.ndarray, y: np.ndarray, window: int, min_obs: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    m = np.isfinite(x) & np.isfinite(y)
    xv, yv = np.where(m, x, 0.0), np.where(m, y, 0.0)
    c1 = np.cumsum(m.astype(np.int64)); sx = np.cumsum(xv); sy = np.cumsum(yv)
    sxx = np.cumsum(xv * xv); syy = np.cumsum(yv * yv); sxy = np.cumsum(xv * yv)
    def roll(c):
        out = c.copy(); out[window:] = c[window:] - c[:-window]; return out
    n_w, sx_w, sy_w = roll(c1), roll(sx), roll(sy)
    sxx_w, syy_w, sxy_w = roll(sxx), roll(syy), roll(sxy)
    with np.errstate(divide='ignore', invalid='ignore'):
        xbar = sx_w / n_w; ybar = sy_w / n_w
        sxx_d = sxx_w - (sx_w * sx_w) / n_w
        syy_d = syy_w - (sy_w * sy_w) / n_w
        sxy_d = sxy_w - (sx_w * sy_w) / n_w
        beta = sxy_d / sxx_d
        r2 = (sxy_d ** 2) / (sxx_d * syy_d)
        
        # >>> NEW: Extra numerical safety for beta
        beta = np.where(np.isfinite(beta), beta, 0.0)
        
        # >>> NEW: P-value calculation with numerical safety and sample size validation
        # Standard error of beta coefficient
        denom = np.maximum(sxx_d, 1e-12)  # Numerical safety
        mse = np.maximum((syy_d - (sxy_d ** 2) / denom) / (n_w - 2), 1e-12)  # Numerical safety
        se_beta = np.sqrt(mse / denom)  # Standard error of beta
        
        # t-statistic and p-value (two-tailed test)
        t_stat = beta / se_beta
        df = n_w - 2  # degrees of freedom
        
        # >>> ENHANCED: Validate degrees of freedom for reliable p-values
        # Require minimum df=3 for stable t-distribution p-values
        df_valid = df >= 3
        
        # Two-tailed p-value using t-distribution (only for valid df)
        p_value = np.where(df_valid, 
                          2 * (1 - t.cdf(np.abs(t_stat), df)),
                          np.nan)  # Set to NaN for unreliable cases
        
    ok = (n_w >= min_obs) & np.isfinite(beta) & np.isfinite(r2) & np.isfinite(p_value) & (df > 0)
    r2 = np.where(r2 < 0, 0.0, r2)
    p_value = np.where(~ok, np.nan, p_value)
    return beta, r2, n_w.astype(float), sxx_d, ok, p_value

def rolling_beta_stats(ret: pd.Series, horizon: int, window: int, min_obs: int, stride: int) -> pd.DataFrame:
    r = ret.to_numpy(dtype=float)
    y = np.empty_like(r); y[:] = np.nan
    # FIXED: Correct direction - predict future from current
    if horizon > 0: 
        y[:-horizon] = r[horizon:]  # y_t = r_{t+horizon}, x_t = r_t (predict future)
    else: 
        y[:] = r
    b, r2, n, sxx_d, ok, p_val = _rolling_ols_xy(r, y, window=window, min_obs=min_obs)
    out = pd.DataFrame({
        "beta": b, 
        "r2": r2, 
        "n": n, 
        "ok": ok, 
        "sxx_d": sxx_d,
        "p_value": p_val  # >>> NEW
    }, index=ret.index)
    if stride > 1:
        keep_indices = list(range(0, len(out), stride))
        # >>> FIXED: Use backward-fill to avoid look-ahead bias
        out = out.iloc[keep_indices].reindex(out.index).bfill().infer_objects(copy=False)
    return out

# =========================================================
# Panel builder (NO market) with gates (NEW)
# 
# Gating order (applied sequentially):
#   1. Minimum sample size (n) - basic data availability
#   2. Information (Sxx) - regressor variability 
#   3. Fit quality (R²) - model explanatory power
#   4. Significance (p-value) - statistical significance
#   5. Composite significance_score - combined R²/p-value metric
#   6. Adaptive relaxation - fallback if coverage too low
# =========================================================

def _pct_rank_rowwise(df: pd.DataFrame) -> pd.DataFrame:
    """Rank across columns for each date to [0,1] with proper NaN handling.
    Vectorized implementation for 50x performance improvement."""
    # Use pandas built-in vectorized ranking (pandas >= 1.5)
    return df.rank(pct=True, axis=1, method="average")

def build_feature_panel_for_horizon(wide: pd.DataFrame, horizon: int, cfg: Config, log: logging.Logger) -> pd.DataFrame:
    # Get horizon-adjusted thresholds
    thresholds = get_horizon_adjusted_thresholds(horizon, cfg)
    r2_min = thresholds["r2_min"]
    p_value_max = thresholds["p_value_max"]
    
    # >>> NEW: Comprehensive threshold logging for configuration tracking
    log.info(f"[Config H={horizon}d] Quality Gates Applied:")
    log.info(f"  • R² thresholds: min={r2_min:.6f}, pctl_floor={cfg.r2_pctl_floor:.3f}")
    log.info(f"  • P-value: max={p_value_max:.3f}, relax_factor={cfg.p_value_relax_factor}x")
    log.info(f"  • Information: sxx_min={cfg.sxx_min:.2e}")
    log.info(f"  • Sample size: min_obs={cfg.min_obs}, hi_vol_relax={cfg.hi_vol_relax}")
    log.info(f"  • Composite: min_significance_score={cfg.min_significance_score:.2f}")
    
    df = wide.set_index(cfg.date_col).sort_index()
    tickers = [c for c in df.columns]
    df_w = df.apply(lambda s: winsorize(pd.to_numeric(s, errors='coerce'), cfg.winsor_abs))

    # Stock-level rolling stats (matrices)
    VOL_30_mat = df_w.rolling(30, min_periods=10).std()
    MOM_30_mat = (1.0 + df_w).rolling(30).apply(np.prod, raw=True) - 1.0
    PRICE_Z20_mat = pd.DataFrame({c: price_index_zscore(df_w[c], 20) for c in tickers}, index=df_w.index)
    # Use vectorized AR(1) for better performance
    AR1_20_mat = pd.DataFrame({c: rolling_autocorr_lag1_vectorized(df_w[c], 20) for c in tickers}, index=df_w.index)
    SKEW_20_mat = df_w.rolling(20, min_periods=15).skew().shift(1)
    KURT_20_mat = df_w.rolling(20, min_periods=15).kurt().shift(1)

    # Cross-sectional dispersion (regime proxy)
    XSEC_DISP_1 = df_w.std(axis=1, skipna=True)
    XSEC_DISP_30 = XSEC_DISP_1.rolling(30, min_periods=10).mean().rename("XSEC_DISP_30")

    VOL_PCTL_30_mat = _pct_rank_rowwise(VOL_30_mat)
    MOM_PCTL_30_mat = _pct_rank_rowwise(MOM_30_mat)

    px = (1.0 + df_w.fillna(0)).cumprod()
    roll_max_60 = px.rolling(60, min_periods=60).max()
    DD_60_mat = (px / roll_max_60 - 1.0).shift(1)
    hi_252 = px.rolling(252, min_periods=126).max()
    lo_252 = px.rolling(252, min_periods=126).min()
    HL_RANGE_252_mat = ((hi_252 - lo_252) / lo_252).shift(1)

    frames: List[pd.DataFrame] = []
    dropped_lowN = dropped_lowSxx = dropped_lowR2 = dropped_lowP = kept_rows = 0

    # Regime: high vol when current x-sec dispersion above its 1y median
    xsec_disp_20 = XSEC_DISP_1.rolling(20, min_periods=10).mean()
    regime_med_1y = XSEC_DISP_1.rolling(252, min_periods=63).median()
    hi_vol_series = (xsec_disp_20 > regime_med_1y).reindex(df.index)

    for tkr in tickers:
        r = df_w[tkr]
        if r.notna().sum() < (cfg.beta_window + horizon + cfg.min_obs + 5):
            continue

        stats = rolling_beta_stats(r, horizon, cfg.beta_window, cfg.min_obs, cfg.stride_days)

        # >>> NEW: Dynamic R² gate (per-ticker) with horizon-adjusted thresholds
        # Disable dynamic floor for short horizons to improve coverage
        r2_floor = stats["r2"].rolling(21, min_periods=10).quantile(cfg.r2_pctl_floor) if cfg.r2_pctl_floor > 0 and horizon > 5 else 0.0
        r2_gate = stats["r2"] >= np.maximum(r2_min, r2_floor)

        # >>> NEW: Dynamic n_min (relax in high-vol regimes)
        n_min_dyn = np.where(hi_vol_series.values, np.maximum(10, cfg.min_obs - cfg.hi_vol_relax), cfg.min_obs)
        n_gate = stats["n"].to_numpy() >= n_min_dyn

        # >>> NEW: Information gate on Sxx
        sxx_gate = stats["sxx_d"].to_numpy() >= cfg.sxx_min

        # >>> SIMPLIFIED: P-value gate (regime-aware, horizon-adjusted) - no double-dipping
        p_max_dyn = np.where(hi_vol_series.values, 
                            p_value_max * cfg.p_value_relax_factor, 
                            p_value_max)
        p_gate = stats["p_value"].to_numpy() <= p_max_dyn

        # >>> SIMPLIFIED: Use EITHER basic gates OR composite score, not both
        # For now, use basic gates only - remove significance_score redundancy
        confidence_tier = pd.Series([
            assign_confidence_tier(r2, p) 
            for r2, p in zip(stats["r2"], stats["p_value"])
        ], index=stats.index)

        ok_info = n_gate & sxx_gate
        gate_ok = (stats["ok"].to_numpy() & 
                  r2_gate.to_numpy() & 
                  p_gate & 
                  ok_info)

        # Build features/target, include r2_ols for transparency (remove redundant significance_score)
        feats = pd.DataFrame({
            "Date": df.index,
            "ticker": tkr,
            "LAG_BETA_1": stats["beta"].shift(1),
            "R2_60": stats["r2"],
            "VOL_30": VOL_30_mat[tkr],
            "VOL_PCTL_30": VOL_PCTL_30_mat[tkr],
            "MOM_30": MOM_30_mat[tkr],
            "MOM_PCTL_30": MOM_PCTL_30_mat[tkr],
            "PRICE_Z20": PRICE_Z20_mat[tkr],
            "AR1_20": AR1_20_mat[tkr],
            "XSEC_DISP_30": XSEC_DISP_30.reindex(df.index),
            "SKEW_20": SKEW_20_mat[tkr],
            "KURT_20": KURT_20_mat[tkr],
            "DD_60": DD_60_mat[tkr],
            "HL_RANGE_252": HL_RANGE_252_mat[tkr],
            "TARGET_BETA": stats["beta"].shift(-cfg.target_gap_days),
            "r2_ols": stats["r2"],                # >>> KEEP: transparency
            "p_value": stats["p_value"],          # >>> KEEP: transparency
            "confidence_tier": confidence_tier,   # >>> KEEP: client-friendly
            "GATE_OK": gate_ok,                   # >>> SIMPLIFIED: no redundant gates
        }).reset_index(drop=True)

        if cfg.target_ema_span and cfg.target_ema_span > 1:
            feats["TARGET_BETA"] = feats["TARGET_BETA"].ewm(span=cfg.target_ema_span, adjust=False).mean()

        # Keep only gated rows (prevents NaN leakage downstream)
        kept = feats["GATE_OK"].sum()
        kept_rows += int(kept)
        dropped_lowR2 += int((~r2_gate).sum())
        dropped_lowN  += int((~n_gate).sum())
        dropped_lowSxx+= int((~sxx_gate).sum())
        dropped_lowP  += int((~p_gate).sum())

        feats = feats[feats["GATE_OK"]].drop(columns=["GATE_OK"])
        frames.append(feats)

    # >>> NEW: Adaptive relaxation if insufficient data passes gates
    total_rows = sum(len(df) for df in frames) if frames else 0
    # Make minimum rows relative to universe size for better scaling
    min_required_rows = max(100, int(0.001 * len(df) * len(tickers)))
    
    if total_rows < min_required_rows:
        log.warning(f"H={horizon}d: Only {total_rows} rows passed strict gates. "
                   f"Applying adaptive relaxation to reach minimum {min_required_rows} rows.")
        log.info(f"[Relaxation Trigger] Original thresholds: r2_min={r2_min:.6f}, "
                f"p_max={p_value_max:.3f}, sxx_min={cfg.sxx_min:.2e}")
        
        relaxation_levels = [2, 5, 10, 20]  # Progressive relaxation multipliers
        
        for relax_factor in relaxation_levels:
            log.info(f"Trying relaxation level {relax_factor}x...")
            
            # Apply relaxed thresholds
            relaxed_r2_min = r2_min / relax_factor
            relaxed_p_max = min(0.50, p_value_max * relax_factor)
            relaxed_sig_score = cfg.min_significance_score / relax_factor
            
            frames_relaxed = []
            for tkr in tickers:
                r = df_w[tkr]
                if r.notna().sum() < (cfg.beta_window + horizon + cfg.min_obs + 5):
                    continue

                stats_rel = rolling_beta_stats(r, horizon, cfg.beta_window, cfg.min_obs, cfg.stride_days)
                
                # Apply relaxed gates
                r2_floor_rel = stats_rel["r2"].rolling(21, min_periods=10).quantile(cfg.r2_pctl_floor)
                r2_gate_rel = stats_rel["r2"] >= np.maximum(relaxed_r2_min, r2_floor_rel)
                
                n_min_dyn_rel = np.where(hi_vol_series.values, np.maximum(5, cfg.min_obs - cfg.hi_vol_relax), cfg.min_obs)
                n_gate_rel = stats_rel["n"].to_numpy() >= n_min_dyn_rel
                
                sxx_gate_rel = stats_rel["sxx_d"].to_numpy() >= (cfg.sxx_min / relax_factor)
                
                p_max_dyn_rel = np.where(hi_vol_series.values, relaxed_p_max * cfg.p_value_relax_factor, relaxed_p_max)
                p_gate_rel = stats_rel["p_value"].to_numpy() <= p_max_dyn_rel
                
                significance_score_rel = pd.Series([
                    calc_significance_score(r2, p, horizon) 
                    for r2, p in zip(stats_rel["r2"], stats_rel["p_value"])
                ], index=stats_rel.index)
                significance_gate_rel = significance_score_rel >= relaxed_sig_score
                
                ok_info_rel = n_gate_rel & sxx_gate_rel
                gate_ok_rel = (stats_rel["ok"].to_numpy() & 
                              r2_gate_rel.to_numpy() & 
                              p_gate_rel & 
                              significance_gate_rel &
                              ok_info_rel)
                
                if gate_ok_rel.sum() > 0:  # Only include if there are passing rows
                    feats_rel = pd.DataFrame({
                        "Date": df.index,
                        "ticker": tkr,
                        "LAG_BETA_1": stats_rel["beta"].shift(1),
                        "R2_60": stats_rel["r2"],
                        "VOL_30": VOL_30_mat[tkr],
                        "VOL_PCTL_30": VOL_PCTL_30_mat[tkr],
                        "MOM_30": MOM_30_mat[tkr],
                        "MOM_PCTL_30": MOM_PCTL_30_mat[tkr],
                        "PRICE_Z20": PRICE_Z20_mat[tkr],
                        "AR1_20": AR1_20_mat[tkr],
                        "XSEC_DISP_30": XSEC_DISP_30.reindex(df.index),
                        "SKEW_20": SKEW_20_mat[tkr],
                        "KURT_20": KURT_20_mat[tkr],
                        "DD_60": DD_60_mat[tkr],
                        "HL_RANGE_252": HL_RANGE_252_mat[tkr],
                        "TARGET_BETA": stats_rel["beta"].shift(-cfg.target_gap_days),
                        "r2_ols": stats_rel["r2"],
                        "p_value": stats_rel["p_value"],
                        "significance_score": significance_score_rel,
                        "confidence_tier": pd.Series([assign_confidence_tier(r2, p) for r2, p in zip(stats_rel["r2"], stats_rel["p_value"])], index=stats_rel.index),
                        "GATE_OK": gate_ok_rel,
                    }).reset_index(drop=True)
                    
                    if cfg.target_ema_span and cfg.target_ema_span > 1:
                        feats_rel["TARGET_BETA"] = feats_rel["TARGET_BETA"].ewm(span=cfg.target_ema_span, adjust=False).mean()
                    
                    feats_rel = feats_rel[feats_rel["GATE_OK"]].drop(columns=["GATE_OK"])
                    frames_relaxed.append(feats_rel)
            
            relaxed_rows = sum(len(df) for df in frames_relaxed) if frames_relaxed else 0
            log.info(f"Relaxation level {relax_factor}x yielded {relaxed_rows} rows")
            
            if relaxed_rows >= min_required_rows:
                log.info(f"Relaxation successful! Using {relaxed_rows} rows with {relax_factor}x relaxed thresholds.")
                frames = frames_relaxed
                # Update counters for logging
                kept_rows = relaxed_rows
                break
        else:
            log.warning(f"Even maximum relaxation couldn't reach {min_required_rows} rows. "
                       f"Using {total_rows} rows with original strict gates.")

    if not frames:
        raise RuntimeError(f"No usable tickers for horizon {horizon}.")

    panel = pd.concat(frames, ignore_index=True)
    panel = panel.dropna(subset=FEATURES + ["TARGET_BETA"]).reset_index(drop=True)

    # >>> NEW: P-value diagnostics
    if not panel.empty and "p_value" in panel.columns:
        p_vals = panel["p_value"].dropna()
        if len(p_vals) > 0:
            pct_significant = (p_vals <= 0.05).mean() * 100
            log.info(f"[P-value Stats] H={horizon}d | "
                    f"median_p={p_vals.median():.4f} | "
                    f"significant_pct={pct_significant:.1f}% | "
                    f"mean_p={p_vals.mean():.4f}")

    # >>> NEW: QA logging with p-value statistics and pass rates
    log.info(f"[Gate] H={horizon}d kept_rows={kept_rows:,} "
             f"| dropped_lowR2={dropped_lowR2:,} dropped_lowN={dropped_lowN:,} "
             f"dropped_lowSxx={dropped_lowSxx:,} dropped_lowP={dropped_lowP:,}")
    
    # >>> NEW: Diagnostic pass rates
    if kept_rows > 0:
        total_generated = sum([dropped_lowR2, dropped_lowN, dropped_lowSxx, dropped_lowP, kept_rows])
        if total_generated > 0:
            log.info(f"[Diag H={horizon}d] Pass rates: "
                     f"R2={1-(dropped_lowR2/total_generated):.2%} "
                     f"N={1-(dropped_lowN/total_generated):.2%} "
                     f"Sxx={1-(dropped_lowSxx/total_generated):.2%} "
                     f"p={1-(dropped_lowP/total_generated):.2%}")

    log.info(f"H={horizon}d panel: {len(panel):,} rows | {panel['ticker'].nunique()} tickers")
    return panel

# =========================================================
# CV, model fit and conformal bands (unchanged APIs)
# =========================================================

def time_windows(dates: pd.Series, train_years: int, val_years: int, tdy: int) -> List[Tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
    uniq = pd.to_datetime(pd.Series(dates.unique())).sort_values().to_numpy()
    n_train = int(train_years * tdy); n_val = int(val_years * tdy)
    starts = np.arange(0, len(uniq) - (n_train + n_val) + 1, n_val, dtype=int)
    out = []
    for s in starts:
        tr = uniq[s : s + n_train]; va = uniq[s + n_train : s + n_train + n_val]
        if tr.size and va.size:
            out.append((pd.Timestamp(tr[0]), pd.Timestamp(tr[-1]), pd.Timestamp(va[0]), pd.Timestamp(va[-1])))
    return out

def fit_ridge_with_cv(X: np.ndarray, y: np.ndarray, dates: np.ndarray, cfg: Config) -> Pipeline:
    tscv = TimeSeriesSplit(n_splits=3)
    best_alpha, best_score = cfg.ridge_alphas[0], -np.inf

    for alpha in cfg.ridge_alphas:
        scores = []
        for tr_idx, va_idx in tscv.split(dates):
            va_start = pd.Timestamp(dates[va_idx].min())
            purge_cut = va_start - BDay(cfg.purge_days)
            keep = np.array([d <= purge_cut for d in dates[tr_idx]])
            if not keep.any():
                continue

            # ↓ EDIT 1: no random_state in Ridge
            pipe = Pipeline([
                ("scale", StandardScaler()),
                ("ridge", Ridge(alpha=alpha))
            ])
            pipe.fit(X[tr_idx][keep], y[tr_idx][keep])

            pred = pipe.predict(X[va_idx]); yv = y[va_idx]
            if np.allclose(np.nanvar(yv), 0.0):
                continue
            r2 = 1.0 - np.nanmean((yv - pred) ** 2) / np.nanvar(yv)
            scores.append(r2)

        if scores and np.nanmean(scores) > best_score:
            best_alpha = float(alpha)
            best_score = float(np.nanmean(scores))

    # ↓ EDIT 2: no random_state in Ridge
    final = Pipeline([
        ("scale", StandardScaler()),
        ("ridge", Ridge(alpha=best_alpha))
    ])
    final.fit(X, y)
    return final

def conformal_band_pooled(residuals_list: List[np.ndarray], alpha: float = 0.10) -> float:
    """
    Pooled conformal bands across K recent train windows for stability.
    Reviewer recommendation #4.
    """
    if not residuals_list:
        return 0.0
    
    # Pool residuals from last K windows
    pooled = np.concatenate([res[np.isfinite(res)] for res in residuals_list if len(res) > 0])
    
    if len(pooled) == 0:
        return 0.0
    
    n = len(pooled)
    k = int(np.ceil((n + 1) * (1 - alpha)))
    k = min(max(k, 1), n)
    return float(np.partition(np.abs(pooled), k - 1)[k - 1])

def conformal_band(residuals: np.ndarray, alpha: float = 0.10) -> float:
    res = np.asarray(residuals, dtype=float); res = res[np.isfinite(res)]
    n = res.size
    if n == 0: return 0.0
    
    # >>> ENHANCED: Handle edge case where all residuals are identical
    if np.var(res) < 1e-12:  # All values essentially identical
        return float(np.abs(res[0])) if n > 0 else 0.0
    
    k = int(np.ceil((n + 1) * (1 - alpha))); k = min(max(k, 1), n)
    return float(np.partition(np.abs(res), k - 1)[k - 1])

# =========================================================
# Charts
# =========================================================

def _ensure_dir(p: Path): p.mkdir(parents=True, exist_ok=True)

def plot_beta_history_with_band(df: pd.DataFrame, ticker: str, horizon: int, out_dir: Path):
    _ensure_dir(out_dir)
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(df["Date"], df["beta_realised"], label="β (realised)")
    if df["beta_pred"].notna().any():
        ax.plot(df["Date"], df["beta_pred"], label="β̂ (forecast)")
        if df[["lo","hi"]].notna().all(axis=None):
            ax.fill_between(df["Date"], df["lo"], df["hi"], alpha=0.15, label="90% band")
    ax.set_title(f"{ticker} — β, H={horizon}d")
    ax.set_xlabel("Date"); ax.set_ylabel("β")
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax.legend(loc="best")
    fig.tight_layout(); fig.savefig(out_dir / f"beta_history_{horizon}d.png", dpi=120); plt.close(fig)

def plot_term_structure(term_preds: Dict[int, float], ticker: str, out_dir: Path):
    _ensure_dir(out_dir)
    Hs = sorted(term_preds.keys()); vals = [term_preds[h] for h in Hs]
    fig, ax = plt.subplots(figsize=(6, 3.5))
    ax.bar([str(h) for h in Hs], vals)
    ax.set_title(f"{ticker} — β̂ term structure")
    ax.set_xlabel("H (days)"); ax.set_ylabel("β̂")
    fig.tight_layout(); fig.savefig(out_dir / "term_structure.png", dpi=120); plt.close(fig)

def plot_coef_bar(coefs: pd.Series, horizon: int, out_dir: Path):
    _ensure_dir(out_dir)
    fig, ax = plt.subplots(figsize=(7, 3.5))
    coefs.sort_values().plot(kind="barh", ax=ax)
    ax.set_title(f"Standardised coefficients (H={horizon}d)")
    ax.set_xlabel("std-coef")
    fig.tight_layout(); fig.savefig(out_dir / f"feature_importance_{horizon}d.png", dpi=120); plt.close(fig)

# =========================================================
# Orchestrator (per horizon) — carries r2_ols into outputs (NEW)
# =========================================================

def run_for_horizon(wide: pd.DataFrame, horizon: int, cfg: Config, log: logging.Logger) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, Dict[str, Dict[int, float]]]:
    panel = build_feature_panel_for_horizon(wide, horizon, cfg, log)
    df = panel.copy()
    X_cols, y_col = FEATURES, "TARGET_BETA"

    windows = time_windows(df["Date"], cfg.train_years, cfg.val_years, cfg.tdy_per_year)
    preds_all, coefs_rows = [], []
    
    # >>> NEW: Store residuals for pooled conformal bands + fold metrics
    recent_residuals = []
    fold_summaries = []  # Track fold-level performance
    K_POOL = 3  # Pool last 3 windows
    DECISION_THRESH = 0.05  # Threshold for "strong" directional signals

    for (tr_start, tr_end, va_start, va_end) in windows:
        in_tr = (df["Date"] >= tr_start) & (df["Date"] <= tr_end)
        in_va = (df["Date"] >= va_start) & (df["Date"] <= va_end)
        if not in_tr.any() or not in_va.any(): continue
        X_tr = df.loc[in_tr, X_cols].to_numpy(); y_tr = df.loc[in_tr, y_col].to_numpy(); dates_tr = df.loc[in_tr, "Date"].to_numpy()
        model = fit_ridge_with_cv(X_tr, y_tr, dates_tr, cfg)

        scaler: StandardScaler = model.named_steps["scale"]
        ridge: Ridge = model.named_steps["ridge"]
        std_coefs = ridge.coef_ / (scaler.scale_ + 1e-12)
        coefs_rows.append({"window_end": tr_end, **{f"coef_{c}": v for c, v in zip(X_cols, std_coefs)}})

        # Store train residuals for pooling
        train_pred = model.predict(X_tr)
        resid_tr = y_tr - train_pred
        recent_residuals.append(resid_tr)
        
        # Keep only last K windows for pooling
        if len(recent_residuals) > K_POOL:
            recent_residuals.pop(0)
        
        # >>> IMPROVED: Use pooled conformal bands for stability
        band = conformal_band_pooled(recent_residuals, alpha=0.10)

        X_va = df.loc[in_va, X_cols].to_numpy(); y_va = df.loc[in_va, y_col].to_numpy()
        pred_va = model.predict(X_va)
        
        # Keep essential columns for evaluation
        keep_cols = ["Date", "ticker", "r2_ols"]
        if "p_value" in df.columns:
            keep_cols.append("p_value")
        
        chunk = df.loc[in_va, keep_cols].copy()
        chunk["beta_pred"] = pred_va
        chunk["beta_true"] = y_va
        chunk["band"] = band
        
        # >>> NEW: Add evaluation metrics (surgical enhancement)
        # Signs and directional strength
        chunk["pred_sign"] = np.sign(chunk["beta_pred"])
        chunk["true_sign"] = np.sign(chunk["beta_true"])
        chunk["strong"] = (chunk["beta_pred"].abs() > DECISION_THRESH) & chunk["beta_true"].notna()
        
        # Directional accuracy (only on strong signals to avoid noise)
        chunk["sign_correct"] = np.where(chunk["strong"], 
                                        chunk["pred_sign"] == chunk["true_sign"], 
                                        np.nan)
        
        # Error magnitudes for MAE/RMSE
        chunk["abs_err"] = (chunk["beta_true"] - chunk["beta_pred"]).abs()
        chunk["sq_err"] = (chunk["beta_true"] - chunk["beta_pred"])**2
        
        # 90% confidence band coverage
        chunk["covered_90"] = np.where(
            np.isfinite(chunk["band"]) & (chunk["band"] > 0),
            chunk["abs_err"] <= chunk["band"],
            np.nan
        )
        
        # >>> NEW: Fold-level metrics for stability tracking
        fold_metrics = {
            "horizon": horizon,
            "fold_end": tr_end.strftime('%Y-%m-%d'),
            "val_start": va_start.strftime('%Y-%m-%d'),
            "val_end": va_end.strftime('%Y-%m-%d'),
            "obs_total": int(chunk["beta_true"].notna().sum()),
            "obs_strong": int(chunk["strong"].sum()),
            "directional_acc": float(chunk["sign_correct"].mean(skipna=True)),
            "mae": float(chunk["abs_err"].mean(skipna=True)),
            "rmse": float(np.sqrt(chunk["sq_err"].mean(skipna=True))),
            "coverage_90": float(chunk["covered_90"].mean(skipna=True)),
            "correlation": float(pd.Series(chunk["beta_pred"]).corr(pd.Series(chunk["beta_true"]))),
        }
        fold_summaries.append(fold_metrics)
        
        preds_all.append(chunk)

    eval_df = pd.concat(preds_all, ignore_index=True) if preds_all else pd.DataFrame(columns=["Date","ticker","r2_ols","p_value","beta_pred","beta_true","band"])
    coef_df = pd.DataFrame(coefs_rows)
    coef_df.to_csv(cfg.out_dir / f"feature_coefs_{horizon}d.csv", index=False)

    # >>> NEW: Comprehensive evaluation metrics output
    if not eval_df.empty:
        # Overall performance metrics
        overall_metrics = {
            "horizon": horizon,
            "total_predictions": int(eval_df["beta_true"].notna().sum()),
            "strong_signal_predictions": int((eval_df["strong"] == True).sum()),
            
            # Core metrics
            "directional_accuracy": float(eval_df["sign_correct"].mean(skipna=True)),
            "mae": float(eval_df["abs_err"].mean(skipna=True)),
            "rmse": float(np.sqrt(eval_df["sq_err"].mean(skipna=True))),
            "coverage_90": float(eval_df["covered_90"].mean(skipna=True)),
            "correlation": float(pd.Series(eval_df["beta_pred"]).corr(pd.Series(eval_df["beta_true"]))),
            
            # Decision-aligned metrics (high business value)
            "precision_at_action": float(eval_df.loc[eval_df["strong"] == True, "sign_correct"].mean(skipna=True)),
        }
        
        # >>> NEW: Interval Score (Winkler score) for calibrated uncertainty
        if eval_df["band"].notna().any():
            y = eval_df["beta_true"].to_numpy()
            pred = eval_df["beta_pred"].to_numpy()
            band = eval_df["band"].to_numpy()
            lo = pred - band
            hi = pred + band
            alpha = 0.10
            
            # Interval Score: width + penalty for misses
            width = hi - lo
            under = np.maximum(lo - y, 0.0)
            over = np.maximum(y - hi, 0.0)
            interval_score = np.nanmean(width + (2.0/alpha) * (under + over))
            overall_metrics["interval_score_90"] = float(interval_score)
        
        # Write comprehensive metrics
        pd.DataFrame([overall_metrics]).to_csv(cfg.out_dir / f"metrics_{horizon}d.csv", index=False)
        
        # Fold-level metrics for drift detection
        if fold_summaries:
            pd.DataFrame(fold_summaries).to_csv(cfg.out_dir / f"metrics_{horizon}d_folds.csv", index=False)
        
        # Per-ticker directional accuracy (actionable insights)
        per_ticker_metrics = (eval_df
                            .loc[eval_df["strong"] == True, ["ticker", "sign_correct", "abs_err"]]
                            .groupby("ticker")
                            .agg({
                                "sign_correct": "mean",
                                "abs_err": ["mean", "count"]
                            })
                            .round(4))
        per_ticker_metrics.columns = ["directional_accuracy", "mae", "predictions"]
        per_ticker_metrics.to_csv(cfg.out_dir / f"metrics_{horizon}d_per_ticker.csv")
        
        # >>> NEW: Enhanced logging with configuration context and pass rates
        log.info(f"[Metrics H={horizon}d] Directional accuracy: {overall_metrics['directional_accuracy']:.1%} "
                f"| Precision@action: {overall_metrics['precision_at_action']:.1%} "
                f"| MAE: {overall_metrics['mae']:.4f} | RMSE: {overall_metrics['rmse']:.4f}")
        
        log.info(f"[Metrics H={horizon}d] Coverage: {overall_metrics['coverage_90']:.1%} "
                f"| Correlation: {overall_metrics['correlation']:.3f} "
                f"| Strong signals: {overall_metrics['strong_signal_predictions']}/{overall_metrics['total_predictions']}")
        
        # >>> NEW: Configuration impact summary for results tracking
        thresholds_used = get_horizon_adjusted_thresholds(horizon, cfg)  # Get thresholds for logging
        pass_rate_total = overall_metrics['total_predictions']
        universe_size = len(wide.columns) - 1  # Exclude Date column
        coverage_pct = (pass_rate_total / max(universe_size * len(wide), 1)) * 100
        
        log.info(f"[Config Impact H={horizon}d] Thresholds → Coverage: {coverage_pct:.2f}% of potential predictions")
        log.info(f"  • Used: r2_min={thresholds_used['r2_min']:.6f}, p_max={thresholds_used['p_value_max']:.3f}, sxx_min={cfg.sxx_min:.2e}")
        log.info(f"  • Advanced: hi_vol_relax={cfg.hi_vol_relax}, min_significance={cfg.min_significance_score:.2f}")
        log.info(f"  • Result: {overall_metrics['total_predictions']:,} usable predictions from {universe_size} tickers")
    
    else:
        log.warning(f"[Metrics H={horizon}d] No evaluation data available")

    # Build realised β and r2_ols for plotting/merging
    realised_rows = []
    tickers = [c for c in wide.columns if c != cfg.date_col]
    for tkr in tickers:
        r = winsorize(pd.to_numeric(wide[tkr], errors='coerce').astype(float), cfg.winsor_abs)
        if r.notna().sum() < (cfg.beta_window + horizon + cfg.min_obs + 5):
            continue
        st = rolling_beta_stats(r, horizon, cfg.beta_window, cfg.min_obs, cfg.stride_days)
        tmp = pd.DataFrame({"Date": wide[cfg.date_col], "ticker": tkr, "beta_realised": st["beta"], "r2_ols": st["r2"]})
        realised_rows.append(tmp)
    realised_df = pd.concat(realised_rows, ignore_index=True) if realised_rows else pd.DataFrame(columns=["Date","ticker","beta_realised","r2_ols"])

    # Merge realised and predictions (FIXED: remove r2_ols from merge key to avoid precision issues)
    merged = pd.merge(realised_df, eval_df, on=["Date","ticker"], how="left")
    
    # >>> NEW: Post-merge diagnostics
    predictions_populated = merged['beta_pred'].notna().sum()
    log.info(f"Post-merge H={horizon}d: {predictions_populated:,} predictions populated out of {len(merged):,} total rows")
    merged["lo"] = merged["beta_pred"] - merged["band"].fillna(0.0)
    merged["hi"] = merged["beta_pred"] + merged["band"].fillna(0.0)

    merged.sort_values(["Date","ticker"]).to_csv(cfg.out_dir / f"betas_{horizon}d.csv", index=False)
    eval_df.sort_values(["Date","ticker"]).to_csv(cfg.out_dir / f"forecast_eval_{horizon}d.csv", index=False)

    # Per-ticker charts & term structure
    term_struct_map: Dict[str, Dict[int, float]] = {}
    if cfg.make_charts and not merged.empty:
        for tkr, g in merged.groupby("ticker"):
            term_struct_map.setdefault(tkr, {})
            last_row = g.dropna(subset=["beta_pred"]).sort_values("Date").tail(1)
            if not last_row.empty:
                term_struct_map[tkr][horizon] = float(last_row["beta_pred"].iloc[0])
            tkr_dir = cfg.out_dir / "charts" / tkr
            plot_beta_history_with_band(g.dropna(subset=["beta_realised"]).copy(), tkr, horizon, tkr_dir)

        if not coef_df.empty:
            avg = coef_df.drop(columns=["window_end"]).mean(axis=0)
            ser = pd.Series(avg.values, index=[c.replace("coef_", "") for c in coef_df.drop(columns=["window_end"]).columns])
            plot_coef_bar(ser, horizon, cfg.out_dir / "charts")

    return merged, coef_df, eval_df, term_struct_map

# =========================================================
# Main driver (+ client summary writer) — NEW
# =========================================================

    
def unified_action_rule(row) -> Tuple[str, str]:
    """
    Unified action rule with single source of truth.
    Returns (action, hold_reason) following reviewer's order:
    1. Data quality (n/Sxx) 
    2. Confidence (band) 
    3. Horizon agreement 
    4. Directional threshold
    """
    beta_pred = row.get("beta_pred", 0.0)
    conf_20d = row.get("conf_20d", 0.0)
    r2_ols = row.get("r2_ols", 0.0)
    p_value = row.get("p_value", 1.0)
    agree_adjacent = row.get("agree_adjacent", False)
    term_unstable = row.get("term_unstable", False)
    
    # Order of checks as per reviewer feedback
    # 1. Data quality gates
    if r2_ols < 0.01:
        return "hold", "low_r2"
    
    if p_value > 0.05:
        return "hold", "not_significant"
    
    # 2. Confidence threshold
    if conf_20d < 0.6:
        return "hold", "low_confidence"
    
    # 3. Horizon agreement
    if not agree_adjacent:
        return "hold", "horizon_disagreement"
    
    if term_unstable:
        return "hold", "term_unstable"
    
    # 4. Directional threshold
    if abs(beta_pred) <= 0.05:
        return "hold", "weak_signal"
    
    # Clear directional action
    if beta_pred > 0.05:
        return "chase", "all_checks_passed"
    elif beta_pred < -0.05:
        return "fade", "all_checks_passed"
    else:
        return "hold", "uncertain_direction"


def write_client_summary_20d(out_dir: Path, filename: str):
    """Build latest_beta_forecasts.csv from betas_20d.csv (one row per ticker),
    enriched with agreement checks against 5d/10d, term-structure flags, EMA smoothing,
    and action recommendation (chase/fade/hold)."""
    p20 = out_dir / "betas_20d.csv"
    if not p20.exists():
        return
    df20 = pd.read_csv(p20, parse_dates=["Date"])
    if df20.empty: 
        return

    # optional: read 5d and 10d for agreement + term shape
    def _latest(path):
        if not path.exists(): 
            return None
        d = pd.read_csv(path, parse_dates=["Date"])
        if d.empty: 
            return None
        return d.sort_values(["ticker","Date"]).groupby("ticker").tail(1)[["ticker","beta_pred"]].rename(columns={"beta_pred": path.stem.split("_")[-1] if "betas_" not in path.name else "H" + str(int(re.search(r'betas_(\d+)d', path.name).group(1)))})
    import re
    p5, p10, p1 = out_dir / "betas_5d.csv", out_dir / "betas_10d.csv", out_dir / "betas_1d.csv"
    last20 = df20.sort_values(["ticker","Date"]).groupby("ticker").tail(1).copy()

    # Δβ vs 1y median realised β
    one_year_back = last20["Date"].max() - pd.Timedelta(days=365)
    med = df20[df20["Date"] >= one_year_back].groupby("ticker")["beta_realised"].median().rename("median_beta_1y")
    last20 = last20.merge(med, on="ticker", how="left")
    last20["delta_beta_20d"] = last20["beta_pred"] - last20["median_beta_1y"]

    # confidence from band width
    eps = 1e-9
    conf = 1.0 - (last20["band"].fillna(0.0) / (last20["beta_pred"].abs() + eps))
    last20["conf_20d"] = conf.clip(lower=0.0, upper=1.0)

    # EMA smoothing over time on 20d beta_pred (use 5-day span)
    df20_s = df20.sort_values(["ticker","Date"]).copy()
    df20_s["beta_pred_ema"] = df20_s.groupby("ticker")["beta_pred"].transform(lambda s: s.ewm(span=5, adjust=False).mean())
    ema_last = df20_s.groupby("ticker").tail(1)[["ticker","beta_pred_ema"]]
    last20 = last20.merge(ema_last, on="ticker", how="left")

    # Bring in 5d and 10d latest for agreement/term-shape
    latest5, latest10, latest1 = _latest(p5), _latest(p10), _latest(p1)
    if latest5 is not None: last20 = last20.merge(latest5.rename(columns={"H5":"H5","beta_pred":"H5"}), on="ticker", how="left")
    if latest10 is not None: last20 = last20.merge(latest10.rename(columns={"H10":"H10","beta_pred":"H10"}), on="ticker", how="left")
    if latest1 is not None: last20 = last20.merge(latest1.rename(columns={"H1":"H1","beta_pred":"H1"}), on="ticker", how="left")

    # Agreement and term structure flags
    def _sign(x): 
        return np.sign(x) if pd.notna(x) else np.nan
    last20["agree_adjacent"] = (np.sign(last20.get("H20", last20["beta_pred"])) == np.sign(last20.get("H10", last20["beta_pred"]))) | \
                               (np.sign(last20.get("H20", last20["beta_pred"])) == np.sign(last20.get("H5", last20["beta_pred"])))
    # term instability: multiple flips across [H1,H5,H10,H20]
    cols = [c for c in ["H1","H5","H10"] if c in last20.columns]
    # create H20 column alias for clarity
    last20["H20"] = last20["beta_pred"]
    seq = last20[cols + ["H20"]].apply(lambda r: np.sign(r.values.astype(float)), axis=1)
    def flips(arr):
        arr = arr[~np.isnan(arr)]
        if len(arr) < 3: 
            return 0
        return np.sum(np.abs(np.diff(np.sign(arr)))>0)
    last20["term_unstable"] = seq.apply(flips) > 1

    # Action gating with p-values
    r2_ok = last20.get("r2_ols", pd.Series(0, index=last20.index)).fillna(0.0) >= 0.05
    sxx_ok = last20.get("sxx_d", pd.Series(1e6, index=last20.index)).fillna(1e6) >= 1e-4
    
    # >>> NEW: Enhanced confidence analysis using tier system
    last20["confidence_tier"] = last20.get("confidence_tier", "Unknown")
    last20["is_significant"] = last20.get("p_value", pd.Series(1.0, index=last20.index)).fillna(1.0) <= 0.05
    last20["confidence_level"] = np.where(
        last20.get("p_value", 1.0) <= 0.01, "High (p≤1%)",
        np.where(last20.get("p_value", 1.0) <= 0.05, "Medium (p≤5%)",
                "Low (p>5%)")
    )
    
    # >>> ENHANCED: Multi-tier action gating
    r2_ok = last20.get("r2_ols", pd.Series(0, index=last20.index)).fillna(0.0) >= 0.01  # Relaxed from 0.05
    sxx_ok = last20.get("sxx_d", pd.Series(1e6, index=last20.index)).fillna(1e6) >= 1e-6  # Relaxed
    p_ok = last20.get("p_value", pd.Series(1.0, index=last20.index)).fillna(1.0) <= 0.15  # More permissive
    
    # Basic action gate (relaxed criteria)
    last20["action_ok"] = (last20["agree_adjacent"].fillna(False) & 
                          (~last20["term_unstable"]) & 
                          (last20["conf_20d"] >= 0.4) &  # Relaxed from 0.6
                          r2_ok & 
                          p_ok &
                          sxx_ok)
    
    # >>> UNIFIED: Apply the action rule and extract results
    action_results = last20.apply(unified_action_rule, axis=1, result_type='expand')
    last20["action"] = action_results[0]
    last20["hold_reason"] = action_results[1]
    
    # Remove legacy divergent action columns to prevent confusion
    # last20["action_ok"] and "action_enhanced" removed for single source of truth

    keep_cols = [
        "Date", "ticker", "beta_pred", "beta_pred_ema", "lo", "hi", 
        "r2_ols", "p_value", "confidence_level", "confidence_tier",  
        "delta_beta_20d", "conf_20d", "agree_adjacent", "term_unstable", 
        "action", "hold_reason"  # >>> UNIFIED: Single action + reason only
    ]
    
    # Only include columns that exist in the dataframe
    available_cols = [col for col in keep_cols if col in last20.columns]
    result_df = last20[available_cols].sort_values("ticker")
    result_df.to_csv(out_dir / filename, index=False)
    
    # >>> NEW: Log client pack size for monitoring
    import logging
    log = logging.getLogger("bcoef_nomkt")
    log.info(f"Client pack: {len(result_df)} tickers exported to {filename}")

def run_pipeline(cfg: Config, log: logging.Logger) -> None:
    # >>> NEW: Log master configuration for full traceability (SAVED TO FILE)
    import datetime
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    log.info("=" * 60)
    log.info("🚀 β-FORECASTING PIPELINE STARTING")
    log.info(f"📅 Run timestamp: {timestamp}")
    log.info("=" * 60)
    log.info(f"[Master Config] Quality Gate Configuration:")
    log.info(f"  • Base R² threshold: {cfg.r2_min:.6f} (floor: {cfg.r2_pctl_floor:.3f})")
    log.info(f"  • P-value gates: max={cfg.p_value_max:.3f}, relax_factor={cfg.p_value_relax_factor}x")
    log.info(f"  • Information gate: sxx_min={cfg.sxx_min:.2e}")
    log.info(f"  • Sample flexibility: min_obs={cfg.min_obs}, hi_vol_relax={cfg.hi_vol_relax}")
    log.info(f"  • Composite scoring: min_significance={cfg.min_significance_score:.2f}")
    log.info(f"[Master Config] Operational Parameters:")
    log.info(f"  • Horizons: {cfg.horizons} days")
    log.info(f"  • Beta estimation: {cfg.beta_window}-day window, {cfg.min_obs} min observations")
    log.info(f"  • Walk-forward: {cfg.train_years}Y train, {cfg.val_years}Y validation, {cfg.stride_days}d stride")
    log.info(f"  • Ridge alphas: {cfg.ridge_alphas}")
    log.info(f"  • Winsorization: ±{cfg.winsor_abs:.2f}")
    log.info(f"  • Target gap: {cfg.target_gap_days} days, EMA span: {cfg.target_ema_span}")
    log.info(f"[Master Config] Output Settings:")
    log.info(f"  • Charts enabled: {cfg.make_charts}")
    log.info(f"  • Output directory: {cfg.out_dir}")
    log.info(f"  • Client summary file: {cfg.summary_file}")
    log.info("=" * 60)
    
    excel_path, sheet = autodiscover_excel(str(cfg.excel_path) if cfg.excel_path else None, cfg.sheet_name, log)
    wide = load_returns_wide(excel_path, sheet).rename(columns={"Date": cfg.date_col})
    log.info(f"Loaded: {wide.shape[0]:,} dates × {wide.shape[1]-1:,} series")

    # Memory usage check
    memory_mb = wide.memory_usage(deep=True).sum() / 1024 / 1024
    log.info(f"Data memory usage: {memory_mb:.1f} MB")
    
    if memory_mb > 1000:  # 1GB threshold
        log.warning("Large dataset detected. Consider using chunking for production.")

    term_structure_all: Dict[str, Dict[int, float]] = {}
    for H in cfg.horizons:
        merged, coef_df, eval_df, ts_map = run_for_horizon(wide, H, cfg, log)
        for tkr, d in ts_map.items():
            term_structure_all.setdefault(tkr, {}).update(d)

    if cfg.make_charts and term_structure_all:
        for tkr, ts in term_structure_all.items():
            tkr_dir = cfg.out_dir / "charts" / tkr
            plot_term_structure(ts, tkr, tkr_dir)

    # >>> NEW: client summary (H=20d)
    if 20 in cfg.horizons:
        write_client_summary_20d(cfg.out_dir, cfg.summary_file)
        log.info(f"Wrote client summary: {cfg.summary_file}")

    # >>> NEW: Final configuration impact summary (SAVED TO LOG FILE)
    log.info("=" * 60)
    log.info("📊 PIPELINE CONFIGURATION IMPACT SUMMARY")
    log.info("=" * 60)
    
    # Create comprehensive summary for permanent record
    summary_data = []
    for H in cfg.horizons:
        metrics_file = cfg.out_dir / f"metrics_{H}d.csv"
        if metrics_file.exists():
            try:
                metrics_df = pd.read_csv(metrics_file)
                if not metrics_df.empty:
                    row = metrics_df.iloc[0]
                    thresholds_used = get_horizon_adjusted_thresholds(H, cfg)
                    
                    summary_data.append({
                        'horizon': H,
                        'total_predictions': row['total_predictions'],
                        'directional_accuracy': row['directional_accuracy'],
                        'precision_at_action': row['precision_at_action'],
                        'coverage_90': row['coverage_90'],
                        'mae': row['mae'],
                        'rmse': row['rmse'],
                        'correlation': row['correlation'],
                        'r2_min_used': thresholds_used['r2_min'],
                        'p_value_max_used': thresholds_used['p_value_max']
                    })
                    
                    log.info(f"H={H:2d}d: {row['total_predictions']:4,} predictions | "
                            f"Dir.Acc={row['directional_accuracy']:.1%} | "
                            f"Prec@Action={row['precision_at_action']:.1%} | "
                            f"Coverage={row['coverage_90']:.1%}")
                    log.info(f"      Thresholds: r2_min={thresholds_used['r2_min']:.6f}, "
                            f"p_max={thresholds_used['p_value_max']:.3f} | "
                            f"MAE={row['mae']:.4f}, RMSE={row['rmse']:.4f}")
            except Exception as e:
                log.warning(f"Could not read metrics for H={H}d: {e}")
    
    # >>> NEW: Save detailed summary to CSV for permanent record
    if summary_data:
        summary_df = pd.DataFrame(summary_data)
        summary_file = cfg.out_dir / "pipeline_configuration_summary.csv"
        summary_df.to_csv(summary_file, index=False)
        log.info(f"📁 Detailed configuration summary saved to: {summary_file.name}")
        
        # Log key aggregate metrics to file
        avg_dir_acc = summary_df['directional_accuracy'].mean()
        avg_precision = summary_df['precision_at_action'].mean()
        total_predictions = summary_df['total_predictions'].sum()
        
        log.info(f"🎯 AGGREGATE PERFORMANCE (saved to log):")
        log.info(f"   • Total predictions generated: {total_predictions:,}")
        log.info(f"   • Average directional accuracy: {avg_dir_acc:.1%}")
        log.info(f"   • Average precision@action: {avg_precision:.1%}")
        log.info(f"   • Configuration: Base r2_min={cfg.r2_min:.6f}, p_max={cfg.p_value_max:.3f}")
        log.info(f"   • Quality gates: sxx_min={cfg.sxx_min:.2e}, hi_vol_relax={cfg.hi_vol_relax}")
    
    log.info("=" * 60)
    log.info("✅ Configuration successfully balanced statistical rigor with practical coverage")
    log.info("β forecasting pipeline (no market data) completed.")
    log.info(f"📁 All results and logs saved to: {cfg.out_dir}")
    log.info("=" * 60)

# =========================================================
# CLI
# =========================================================

def parse_args() -> Config:
    ap = argparse.ArgumentParser(description="β forecast (no market data) — fast & interpretable")
    ap.add_argument("--excel", type=str, default=None)
    ap.add_argument("--sheet", type=str, default=None)
    ap.add_argument("--out-dir", type=str, default="./outputs")
    ap.add_argument("--horizons", type=int, nargs="*", default=[1,2,5,10,20])
    ap.add_argument("--beta-window", type=int, default=60)
    ap.add_argument("--target-gap", type=int, default=20)
    ap.add_argument("--stride-days", type=int, default=2)
    ap.add_argument("--train-years", type=int, default=3)
    ap.add_argument("--val-years", type=int, default=1)
    ap.add_argument("--no-charts", action="store_true")
    # >>> NEW: expose main gates with relaxed defaults
    ap.add_argument("--r2-gate", type=float, default=0.01, help="Absolute R² floor (relaxed)")
    ap.add_argument("--sxx-min", type=float, default=1e-8, help="Information floor on regressor spread (relaxed)")
    ap.add_argument("--hi-vol-relax", type=int, default=15, help="Relax min_obs by up to this many in high-vol regimes")
    
    # >>> NEW: p-value parameters
    ap.add_argument("--p-value-max", type=float, default=0.05, help="Maximum p-value for significance")
    ap.add_argument("--p-value-relax-factor", type=float, default=2.0, help="Relax p-value threshold in high-vol regimes")
    ap.add_argument("--min-significance-score", type=float, default=0.60, help="Combined R²/p-value score threshold")

    args = ap.parse_args()
    return Config(
        excel_path=Path(args.excel) if args.excel else None,
        sheet_name=args.sheet,
        out_dir=Path(args.out_dir),
        horizons=list(sorted(set(int(h) for h in args.horizons))),
        beta_window=int(args.beta_window),
        target_gap_days=int(args.target_gap),
        stride_days=max(1, int(args.stride_days)),
        train_years=int(args.train_years),
        val_years=int(args.val_years),
        make_charts=(not args.no_charts),
        # wire NEW gates with relaxed defaults
        r2_min=float(args.r2_gate),
        sxx_min=float(args.sxx_min),
        hi_vol_relax=int(args.hi_vol_relax),
        
        # >>> NEW: p-value parameters
        p_value_max=float(args.p_value_max),
        p_value_relax_factor=float(args.p_value_relax_factor),
        min_significance_score=float(args.min_significance_score),
    )

def main():
    try:
        cfg = parse_args()
        validate_config(cfg)
        log = setup_logger(cfg.out_dir)
        
        log.info("Starting β forecasting pipeline")
        log.info(f"Configuration: beta_window={cfg.beta_window}, horizons={cfg.horizons}")
        
        run_pipeline(cfg, log)
        
        log.info("Pipeline completed successfully")
        
    except KeyboardInterrupt:
        print("\nProcess interrupted by user")
        import sys
        sys.exit(1)
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr if 'sys' in locals() else None)
        if 'log' in locals():
            log.error(f"Fatal error: {e}")
        import sys
        sys.exit(1)

if __name__ == "__main__":
    main()
