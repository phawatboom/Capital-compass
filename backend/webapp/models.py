from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.core.validators import FileExtensionValidator
from django.contrib.auth.models import User
from django.db.models import JSONField
from django.utils import timezone
from django.db import transaction  # (May be unused; retained if future atomic ops needed)
"""Domain models and model-level helpers (no API views here).

NOTE: View classes were previously (incorrectly) embedded in this file. They have
been moved to views.py to follow Django separation of concerns and prevent
import side‑effects / circular dependencies.
"""

import os
import re
from pathlib import Path
from typing import Optional

# Create your models here.
class Stock(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name

class StockData(models.Model):
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE)
    date = models.DateField()
    value = models.FloatField(null=True, blank=True)  # Allow null for #N/A values
    data_type = models.CharField(
        max_length=50,
        choices=[
            ('price', 'Price'),
            ('return', 'Return'),
            ('equity', 'Equity'),
        ]
    )

    class Meta:
        unique_together = ('stock', 'date', 'data_type')

    def __str__(self):
        return f"{self.stock.name} on {self.date} ({self.data_type}): {self.value}"

class CSVUploadRecord(models.Model):
    filename = models.FileField(upload_to='csv_uploads/')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    file_size = models.PositiveIntegerField(default=0)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, related_name='csv_uploads')
    
    def __str__(self):
        return f"{self.filename.name} ({self.file_size} bytes) uploaded at {self.uploaded_at}"

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    display_name = models.CharField(max_length=150, blank=True)
    bio = models.TextField(blank=True)
    timezone = models.CharField(max_length=64, blank=True)
    avatar = models.ImageField(upload_to='avatars/', null=True, blank=True)
    organization = models.CharField(max_length=150, blank=True)
    job_title = models.CharField(max_length=150, blank=True)
    notify_email_reports = models.BooleanField(default=False)

    def __str__(self):
        return f"Profile for {self.user.username}"

def select_latest_forecast_file(dir_path: str) -> Optional[Path]:
    """Return the latest forecast_*.csv file in dir_path.

    Preference: If files have suffix _vN choose highest N else newest mtime.
    """
    p = Path(dir_path)
    candidates = list(p.glob("forecast_*.csv"))
    if not candidates:
        return None
    versioned = []
    pattern = re.compile(r'.*_v(\d+)\.csv$')
    for f in candidates:
        m = pattern.match(f.name)
        if m:
            versioned.append((int(m.group(1)), f))
    if versioned:
        versioned.sort(key=lambda x: x[0], reverse=True)
        return versioned[0][1]
    candidates.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return candidates[0]

# Beta Coefficient Model Output Support
class BetaRealized(models.Model):
    """Model for storing beta_20d.csv output data"""
    date = models.DateField()
    ticker = models.CharField(max_length=10)
    beta_realised = models.FloatField(null=True, blank=True)
    r2_ols_x = models.FloatField(null=True, blank=True)
    r2_ols_y = models.FloatField(null=True, blank=True)
    p_value = models.FloatField(null=True, blank=True)
    significance_score = models.FloatField(null=True, blank=True)
    beta_pred = models.FloatField(null=True, blank=True)
    beta_true = models.FloatField(null=True, blank=True)
    band = models.FloatField(null=True, blank=True)
    lo = models.FloatField(null=True, blank=True)
    hi = models.FloatField(null=True, blank=True)
    
    class Meta:
        unique_together = ('date', 'ticker')
        indexes = [
            models.Index(fields=['ticker', 'date']),
            models.Index(fields=['date']),
        ]
    
    def __str__(self):
        return f"{self.ticker} {self.date}: β_realized={self.beta_realised}"

class ForecastEvaluation(models.Model):
    """Model for storing forecast_eval_20d.csv output data"""
    date = models.DateField()
    ticker = models.CharField(max_length=10)
    r2_ols = models.FloatField()
    p_value = models.FloatField()
    significance_score = models.FloatField()
    beta_pred = models.FloatField()
    beta_true = models.FloatField()
    band = models.FloatField()
    
    class Meta:
        unique_together = ('date', 'ticker')
        indexes = [
            models.Index(fields=['ticker', 'date']),
            models.Index(fields=['date']),
            models.Index(fields=['significance_score']),
        ]
    
    def __str__(self):
        return f"{self.ticker} {self.date}: β_pred={self.beta_pred:.3f}, R²={self.r2_ols:.3f}"


class FactorSharedStats(models.Model):
    """Stores the pooled ElasticNet model's shared/global coefficients and factor averages."""
    created_at = models.DateTimeField(default=timezone.now)
    model_used = models.CharField(max_length=50, default="enet")
    intercept_raw = models.FloatField(null=True)

    # models.py
    volatility_coeff = models.FloatField(null=True)   # standardized intercept (already present)
    coef_std = models.JSONField(default=dict)         # NEW: standardized coef by feature
    intercept_raw = models.FloatField(null=True)      # NEW: raw intercept
    coef_raw = models.JSONField(default=dict)         # NEW: raw coef by feature
    feature_means = models.JSONField(default=dict)    # optional
    feature_scales = models.JSONField(default=dict)   # optional
    model_equation = models.TextField(blank=True, default="")  # optional pretty string

    # FactorSharedStats
    training_days     = models.IntegerField(null=True)   # base_train_len_days
    testing_days      = models.IntegerField(null=True)   # base_test_len_days
    enet_alpha        = models.FloatField(null=True)
    enet_l1_ratio     = models.FloatField(null=True)
    oos_min_train_rows= models.IntegerField(null=True)
    run_params        = models.JSONField(default=dict)   # future-proof catch-all

    # --- Coefficients (ElasticNet learned weights for each factor) ---
    coef_train_b = models.FloatField(null=True, blank=True)
    coef_lag_train_b = models.FloatField(null=True, blank=True)
    coef_ar1_corr_10d = models.FloatField(null=True, blank=True)
    coef_ar1_corr_20d = models.FloatField(null=True, blank=True)
    coef_ar1_corr_60d = models.FloatField(null=True, blank=True)
    coef_sign_persist_20d = models.FloatField(null=True, blank=True)
    coef_sign_persist_60d = models.FloatField(null=True, blank=True)
    coef_ret_1d = models.FloatField(null=True, blank=True)
    coef_ret_5d = models.FloatField(null=True, blank=True)
    coef_ret_20d = models.FloatField(null=True, blank=True)
    coef_vol_63d = models.FloatField(null=True, blank=True)
    coef_vol_126d = models.FloatField(null=True, blank=True)
    coef_vol_252d = models.FloatField(null=True, blank=True)
    coef_vol_756d = models.FloatField(null=True, blank=True)
    coef_Z_ma_20d = models.FloatField(null=True, blank=True)
    coef_cs_rank_ret_1d = models.FloatField(null=True, blank=True)
    coef_cs_rank_ret_5d = models.FloatField(null=True, blank=True)
    coef_cs_rank_ret_20d = models.FloatField(null=True, blank=True)
    coef_cs_rank_z_ma_20d = models.FloatField(null=True, blank=True)
    coef_cs_rank_vol_63d = models.FloatField(null=True, blank=True)
    coef_cs_rank_vol_126d = models.FloatField(null=True, blank=True)
    coef_cs_rank_vol_252d = models.FloatField(null=True, blank=True)
    coef_cs_rank_vol_756d = models.FloatField(null=True, blank=True)

    # --- Averages (cross-sectional means for each factor at end of training sample) ---
    avg_train_b = models.FloatField(null=True, blank=True)
    avg_lag_train_b = models.FloatField(null=True, blank=True)
    avg_ar1_corr_10d = models.FloatField(null=True, blank=True)
    avg_ar1_corr_20d = models.FloatField(null=True, blank=True)
    avg_ar1_corr_60d = models.FloatField(null=True, blank=True)
    avg_sign_persist_20d = models.FloatField(null=True, blank=True)
    avg_sign_persist_60d = models.FloatField(null=True, blank=True)
    avg_ret_1d = models.FloatField(null=True, blank=True)
    avg_ret_5d = models.FloatField(null=True, blank=True)
    avg_ret_20d = models.FloatField(null=True, blank=True)
    avg_vol_63d = models.FloatField(null=True, blank=True)
    avg_vol_126d = models.FloatField(null=True, blank=True)
    avg_vol_252d = models.FloatField(null=True, blank=True)
    avg_vol_756d = models.FloatField(null=True, blank=True)
    avg_Z_ma_20d = models.FloatField(null=True, blank=True)
    avg_cs_rank_ret_1d = models.FloatField(null=True, blank=True)
    avg_cs_rank_ret_5d = models.FloatField(null=True, blank=True)
    avg_cs_rank_ret_20d = models.FloatField(null=True, blank=True)
    avg_cs_rank_z_ma_20d = models.FloatField(null=True, blank=True)
    avg_cs_rank_vol_63d = models.FloatField(null=True, blank=True)
    avg_cs_rank_vol_126d = models.FloatField(null=True, blank=True)
    avg_cs_rank_vol_252d = models.FloatField(null=True, blank=True)
    avg_cs_rank_vol_756d = models.FloatField(null=True, blank=True)

    # --- Model-level metrics ---
    r2_global = models.FloatField(null=True, blank=True)
    volatility_coeff = models.FloatField(null=True, blank=True)

    horizon_days = models.IntegerField(default=5)

    def __str__(self):
        return f"SharedStats ({self.model_used}, {self.horizon_days}d) @ {self.created_at:%Y-%m-%d %H:%M:%S}"


class StockFactorResult(models.Model):
    """Stores per-stock factor regression and forecast results (linked to a shared model)."""
    created_at = models.DateTimeField(default=timezone.now)
    ticker = models.CharField(max_length=50)
    shared_stats = models.ForeignKey(
        FactorSharedStats, on_delete=models.CASCADE, related_name="stocks", null=True, blank=True
    )

    # --- Regression outputs ---
    b_coefficient = models.FloatField(null=True, blank=True)  # Predicted next-period b
    volatility = models.FloatField(null=True, blank=True)
    y_intercept = models.FloatField(null=True, blank=True)

    # --- Core factor columns (explicit) ---
    train_b = models.FloatField(null=True, blank=True)
    lag_train_b = models.FloatField(null=True, blank=True)
    ar1_corr_10d = models.FloatField(null=True, blank=True)
    ar1_corr_20d = models.FloatField(null=True, blank=True)
    ar1_corr_60d = models.FloatField(null=True, blank=True)
    sign_persist_20d = models.FloatField(null=True, blank=True)
    sign_persist_60d = models.FloatField(null=True, blank=True)
    ret_1d = models.FloatField(null=True, blank=True)
    ret_5d = models.FloatField(null=True, blank=True)
    ret_20d = models.FloatField(null=True, blank=True)
    vol_63d = models.FloatField(null=True, blank=True)
    vol_126d = models.FloatField(null=True, blank=True)
    vol_252d = models.FloatField(null=True, blank=True)
    vol_756d = models.FloatField(null=True, blank=True)
    Z_ma_20d = models.FloatField(null=True, blank=True)
    cs_rank_ret_1d = models.FloatField(null=True, blank=True)
    cs_rank_ret_5d = models.FloatField(null=True, blank=True)
    cs_rank_ret_20d = models.FloatField(null=True, blank=True)
    cs_rank_z_ma_20d = models.FloatField(null=True, blank=True)
    cs_rank_vol_63d = models.FloatField(null=True, blank=True)
    cs_rank_vol_126d = models.FloatField(null=True, blank=True)
    cs_rank_vol_252d = models.FloatField(null=True, blank=True)
    cs_rank_vol_756d = models.FloatField(null=True, blank=True)
    xsec_disp_1d = models.FloatField(null=True, blank=True)
    xsec_disp_30d = models.FloatField(null=True, blank=True)

    horizon_days = models.IntegerField(default=5)
    intercept_raw = models.FloatField(null=True)
    coef_raw = models.JSONField(default=dict)        # {"feature": coef_raw}
    feature_means = models.JSONField(default=dict)   # {"feature": mean}
    feature_scales = models.JSONField(default=dict)  # {"feature": scale}

    def __str__(self):
        return f"{self.ticker} ({self.horizon_days}d) @ {self.created_at:%Y-%m-%d}"

class StockOOSMetric(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    shared_stats = models.ForeignKey(
        FactorSharedStats, on_delete=models.CASCADE, related_name="oos_metrics"
    )
    ticker = models.CharField(max_length=16, db_index=True)
    horizon_days = models.IntegerField(db_index=True)
    r2_oos = models.FloatField(null=True)
    rmse_oos = models.FloatField(null=True)
    mae_oos = models.FloatField(null=True)
    mase_oos = models.FloatField(null=True)
    diracc_oos = models.FloatField(null=True)
    predstd_oos = models.FloatField(null=True)
    n_oos = models.IntegerField(default=0)

    class Meta:
        unique_together = ("shared_stats", "ticker", "horizon_days")
        indexes = [models.Index(fields=["ticker", "horizon_days"])]


# New Models for Pooled Model Outputs
class AnalysisRun(models.Model):
    """Represents a complete analysis run with pooled model outputs"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='analysis_runs')
    csv_upload = models.ForeignKey(CSVUploadRecord, on_delete=models.CASCADE, null=True, blank=True)
    
    # Run metadata
    run_name = models.CharField(max_length=100)
    model_type = models.CharField(max_length=50, default='pooled_enet')
    horizon_days = models.IntegerField(default=10)  # 10d, 20d, etc.
    created_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=[
            ('running', 'Running'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
        ],
        default='running'
    )
    
    # Overall model performance metrics (from oos_metrics.csv)
    mae = models.FloatField(null=True, blank=True, help_text="Mean Absolute Error")
    rmse = models.FloatField(null=True, blank=True, help_text="Root Mean Square Error")
    directional_accuracy = models.FloatField(null=True, blank=True, help_text="Directional Accuracy")
    sample_size = models.IntegerField(null=True, blank=True, help_text="Total observations")
    r2_global = models.FloatField(null=True, blank=True, help_text="Global R-squared")
    r2_fold_mean = models.FloatField(null=True, blank=True, help_text="Mean R-squared across folds")
    r2_fold_weighted = models.FloatField(null=True, blank=True, help_text="Weighted R-squared across folds")
    mae_ratio_global = models.FloatField(null=True, blank=True, help_text="Global MAE ratio")
    mae_ratio_fold_mean = models.FloatField(null=True, blank=True, help_text="Mean MAE ratio across folds")
    mae_ratio_fold_weighted = models.FloatField(null=True, blank=True, help_text="Weighted MAE ratio across folds")
    
    class Meta:
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['status']),
            models.Index(fields=['model_type', 'horizon_days']),
        ]
    
    def __str__(self):
        return f"{self.run_name} ({self.model_type}_{self.horizon_days}d) - {self.status}"

class ModelCoefficient(models.Model):
    """Stores the learned coefficients from the pooled ElasticNet model (from enet_coefficients.csv)"""
    analysis_run = models.ForeignKey(AnalysisRun, on_delete=models.CASCADE, related_name='coefficients')
    feature_name = models.CharField(max_length=100)
    coefficient_value = models.FloatField()
    
    class Meta:
        unique_together = ('analysis_run', 'feature_name')
        indexes = [
            models.Index(fields=['analysis_run', 'feature_name']),
        ]
    
    def __str__(self):
        return f"{self.analysis_run.run_name}: {self.feature_name} = {self.coefficient_value:.6f}"

class StockPrediction(models.Model):
    """Stores per-stock predictions and features (from final_predictions.csv)"""
    analysis_run = models.ForeignKey(AnalysisRun, on_delete=models.CASCADE, related_name='predictions')
    ticker = models.CharField(max_length=20)
    prediction_date = models.DateField()
    
    # Core prediction
    final_prediction = models.FloatField(help_text="Model's final prediction")
    
    # Beta features
    train_b = models.FloatField(null=True, blank=True)
    lag_train_b = models.FloatField(null=True, blank=True)
    
    # Autocorrelation features
    ar1_corr_10d = models.FloatField(null=True, blank=True)
    ar1_corr_20d = models.FloatField(null=True, blank=True)
    ar1_corr_60d = models.FloatField(null=True, blank=True)
    
    # Persistence features
    sign_persist_20d = models.FloatField(null=True, blank=True)
    sign_persist_60d = models.FloatField(null=True, blank=True)
    
    # Return features
    ret_1d = models.FloatField(null=True, blank=True)
    ret_5d = models.FloatField(null=True, blank=True)
    ret_20d = models.FloatField(null=True, blank=True)
    
    # Volatility features
    vol_63d = models.FloatField(null=True, blank=True)
    vol_126d = models.FloatField(null=True, blank=True)
    vol_252d = models.FloatField(null=True, blank=True)
    vol_756d = models.FloatField(null=True, blank=True)
    
    # Technical indicators
    z_ma_20d = models.FloatField(null=True, blank=True)
    
    # Cross-sectional ranks
    cs_rank_ret_1d = models.FloatField(null=True, blank=True)
    cs_rank_ret_5d = models.FloatField(null=True, blank=True)
    cs_rank_ret_20d = models.FloatField(null=True, blank=True)
    cs_rank_z_ma_20d = models.FloatField(null=True, blank=True)
    cs_rank_vol_63d = models.FloatField(null=True, blank=True)
    cs_rank_vol_126d = models.FloatField(null=True, blank=True)
    cs_rank_vol_252d = models.FloatField(null=True, blank=True)
    cs_rank_vol_756d = models.FloatField(null=True, blank=True)
    
    # Cross-sectional dispersion
    xsec_disp_30d = models.FloatField(null=True, blank=True)
    
    # Coefficient-weighted features (coeff_* columns)
    coeff_train_b = models.FloatField(null=True, blank=True)
    coeff_lag_train_b = models.FloatField(null=True, blank=True)
    coeff_ar1_corr_10d = models.FloatField(null=True, blank=True)
    coeff_ar1_corr_20d = models.FloatField(null=True, blank=True)
    coeff_ar1_corr_60d = models.FloatField(null=True, blank=True)
    coeff_sign_persist_20d = models.FloatField(null=True, blank=True)
    coeff_sign_persist_60d = models.FloatField(null=True, blank=True)
    coeff_ret_1d = models.FloatField(null=True, blank=True)
    coeff_ret_5d = models.FloatField(null=True, blank=True)
    coeff_ret_20d = models.FloatField(null=True, blank=True)
    coeff_vol_63d = models.FloatField(null=True, blank=True)
    coeff_vol_126d = models.FloatField(null=True, blank=True)
    coeff_vol_252d = models.FloatField(null=True, blank=True)
    coeff_vol_756d = models.FloatField(null=True, blank=True)
    coeff_z_ma_20d = models.FloatField(null=True, blank=True)
    coeff_cs_rank_ret_1d = models.FloatField(null=True, blank=True)
    coeff_cs_rank_ret_5d = models.FloatField(null=True, blank=True)
    coeff_cs_rank_ret_20d = models.FloatField(null=True, blank=True)
    coeff_cs_rank_z_ma_20d = models.FloatField(null=True, blank=True)
    coeff_cs_rank_vol_63d = models.FloatField(null=True, blank=True)
    coeff_cs_rank_vol_126d = models.FloatField(null=True, blank=True)
    coeff_cs_rank_vol_252d = models.FloatField(null=True, blank=True)
    coeff_cs_rank_vol_756d = models.FloatField(null=True, blank=True)
    coeff_xsec_disp_30d = models.FloatField(null=True, blank=True)
    
    class Meta:
        unique_together = ('analysis_run', 'ticker', 'prediction_date')
        indexes = [
            models.Index(fields=['analysis_run', 'ticker']),
            models.Index(fields=['prediction_date']),
            models.Index(fields=['final_prediction']),
        ]
    
    def __str__(self):
        return f"{self.ticker} {self.prediction_date}: {self.final_prediction:.6f}"

class StockPerformanceMetrics(models.Model):
    """Stores per-stock out-of-sample performance metrics (from per_stock_oos_metrics.csv)"""
    analysis_run = models.ForeignKey(AnalysisRun, on_delete=models.CASCADE, related_name='stock_metrics')
    ticker = models.CharField(max_length=20)
    
    # Performance metrics
    r2_oos = models.FloatField(help_text="Out-of-sample R-squared")
    rmse_oos = models.FloatField(help_text="Out-of-sample RMSE")
    mae_oos = models.FloatField(help_text="Out-of-sample MAE")
    mase_oos = models.FloatField(help_text="Mean Absolute Scaled Error")
    dir_acc_oos = models.FloatField(help_text="Directional accuracy out-of-sample")
    pred_std_oos = models.FloatField(help_text="Standard deviation of predictions")
    n_obs_oos = models.IntegerField(help_text="Number of out-of-sample observations")
    
    class Meta:
        unique_together = ('analysis_run', 'ticker')
        indexes = [
            models.Index(fields=['analysis_run', 'ticker']),
            models.Index(fields=['r2_oos']),
            models.Index(fields=['dir_acc_oos']),
        ]
    
    def __str__(self):
        return f"{self.ticker} (Run {self.analysis_run.id}): R²={self.r2_oos:.3f}, Acc={self.dir_acc_oos:.3f}"

class OutOfSamplePrediction(models.Model):
    """Stores detailed out-of-sample predictions (from oos_predictions.csv)"""
    analysis_run = models.ForeignKey(AnalysisRun, on_delete=models.CASCADE, related_name='oos_predictions')
    ticker = models.CharField(max_length=20)
    date = models.DateField()
    
    # Predictions and actuals
    y_pred = models.FloatField(help_text="Model prediction")
    y_actual = models.FloatField(null=True, blank=True, help_text="Actual outcome")
    prediction_error = models.FloatField(null=True, blank=True, help_text="y_actual - y_pred")
    abs_error = models.FloatField(null=True, blank=True, help_text="Absolute prediction error")
    squared_error = models.FloatField(null=True, blank=True, help_text="Squared prediction error")
    
    # Additional features if available in oos_predictions.csv
    fold_id = models.IntegerField(null=True, blank=True, help_text="Cross-validation fold")
    
    class Meta:
        unique_together = ('analysis_run', 'ticker', 'date')
        indexes = [
            models.Index(fields=['analysis_run', 'ticker', 'date']),
            models.Index(fields=['date']),
            models.Index(fields=['abs_error']),
        ]
    
    def __str__(self):
        return f"{self.ticker} {self.date}: pred={self.y_pred:.4f}, actual={self.y_actual:.4f if self.y_actual else 'N/A'}"

class FoldStatistics(models.Model):
    """Stores cross-validation fold statistics (from oos_fold_stats.csv)"""
    analysis_run = models.ForeignKey(AnalysisRun, on_delete=models.CASCADE, related_name='fold_stats')
    fold_id = models.IntegerField()
    
    # Fold-specific metrics
    fold_r2 = models.FloatField(null=True, blank=True, help_text="R-squared for this fold")
    fold_mae = models.FloatField(null=True, blank=True, help_text="MAE for this fold")
    fold_rmse = models.FloatField(null=True, blank=True, help_text="RMSE for this fold")
    fold_directional_acc = models.FloatField(null=True, blank=True, help_text="Directional accuracy for this fold")
    fold_n_obs = models.IntegerField(null=True, blank=True, help_text="Number of observations in fold")
    
    # Training/validation split info
    train_start_date = models.DateField(null=True, blank=True)
    train_end_date = models.DateField(null=True, blank=True)
    val_start_date = models.DateField(null=True, blank=True)
    val_end_date = models.DateField(null=True, blank=True)
    
    class Meta:
        unique_together = ('analysis_run', 'fold_id')
        indexes = [
            models.Index(fields=['analysis_run', 'fold_id']),
            models.Index(fields=['fold_r2']),
        ]
    
    def __str__(self):
        return f"Fold {self.fold_id} (Run {self.analysis_run.id}): R²={self.fold_r2:.3f if self.fold_r2 else 'N/A'}"

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)