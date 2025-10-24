# models_universal.py
"""
New models for Universal Beta Forecasting Model
These complement existing models without replacing them
"""

from django.db import models
from django.contrib.auth.models import User
from .models import AnalysisResult

class UniversalBetaPrediction(models.Model):
    """
    Model for storing Universal Beta Model predictions from final_predictions.csv
    This is the primary model clients will use for trading decisions
    """
    # Core identification
    ticker = models.CharField(max_length=10, db_index=True)
    date = models.DateField(db_index=True, help_text="Date of the prediction")
    horizon_days = models.IntegerField(help_text="Prediction horizon (1, 5, 10, 20 days)")
    
    # Primary prediction
    final_prediction = models.FloatField(help_text="Universal model beta prediction")
    
    # Historical beta features (AR layer inputs)
    train_b = models.FloatField(help_text="Historical training beta coefficient")
    lag_train_b = models.FloatField(null=True, blank=True, help_text="Lagged training beta")
    
    # Technical features
    ar1_corr_10d = models.FloatField(null=True, blank=True)
    ar1_corr_20d = models.FloatField(null=True, blank=True)
    ar1_corr_60d = models.FloatField(null=True, blank=True)
    sign_persist_20d = models.FloatField(null=True, blank=True)
    sign_persist_60d = models.FloatField(null=True, blank=True)
    
    # Return features
    ret_1d = models.FloatField(null=True, blank=True)
    ret_5d = models.FloatField(null=True, blank=True)
    ret_20d = models.FloatField(null=True, blank=True)
    
    # Volatility features (multi-horizon)
    vol_63d = models.FloatField(null=True, blank=True)
    vol_126d = models.FloatField(null=True, blank=True)
    vol_252d = models.FloatField(null=True, blank=True)
    vol_756d = models.FloatField(null=True, blank=True)
    
    # Technical indicators
    z_ma_20d = models.FloatField(null=True, blank=True)
    
    # Cross-sectional rankings (relative performance)
    cs_rank_ret_1d = models.FloatField(null=True, blank=True)
    cs_rank_ret_5d = models.FloatField(null=True, blank=True)
    cs_rank_ret_20d = models.FloatField(null=True, blank=True)
    cs_rank_z_ma_20d = models.FloatField(null=True, blank=True)
    cs_rank_vol_63d = models.FloatField(null=True, blank=True)
    cs_rank_vol_126d = models.FloatField(null=True, blank=True)
    cs_rank_vol_252d = models.FloatField(null=True, blank=True)
    cs_rank_vol_756d = models.FloatField(null=True, blank=True)
    
    # Market regime indicator
    xsec_disp_30d = models.FloatField(null=True, blank=True, help_text="Cross-sectional dispersion")
    
    # Business logic fields (computed)
    prediction_direction = models.CharField(
        max_length=10,
        choices=[
            ('INCREASE', 'Beta Increase'),
            ('DECREASE', 'Beta Decrease'),
            ('STABLE', 'Beta Stable'),
        ],
        help_text="Direction of beta change"
    )
    
    confidence_tier = models.CharField(
        max_length=20,
        choices=[
            ('HIGH', 'High Confidence'),
            ('MEDIUM', 'Medium Confidence'),
            ('LOW', 'Low Confidence'),
        ],
        help_text="Model confidence level"
    )
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    model_version = models.CharField(max_length=50, default="universal_v1")
    
    class Meta:
        unique_together = ('ticker', 'date', 'horizon_days')
        indexes = [
            models.Index(fields=['ticker', 'date']),
            models.Index(fields=['date', 'horizon_days']),
            models.Index(fields=['prediction_direction']),
            models.Index(fields=['confidence_tier']),
        ]
        ordering = ['-date', 'ticker']
    
    def save(self, *args, **kwargs):
        # Auto-compute business logic fields
        if self.final_prediction > 0.05:
            self.prediction_direction = 'INCREASE'
        elif self.final_prediction < -0.05:
            self.prediction_direction = 'DECREASE'
        else:
            self.prediction_direction = 'STABLE'
            
        # Confidence based on volatility and cross-sectional features
        vol_avg = (self.vol_63d or 0 + self.vol_126d or 0 + self.vol_252d or 0) / 3
        if vol_avg < 0.015 and (self.xsec_disp_30d or 0) < 0.02:
            self.confidence_tier = 'HIGH'
        elif vol_avg < 0.025:
            self.confidence_tier = 'MEDIUM'
        else:
            self.confidence_tier = 'LOW'
            
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.ticker} {self.date} ({self.horizon_days}d): β={self.final_prediction:.3f}"


class UniversalModelMetrics(models.Model):
    """
    Model performance metrics from oos_metrics.csv
    """
    horizon_days = models.IntegerField(primary_key=True)
    
    # Global metrics
    mae = models.FloatField(help_text="Mean Absolute Error")
    rmse = models.FloatField(help_text="Root Mean Square Error")
    r2_global = models.FloatField(help_text="Global R-squared")
    r2_fold_mean = models.FloatField(help_text="Average fold R-squared")
    r2_fold_weighted = models.FloatField(help_text="Weighted fold R-squared")
    directional_accuracy = models.FloatField(help_text="Directional prediction accuracy")
    
    # Sample size
    n_predictions = models.IntegerField(help_text="Total out-of-sample predictions")
    
    # Relative performance metrics
    mae_ratio_global = models.FloatField(help_text="MAE relative to naive forecast")
    
    # Metadata
    last_updated = models.DateTimeField(auto_now=True)
    model_version = models.CharField(max_length=50, default="universal_v1")
    
    def __str__(self):
        return f"Universal Model {self.horizon_days}d: R²={self.r2_global:.3f}, DirAcc={self.directional_accuracy:.1%}"


class StockUniversalMetrics(models.Model):
    """
    Per-stock performance metrics from per_stock_oos_metrics.csv
    """
    ticker = models.CharField(max_length=10, db_index=True)
    horizon_days = models.IntegerField()
    
    # Performance metrics
    r2_oos = models.FloatField(help_text="Out-of-sample R-squared")
    rmse_oos = models.FloatField(help_text="Out-of-sample RMSE")
    mae_oos = models.FloatField(help_text="Out-of-sample MAE")
    mase_oos = models.FloatField(help_text="Mean Absolute Scaled Error")
    dir_acc_oos = models.FloatField(help_text="Directional accuracy")
    pred_std_oos = models.FloatField(help_text="Prediction standard deviation")
    n_oos = models.IntegerField(help_text="Number of out-of-sample observations")
    
    # Business categories
    performance_tier = models.CharField(
        max_length=20,
        choices=[
            ('EXCELLENT', 'Excellent (R²>0.1)'),
            ('GOOD', 'Good (R²>0.05)'),
            ('FAIR', 'Fair (R²>0.0)'),
            ('POOR', 'Poor (R²≤0.0)'),
        ],
        help_text="Performance classification"
    )
    
    # Metadata
    last_updated = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ('ticker', 'horizon_days')
        indexes = [
            models.Index(fields=['performance_tier']),
            models.Index(fields=['r2_oos']),
            models.Index(fields=['dir_acc_oos']),
        ]
        ordering = ['-r2_oos']
    
    def save(self, *args, **kwargs):
        # Auto-classify performance
        if self.r2_oos > 0.1:
            self.performance_tier = 'EXCELLENT'
        elif self.r2_oos > 0.05:
            self.performance_tier = 'GOOD'
        elif self.r2_oos > 0.0:
            self.performance_tier = 'FAIR'
        else:
            self.performance_tier = 'POOR'
            
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.ticker} ({self.horizon_days}d): {self.performance_tier} - R²={self.r2_oos:.3f}"