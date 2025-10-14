from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.core.validators import FileExtensionValidator
from django.contrib.auth.models import User 
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

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)