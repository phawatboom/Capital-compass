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
    filename = models.FileField(upload_to='csv_uploads/')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    file_size = models.PositiveIntegerField(default=1)

    def __str__(self):
        return f"{self.filename} ({self.uploaded_at}) - {self.file_size} bytes"