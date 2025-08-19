from django.db import models

# Create your models here.
class Stock(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name

class StockData(models.Model):
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE)
    date = models.DateField()
    value = models.FloatField(null=True, blank=True)  # Allow null for #N/A values

    class Meta:
        unique_together = ('stock', 'date')  # Ensure no duplicate entries for the same stock and date

    def __str__(self):
        return f"{self.stock.name} on {self.date}: {self.value}"


# This model is used to record the uploaded CSV files.
class CSVUploadRecord(models.Model):
    filename = models.FileField(upload_to='csv_uploads/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.filename} ({self.uploaded_at})"
