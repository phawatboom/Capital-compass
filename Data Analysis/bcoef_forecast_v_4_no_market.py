#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
β-forecast (fast, interpretable) — Strategy‑1 with feature head (NO market data)
==============================================================================

This version removes dependence on an external market index and replaces
market‑dependent features with **cross‑sectional, price‑only proxies** built from
your own return panel.

Key changes vs your previous `bcoef_forecast_v_4_with_key_features.py`:
- Drop `VOL_MKT_30`, `CORR_MKT_30`, `VOL_RATIO_30` features.
- Add **cross‑sectional regime/context features**:
  • `XSEC_DISP_30` – 30d average of same‑day cross‑sectional dispersion (std).
  • `VOL_PCTL_30`, `MOM_PCTL_30` – per‑date percentiles of each stock’s 30d vol & 30d momentum.
  • `DD_60`, `HL_RANGE_252` – drawdown & 52‑week high‑low range (stock‑level, lagged).
  • `SKEW_20`, `KURT_20` – realized skew/kurtosis (20d) of returns.
- Keep the **7 core, price‑only signals** you had that are independent of a benchmark.
- All features are **lagged by one day**; labels are future β (shifted by target gap).

Outputs (under --out-dir):
- CSVs per horizon: `betas_{H}d.csv`, `feature_coefs_{H}d.csv`, `forecast_eval_{H}d.csv`.
- Charts per ticker: β history with 90% conformal band; term‑structure bars.

"""
from __future__ import annotations

import argparse
import logging
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

# Optional plotting
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

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
    horizons: List[int] = field(default_factory=lambda: [1, 2, 5, 10, 20])
    beta_window: int = 60
    min_obs: int = 25
    stride_days: int = 2          # compute β every k days, ffill (speed)

    # β target horizon (how far ahead to forecast the β itself)
    target_gap_days: int = 20
    target_ema_span: Optional[int] = 5  # smooth β to keep ~1‑month relevance

    # walk‑forward
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


# Final feature list (price‑only, no external market)
FEATURES = [
    # persistence / reliability / local structure
    "LAG_BETA_1",   # prior β
    "R2_60",        # coupling strength of rolling OLS

    # own‑asset level & relative context
    "VOL_30",       # own realized volatility
    "VOL_PCTL_30",  # per‑date percentile of VOL_30 across tickers
    "MOM_30",       # medium‑term momentum (compounded simple)
    "MOM_PCTL_30",  # per‑date percentile of MOM_30 across tickers
    "PRICE_Z20",    # local over/under‑extension
    "AR1_20",       # 1‑lag autocorr (20d)

    # regime/shape/tails & stretch
    "XSEC_DISP_30", # cross‑sectional dispersion of returns (30d avg)
    "SKEW_20",      # realized skew (20d)
    "KURT_20",      # realized kurtosis (20d)
    "DD_60",        # 60d drawdown
    "HL_RANGE_252", # 1‑year high‑low range
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

# =========================================================
# Data loading
# =========================================================

def autodiscover_excel(excel_arg: Optional[str], sheet_arg: Optional[str], log: logging.Logger) -> Tuple[Path, str]:
    def choose_sheet(xls: pd.ExcelFile, preferred: Optional[str]) -> str:
        if preferred and preferred in xls.sheet_names:
            return preferred
        if "Returns" in xls.sheet_names:
            return "Returns"
        for n in xls.sheet_names:
            if "return" in n.lower():
                return n
        return xls.sheet_names[0]

    if excel_arg:
        p = Path(excel_arg)
        xls = pd.ExcelFile(p, engine="openpyxl")
        sheet = choose_sheet(xls, sheet_arg)
        log.info(f"Using Excel: {p.name} | sheet: {sheet}")
        return p, sheet
    for base in [Path.cwd(), Path("/mnt/data")]:
        for pat in ["MXUS_Data_*.xlsx", "MXUS_Data.xlsx", "*.xlsx"]:
            cands = sorted(base.glob(pat), key=lambda q: q.stat().st_mtime, reverse=True)
            if cands:
                xls = pd.ExcelFile(cands[0], engine="openpyxl")
                sheet = choose_sheet(xls, sheet_arg)
                log.info(f"Autodiscovered Excel: {cands[0].name} | sheet: {sheet}")
                return cands[0], sheet
    raise FileNotFoundError("Excel not found. Provide --excel or place MXUS_Data*.xlsx in working dir.")


def _parse_percentish(series: pd.Series) -> pd.Series:
    s = pd.to_numeric(series.astype(str).str.replace('%', '', regex=False).str.strip(), errors='coerce')
    q90 = s.abs().quantile(0.90)
    q95 = s.abs().quantile(0.95)
    q99 = s.abs().quantile(0.99)
    if (0.20 < q90 <= 100) or (q95 > 1.0 and q99 <= 100):
        s = s / 100.0
    return s


def load_returns_wide(excel_path: Path, sheet_name: str) -> pd.DataFrame:
    raw = pd.read_excel(excel_path, sheet_name=sheet_name, header=None, engine="openpyxl")
    col0 = raw.iloc[:, 0].astype(str).str.strip().str.lower()
    header_idx = col0[col0.eq("date")].index.tolist()
    header_idx = header_idx[0] if header_idx else 0
    headers = raw.iloc[header_idx].astype(str).str.strip().tolist()
    df = raw.iloc[header_idx + 1:].copy()
    df.columns = headers
    if "Date" not in df.columns:
        df = df.rename(columns={df.columns[0]: "Date"})
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df[df["Date"].notna()].sort_values("Date").reset_index(drop=True)
    for c in [c for c in df.columns if c != "Date"]:
        df[c] = _parse_percentish(df[c])
    keep = ["Date"] + [c for c in df.columns if c != "Date" and df[c].notna().sum() > 0]
    return df[keep]

# =========================================================
# Feature engineering primitives
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


def rolling_autocorr_lag1(series: pd.Series, window: int) -> pd.Series:
    x_prev = series.shift(1)
    corr = series.rolling(window).corr(x_prev)
    return corr.shift(1)

# =========================================================
# Fast rolling OLS for y on x over a fixed window (vectorised)
# =========================================================

def _rolling_ols_xy(x: np.ndarray, y: np.ndarray, window: int, min_obs: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Vectorised rolling OLS for y ~ a + b x.
    Returns (beta, r2, n, sxx_d, ok_mask). Works with NaNs.
    """
    m = np.isfinite(x) & np.isfinite(y)
    xv = np.where(m, x, 0.0)
    yv = np.where(m, y, 0.0)

    c1 = np.cumsum(m.astype(np.int64))
    sx = np.cumsum(xv)
    sy = np.cumsum(yv)
    sxx = np.cumsum(xv * xv)
    syy = np.cumsum(yv * yv)
    sxy = np.cumsum(xv * yv)

    def roll(c):
        out = c.copy()
        out[window:] = c[window:] - c[:-window]
        return out

    n_w = roll(c1)
    sx_w = roll(sx)
    sy_w = roll(sy)
    sxx_w = roll(sxx)
    syy_w = roll(syy)
    sxy_w = roll(sxy)

    with np.errstate(divide='ignore', invalid='ignore'):
        xbar = sx_w / n_w
        ybar = sy_w / n_w
        sxx_d = sxx_w - (sx_w * sx_w) / n_w
        syy_d = syy_w - (sy_w * sy_w) / n_w
        sxy_d = sxy_w - (sx_w * sy_w) / n_w

        beta = sxy_d / sxx_d
        r2 = (sxy_d ** 2) / (sxx_d * syy_d)

    ok = (n_w >= min_obs) & np.isfinite(beta) & np.isfinite(r2)
    r2 = np.where(r2 < 0, 0.0, r2)
    return beta, r2, n_w.astype(float), sxx_d, ok


def rolling_beta_stats(ret: pd.Series, horizon: int, window: int, min_obs: int, stride: int) -> pd.DataFrame:
    """Compute β and R² for E[r_{t+h}] = a + β r_t. Align to end of window."""
    r = ret.to_numpy(dtype=float)
    y = np.empty_like(r); y[:] = np.nan
    if horizon > 0:
        y[:-horizon] = r[horizon:]
    else:
        y[:] = r

    b, r2, n, sxx_d, ok = _rolling_ols_xy(r, y, window=window, min_obs=min_obs)

    out = pd.DataFrame({
        "beta": b,
        "r2": r2,
        "n": n,
        "ok": ok,
        "sxx_d": sxx_d,
    }, index=ret.index)

    if stride > 1:
        # Fix: Use iloc indexing instead of where/mask to avoid shape mismatch
        keep_indices = list(range(0, len(out), stride))
        out_strided = out.iloc[keep_indices].reindex(out.index).ffill().infer_objects(copy=False)
        out = out_strided
    return out

# =========================================================
# Panel builder (NO market series): price‑only + cross‑sectional proxies
# =========================================================

def _pct_rank_rowwise(df: pd.DataFrame) -> pd.DataFrame:
    # rank across columns for each date to [0,1]
    return df.rank(pct=True, axis=1, method="average")


def build_feature_panel_for_horizon(wide: pd.DataFrame, horizon: int, cfg: Config, log: logging.Logger) -> pd.DataFrame:
    # Set up matrices for cross‑sectional computations
    df = wide.set_index(cfg.date_col).sort_index()
    tickers = [c for c in df.columns]

    # Winsorize per series (copy dataframe)
    df_w = df.apply(lambda s: winsorize(pd.to_numeric(s, errors='coerce'), cfg.winsor_abs))

    # Stock‑level rolling stats (entire matrices, then we can pick columns cheaply)
    VOL_30_mat = df_w.rolling(30, min_periods=10).std()
    MOM_30_mat = (1.0 + df_w).rolling(30).apply(np.prod, raw=True) - 1.0
    PRICE_Z20_mat = pd.DataFrame({c: price_index_zscore(df_w[c], 20) for c in tickers}, index=df_w.index)
    AR1_20_mat = df_w.rolling(20).apply(lambda x: pd.Series(x).autocorr(lag=1), raw=False).shift(1)
    # realized skew/kurt (20d)
    SKEW_20_mat = df_w.rolling(20, min_periods=15).skew().shift(1)
    KURT_20_mat = df_w.rolling(20, min_periods=15).kurt().shift(1)

    # Cross‑sectional dispersion: std across tickers per day → 30d avg
    XSEC_DISP_1 = df_w.std(axis=1, skipna=True)
    XSEC_DISP_30 = XSEC_DISP_1.rolling(30, min_periods=10).mean().rename("XSEC_DISP_30")

    # Percentiles per date for VOL_30 & MOM_30
    VOL_PCTL_30_mat = _pct_rank_rowwise(VOL_30_mat)
    MOM_PCTL_30_mat = _pct_rank_rowwise(MOM_30_mat)

    # Drawdown & 52w range per stock
    px = (1.0 + df_w.fillna(0)).cumprod()
    roll_max_60 = px.rolling(60, min_periods=60).max()
    DD_60_mat = (px / roll_max_60 - 1.0).shift(1)
    hi_252 = px.rolling(252, min_periods=126).max()
    lo_252 = px.rolling(252, min_periods=126).min()
    HL_RANGE_252_mat = ((hi_252 - lo_252) / lo_252).shift(1)

    frames: List[pd.DataFrame] = []
    for tkr in tickers:
        r = df_w[tkr]
        # gate: need enough observations
        if r.notna().sum() < (cfg.beta_window + horizon + cfg.min_obs + 5):
            continue
        stats = rolling_beta_stats(r, horizon, cfg.beta_window, cfg.min_obs, cfg.stride_days)
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
            # target: future β (Δ days ahead)
            "TARGET_BETA": stats["beta"].shift(-cfg.target_gap_days),
            # for potential gating/diagnostics
            "GATE_OK": stats["ok"],
        }).reset_index(drop=True)
        if cfg.target_ema_span and cfg.target_ema_span > 1:
            feats["TARGET_BETA"] = feats["TARGET_BETA"].ewm(span=cfg.target_ema_span, adjust=False).mean()
        frames.append(feats)

    if not frames:
        raise RuntimeError(f"No usable tickers for horizon {horizon}.")

    panel = pd.concat(frames, ignore_index=True)
    panel = panel.dropna(subset=FEATURES + ["TARGET_BETA"]).reset_index(drop=True)
    log.info(f"H={horizon}d panel: {len(panel):,} rows | {panel['ticker'].nunique()} tickers")
    return panel

# =========================================================
# CV, model fit and conformal bands
# =========================================================

def time_windows(dates: pd.Series, train_years: int, val_years: int, tdy: int) -> List[Tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
    uniq = pd.to_datetime(pd.Series(dates.unique())).sort_values().to_numpy()
    n_train = int(train_years * tdy)
    n_val = int(val_years * tdy)
    starts = np.arange(0, len(uniq) - (n_train + n_val) + 1, n_val, dtype=int)
    out = []
    for s in starts:
        tr = uniq[s : s + n_train]
        va = uniq[s + n_train : s + n_train + n_val]
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
            pipe = Pipeline([
                ("scale", StandardScaler()),
                ("ridge", Ridge(alpha=alpha, random_state=cfg.random_state))
            ])
            pipe.fit(X[tr_idx][keep], y[tr_idx][keep])
            pred = pipe.predict(X[va_idx])
            yv = y[va_idx]
            if np.allclose(np.nanvar(yv), 0.0):
                continue
            r2 = 1.0 - np.nanmean((yv - pred) ** 2) / np.nanvar(yv)
            scores.append(r2)
        if scores and np.nanmean(scores) > best_score:
            best_alpha = float(alpha)
            best_score = float(np.nanmean(scores))
    final = Pipeline([
        ("scale", StandardScaler()),
        ("ridge", Ridge(alpha=best_alpha, random_state=cfg.random_state))
    ])
    final.fit(X, y)
    return final


def conformal_band(residuals: np.ndarray, alpha: float = 0.10) -> float:
    res = np.asarray(residuals, dtype=float)
    res = res[np.isfinite(res)]
    n = res.size
    if n == 0:
        return 0.0
    k = int(np.ceil((n + 1) * (1 - alpha)))
    k = min(max(k, 1), n)
    return float(np.partition(np.abs(res), k - 1)[k - 1])

# =========================================================
# Chart helpers
# =========================================================

def _ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)


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
    fig.tight_layout()
    fig.savefig(out_dir / f"beta_history_{horizon}d.png", dpi=120)
    plt.close(fig)


def plot_term_structure(term_preds: Dict[int, float], ticker: str, out_dir: Path):
    _ensure_dir(out_dir)
    Hs = sorted(term_preds.keys())
    vals = [term_preds[h] for h in Hs]
    fig, ax = plt.subplots(figsize=(6, 3.5))
    ax.bar([str(h) for h in Hs], vals)
    ax.set_title(f"{ticker} — β̂ term structure")
    ax.set_xlabel("H (days)"); ax.set_ylabel("β̂")
    fig.tight_layout(); fig.savefig(out_dir / "term_structure.png", dpi=120)
    plt.close(fig)


def plot_coef_bar(coefs: pd.Series, horizon: int, out_dir: Path):
    _ensure_dir(out_dir)
    fig, ax = plt.subplots(figsize=(7, 3.5))
    coefs.sort_values().plot(kind="barh", ax=ax)
    ax.set_title(f"Standardised coefficients (H={horizon}d)")
    ax.set_xlabel("std‑coef")
    fig.tight_layout(); fig.savefig(out_dir / f"feature_importance_{horizon}d.png", dpi=120)
    plt.close(fig)

# =========================================================
# Orchestrator (per horizon)
# =========================================================

def run_for_horizon(wide: pd.DataFrame, horizon: int, cfg: Config, log: logging.Logger) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, Dict[str, Dict[int, float]]]:
    panel = build_feature_panel_for_horizon(wide, horizon, cfg, log)
    df = panel.copy()
    X_cols, y_col = FEATURES, "TARGET_BETA"

    windows = time_windows(df["Date"], cfg.train_years, cfg.val_years, cfg.tdy_per_year)
    preds_all = []
    coefs_rows = []

    for (tr_start, tr_end, va_start, va_end) in windows:
        in_tr = (df["Date"] >= tr_start) & (df["Date"] <= tr_end)
        in_va = (df["Date"] >= va_start) & (df["Date"] <= va_end)
        if not in_tr.any() or not in_va.any():
            continue
        X_tr = df.loc[in_tr, X_cols].to_numpy(); y_tr = df.loc[in_tr, y_col].to_numpy(); dates_tr = df.loc[in_tr, "Date"].to_numpy()
        model = fit_ridge_with_cv(X_tr, y_tr, dates_tr, cfg)

        scaler: StandardScaler = model.named_steps["scale"]
        ridge: Ridge = model.named_steps["ridge"]
        std_coefs = ridge.coef_ / (scaler.scale_ + 1e-12)
        coefs_rows.append({"window_end": tr_end, **{f"coef_{c}": v for c, v in zip(X_cols, std_coefs)}})

        # conformal band from train residuals
        train_pred = model.predict(X_tr)
        resid_tr = y_tr - train_pred
        band = conformal_band(resid_tr, alpha=0.10)

        X_va = df.loc[in_va, X_cols].to_numpy(); y_va = df.loc[in_va, y_col].to_numpy()
        pred_va = model.predict(X_va)
        chunk = df.loc[in_va, ["Date", "ticker"]].copy()
        chunk["beta_pred"] = pred_va
        chunk["beta_true"] = y_va
        chunk["band"] = band
        preds_all.append(chunk)

    eval_df = pd.concat(preds_all, ignore_index=True) if preds_all else pd.DataFrame(columns=["Date","ticker","beta_pred","beta_true","band"]) 

    # Save coefficients
    coef_df = pd.DataFrame(coefs_rows)
    coef_df.to_csv(cfg.out_dir / f"feature_coefs_{horizon}d.csv", index=False)

    # Build per‑date realised β (for plotting side by side with β̂)
    realised_rows = []
    tickers = [c for c in wide.columns if c != cfg.date_col]
    for tkr in tickers:
        r = winsorize(pd.to_numeric(wide[tkr], errors='coerce').astype(float), cfg.winsor_abs)
        if r.notna().sum() < (cfg.beta_window + horizon + cfg.min_obs + 5):
            continue
        st = rolling_beta_stats(r, horizon, cfg.beta_window, cfg.min_obs, cfg.stride_days)
        tmp = pd.DataFrame({"Date": wide[cfg.date_col], "ticker": tkr, "beta_realised": st["beta"]})
        realised_rows.append(tmp)
    realised_df = pd.concat(realised_rows, ignore_index=True) if realised_rows else pd.DataFrame(columns=["Date","ticker","beta_realised"]) 

    # Merge realised and predictions
    merged = pd.merge(realised_df, eval_df, on=["Date","ticker"], how="left")
    merged["lo"] = merged["beta_pred"] - merged["band"].fillna(0.0)
    merged["hi"] = merged["beta_pred"] + merged["band"].fillna(0.0)

    merged.sort_values(["Date","ticker"]).to_csv(cfg.out_dir / f"betas_{horizon}d.csv", index=False)
    eval_df.sort_values(["Date","ticker"]).to_csv(cfg.out_dir / f"forecast_eval_{horizon}d.csv", index=False)

    # Per‑ticker charts & term structure
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
# Main driver
# =========================================================

def run_pipeline(cfg: Config, log: logging.Logger) -> None:
    excel_path, sheet = autodiscover_excel(str(cfg.excel_path) if cfg.excel_path else None, cfg.sheet_name, log)
    wide = load_returns_wide(excel_path, sheet).rename(columns={"Date": cfg.date_col})
    log.info(f"Loaded: {wide.shape[0]:,} dates × {wide.shape[1]-1:,} series")

    term_structure_all: Dict[str, Dict[int, float]] = {}
    for H in cfg.horizons:
        merged, coef_df, eval_df, ts_map = run_for_horizon(wide, H, cfg, log)
        for tkr, d in ts_map.items():
            term_structure_all.setdefault(tkr, {}).update(d)

    if cfg.make_charts and term_structure_all:
        for tkr, ts in term_structure_all.items():
            tkr_dir = cfg.out_dir / "charts" / tkr
            plot_term_structure(ts, tkr, tkr_dir)

    log.info("β forecasting pipeline (no market data) completed.")

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
    )


def main():
    cfg = parse_args()
    log = setup_logger(cfg.out_dir)
    run_pipeline(cfg, log)


if __name__ == "__main__":
    main()
