#!/usr/bin/env Rscript
# MR-PROD — Mean-Reversion Research → Production (headless, R)
# ===========================================================
# Produces per-stock, per-date mean-reversion probabilities and expected move sizes
# for horizons d1, d3, d7, d15, d30 with leak-aware validation, probability calibration,
# and conformal magnitude bands.
#
# Dependencies:
#   install.packages(c("data.table","readxl","zoo","glmnet","optparse"))
#   # Optional tree head:
#   install.packages("xgboost")
#
# Usage:
#   Rscript mr_prod.R --mode forecast --excel MXUS_Data.xlsx --sheet Returns --out results
#   Rscript mr_prod.R --mode backtest --excel MXUS_Data.xlsx --sheet Returns --out results
#
# Notes:
# - Market features are loaded from an optional "Market" sheet (no web fetching in this R port).
# - Classifier: glmnet (logit) with inner time-series CV + purge; class weights via sample weights.
# - Isotonic: base::isoreg used; predicted via stepwise interpolation helper.
# - Magnitude head: xgboost regressor (optional; falls back to median if not installed).
# - Conformal bands: absolute-residual quantiles on a held-out calibration slice.
# - Thresholding: symmetric coverage rule identical to Python (choose largest τ meeting min coverage).

suppressPackageStartupMessages({
  library(data.table)
  library(readxl)
  library(zoo)
  library(glmnet)
  library(optparse)
})

ABSTAIN <- -1L

# -------------------------
# Config (as a list)
# -------------------------
make_config <- function(
  excel_path = "MXUS_Data.xlsx",
  sheet_name = "Returns",
  output_dir = "results",
  with_market = TRUE,
  market_sheet = "Market",
  vol_window = 20L,
  vol_k = 0.5,
  train_years = 3L,
  validation_years = 1L,
  trading_days_per_year = 252L,
  embargo_days = 5L,
  alpha_grid = c(0.0, 1.0),              # l2 (ridge) or l1 (lasso)
  reg_strengths_C = c(0.1, 1.0, 10.0),   # transformed to lambda = 1/C
  inner_cv_folds = 3L,
  horizons = list(
    list(name="d1",  h=1L,  k=1L),
    list(name="d3",  h=3L,  k=3L),
    list(name="d7",  h=7L,  k=7L),
    list(name="d15", h=15L, k=15L),
    list(name="d30", h=30L, k=30L)
  ),
  ar_windows = c(10L, 20L, 60L),
  sign_persist_windows = c(20L, 60L),
  vol_feat_windows = c(10L, 20L),
  z_score_windows = c(20L),
  winsor_abs_limit = 0.10,
  random_state = 42L,
  threshold_grid = round(seq(0.55, 0.91, by=0.01), 2),
  min_coverage = NA_real_,              # e.g., 0.40
  threshold_fixed = NA_real_,           # fixed τ if provided
  min_exp_move_abs = NA_real_,          # e.g., 0.01
  threshold_rule = "coverage",
  min_valid_frac = 0.70,
  calib_frac = 0.20,
  conformal_alpha = 0.10,
  verbose = TRUE,
  show_progress = TRUE
){
  list(
    excel_path=excel_path, sheet_name=sheet_name, output_dir=output_dir,
    with_market=with_market, market_sheet=market_sheet,
    vol_window=vol_window, vol_k=vol_k,
    train_years=train_years, validation_years=validation_years,
    trading_days_per_year=trading_days_per_year, embargo_days=embargo_days,
    alpha_grid=alpha_grid, reg_strengths_C=reg_strengths_C, inner_cv_folds=inner_cv_folds,
    horizons=horizons,
    ar_windows=ar_windows, sign_persist_windows=sign_persist_windows,
    vol_feat_windows=vol_feat_windows, z_score_windows=z_score_windows,
    winsor_abs_limit=winsor_abs_limit, random_state=random_state,
    threshold_grid=threshold_grid, min_coverage=min_coverage,
    threshold_fixed=threshold_fixed, min_exp_move_abs=min_exp_move_abs,
    threshold_rule=threshold_rule, min_valid_frac=min_valid_frac,
    calib_frac=calib_frac, conformal_alpha=conformal_alpha,
    verbose=verbose, show_progress=show_progress
  )
}

# -------------------------
# Logging helpers
# -------------------------
log_info <- function(...){ cat(format(Sys.time(), "%Y-%m-%d %H:%M:%S"), "| INFO |", ..., "\n") }

# -------------------------
# Utils
# -------------------------
parse_percentish <- function(x) {
  # Convert strings like "0.56%" or "0.56" to decimals. If values look like [0,100], divide by 100.
  v <- suppressWarnings(as.numeric(gsub("%","",as.character(x), fixed=TRUE)))
  q90 <- quantile(abs(v), 0.90, na.rm=TRUE)
  q95 <- quantile(abs(v), 0.95, na.rm=TRUE)
  q99 <- quantile(abs(v), 0.99, na.rm=TRUE)
  if (!is.na(q90) && ( (q90>0.20 && q90<=100) || (!is.na(q95) && q95>1.0 && !is.na(q99) && q99<=100) )) {
    v <- v/100.0
  }
  v
}

winsorize <- function(x, lim) pmin(pmax(x, -lim), lim)

compound_forward_simple <- function(r, h){
  # forward compounded simple returns: prod(1+r) over horizon - 1
  if (h == 0L) return(rep(NA_real_, length(r)))
  cp <- cumprod(1 + ifelse(is.na(r), 0, r))
  # shift(-h): cp_{t+h} / cp_t - 1
  out <- (shift(cp, type="lead", n=h) / cp) - 1
  out[(length(out)-h+1L):length(out)] <- NA_real_
  out
}

compound_past_simple <- function(r, w){
  # rolling past compounded simple returns, shifted by 1 to avoid leakage
  if (w <= 0L) return(rep(NA_real_, length(r)))
  roll <- rollapply(1 + r, width=w, FUN=function(x) prod(x)-1, align="right", fill=NA_real_, partial=FALSE)
  shift(roll, n=1L, type="lag")
}

rolling_autocorr <- function(r, window, lag=1L){
  xprev <- shift(r, n=lag, type="lag")
  # use rollapply to compute rolling correlation
  f <- function(idx){
    cor(r[idx], xprev[idx], use="complete.obs")
  }
  out <- rep(NA_real_, length(r))
  if (length(r) >= window){
    idxs <- embed(seq_along(r), window)[, window:1]
    vals <- apply(idxs, 1, f)
    out[seq_along(vals) + (window-1L)] <- vals
  }
  shift(out, n=1L, type="lag")
}

rolling_sign_persist <- function(r, window){
  same <- sign(r) * sign(shift(r, 1L, type="lag")) > 0
  rate <- rollapply(as.numeric(same), width=window, FUN=function(x) mean(x, na.rm=TRUE), align="right", fill=NA_real_)
  shift(rate, n=1L, type="lag")
}

choose_threshold_by_coverage <- function(p, thresholds, min_coverage){
  # Largest τ whose symmetric coverage meets/exceeds min_coverage
  for (thr in sort(thresholds[thresholds>0.5], decreasing=TRUE)){
    covered <- (p >= thr) | (p <= (1.0 - thr))
    cov <- mean(covered)
    if (!is.na(min_coverage) && is.finite(cov) && cov + 1e-12 >= min_coverage){
      return(list(threshold=thr, coverage=cov))
    }
  }
  list(threshold=0.5, coverage=1.0)
}

auc_safe <- function(y, p){
  y <- as.integer(y)
  keep <- (y %in% c(0L,1L)) & is.finite(p)
  y <- y[keep]; p <- p[keep]
  if (length(y) == 0L || length(unique(y)) < 2L) return(0.5)
  # PRROC::roc.curve alternative; use pROC::auc if available
  if (requireNamespace("pROC", quietly=TRUE)){
    as.numeric(pROC::auc(y, p))
  } else {
    # simple Mann–Whitney U approximation
    o <- order(p, decreasing=TRUE)
    y2 <- y[o]
    pos <- which(y2==1L); neg <- which(y2==0L)
    if (!length(pos) || !length(neg)) return(0.5)
    ranks <- rank(p[o], ties.method="average")
    auc <- (sum(ranks[pos]) - length(pos)*(length(pos)+1)/2) / (length(pos)*length(neg))
    as.numeric(auc)
  }
}

# isoreg predict helper (monotone calibration)
predict_isoreg <- function(iso, x){
  # base::isoreg returns a step function through iso$x, iso$yf
  # We'll do right-continuous step interpolation
  xi <- iso$x; yi <- iso$yf
  ord <- order(xi)
  xi <- xi[ord]; yi <- yi[ord]
  approx(x = xi, y = yi, xout = x, method = "constant", f = 1, ties = "ordered")$y
}

conformal_q <- function(residuals, alpha){
  res <- residuals[is.finite(residuals)]
  n <- length(res)
  if (n == 0L) return(0.0)
  # quantile per Vovk et al. (ceil((n+1)*(1-alpha)) order statistic)
  k <- min(max(ceiling((n+1)*(1-alpha)), 1L), n)
  sort(res, partial=k)[k]
}

# -------------------------
# Data I/O
# -------------------------
autodiscover_excel_and_sheet <- function(excel_arg, sheet_arg){
  choose_sheet <- function(path, preferred){
    sheets <- readxl::excel_sheets(path)
    if (!is.null(preferred) && preferred %in% sheets) return(preferred)
    if ("Returns" %in% sheets) return("Returns")
    cand <- sheets[grepl("return", tolower(sheets))]
    if (length(cand)) return(cand[1])
    sheets[1]
  }
  if (!is.null(excel_arg) && file.exists(excel_arg)){
    sh <- choose_sheet(excel_arg, sheet_arg)
    return(list(path=excel_arg, sheet=sh))
  }
  pats <- c("MXUS_Data_*.xlsx","MXUS_Data.xlsx",".*.xlsx")
  for (pat in pats){
    cand <- Sys.glob(pat)
    if (length(cand)){
      # most recently modified first
      o <- order(file.info(cand)$mtime, decreasing=TRUE)
      cand <- cand[o]
      for (p in cand){
        return(list(path=p, sheet=choose_sheet(p, sheet_arg)))
      }
    }
  }
  stop("Excel file not specified and not found. Provide --excel or place the file in working dir.")
}

load_returns_wide <- function(path, sheet_name){
  dt <- as.data.table(readxl::read_excel(path, sheet=sheet_name))
  if (ncol(dt) < 2L) stop("Expected 'Date' + ≥1 ticker columns in Returns sheet.")
  setnames(dt, names(dt)[1], "Date")
  dt[, Date := as.Date(Date)]
  dt <- dt[!is.na(Date)][order(Date)]
  for (c in setdiff(names(dt), "Date")) dt[[c]] <- parse_percentish(dt[[c]])
  dt
}

validate_returns_wide <- function(dt){
  issues <- list()
  dup <- sum(duplicated(dt$Date))
  if (dup) issues <- append(issues, list(list(issue="duplicate_dates", count=dup)))
  if (!isTRUE(all(order(dt$Date)==seq_len(nrow(dt))))) {
    issues <- append(issues, list(list(issue="non_monotone_dates", count=nrow(dt))))
  }
  bad <- setdiff(names(dt), "Date")[sapply(setdiff(names(dt), "Date"), function(c) all(is.na(dt[[c]])))]
  if (length(bad)) issues <- append(issues, list(list(issue="all_nan_tickers", tickers=paste(bad, collapse=","), count=length(bad))))
  as.data.table(issues)
}

load_market_from_excel <- function(path, sheet_name="Market"){
  if (!sheet_name %in% readxl::excel_sheets(path)) return(NULL)
  d <- as.data.table(readxl::read_excel(path, sheet=sheet_name))
  if (ncol(d) < 2L) return(NULL)
  setnames(d, names(d)[1], "Date")
  d[, Date := as.Date(Date)]
  d <- d[!is.na(Date)][order(Date)]
  cols <- setdiff(names(d), "Date")
  ret <- NULL
  if ("MKT_RET" %in% names(d)) {
    ret <- suppressWarnings(as.numeric(d$MKT_RET))
  } else {
    # try to infer from a price-like column
    cand <- cols[tolower(cols) %in% c("mkt_px","px","close","adj close","price","value")]
    if (!length(cand) && length(cols)==1L) cand <- cols[1]
    if (length(cand)) {
      px <- suppressWarnings(as.numeric(d[[cand[1]]]))
      ret <- c(NA_real_, diff(px)/shift(px, n=1L, type="lag")[-1L])
    }
  }
  if (is.null(ret)) return(NULL)
  out <- data.table(Date=d$Date, MKT_RET=ret)
  out[is.finite(MKT_RET)]
}

compute_market_features <- function(mkt){
  d <- copy(mkt)[order(Date)]
  d[, MKT_RET_1D := MKT_RET]
  d[, MKT_RET_5D := rollapply(1+MKT_RET, 5, function(x) prod(x)-1, align="right", fill=NA_real_)]
  d[, MKT_VOL_20D := rollapply(MKT_RET, 20, sd, align="right", fill=NA_real_)]
  px_index <- cumprod(1 + fifelse(is.na(MKT_RET), 0, MKT_RET))
  w <- 20L
  ma <- rollapply(px_index, w, mean, align="right", fill=NA_real_)
  sdv <- rollapply(px_index, w, sd, align="right", fill=NA_real_)
  d[, MKT_Z_MA_20D := (px_index - ma)/sdv]
  # shift all by 1 day to avoid leakage
  for (c in c("MKT_RET_1D","MKT_RET_5D","MKT_VOL_20D","MKT_Z_MA_20D")) {
    d[[c]] <- shift(d[[c]], 1L, type="lag")
  }
  d[is.finite(MKT_RET_1D) & is.finite(MKT_RET_5D) & is.finite(MKT_VOL_20D) & is.finite(MKT_Z_MA_20D),
    .(Date, MKT_RET_1D, MKT_RET_5D, MKT_VOL_20D, MKT_Z_MA_20D)]
}

# -------------------------
# Feature panel + labels
# -------------------------
build_feature_panel <- function(returns_wide, cfg){
  tickers <- setdiff(names(returns_wide), "Date")
  frames <- vector("list", length(tickers))
  ii <- 0L
  for (tkr in tickers){
    r <- as.numeric(returns_wide[[tkr]])
    # drop very sparse series
    if (mean(is.finite(r)) < cfg$min_valid_frac) next
    r <- winsorize(r, cfg$winsor_abs_limit)
    base <- data.table(Date=returns_wide$Date, ticker=tkr)
    feats <- list()
    # AR(1)
    for (w in cfg$ar_windows) feats[[paste0("ar1_corr_", w, "d")]] <- rolling_autocorr(r, w)
    # Sign persistence
    for (w in cfg$sign_persist_windows) feats[[paste0("sign_persist_", w, "d")]] <- rolling_sign_persist(r, w)
    # Momentum & short history
    feats$ret_1d  <- shift(r, 1L, type="lag")
    feats$ret_5d  <- compound_past_simple(r, 5L)
    feats$ret_20d <- compound_past_simple(r, 20L)
    # Volatility feats
    for (w in cfg$vol_feat_windows) feats[[paste0("vol_",w,"d")]] <- shift(rollapply(r, w, sd, align="right", fill=NA_real_), 1L)
    # Price-index z-score vs rolling MA
    price_index <- cumprod(1 + ifelse(is.na(r), 0, r))
    for (w in cfg$z_score_windows){
      ma <- rollapply(price_index, w, mean, align="right", fill=NA_real_)
      sdv <- rollapply(price_index, w, sd, align="right", fill=NA_real_)
      feats[[paste0("z_ma_", w, "d")]] <- shift((price_index - ma)/sdv, 1L)
    }
    feats_dt <- as.data.table(feats)
    # Forward returns & momentum windows for all horizons
    fwd_list <- list(); mom_list <- list()
    for (hz in cfg$horizons){
      fwd_list[[paste0("fwd_", hz$h, "d")]] <- compound_forward_simple(r, hz$h)
      mom_list[[paste0("mom_", hz$k, "d")]] <- compound_past_simple(r, hz$k)
    }
    fwd_dt <- as.data.table(fwd_list)
    mom_dt <- as.data.table(mom_list)
    ii <- ii + 1L
    frames[[ii]] <- cbind(base, feats_dt, fwd_dt, mom_dt)
  }
  frames <- frames[seq_len(ii)]
  if (!length(frames)) stop("No usable tickers after cleaning.")
  panel <- rbindlist(frames, use.names=TRUE, fill=TRUE)

  # Cross-sectional ranks for interpretability
  rank_cols <- c("ret_1d","ret_5d","ret_20d", paste0("z_ma_", cfg$z_score_windows, "d"))
  for (col in rank_cols[rank_cols %in% names(panel)]) {
    panel[, paste0("cs_rank_", col) := {
      x <- get(col); ave(rank(x, na.last="keep", ties.method="average")/sum(!is.na(x)), Date)
    }, by=Date]
  }

  # daily vol per ticker
  panel[, daily_vol := ave(panel$ret_1d, panel$ticker, FUN=function(x)
    rollapply(x, cfg$vol_window, sd, align="right", fill=NA_real_))]

  # Vol-scaled label gate & labels
  for (hz in cfg$horizons){
    name <- hz$name; h <- hz$h; k <- hz$k
    fwd_col <- paste0("fwd_", h, "d")
    mom_col <- paste0("mom_", k, "d")
    gate <- cfg$vol_k * panel$daily_vol * sqrt(max(h,1))
    # within-ticker fill of gate
    gate <- ave(gate, panel$ticker, FUN=function(s){
      med <- median(s, na.rm=TRUE); if (!is.finite(med)) med <- 0
      ifelse(is.na(s), med, s)
    })
    sign_future <- sign(panel[[fwd_col]])
    sign_recent <- sign(panel[[mom_col]])
    mask_big <- abs(panel[[fwd_col]]) > gate
    label <- ifelse(mask_big & (sign_recent!=0) & (sign_future == -sign_recent), 1L,
                    ifelse(mask_big & (sign_recent!=0), 0L, NA_integer_))
    panel[[paste0("label_mr_", name)]] <- label
  }

  # drop rows with NA in feature inputs
  drop_cols <- c("Date","ticker","daily_vol",
                 grep("^fwd_|^mom_|^label_", names(panel), value=TRUE))
  feat_cols <- setdiff(names(panel), drop_cols)
  panel <- panel[complete.cases(panel[, ..feat_cols])]
  panel[]
}

# -------------------------
# Splits
# -------------------------
walk_forward_windows <- function(dates, train_years, val_years, tdy){
  uniq <- sort(unique(as.Date(dates)))
  n_train <- as.integer(train_years * tdy)
  n_val   <- as.integer(val_years   * tdy)
  starts <- seq(1L, length(uniq) - (n_train + n_val) + 1L, by = n_val)
  wins <- list()
  for (s in starts){
    tr <- uniq[s:(s+n_train-1L)]
    va <- uniq[(s+n_train):(s+n_train+n_val-1L)]
    if (!length(tr) || !length(va)) next
    wins[[length(wins)+1L]] <- list(tr_start=tr[1], tr_end=tr[length(tr)],
                                    va_start=va[1], va_end=va[length(va)])
  }
  wins
}

purged_inner_splits <- function(dates, n_splits, purge_days){
  # Simple forward rolling splits with purge before val start on train side
  N <- length(dates)
  # indices for K-fold-like time splits
  # Use evenly spaced split points:
  cuts <- unique(floor(seq(1, N, length.out = n_splits+1)))
  if (length(cuts) < 2L) return(list())
  out <- list()
  for (k in 1:n_splits){
    tr_idx <- seq(1, cuts[k+1]-1L)
    va_idx <- seq(cuts[k]+1L, min(cuts[k+1], N))
    if (!length(tr_idx) || !length(va_idx)) next
    val_start <- as.Date(dates[min(va_idx)])
    purge_cut <- val_start - purge_days
    keep <- as.Date(dates[tr_idx]) <= purge_cut & as.Date(dates[tr_idx]) < val_start
    tr_idx_purged <- tr_idx[keep]
    if (!length(tr_idx_purged)) next
    out[[length(out)+1L]] <- list(tr=tr_idx_purged, va=va_idx)
  }
  out
}

# -------------------------
# Model builders (glmnet)
# -------------------------
fit_glmnet_logit <- function(X, y, alpha, C){
  # glmnet uses lambda; Python used C = 1/lambda
  # We'll map by setting lambda = 1/C grid around that value
  set.seed(42)
  lambda_target <- 1.0 / C
  lam_seq <- sort(unique(c(lambda_target * c(10, 3, 1, 1/3, 1/10), 0.0)), decreasing=TRUE)
  glmnet::glmnet(x=X, y=y, alpha=alpha, family="binomial", lambda=lam_seq,
                 standardize=TRUE)
}
predict_prob_glmnet <- function(model, X){
  as.numeric(pmin(pmax(predict(model, newx=X, type="response", s=model$lambda[which.max(model$dev.ratio)]), 1e-6), 1-1e-6))
}

# -------------------------
# Magnitude regressor (xgboost if available)
# -------------------------
fit_regressor <- function(X, y){
  y <- as.numeric(y)
  keep <- is.finite(y)
  if (sum(keep) < 30 || sd(y[keep]) == 0) return(list(model=NULL, med=median(y[keep], na.rm=TRUE)))
  med <- median(y[keep], na.rm=TRUE)
  if (requireNamespace("xgboost", quietly=TRUE)){
    dtr <- xgboost::xgb.DMatrix(data = X[keep,,drop=FALSE], label = y[keep])
    set.seed(42)
    mdl <- xgboost::xgb.train(
      params=list(objective="reg:squarederror", eta=0.05, max_depth=3, subsample=0.8, colsample_bytree=0.8),
      data=dtr, nrounds=300, verbose=0
    )
    return(list(model=mdl, med=med))
  } else {
    return(list(model=NULL, med=med))
  }
}
predict_regressor <- function(obj, X){
  if (is.null(obj$model)) {
    rep(ifelse(is.finite(obj$med), obj$med, 0.0), nrow(X))
  } else {
    as.numeric(pmax(0, xgboost::predict(obj$model, xgboost::xgb.DMatrix(X))))
  }
}

# -------------------------
# Core: one horizon backtest
# -------------------------
run_one_horizon <- function(panel, horizon_name, cfg){
  label_col <- paste0("label_mr_", horizon_name)
  drop_cols <- c("Date","ticker","daily_vol",
                 grep("^fwd_|^mom_|^label_", names(panel), value=TRUE))
  feat_cols <- setdiff(names(panel), drop_cols)

  df <- panel[!is.na(panel[[label_col]])]
  if (!nrow(df)) return(list(preds=data.table(), metrics=data.table()))

  X_all <- as.matrix(df[, ..feat_cols])
  y_all <- as.integer(df[[label_col]])
  dates_all <- as.Date(df$Date)

  hz <- cfg$horizons[[which(vapply(cfg$horizons, function(h) h$name==horizon_name, logical(1)))]]
  h_days <- hz$h; k_days <- hz$k
  fwd_col <- paste0("fwd_", h_days, "d")
  mom_col <- paste0("mom_", k_days, "d")

  windows <- walk_forward_windows(df$Date, cfg$train_years, cfg$validation_years, cfg$trading_days_per_year)
  all_preds <- list()

  for (w_idx in seq_along(windows)){
    w <- windows[[w_idx]]
    # horizon-aware purge + embargo
    train_cutoff <- w$tr_end - h_days
    test_start_adj <- w$va_start + cfg$embargo_days
    test_cutoff <- w$va_end - h_days

    in_tr <- dates_all >= w$tr_start & dates_all <= train_cutoff
    in_te <- dates_all >= test_start_adj & dates_all <= test_cutoff
    if (!any(in_tr) || !any(in_te)) next

    X_tr <- X_all[in_tr,,drop=FALSE]; y_tr <- y_all[in_tr]
    X_te <- X_all[in_te,,drop=FALSE]; y_te <- y_all[in_te]
    dates_tr <- dates_all[in_tr]; dates_te <- df$Date[in_te]
    tickers_te <- df$ticker[in_te]
    fwd_tr <- as.numeric(df[[fwd_col]][in_tr]); fwd_te <- as.numeric(df[[fwd_col]][in_te])
    mom_tr <- sign(as.numeric(df[[mom_col]][in_tr])); mom_te <- sign(as.numeric(df[[mom_col]][in_te]))

    if (length(unique(y_tr)) < 2 || length(unique(y_te)) < 2) next

    # inner CV param search (AUC + PR-AUC; simplified to AUC)
    best_auc <- -Inf; best_alpha <- NA_real_; best_C <- NA_real_; best_model <- NULL
    splits <- purged_inner_splits(dates_tr, cfg$inner_cv_folds, purge_days=h_days)

    for (alpha in cfg$alpha_grid){
      for (C in cfg$reg_strengths_C){
        aucs <- c()
        for (sp in splits){
          mdl <- fit_glmnet_logit(X_tr[sp$tr,,drop=FALSE], y_tr[sp$tr], alpha=alpha, C=C)
          p <- predict_prob_glmnet(mdl, X_tr[sp$va,,drop=FALSE])
          aucs <- c(aucs, auc_safe(y_tr[sp$va], p))
        }
        sc <- mean(aucs)
        if (is.finite(sc) && sc > best_auc){
          best_auc <- sc; best_alpha <- alpha; best_C <- C
        }
      }
    }
    if (!is.finite(best_alpha)) { best_alpha <- 0.0; best_C <- 1.0 }

    # OOS probs for OUTER-TRAIN for isotonic
    oos_prob <- rep(NA_real_, length(y_tr))
    for (sp in splits){
      mdl <- fit_glmnet_logit(X_tr[sp$tr,,drop=FALSE], y_tr[sp$tr], alpha=best_alpha, C=best_C)
      oos_prob[sp$va] <- predict_prob_glmnet(mdl, X_tr[sp$va,,drop=FALSE])
    }
    # fit isotonic if possible
    iso <- tryCatch({
      keep <- is.finite(oos_prob) & (y_tr %in% c(0L,1L))
      if (sum(keep) >= 30 && length(unique(y_tr[keep]))==2) isoreg(oos_prob[keep], y_tr[keep]) else NULL
    }, error=function(e) NULL)

    # temporal calibration split inside OUTER-TRAIN
    uniq <- sort(unique(as.Date(dates_tr)))
    n_cal <- max(as.integer(length(uniq) * cfg$calib_frac), 30L)
    cutoff <- if (length(uniq) > n_cal) uniq[length(uniq)-n_cal+1L] else uniq[length(uniq)]
    calib_mask <- dates_tr >= cutoff
    model_mask <- !calib_mask

    X_tr_model <- X_tr[model_mask,,drop=FALSE]; y_tr_model <- y_tr[model_mask]
    X_tr_calib <- X_tr[calib_mask,,drop=FALSE]; y_tr_calib <- y_tr[calib_mask]
    fwd_tr_calib <- fwd_tr[calib_mask]

    # final classifier on FULL OUTER-TRAIN
    clf_full <- fit_glmnet_logit(X_tr, y_tr, alpha=best_alpha, C=best_C)
    p_raw <- predict_prob_glmnet(clf_full, X_te)
    p_cal <- if (!is.null(iso)) predict_isoreg(iso, p_raw) else p_raw
    p_cal <- pmin(pmax(p_cal, 1e-6), 1-1e-6)

    # magnitude head: separate per-regime (MR vs Momentum)
    y_abs_model <- abs(fwd_tr[model_mask])
    mr_mask_model <- y_tr_model == 1L; mo_mask_model <- y_tr_model == 0L

    reg_mr <- fit_regressor(X_tr_model[mr_mask_model,,drop=FALSE], y_abs_model[mr_mask_model])
    reg_mo <- fit_regressor(X_tr_model[mo_mask_model,,drop=FALSE], y_abs_model[mo_mask_model])

    pred_mr_abs <- predict_regressor(reg_mr, X_te)
    pred_mo_abs <- predict_regressor(reg_mo, X_te)

    exp_move <- p_cal * (-mom_te) * pred_mr_abs + (1.0 - p_cal) * (mom_te) * pred_mo_abs

    # conformal residuals (CALIB slice)
    res_mr <- abs( abs(fwd_tr_calib[y_tr_calib==1L]) - predict_regressor(reg_mr, X_tr_calib[y_tr_calib==1L,,drop=FALSE]) )
    res_mo <- abs( abs(fwd_tr_calib[y_tr_calib==0L]) - predict_regressor(reg_mo, X_tr_calib[y_tr_calib==0L,,drop=FALSE]) )
    q_mr <- conformal_q(res_mr, cfg$conformal_alpha)
    q_mo <- conformal_q(res_mo, cfg$conformal_alpha)

    low_move  <- p_cal * (-mom_te) * (pred_mr_abs - q_mr) + (1.0 - p_cal) * ( mom_te) * (pred_mo_abs - q_mo)
    high_move <- p_cal * (-mom_te) * (pred_mr_abs + q_mr) + (1.0 - p_cal) * ( mom_te) * (pred_mo_abs + q_mo)

    mr_score <- 1.0 - 2.0 * p_cal
    action_conf <- pmax(p_cal, 1.0 - p_cal)

    threshold_used <- NA_real_
    y_pred <- rep(ABSTAIN, length(p_cal))
    abstained <- rep(TRUE, length(p_cal))
    hi <- lo <- rep(FALSE, length(p_cal))

    if (!is.na(cfg$threshold_fixed)) {
      threshold_used <- cfg$threshold_fixed
      hi <- p_cal >= threshold_used; lo <- p_cal <= (1.0 - threshold_used)
    } else if (!is.na(cfg$min_coverage) && cfg$threshold_rule == "coverage"){
      th <- choose_threshold_by_coverage(p_cal, cfg$threshold_grid, cfg$min_coverage)
      threshold_used <- th$threshold
      hi <- p_cal >= threshold_used; lo <- p_cal <= (1.0 - threshold_used)
    }
    if (any(hi | lo)){
      y_pred[hi] <- 1L; y_pred[lo] <- 0L
      abstained <- !(hi | lo)
    }

    preds <- data.table(
      Date = dates_te,
      ticker = tickers_te,
      horizon = horizon_name,
      y_true = y_te,
      fwd_ret = fwd_te,
      mom_sign = mom_te,
      y_prob = p_raw,
      y_prob_cal = p_cal,
      mr_score = mr_score,
      confidence = action_conf,
      exp_move = exp_move,
      pi_low = low_move,
      pi_high = high_move,
      threshold = threshold_used,
      y_pred = y_pred,
      abstained = abstained
    )
    all_preds[[length(all_preds)+1L]] <- preds
  }

  if (!length(all_preds)) return(list(preds=data.table(), metrics=data.table()))
  preds_all <- rbindlist(all_preds, use.names=TRUE, fill=TRUE)

  # per-ticker metrics
  rows <- list()
  for (tkr in unique(preds_all$ticker)){
    g <- preds_all[ticker == tkr]
    yt <- as.integer(g$y_true)
    pp <- as.numeric(g$y_prob_cal)
    aucv <- auc_safe(yt, pp)
    if ("abstained" %in% names(g) && !is.na(cfg$min_coverage)){
      gg <- g[!abstained]
      yt2 <- as.integer(gg$y_true)
      yp2 <- as.integer(gg$y_pred)
      cov <- 1.0 - mean(g$abstained)
      if (length(unique(yt2)) < 2L || !length(yt2)){
        rows[[length(rows)+1L]] <- data.table(ticker=tkr, support=length(yt), covered=length(yt2),
                                              coverage=cov, accuracy=NA_real_, precision=NA_real_,
                                              recall=NA_real_, f1=NA_real_, auc=aucv)
      } else {
        acc <- mean(yt2 == yp2)
        pr  <- if (sum(yp2==1L)) sum(yp2==1L & yt2==1L)/sum(yp2==1L) else 0
        rc  <- if (sum(yt2==1L)) sum(yp2==1L & yt2==1L)/sum(yt2==1L) else 0
        f1  <- if (pr+rc>0) 2*pr*rc/(pr+rc) else 0
        rows[[length(rows)+1L]] <- data.table(ticker=tkr, support=length(yt), covered=length(yt2),
                                              coverage=cov, accuracy=acc, precision=pr, recall=rc,
                                              f1=f1, auc=aucv)
      }
    } else {
      if (length(unique(yt)) < 2L || !length(yt)){
        rows[[length(rows)+1L]] <- data.table(ticker=tkr, support=length(yt),
                                              accuracy=NA_real_, precision=NA_real_,
                                              recall=NA_real_, f1=NA_real_, auc=aucv)
      } else {
        yp <- as.integer(pp >= 0.5)
        acc <- mean(yt==yp)
        pr  <- if (sum(yp==1L)) sum(yp==1L & yt==1L)/sum(yp==1L) else 0
        rc  <- if (sum(yt==1L)) sum(yp==1L & yt==1L)/sum(yt==1L) else 0
        f1  <- if (pr+rc>0) 2*pr*rc/(pr+rc) else 0
        rows[[length(rows)+1L]] <- data.table(ticker=tkr, support=length(yt),
                                              accuracy=acc, precision=pr, recall=rc, f1=f1, auc=aucv)
      }
    }
  }
  metrics <- rbindlist(rows, use.names=TRUE, fill=TRUE)[order(ticker)]
  list(preds=preds_all, metrics=metrics)
}

# -------------------------
# Pipeline (backtest)
# -------------------------
run_pipeline <- function(cfg){
  dir.create(cfg$output_dir, showWarnings=FALSE, recursive=TRUE)
  set.seed(cfg$random_state)

  log_info("Resolving input Excel + sheet…")
  io <- autodiscover_excel_and_sheet(cfg$excel_path, cfg$sheet_name)
  cfg$excel_path <- io$path; cfg$sheet_name <- io$sheet

  log_info("Loading returns (wide)…")
  returns_wide <- load_returns_wide(cfg$excel_path, cfg$sheet_name)
  qc <- validate_returns_wide(returns_wide)
  if (nrow(qc)) fwrite(qc, file=file.path(cfg$output_dir,"data_qc.csv"))
  returns_wide <- unique(returns_wide, by="Date")[order(Date)]

  market_feats <- NULL
  if (cfg$with_market){
    log_info("Loading market context from sheet…")
    mkt <- load_market_from_excel(cfg$excel_path, cfg$market_sheet)
    if (!is.null(mkt) && nrow(mkt)) {
      market_feats <- compute_market_features(mkt)
      log_info("Market features ready.")
    } else {
      log_info("No usable market sheet; proceeding without market features.")
    }
  }

  log_info("Building feature panel + labels…")
  panel <- build_feature_panel(returns_wide, cfg)
  if (!is.null(market_feats)){
    panel <- merge(panel, market_feats, by="Date", all.x=TRUE)
  }

  feat_cols <- setdiff(names(panel),
                       c("Date","ticker","daily_vol",
                         grep("^fwd_|^mom_|^label_", names(panel), value=TRUE)))
  writeLines(feat_cols, con=file.path(cfg$output_dir,"feature_columns.txt"))

  summary_rows <- list()
  for (hz in cfg$horizons){
    name <- hz$name
    log_info(sprintf("=== Horizon: %s ===", name))
    res <- run_one_horizon(panel, name, cfg)
    if (!nrow(res$preds)){
      log_info(sprintf("No results for horizon %s — skipping saves.", name))
      next
    }
    preds_path <- file.path(cfg$output_dir, sprintf("predictions_%s.csv", name))
    metrics_path <- file.path(cfg$output_dir, sprintf("metrics_%s.csv", name))
    fwrite(res$preds[order(Date, ticker)], preds_path)
    fwrite(res$metrics, metrics_path)
    auc_all <- auc_safe(as.integer(res$preds$y_true), as.numeric(res$preds$y_prob_cal))
    coverage <- if (!is.na(cfg$min_coverage) && "abstained" %in% names(res$preds))
      mean(!res$preds$abstained) else mean(is.finite(res$preds$y_prob_cal))
    summary_rows[[length(summary_rows)+1L]] <- data.table(horizon=name, rows=nrow(res$preds),
                                                          auc=as.numeric(auc_all), coverage=as.numeric(coverage))
  }
  if (length(summary_rows)){
    fwrite(rbindlist(summary_rows), file.path(cfg$output_dir, "summary.csv"))
  }

  meta <- list(
    timestamp = format(Sys.time(), "%Y-%m-%dT%H:%M:%SZ"),
    excel = cfg$excel_path,
    sheet = cfg$sheet_name,
    model = "logit(glmnet)",
    mode = "backtest",
    config = cfg
  )
  writeLines(jsonlite::toJSON(meta, pretty=TRUE, auto_unbox=TRUE),
             con=file.path(cfg$output_dir, "run_meta.json"))
  log_info("Done. Artifacts: predictions_*.csv, metrics_*.csv, summary.csv, run_meta.json")
}

# -------------------------
# Forecast mode
# -------------------------
forecast_one_horizon <- function(train_panel, forecast_panel, horizon_name, cfg){
  label_col <- paste0("label_mr_", horizon_name)
  drop_cols <- c("Date","ticker","daily_vol",
                 grep("^fwd_|^mom_|^label_", names(train_panel), value=TRUE))
  feat_cols <- setdiff(names(train_panel), drop_cols)

  df_tr <- train_panel[!is.na(train_panel[[label_col]])]
  if (nrow(df_tr) < 100 || length(unique(df_tr[[label_col]])) < 2) return(data.table())

  X_tr <- as.matrix(df_tr[, ..feat_cols]); y_tr <- as.integer(df_tr[[label_col]])
  dates_tr <- as.Date(df_tr$Date)

  hz <- cfg$horizons[[which(vapply(cfg$horizons, function(h) h$name==horizon_name, logical(1)))]]
  h_days <- hz$h; k_days <- hz$k
  fwd_col <- paste0("fwd_", h_days, "d"); mom_col <- paste0("mom_", k_days, "d")
  fwd_tr <- as.numeric(df_tr[[fwd_col]])

  X_fc <- as.matrix(forecast_panel[, ..feat_cols])
  tickers_fc <- forecast_panel$ticker
  mom_fc_sign <- sign(as.numeric(forecast_panel[[mom_col]]))

  # inner CV param search
  best_auc <- -Inf; best_alpha <- NA_real_; best_C <- NA_real_
  splits <- purged_inner_splits(dates_tr, cfg$inner_cv_folds, purge_days=h_days)
  for (alpha in cfg$alpha_grid){
    for (C in cfg$reg_strengths_C){
      aucs <- c()
      for (sp in splits){
        mdl <- fit_glmnet_logit(X_tr[sp$tr,,drop=FALSE], y_tr[sp$tr], alpha=alpha, C=C)
        p <- predict_prob_glmnet(mdl, X_tr[sp$va,,drop=FALSE])
        aucs <- c(aucs, auc_safe(y_tr[sp$va], p))
      }
      sc <- mean(aucs)
      if (is.finite(sc) && sc > best_auc) { best_auc <- sc; best_alpha <- alpha; best_C <- C }
    }
  }
  if (!is.finite(best_alpha)) { best_alpha <- 0.0; best_C <- 1.0 }

  # OOS probs for isotonic
  oos_prob <- rep(NA_real_, length(y_tr))
  for (sp in splits){
    mdl <- fit_glmnet_logit(X_tr[sp$tr,,drop=FALSE], y_tr[sp$tr], alpha=best_alpha, C=best_C)
    oos_prob[sp$va] <- predict_prob_glmnet(mdl, X_tr[sp$va,,drop=FALSE])
  }
  iso <- tryCatch({
    keep <- is.finite(oos_prob) & (y_tr %in% c(0L,1L))
    if (sum(keep) >= 30 && length(unique(y_tr[keep]))==2) isoreg(oos_prob[keep], y_tr[keep]) else NULL
  }, error=function(e) NULL)

  # temporal calibration inside train
  uniq <- sort(unique(as.Date(dates_tr)))
  n_cal <- max(as.integer(length(uniq) * cfg$calib_frac), 30L)
  cutoff <- if (length(uniq) > n_cal) uniq[length(uniq)-n_cal+1L] else uniq[length(uniq)]
  calib_mask <- dates_tr >= cutoff
  model_mask <- !calib_mask
  X_tr_model <- X_tr[model_mask,,drop=FALSE]; y_tr_model <- y_tr[model_mask]
  X_tr_calib <- X_tr[calib_mask,,drop=FALSE]; y_tr_calib <- y_tr[calib_mask]
  fwd_tr_calib <- fwd_tr[calib_mask]

  clf_final <- fit_glmnet_logit(X_tr, y_tr, alpha=best_alpha, C=best_C)
  p_raw <- predict_prob_glmnet(clf_final, X_fc)
  p_cal <- if (!is.null(iso)) predict_isoreg(iso, p_raw) else p_raw
  p_cal <- pmin(pmax(p_cal, 1e-6), 1-1e-6)

  # magnitude head
  y_abs_model <- abs(fwd_tr[model_mask])
  reg_mr <- fit_regressor(X_tr_model[y_tr_model==1L,,drop=FALSE], y_abs_model[y_tr_model==1L])
  reg_mo <- fit_regressor(X_tr_model[y_tr_model==0L,,drop=FALSE], y_abs_model[y_tr_model==0L])

  pred_mr_abs <- predict_regressor(reg_mr, X_fc)
  pred_mo_abs <- predict_regressor(reg_mo, X_fc)

  exp_move <- p_cal * (-mom_fc_sign) * pred_mr_abs + (1.0 - p_cal) * (mom_fc_sign) * pred_mo_abs

  res_mr <- abs( abs(fwd_tr_calib[y_tr_calib==1L]) - predict_regressor(reg_mr, X_tr_calib[y_tr_calib==1L,,drop=FALSE]) )
  res_mo <- abs( abs(fwd_tr_calib[y_tr_calib==0L]) - predict_regressor(reg_mo, X_tr_calib[y_tr_calib==0L,,drop=FALSE]) )
  q_mr <- conformal_q(res_mr, cfg$conformal_alpha)
  q_mo <- conformal_q(res_mo, cfg$conformal_alpha)

  low_move  <- p_cal * (-mom_fc_sign) * (pred_mr_abs - q_mr) + (1.0 - p_cal) * ( mom_fc_sign) * (pred_mo_abs - q_mo)
  high_move <- p_cal * (-mom_fc_sign) * (pred_mr_abs + q_mr) + (1.0 - p_cal) * ( mom_fc_sign) * (pred_mo_abs + q_mo)

  threshold_used <- NA_real_
  y_pred <- rep(ABSTAIN, length(p_cal))
  abstained <- rep(TRUE, length(p_cal))
  hi_prob <- lo_prob <- rep(FALSE, length(p_cal))

  if (!is.na(cfg$threshold_fixed)) {
    threshold_used <- cfg$threshold_fixed
    hi_prob <- p_cal >= threshold_used
    lo_prob <- p_cal <= (1.0 - threshold_used)
  } else if (!is.na(cfg$min_coverage) && cfg$threshold_rule == "coverage"){
    th <- choose_threshold_by_coverage(p_cal, cfg$threshold_grid, cfg$min_coverage)
    threshold_used <- th$threshold
    hi_prob <- p_cal >= threshold_used
    lo_prob <- p_cal <= (1.0 - threshold_used)
  }

  mag_filter <- rep(TRUE, length(p_cal))
  if (!is.na(cfg$min_exp_move_abs)) mag_filter <- abs(exp_move) >= cfg$min_exp_move_abs

  hi <- hi_prob & mag_filter
  lo <- lo_prob & mag_filter
  if (any(hi | lo)){
    y_pred[hi] <- 1L; y_pred[lo] <- 0L; abstained <- !(hi | lo)
  }

  cbind(
    data.table(
      forecast_date = forecast_panel$Date,
      ticker = tickers_fc,
      horizon = horizon_name,
      y_prob = p_raw,
      y_prob_cal = p_cal,
      confidence = pmax(p_cal, 1.0 - p_cal),
      exp_move = exp_move,
      pi_low = low_move,
      pi_high = high_move,
      mom_sign = mom_fc_sign,
      threshold = threshold_used,
      y_pred = y_pred,
      abstained = abstained
    ),
    forecast_panel[, ..feat_cols]
  )
}

run_forecast <- function(cfg){
  dir.create(cfg$output_dir, showWarnings=FALSE, recursive=TRUE)
  set.seed(cfg$random_state)
  log_info("--- Running in FORECAST mode ---")

  io <- autodiscover_excel_and_sheet(cfg$excel_path, cfg$sheet_name)
  cfg$excel_path <- io$path; cfg$sheet_name <- io$sheet

  log_info("Loading returns (wide)…")
  returns_wide <- load_returns_wide(cfg$excel_path, cfg$sheet_name)
  returns_wide <- unique(returns_wide, by="Date")[order(Date)]

  market_feats <- NULL
  if (cfg$with_market){
    log_info("Loading market context from sheet…")
    mkt <- load_market_from_excel(cfg$excel_path, cfg$market_sheet)
    if (!is.null(mkt) && nrow(mkt)){
      market_feats <- compute_market_features(mkt)
    } else {
      log_info("No usable market sheet; proceeding without market features.")
    }
  }

  log_info("Building feature panel…")
  panel <- build_feature_panel(returns_wide, cfg)
  if (!is.null(market_feats)){
    panel <- merge(panel, market_feats, by="Date", all.x=TRUE)
  }

  last_feature_date <- max(panel$Date)
  log_info(sprintf("Most recent feature date: %s", as.character(last_feature_date)))
  train_start_date <- as.Date(last_feature_date) - as.difftime(365L*cfg$train_years, units="days")
  log_info(sprintf("Training window: %s → %s", as.character(train_start_date), as.character(last_feature_date)))

  all_fc <- list()
  for (hz in cfg$horizons){
    name <- hz$name; h_days <- hz$h
    log_info(sprintf("[Forecast] Horizon %s", name))
    train_cutoff <- last_feature_date - h_days
    train_panel <- panel[Date >= train_start_date & Date <= train_cutoff]
    forecast_panel <- panel[Date == last_feature_date]
    if (!nrow(train_panel) || !nrow(forecast_panel)){
      log_info(sprintf("[Forecast] Skipping %s: insufficient rows.", name))
      next
    }
    df_fc <- forecast_one_horizon(train_panel, forecast_panel, name, cfg)
    if (nrow(df_fc)) all_fc[[length(all_fc)+1L]] <- df_fc
  }

  if (!length(all_fc)){ log_info("No forecasts produced for any horizon."); return(invisible()) }
  final_fc <- rbindlist(all_fc, use.names=TRUE, fill=TRUE)[order(horizon, ticker)]

  out_csv <- file.path(cfg$output_dir, sprintf("forecast_%s.csv", format(Sys.time(), "%Y%m%d")))
  fwrite(final_fc, out_csv, sep=",")
  log_info(sprintf("Saved forecast file: %s (%d rows)", basename(out_csv), nrow(final_fc)))

  meta <- list(
    timestamp = format(Sys.time(), "%Y-%m-%dT%H:%M:%SZ"),
    excel = cfg$excel_path,
    sheet = cfg$sheet_name,
    model = "logit(glmnet)",
    mode = "forecast",
    last_feature_date = as.character(last_feature_date),
    config = cfg,
    artifacts = list(forecast_csv = basename(out_csv))
  )
  writeLines(jsonlite::toJSON(meta, pretty=TRUE, auto_unbox=TRUE),
             con=file.path(cfg$output_dir, "run_meta_forecast.json"))
  log_info("Forecast complete. Artifacts: forecast_YYYYMMDD.csv, run_meta_forecast.json")
}

# -------------------------
# CLI
# -------------------------
main <- function(){
  option_list <- list(
    make_option("--mode", default="forecast", help="backtest or forecast"),
    make_option("--excel", default=NULL, help="Path to Excel file"),
    make_option("--sheet", default=NULL, help="Returns sheet name"),
    make_option("--out", default="results", help="Output directory"),
    make_option("--train_years", type="integer", default=3L),
    make_option("--val_years", type="integer", default=1L),
    make_option("--embargo", type="integer", default=5L),
    make_option("--random_state", type="integer", default=42L),
    make_option("--min_valid_frac", type="double", default=0.70),
    make_option("--no_market", action="store_true", default=FALSE, help="Disable market merge"),
    make_option("--market_sheet", default="Market"),
    make_option("--min_coverage", type="double", default=NA_real_),
    make_option("--threshold_fixed", type="double", default=NA_real_),
    make_option("--min_exp_move", type="double", default=NA_real_),
    make_option("--threshold_rule", default="coverage")
  )
  opt <- parse_args(OptionParser(option_list=option_list))
  cfg <- make_config(
    excel_path = opt$excel, sheet_name = opt$sheet, output_dir = opt$out,
    with_market = !isTRUE(opt$no_market), market_sheet = opt$market_sheet,
    train_years = opt$train_years, validation_years = opt$val_years,
    embargo_days = opt$embargo, random_state = opt$random_state,
    min_valid_frac = opt$min_valid_frac,
    min_coverage = opt$min_coverage, threshold_fixed = opt$threshold_fixed,
    threshold_rule = opt$threshold_rule, min_exp_move_abs = opt$min_exp_move
  )
  if (opt$mode == "forecast") run_forecast(cfg) else run_pipeline(cfg)
}

if (identical(environment(), globalenv()) && !length(sys.frames())) main()
