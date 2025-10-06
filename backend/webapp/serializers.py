from rest_framework import serializers
from .models import Stock, StockData, CSVUploadRecord, UserProfile
from django.contrib.auth import get_user_model

User = get_user_model()

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



class UserProfileSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)
    email = serializers.EmailField(source="user.email", required=False, allow_blank=True)
    avatar_url = serializers.SerializerMethodField()

    organization = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    job_title = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    timezone = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    bio = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    class Meta:
        model = UserProfile
        fields = [
            "username",
            "email",
            "display_name",
            "bio",
            "timezone",
            "organization",
            "job_title",
            "notify_email_reports",
            "avatar_url",
        ]


    def get_avatar_url(self, obj):
        request = self.context.get("request")
        if obj.avatar:
            url = obj.avatar.url
            return request.build_absolute_uri(url) if request else url
        return None

    def update(self, instance, validated_data):
        user_data = validated_data.pop("user", {})
        email = user_data.get("email")
        if email is not None:
            instance.user.email = email
            instance.user.save(update_fields=["email"])
        return super().update(instance, validated_data)



class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)