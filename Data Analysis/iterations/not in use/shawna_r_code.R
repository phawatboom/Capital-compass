# =========================
# Packages
# =========================
library(readxl)
library(dplyr)
library(tidyr)
library(glmnet)
library(data.table)

# =========================
# Config
# =========================
path      <- "MXUS_Data.xlsx"
sheet     <- "Returns"
fwd_h     <- 5      # forward horizon (days) for the label
thr_label <- 0.005  # 0.5% future move threshold: only learn on |fwd_ret| > thr_label
years_tr  <- 3      # train window length (years)
years_val <- 1      # validation window length (years)
alpha_grid <- c(0, 0.5, 1)                # ridge, elastic, lasso
thr_grid   <- seq(0.55, 0.85, by = 0.01)  # probability cutoffs to test (two-sided band)
inner_nfolds <- 5                         # cv.glmnet folds for lambda

# =========================
# Helpers
# =========================
read_returns_clean <- function(path, sheet) {
  raw <- readxl::read_excel(path, sheet = sheet, col_names = FALSE)
  date_row <- which(trimws(as.character(raw[[1]])) == "Date")
  stopifnot(length(date_row) == 1)
  hdr <- as.character(unlist(raw[date_row, ]))
  dat <- raw[(date_row + 1):nrow(raw), , drop = FALSE]
  colnames(dat) <- hdr
  dat <- dat %>%
    mutate(Date = as.Date(as.numeric(Date), origin = "1899-12-30")) %>%
    filter(!is.na(Date))
  num_cols <- setdiff(names(dat), "Date")
  dat[num_cols] <- lapply(dat[num_cols], function(x) suppressWarnings(as.numeric(x)))
  dat
}

# AUC (robust; never NA; clamps to [0,1])
auc_safe <- function(p, y) {
  keep <- is.finite(p) & !is.na(y)
  if (!any(keep)) return(0.5)
  p <- as.numeric(p[keep])
  y <- as.integer(y[keep])
  n1 <- sum(y == 1L); n0 <- sum(y == 0L)
  if (n1 == 0L || n0 == 0L) return(0.5)
  if (isTRUE(all.equal(sd(p), 0))) return(0.5)
  r <- rank(p, ties.method = "average")
  n1_d <- as.double(n1); n0_d <- as.double(n0)
  num <- as.double(sum(r[y == 1L])) - n1_d * (n1_d + 1.0) / 2.0
  den <- n1_d * n0_d
  if (!is.finite(num) || !is.finite(den) || den == 0) return(0.5)
  auc <- num / den
  if (!is.finite(auc)) return(0.5)
  max(0, min(1, auc))
}

# Build folds on unique dates (walk-forward)
make_folds <- function(all_dates, years_tr, years_val) {
  tr <- years_tr * 252L
  va <- years_val * 252L
  starts <- seq.int(1L, length(all_dates) - (tr + va) + 1L, by = va)
  lapply(starts, function(s) {
    tr_idx <- s:(s + tr - 1L)
    va_idx <- (s + tr):(s + tr + va - 1L)
    list(train_dates = all_dates[tr_idx], val_dates = all_dates[va_idx])
  })
}

# =========================
# Data prep
# =========================
rets <- read_returns_clean(path, sheet)

# Long format (stock, Date, ret)
DT <- as.data.table(rets)
setkey(DT, Date)
long <- melt(DT, id.vars = "Date", variable.name = "stock", value.name = "ret")
setorder(long, stock, Date)

# =========================
# Feature engineering (by stock)
# =========================
# price index px (treat NA returns as 0 ONLY for cumprod stability)
long[, px := cumprod(1 + fifelse(is.na(ret), 0, ret)), by = stock]

# simple AR proxy
long[, ret_lag1 := shift(ret, 1L), by = stock]

# momentum on price
long[, ret_5  := px / shift(px, 5L)  - 1, by = stock]
long[, ret_20 := px / shift(px, 20L) - 1, by = stock]

# rolling mean/sd on price for z-score
long[, ma_20  := frollmean(px, 20L), by = stock]
long[, sd_20  := frollapply(px, 20L, sd, na.rm = TRUE), by = stock]
# guard against tiny sd to avoid Inf
long[, z_ma_20 := (px - ma_20) / pmax(sd_20, 1e-8)]

# volatility (SD of returns) over 20d
long[, vol_20 := frollapply(ret, 20L, sd, na.rm = TRUE), by = stock]

# Forward return for label (from price)
long[, fwd_ret := shift(px, -fwd_h) / px - 1, by = stock]

# Thresholded label: (1 = up, 0 = down, NA = small/weak move)
long[, y := fifelse(fwd_ret >  thr_label, 1L,
                    fifelse(fwd_ret < -thr_label, 0L, NA_integer_))]

# Drop rows without features/labels
feat <- long[, .(Date, stock, y, ret_lag1, ret_5, ret_20, vol_20, z_ma_20)]
feat <- feat[complete.cases(feat)]

# Design matrix (glmnet will standardize internally)
X <- model.matrix(~ ret_lag1 + ret_5 + ret_20 + vol_20 + z_ma_20, data = feat)[, -1, drop = FALSE]
y <- feat$y
dates  <- feat$Date
stocks <- feat$stock

# =========================
# Walk-forward CV (outer)
# =========================
all_dates <- sort(unique(dates))
folds <- make_folds(all_dates, years_tr, years_val)

cv_prob_store <- list()  # per alpha: OOS probabilities aligned to feat rows

for (alpha in alpha_grid) {
  p_all <- rep(NA_real_, nrow(feat))
  for (f in seq_along(folds)) {
    tr_dates <- folds[[f]]$train_dates
    va_dates <- folds[[f]]$val_dates
    tr_idx <- which(dates %in% tr_dates)
    va_idx <- which(dates %in% va_dates)
    
    # need both classes to fit
    if (length(unique(y[tr_idx])) < 2L) next
    
    cvfit <- cv.glmnet(
      x = X[tr_idx, , drop = FALSE],
      y = y[tr_idx],
      family = "binomial",
      alpha = alpha,
      nfolds = inner_nfolds,
      type.measure = "deviance",
      standardize = TRUE,
      maxit = 1e5
    )
    
    p <- as.numeric(predict(cvfit, newx = X[va_idx, , drop = FALSE],
                            s = cvfit$lambda.min, type = "response"))
    p_all[va_idx] <- p
  }
  cv_prob_store[[as.character(alpha)]] <- p_all
}

# =========================
# Evaluate thresholds & collect metrics (per fold)
# =========================
eval_table <- list()

for (alpha in names(cv_prob_store)) {
  p_all <- cv_prob_store[[alpha]]
  
  for (f in seq_along(folds)) {
    va_dates <- folds[[f]]$val_dates
    va_idx   <- which(dates %in% va_dates)
    
    p     <- p_all[va_idx]
    y_sub <- y[va_idx]
    
    keep <- is.finite(p) & !is.na(y_sub)
    if (!any(keep)) next
    
    y_keep <- as.integer(y_sub[keep])
    p_keep <- as.numeric(p[keep])
    
    # For stock-count metrics
    stock_keep <- stocks[va_idx][keep]
    date_keep  <- dates[va_idx][keep]
    
    # AUC (threshold-free)
    fold_auc <- auc_safe(p_keep, y_keep)
    
    for (thr in thr_grid) {
      # Two-sided decision rule with abstention:
      # predict 1 if p >= thr; predict 0 if p <= 1 - thr; else NA
      pred <- rep(NA_integer_, length(p_keep))
      pred[p_keep >=  thr]      <- 1L
      pred[p_keep <= (1 - thr)] <- 0L
      
      has_pred <- !is.na(pred)
      
      covg <- mean(has_pred)  # row-level coverage within this fold
      acc  <- if (all(is.na(pred))) NA_real_ else mean(pred == y_keep, na.rm = TRUE)
      
      # ---- NEW: stock-count metrics ----
      n_unique_stocks <- if (any(has_pred)) data.table::uniqueN(stock_keep[has_pred]) else 0L
      
      if (any(has_pred)) {
        dt_day <- data.table::data.table(date = date_keep[has_pred],
                                         stock = stock_keep[has_pred])
        stocks_per_day <- dt_day[, .N, by = date][, N]
        avg_stocks_per_day <- mean(stocks_per_day)
      } else {
        avg_stocks_per_day <- 0
      }
      # ----------------------------------
      
      eval_table[[length(eval_table) + 1L]] <- data.frame(
        alpha     = as.numeric(alpha),
        fold      = f,
        threshold = thr,
        accuracy  = acc,
        auc       = fold_auc,
        coverage  = covg,
        n_unique_stocks    = n_unique_stocks,
        avg_stocks_per_day = avg_stocks_per_day,
        stringsAsFactors = FALSE
      )
    }
  }
}

# =========================
# Aggregate across folds and rank
# =========================
results <- bind_rows(eval_table) %>%
  group_by(alpha, threshold) %>%
  summarise(
    mean_acc = mean(accuracy, na.rm = TRUE),
    mean_auc = mean(auc, na.rm = TRUE),
    mean_cov = mean(coverage, na.rm = TRUE),
    mean_n_stocks       = mean(n_unique_stocks, na.rm = TRUE),     # NEW
    mean_stocks_per_day = mean(avg_stocks_per_day, na.rm = TRUE),  # NEW
    n_folds  = n(),
    .groups  = "drop"
  ) %>%
  mutate(score_prod = mean_acc * mean_cov) %>%
  arrange(desc(score_prod), desc(mean_acc))

print(head(results, 12))

best <- results %>% slice(1)
cat(sprintf(
  "\nBest (by accuracy*coverage): alpha=%.2f, thr=%.2f | acc=%.3f, AUC=%.3f, cov=%.2f | mean_n_stocks=%.1f, mean_stocks_per_day=%.1f\n",
  best$alpha, best$threshold, best$mean_acc, best$mean_auc, best$mean_cov,
  best$mean_n_stocks, best$mean_stocks_per_day
))

# =========================
# Refit on ALL data with chosen alpha (keep for live use)
# =========================
alpha_star <- best$alpha[1]
thr_star   <- best$threshold[1]

cvfit_all <- cv.glmnet(
  x = X, y = y, family = "binomial",
  alpha = alpha_star, nfolds = inner_nfolds,
  type.measure = "deviance", standardize = TRUE, maxit = 1e5
)

cat("\nRefit complete. Use `cvfit_all` with s = \"lambda.min\" for predictions.\n")
cat(sprintf("Locked alpha: %.2f | Locked classification threshold: %.2f\n",
            alpha_star, thr_star))