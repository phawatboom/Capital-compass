from rest_framework import serializers
from .models import (
    Stock, StockData, CSVUploadRecord, UserProfile, 
    BetaForecastResult, MeanReversionResult, BetaRealized, ForecastEvaluation, StockFactorResult, FactorSharedStats
)
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
    is_significant = serializers.BooleanField(read_only=True)

    class Meta:
        model = Stock
        fields = '__all__'


class StockDetailSerializer(StockSerializer):
    data = serializers.SerializerMethodField()

    class Meta(StockSerializer.Meta):
        fields = ['id', 'name', 'b_coefficient', 'p_value', 'data']

    def get_data(self, obj: Stock):
        all_data = StockData.objects.filter(stock=obj).order_by('date')

        data_by_date = {}
        for item in all_data:
            date_str = item.date.isoformat()
            if date_str not in data_by_date:
                data_by_date[date_str] = {'date': date_str, 'price': None, 'return': None, 'equity': None}

            if item.data_type == 'price':
                data_by_date[date_str]['price'] = item.value
            elif item.data_type == 'return':
                data_by_date[date_str]['return'] = item.value
            elif item.data_type == 'equity':
                data_by_date[date_str]['equity'] = item.value

        return list(data_by_date.values())


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


# Dual-Model Architecture Serializers

class BetaForecastResultSerializer(serializers.ModelSerializer):
    """Serializer for beta forecasting results"""
    
    class Meta:
        model = BetaForecastResult
        fields = [
            'forecast_date', 'ticker', 'beta_pred', 'beta_pred_ema',
            'lo', 'hi', 'r2_ols', 'p_value', 'confidence_level',
            'confidence_tier', 'delta_beta_20d', 'conf_20d',
            'agree_adjacent', 'term_unstable', 'action', 'hold_reason'
        ]


class MeanReversionResultSerializer(serializers.ModelSerializer):
    """Serializer for mean-reversion analysis results"""
    
    class Meta:
        model = MeanReversionResult
        fields = [
            'analysis_date', 'ticker', 'z_score_current', 'z_score_trend',
            'mean_reversion_probability', 'reversion_strength',
            'magnitude_prediction', 'magnitude_lower_bound', 'magnitude_upper_bound',
            'calibration_score', 'confidence_interval_90', 'confidence_interval_95',
            'historical_accuracy', 'lookback_period_days',
            'recommendation', 'recommendation_confidence'
        ]


class UnifiedAnalysisResultSerializer(serializers.Serializer):
    """Unified serializer supporting both model types"""
    
    MODEL_TYPE_CHOICES = [
        ('mean-reversion', 'Mean Reversion'),
        ('beta-forecasting', 'Beta Forecasting'),
    ]
    
    analysis_id = serializers.CharField()
    model_type = serializers.ChoiceField(choices=MODEL_TYPE_CHOICES)
    ticker = serializers.CharField()
    name = serializers.CharField()
    analysis_date = serializers.DateField()
    recommendation = serializers.ChoiceField(choices=[('BUY', 'Buy'), ('SELL', 'Sell'), ('HOLD', 'Hold')])
    confidence = serializers.FloatField()
    model_data = serializers.SerializerMethodField()
    
    def get_model_data(self, obj):
        """Return model-specific data based on model_type"""
        if obj.get('model_type') == 'mean-reversion':
            return obj.get('mean_reversion_data', {})
        elif obj.get('model_type') == 'beta-forecasting':
            return obj.get('beta_forecast_data', {})
        return {}


class ModelComparisonSerializer(serializers.Serializer):
    """Serializer for comparing both models"""
    
    mean_reversion = UnifiedAnalysisResultSerializer()
    beta_forecasting = UnifiedAnalysisResultSerializer()
    comparison = serializers.DictField(child=serializers.CharField())


class AnalysisRequestSerializer(serializers.Serializer):
    """Serializer for analysis requests with model selection"""
    
    upload_id = serializers.CharField()
    model_type = serializers.ChoiceField(
        choices=[
            ('mean-reversion', 'Mean Reversion'),
            ('beta-forecasting', 'Beta Forecasting'),
            ('both', 'Both Models'),
        ]
    )
    tickers = serializers.ListField(
        child=serializers.CharField(max_length=10),
        required=False,
        help_text="Optional list of specific tickers to analyze"
    )


# Beta Coefficient Model Output Serializers
class BetaRealizedSerializer(serializers.ModelSerializer):
    """Serializer for beta realized data from betas_20d.csv"""
    
    class Meta:
        model = BetaRealized
        fields = [
            'date', 'ticker', 'beta_realised', 'r2_ols_x', 'r2_ols_y',
            'p_value', 'significance_score', 'beta_pred', 'beta_true',
            'band', 'lo', 'hi'
        ]


class ForecastEvaluationSerializer(serializers.ModelSerializer):
    """Serializer for forecast evaluation data from forecast_eval_20d.csv"""
    
    class Meta:
        model = ForecastEvaluation
        fields = [
            'date', 'ticker', 'r2_ols', 'p_value', 'significance_score',
            'beta_pred', 'beta_true', 'band'
        ]


class BetaCoefficientSummarySerializer(serializers.Serializer):
    """Combined summary serializer for beta coefficient analysis"""
    
    ticker = serializers.CharField()
    latest_date = serializers.DateField()
    latest_beta_pred = serializers.FloatField()
    latest_beta_true = serializers.FloatField(allow_null=True)
    avg_r2_ols = serializers.FloatField()
    prediction_accuracy = serializers.FloatField()
    forecast_count = serializers.IntegerField()
    confidence_level = serializers.CharField()


class BetaCoefficientTimeSeriesSerializer(serializers.Serializer):
    """Time series data for beta coefficient visualization"""
    
    dates = serializers.ListField(child=serializers.DateField())
    beta_pred = serializers.ListField(child=serializers.FloatField())
    beta_true = serializers.ListField(child=serializers.FloatField(allow_null=True))
    confidence_bands = serializers.ListField(
        child=serializers.DictField(child=serializers.FloatField())
    )


class FactorSharedStatsSerializer(serializers.ModelSerializer):
    class Meta:
        model = FactorSharedStats
        fields = "__all__"


class StockFactorResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockFactorResult
        fields = [
            "id", "ticker", "b_coefficient", "y_intercept", "volatility",
            "train_b", "lag_train_b", "ar1_corr_10d", "ar1_corr_20d", "ar1_corr_60d",
            "sign_persist_20d", "sign_persist_60d", "ret_1d", "ret_5d", "ret_20d",
            "vol_63d", "vol_126d", "vol_252d", "vol_756d", "Z_ma_20d",
            "cs_rank_ret_1d", "cs_rank_ret_5d", "cs_rank_ret_20d", "cs_rank_ret_20d",
            "created_at", "shared_stats_id"
        ]


class StockFactorTimeSeriesSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockFactorResult
        fields = [
            "created_at",
            "b_coefficient",
            "volatility",
            "train_b",
            "lag_train_b",
            "ret_1d",
            "ret_5d",
            "ret_20d",
            "vol_63d",
            "vol_126d",
            "vol_252d",
            "vol_756d",
            "Z_ma_20d",
        ]
