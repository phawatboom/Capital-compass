from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.core.validators import FileExtensionValidator
from django.contrib.auth.models import User 

import os
# Create your models here.
class Stock(models.Model):
    name = models.CharField(max_length=100, unique=True)
    b_coefficient = models.FloatField(null=True, blank=True)
    p_value = models.FloatField(null=True, blank=True)

    def __str__(self):
        return self.name

    @property
    def is_significant(self):
        return self.p_value is not None and self.p_value < 0.05

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
        unique_together = ('stock', 'date', 'data_type')  # Ensure no duplicate entries for the same stock, date, and type

    def __str__(self):
        return f"{self.stock.name} on {self.date} ({self.data_type}): {self.value}"


# This model is used to record the uploaded CSV files.
class CSVUploadRecord(models.Model):
    filename = models.FileField(
        upload_to="csv_uploads/",
        validators=[FileExtensionValidator(allowed_extensions=["csv", "xlsx"])],  # Allow both CSV and Excel files
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    file_size = models.PositiveIntegerField(default=0)
    user = models.ForeignKey(User, on_delete=models.CASCADE) # <-- Add this line

    def save(self, *args, **kwargs):
        # If a file is present and saved to disk, update file_size
        if self.filename and hasattr(self.filename, "path"):
            try:
                self.file_size = os.path.getsize(self.filename.path)
            except (OSError, ValueError):
                # File might not exist yet during initial save
                pass
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.filename} ({self.uploaded_at}) - {self.file_size} bytes"


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    display_name = models.CharField(max_length=150, blank=True)
    bio = models.TextField(blank=True)
    timezone = models.CharField(max_length=64, blank=True)
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)

    organization = models.CharField(max_length=150, blank=True)
    job_title = models.CharField(max_length=150, blank=True)
    notify_email_reports = models.BooleanField(default=False)

    def __str__(self):
        return f"Profile({self.user.username})"

@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def ensure_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(user=instance)