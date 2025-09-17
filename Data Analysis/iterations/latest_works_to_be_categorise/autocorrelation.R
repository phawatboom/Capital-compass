# =========================
# Libraries
# =========================
# Need to do install.packages("...") in console for each library
library(readxl)
library(dplyr)
library(tidyr)
library(zoo)
library(ggplot2)
library(ggrepel)
library(rlang)
library(data.table)
library(roll)        # fast rolling correlation / variance / sums (C)
library(RcppRoll)    # fast rolling sums/vars (C++)


# =========================
# 0) Load & clean Excel
#     (handles extra header/meta rows)
# =========================
path <- "MXUS_data.xlsx"   # adjust if needed
raw  <- readxl::read_excel(path, col_names = FALSE, sheet = "Returns")

# find the header row where first column literally equals "Date"
date_row <- which(trimws(as.character(raw[[1]])) == "Date")
stopifnot(length(date_row) == 1)

hdr <- as.character(unlist(raw[date_row, ]))
dat <- raw[(date_row + 1):nrow(raw), , drop = FALSE]
colnames(dat) <- hdr

# keep Date + stock columns; coerce returns to numeric
# keep Date + stock columns; coerce returns to numeric (but NOT Date)
returns_df <- dat %>%
  select(where(~ !all(is.na(.x)))) %>%
  mutate(Date = as.Date(as.numeric(Date), origin = "1899-12-30")) %>%
  mutate(across(-Date, ~ suppressWarnings(as.numeric(.x)))) %>%
  filter(!is.na(Date)) %>%
  filter(rowSums(!is.na(across(-Date))) > 0) %>%
  arrange(Date)

# sanity: drop rows where Date is NA
returns_df <- returns_df %>% filter(!is.na(Date))

# =========================
# 1) Helpers
# =========================

# mean of ACF at lags 1..K inside a window vector x
mean_acf_lags <- function(x, lags = 1:10) {
  x <- x[is.finite(x)]
  n <- length(x)
  if (n <= max(lags)) return(NA_real_)
  acfs <- vapply(lags, function(k) {
    # correlation of x_t with x_{t-k} inside the window
    cor(x[(k+1):n], x[1:(n-k)], use = "complete.obs")
  }, numeric(1))
  mean(acfs, na.rm = TRUE)
}

# Lo–MacKinlay-style variance ratio at horizon q inside a window x
variance_ratio <- function(x, q) {
  x <- x[is.finite(x)]
  n <- length(x)
  if (n < q + 1) return(NA_real_)
  # q-period returns (rolling sums)
  rq <- rollapply(x, q, sum, align = "right", fill = NA)
  var_q <- var(rq, na.rm = TRUE)
  var_1 <- var(x, na.rm = TRUE)
  if (!is.finite(var_q) || !is.finite(var_1) || var_1 == 0) return(NA_real_)
  var_q / (q * var_1)
}

# compute rolling features for one numeric returns vector
compute_rolling_features_fast <- function(ret, window = 252, lags = 1:10, vr_q = c(5,10)) {
  trend_score <- roll_trend_score_fast(ret, window = window, lags = lags)
  
  # Handle empty vr_q safely
  if (length(vr_q) > 0) {
    vr_list <- lapply(vr_q, function(q) variance_ratio_fast(ret, q = q, window = window))
    names(vr_list) <- paste0("VR", vr_q)
  } else {
    vr_list <- list()
  }
  
  list(trend_score = trend_score, vr_list = vr_list)
}


# =========================
# 2) Long-format + rolling metrics for ALL stocks
# =========================
window_days <- 252
acf_lags    <- 1:10
vr_q <- c(5, 10)

# compute per-stock rolling metrics

# -----------------------
# Helpers (fast versions)
# -----------------------

# Rolling mean of autocorrelations at lags 1:K using roll::roll_cor
# Returns a numeric vector aligned with x length, NA for first window_days-1
roll_trend_score_fast <- function(x, window = 252, lags = 1:10) {
  n <- length(x)
  if (n < window + max(lags)) return(rep(NA_real_, n))
  
  # For each lag k, compute rolling correlation between x[t] and x[t-k]
  # Width must be >= 2; we use (window) pairs so the correlation is based on the same horizon.
  acf_mat <- sapply(lags, function(k) {
    x1 <- x[(k+1):n]
    x2 <- x[1:(n-k)]
    # roll_cor expects equal-length vectors; width = window (or window - k? choose window for consistency)
    rc <- roll::roll_cor(x1, x2, width = window, min_obs = window, center = FALSE)
    # pad the first k positions with NA to re-align to original length n
    c(rep(NA_real_, k), rc)
  })
  
  # Average across lags row-wise
  # First (window_days-1)+max(lags) positions will be NA; that’s fine/expected
  rowMeans(acf_mat, na.rm = TRUE)
}

# Fast variance ratio using RcppRoll
variance_ratio_fast <- function(x, q, window = 252) {
  n <- length(x)
  if (n < window) return(rep(NA_real_, n))
  # rolling q-sum of returns => q-period returns
  rq <- RcppRoll::roll_sum(x, n = q, align = "right", fill = NA)
  # rolling variances over last 'window' observations
  var_q  <- RcppRoll::roll_var(rq, n = window, align = "right", fill = NA)
  var_1  <- RcppRoll::roll_var(x,  n = window, align = "right", fill = NA)
  out <- var_q / (q * var_1)
  out[!is.finite(out)] <- NA_real_
  out
}

# Wrapper: compute all rolling features for one vector
compute_rolling_features_fast <- function(ret, window = 252, lags = 1:10, vr_q = c(5,10)) {
  trend_score <- roll_trend_score_fast(ret, window = window, lags = lags)
  vr_list <- lapply(vr_q, function(q) variance_ratio_fast(ret, q = q, window = window))
  names(vr_list) <- paste0("VR", vr_q)
  list(trend_score = trend_score, vr_list = vr_list)
}

# -----------------------
# Long format from returns_df (Date + stock columns of returns)
# -----------------------
# returns_df <- ...  # your cleaned data frame
long <- returns_df %>%
  pivot_longer(-Date, names_to = "stock", values_to = "ret") %>%
  arrange(stock, Date)

# -----------------------
# Compute per-stock rolling metrics (fast)
# -----------------------
# data.table is faster for split-apply-combine on large data
DT <- as.data.table(long)
setkey(DT, stock, Date)

features_list <- DT[, {
  feats <- compute_rolling_features_fast(ret,
                                         window = window_days,
                                         lags   = acf_lags,
                                         vr_q   = vr_q)
  .(Date        = Date,
    ret         = ret,
    trend_score = feats$trend_score,
    VR5         = feats$vr_list$VR5,
    VR10        = feats$vr_list$VR10)
}, by = stock]

features_long <- as_tibble(features_list) %>%
  mutate(signal = case_when(
    trend_score >  0.01 ~ "Trending",
    trend_score <  -0.01 ~ "MeanReverting",
    TRUE             ~ NA_character_
  ))

# -----------------------
# Summary at last valid date
# -----------------------
last_date <- max(features_long$Date, na.rm = TRUE)

summary_now <- features_long %>%
  filter(Date == last_date) %>%
  select(stock, Date, trend_score, VR5, VR10, signal) %>%
  arrange(stock)

print(summary_now, n = nrow(summary_now))

# Quick interpretation helper:
# • trend_score > 0  => trending bias for next ~1–10 days
# • trend_score < 0  => mean-reversion bias
# • VR5/VR10 > 1     => trend confirmation; < 1 => mean-reversion confirmation

# =========================
# 4) (Optional) Visualize one stock’s TrendScore over time
# =========================
plot_trendscore <- function(stock_ticker) {
  dfp <- features_long %>% filter(stock == stock_ticker)
  ggplot(dfp, aes(Date, trend_score, color = signal)) +
    geom_hline(yintercept = 0, linetype = "dashed") +
    geom_line(na.rm = TRUE) +
    labs(title = paste0(stock_ticker, " — Rolling TrendScore (mean ACF lags 1–10, window = ", window_days, ")"),
         y = "TrendScore", x = "Date", color = "Regime") +
    theme_minimal()
}

# Example:
#plot_trendscore("AXP UN")

#####################
#### Cross validation
#####################

# ------------ 1) Config ------------
trading_days_per_year <- 252L
train_len <- 3L * trading_days_per_year
val_len   <- 1L * trading_days_per_year
h         <- 10L                                  # lookahead horizon for labels
grid <- expand.grid(
  window_days = c(126L, 252L, 504L),
  lag_max     = c(5L, 10L, 20L),
  threshold   = c(0.01, 0.02, 0.03, 0.05),
  KEEP.OUT.ATTRS = FALSE, stringsAsFactors = FALSE
)

# If you don't have it already:
long_all <- returns_df %>%
  tidyr::pivot_longer(-Date, names_to = "stock", values_to = "ret") %>%
  arrange(stock, Date)

# ------------ 2) Build folds (dates only) ------------
all_dates <- sort(unique(long_all$Date))
N <- length(all_dates)
fold_starts <- seq.int(
  from = 1L,
  to   = N - (train_len + val_len + h) + 1L,    # leave room for lookahead
  by   = val_len
)
folds <- lapply(fold_starts, function(s) {
  train_idx <- s:(s + train_len - 1L)
  val_idx   <- (s + train_len):(s + train_len + val_len - 1L)
  list(
    train_start = all_dates[min(train_idx)],
    train_end   = all_dates[max(train_idx)],
    val_start   = all_dates[min(val_idx)],
    val_end     = all_dates[max(val_idx)]
  )
})

# ------------ 3) Labels ONCE (h-day lookahead) ------------
make_labels <- function(df_long, horizon = 10) {
  df_long %>%
    group_by(stock) %>%
    arrange(Date, .by_group = TRUE) %>%
    mutate(
      fut_sum = zoo::rollapply(ret, width = horizon, align = "left", fill = NA, sum),
      actual_signal = case_when(
        fut_sum > +0.01 ~ "Trending",
        fut_sum < -0.01 ~ "MeanReverting",
        TRUE           ~ NA
      )
    ) %>%
    ungroup() %>%
    select(stock, Date, actual_signal)
}
labels_all <- make_labels(long_all, horizon = h)

# ------------ 4) Helper: precompute features ONCE per (W, L) ------------
precompute_features <- function(W, Lm, df_long) {
  DT <- as.data.table(df_long); setkey(DT, stock, Date)
  out <- DT[, {
    feats <- compute_rolling_features_fast(ret, window = W, lags = 1:Lm, vr_q = integer(0))
    .(Date = Date, trend_score = feats$trend_score)
  }, by = stock]
  tibble::as_tibble(out)
}

# ------------ 5) Parallel CV over the grid ------------
# REMOVE: library(future.apply); plan(multisession)

cv_list <- lapply(seq_len(nrow(grid)), function(gi) {
  W   <- grid$window_days[gi]
  Lm  <- grid$lag_max[gi]
  thr <- grid$threshold[gi]
  
  feats_all <- precompute_features(W, Lm, long_all)
  
  joined_all <- feats_all %>%
    inner_join(labels_all, by = c("stock","Date"))
  
  fold_scores <- numeric(length(folds))
  fold_coverage <- numeric(length(folds))
  
  for (fi in seq_along(folds)) {
    f <- folds[[fi]]
    preds <- joined_all %>%
      filter(Date >= f$val_start, Date <= f$val_end) %>%
      mutate(pred_signal = case_when(
        trend_score >  thr ~ "Trending",
        trend_score < -thr ~ "MeanReverting",
        TRUE               ~ NA_character_
      )) %>%
      filter(!is.na(pred_signal), !is.na(actual_signal))
    
    fold_scores[fi]   <- if (nrow(preds) > 0) mean(preds$pred_signal == preds$actual_signal) else NA_real_
    total_val_rows    <- nrow(joined_all %>% filter(Date >= f$val_start, Date <= f$val_end))
    fold_coverage[fi] <- if (total_val_rows > 0) nrow(preds) / total_val_rows else NA_real_
  }
  
  tibble::tibble(
    window_days = W, lag_max = Lm, threshold = thr,
    fold = seq_along(folds),
    accuracy = fold_scores, coverage = fold_coverage
  )
})

cv_tbl <- dplyr::bind_rows(cv_list)


# ------------ 6) Summaries & model selection ------------
by_setting <- cv_tbl %>%
  group_by(window_days, lag_max, threshold) %>%
  summarise(
    mean_acc = mean(accuracy, na.rm = TRUE),
    med_acc  = median(accuracy, na.rm = TRUE),
    mean_cov = mean(coverage, na.rm = TRUE),
    n_folds  = sum(!is.na(accuracy)),
    .groups  = "drop"
  ) %>%
  # Scores capturing the tradeoff:
  mutate(
    # Product: favors balanced settings
    score_prod = mean_acc * mean_cov,
    # Harmonic mean (like an F1 of acc & cov): punishes imbalance
    score_hm   = ifelse(mean_acc + mean_cov > 0,
                        2 * mean_acc * mean_cov / (mean_acc + mean_cov),
                        NA_real_),
    # Constrained product: 0 if coverage below a minimum (e.g., 10%)
    min_cov_req = 0.10,
    score_constr = ifelse(mean_cov >= min_cov_req, mean_acc * mean_cov, 0)
  ) %>%
  arrange(desc(score_prod))

print(by_setting, n = nrow(by_setting))

best_by_prod   <- by_setting %>% arrange(desc(score_prod), desc(mean_acc)) %>% slice(1)
best_by_hm     <- by_setting %>% arrange(desc(score_hm),   desc(mean_acc)) %>% slice(1)
best_by_constr <- by_setting %>% arrange(desc(score_constr), desc(mean_acc)) %>% slice(1)

cat("\nBest (Product acc*cov):\n"); print(best_by_prod)
cat("\nBest (Harmonic mean of acc & cov):\n"); print(best_by_hm)
cat("\nBest (Constrained product, cov >= 10%):\n"); print(best_by_constr)


