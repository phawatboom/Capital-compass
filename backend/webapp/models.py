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

class AnalysisResult(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    csv_upload = models.ForeignKey(CSVUploadRecord, on_delete=models.CASCADE)
    analysis_type = models.CharField(max_length=50)
    status = models.CharField(max_length=20, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True)
    completed_at = models.DateTimeField(null=True)
    parameters = models.JSONField(default=dict)
    summary_stats = models.JSONField(default=dict)
    error_message = models.TextField(blank=True)
    result_file = models.FileField(upload_to='analysis_results/', null=True, blank=True)
    
    @property
    def duration(self):
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None
    
    def __str__(self):
        return f"Analysis {self.id}: {self.analysis_type} ({self.status})"

class ForecastResult(models.Model):
    analysis_result = models.ForeignKey(AnalysisResult, on_delete=models.CASCADE, related_name='forecasts')
    forecast_date = models.DateField()
    ticker = models.CharField(max_length=10)
    forecast_horizon = models.IntegerField()
    raw_probability = models.FloatField()
    calibrated_probability = models.FloatField()
    confidence = models.FloatField()
    expected_move = models.FloatField()
    prediction_interval_low = models.FloatField()
    prediction_interval_high = models.FloatField()
    momentum_sign = models.IntegerField()
    decision_threshold = models.FloatField(null=True)
    prediction = models.IntegerField()
    abstained = models.BooleanField(default=False)
    
    class Meta:
        unique_together = ('analysis_result', 'ticker', 'forecast_horizon')
    
    def __str__(self):
        return f"{self.ticker} {self.forecast_date}: {'+' if self.prediction > 0 else '-'} ({self.confidence:.2f})"

class BacktestResult(models.Model):
    analysis_result = models.ForeignKey(AnalysisResult, on_delete=models.CASCADE, related_name='backtests')
    date = models.DateField()
    ticker = models.CharField(max_length=10)
    horizon = models.CharField(max_length=5)  # 'd1', 'd3', etc.
    y_true = models.IntegerField()
    y_prob_cal = models.FloatField()
    y_pred = models.IntegerField()
    fwd_ret = models.FloatField()
    mr_score = models.FloatField()
    confidence = models.FloatField()
    abstained = models.BooleanField(default=False)
    
    class Meta:
        unique_together = ('analysis_result', 'ticker', 'date', 'horizon')
    
    def __str__(self):
        return f"{self.ticker} {self.date} ({self.horizon}): {'+' if self.y_pred > 0 else '-'} ({self.confidence:.2f})"

class BetaForecastResult(models.Model):
    """New model for beta forecasting results from the enhanced pipeline"""
    analysis_result = models.ForeignKey(AnalysisResult, on_delete=models.CASCADE, related_name='beta_forecasts')
    forecast_date = models.DateField()
    ticker = models.CharField(max_length=10)
    
    # Core beta prediction
    beta_pred = models.FloatField(help_text="Predicted beta coefficient")
    beta_pred_ema = models.FloatField(null=True, blank=True, help_text="EMA-smoothed beta prediction")
    
    # Confidence intervals
    lo = models.FloatField(help_text="Lower confidence bound")
    hi = models.FloatField(help_text="Upper confidence bound")
    
    # Statistical quality measures
    r2_ols = models.FloatField(help_text="R-squared from OLS regression")
    p_value = models.FloatField(help_text="Statistical p-value")
    confidence_level = models.CharField(
        max_length=20,
        choices=[
            ('High (p≤1%)', 'High (p≤1%)'),
            ('Medium (p≤5%)', 'Medium (p≤5%)'),
            ('Low (p>5%)', 'Low (p>5%)'),
        ],
        help_text="Statistical confidence level"
    )
    confidence_tier = models.CharField(max_length=10, help_text="Risk tier classification")
    
    # Business context
    delta_beta_20d = models.FloatField(help_text="Change vs 1-year median realized beta")
    conf_20d = models.FloatField(help_text="Prediction confidence score [0,1]")
    
    # Agreement and stability checks
    agree_adjacent = models.BooleanField(help_text="Adjacent horizons agree on direction")
    term_unstable = models.BooleanField(help_text="Term structure shows instability")
    
    # Action recommendation
    action = models.CharField(
        max_length=10,
        choices=[
            ('chase', 'Chase'),
            ('fade', 'Fade'),
            ('hold', 'Hold'),
        ],
        help_text="Recommended trading action"
    )
    hold_reason = models.CharField(max_length=50, blank=True, help_text="Reason for hold recommendation")
    
    class Meta:
        unique_together = ('analysis_result', 'ticker', 'forecast_date')
        indexes = [
            models.Index(fields=['ticker', 'forecast_date']),
            models.Index(fields=['action']),
            models.Index(fields=['confidence_level']),
        ]
    
    def __str__(self):
        return f"{self.ticker} {self.forecast_date}: β={self.beta_pred:.3f} ({self.action})"


class MeanReversionResult(models.Model):
    """Model for mean-reversion analysis results from the legacy pipeline"""
    analysis_result = models.ForeignKey(AnalysisResult, on_delete=models.CASCADE, related_name='mean_reversion_results')
    analysis_date = models.DateField()
    ticker = models.CharField(max_length=10)
    
    # Z-score analysis
    z_score_current = models.FloatField(help_text="Current price Z-score")
    z_score_trend = models.FloatField(help_text="Z-score trend over analysis period")
    
    # Mean reversion probabilities
    mean_reversion_probability = models.FloatField(help_text="Probability of mean reversion [0,1]")
    reversion_strength = models.CharField(
        max_length=20,
        choices=[
            ('Strong', 'Strong'),
            ('Moderate', 'Moderate'),
            ('Weak', 'Weak'),
        ],
        help_text="Expected strength of mean reversion"
    )
    
    # Magnitude predictions with conformal intervals
    magnitude_prediction = models.FloatField(help_text="Predicted magnitude of price movement")
    magnitude_lower_bound = models.FloatField(help_text="Lower conformal bound for magnitude")
    magnitude_upper_bound = models.FloatField(help_text="Upper conformal bound for magnitude")
    
    # Statistical confidence measures
    calibration_score = models.FloatField(help_text="Isotonic calibration confidence score")
    confidence_interval_90 = models.JSONField(help_text="90% confidence interval [lower, upper]")
    confidence_interval_95 = models.JSONField(help_text="95% confidence interval [lower, upper]")
    
    # Historical performance context
    historical_accuracy = models.FloatField(help_text="Historical accuracy rate for similar signals")
    lookback_period_days = models.IntegerField(help_text="Analysis lookback period in days")
    
    # Recommendation
    recommendation = models.CharField(
        max_length=10,
        choices=[
            ('BUY', 'Buy'),
            ('SELL', 'Sell'),
            ('HOLD', 'Hold'),
        ],
        help_text="Trading recommendation based on mean reversion analysis"
    )
    recommendation_confidence = models.FloatField(help_text="Confidence in recommendation [0,1]")
    
    class Meta:
        unique_together = ('analysis_result', 'ticker', 'analysis_date')
        indexes = [
            models.Index(fields=['ticker', 'analysis_date']),
            models.Index(fields=['recommendation']),
            models.Index(fields=['reversion_strength']),
        ]
    
    def __str__(self):
        return f"{self.ticker} {self.analysis_date}: MR={self.mean_reversion_probability:.3f} ({self.recommendation})"


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

    def __str__(self):
        return f"SharedStats ({self.model_used}) @ {self.created_at:%Y-%m-%d %H:%M:%S}"


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

    def __str__(self):
        return f"{self.ticker} @ {self.created_at:%Y-%m-%d}"

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)