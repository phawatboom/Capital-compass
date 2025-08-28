from rest_framework import serializers
from .models import Stock, StockData, CSVUploadRecord

# This serialiser is used to validate the uploaded CSV file.
class CSVUploadSerializer(serializers.ModelSerializer):
    def validate_filename(self, value):
        if not (value.name.endswith('.csv') or value.name.endswith('.xlsx')):
            raise serializers.ValidationError("Only CSV and XLSX files are allowed.")
        return value

    class Meta:
        model = CSVUploadRecord
        fields = ['filename']

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