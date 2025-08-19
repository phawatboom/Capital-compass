from rest_framework import serializers
from .models import Stock, StockData, CSVUploadRecord

# This serialiser is used to validate the uploaded CSV file.
def validate_file(value):
    if not value.name.endswith('.csv'):
        raise serializers.ValidationError("Only CSV files are allowed.")
    return value

# This serializer is used to handle the file upload for CSV files.
class CSVUploadSerializer(serializers.Serializer):
    file = serializers.FileField()

# This serializer is used to serialise the Stock model.
class StockSerializer(serializers.ModelSerializer):
    class Meta:
        model = Stock
        fields = '__all__'

# This serializer is used to serialise the StockData model.
class StockDataSerializer(serializers.ModelSerializer):
    stock = serializers.SlugRelatedField(slug_field='name', queryset=Stock.objects.all())

    class Meta:
        model = StockData
        fields = '__all__'

# This serializer is used to serialise the CSV upload records.
class CSVUploadRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = CSVUploadRecord
        fields = ['id', 'filename', 'uploaded_at']
