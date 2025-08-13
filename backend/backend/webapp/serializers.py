from rest_framework import serializers

# This serializer is used to validate the uploaded CSV file.
def validate_file(value):
    if not value.name.endswith('.csv'):
        raise serializers.ValidationError("Only CSV files are allowed.")
    return value

# This serializer is used to handle the file upload for CSV files.
class CSVUploadSerializer(serializers.Serializer):
    file = serializers.FileField()

