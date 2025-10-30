from rest_framework import serializers
from .models import (
    Stock, StockData, CSVUploadRecord, StockOOSMetric, UserProfile, 
     BetaRealized, StockFactorResult, FactorSharedStats,
    AnalysisRun, ModelCoefficient, StockPrediction, StockPerformanceMetrics, OutOfSamplePrediction, FoldStatistics
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
    y_intercept = serializers.FloatField(source="intercept_raw", read_only=True)  # <-- add this line
    class Meta:
        model = FactorSharedStats
        fields = "__all__"


class StockFactorResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockFactorResult
        fields = [
            "id",
            "ticker",
            "b_coefficient",
            "y_intercept",
            "volatility",
            "train_b",
            "lag_train_b",
            "ar1_corr_10d",
            "ar1_corr_20d",
            "ar1_corr_60d",
            "sign_persist_20d",
            "sign_persist_60d",
            "ret_1d",
            "ret_5d",
            "ret_20d",
            "vol_63d",
            "vol_126d",
            "vol_252d",
            "vol_756d",
            "Z_ma_20d",
            "cs_rank_ret_1d",
            "cs_rank_ret_5d",
            "cs_rank_ret_20d",
            "cs_rank_z_ma_20d",
            "xsec_disp_1d",
            "xsec_disp_30d",
            "created_at",
            "shared_stats_id",
            "horizon_days",  
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
            "horizon_days",
        ]

class FactorSharedStatsSummarySerializer(serializers.ModelSerializer):
    top_abs   = serializers.SerializerMethodField()
    top_pos   = serializers.SerializerMethodField()
    top_neg   = serializers.SerializerMethodField()
    equation  = serializers.CharField(source="model_equation", read_only=True)
    config    = serializers.SerializerMethodField()
    class Meta:
        model = FactorSharedStats
        fields = ["id", "created_at", "model_used", "horizon_days",
                  "r2_global", "equation", "top_abs", "top_pos", "top_neg", "config"]

    def _sorted(self, obj):
        items = (obj.coef_raw or {}).items()
        return sorted(items, key=lambda kv: abs(kv[1]), reverse=True)

    def get_top_abs(self, obj):
        s = self._sorted(obj)
        return {"feature": s[0][0], "coef": s[0][1]} if s else None

    def get_top_pos(self, obj):
        pos = [(k, v) for k, v in (obj.coef_raw or {}).items() if v > 0]
        if not pos: return None
        k, v = max(pos, key=lambda kv: kv[1]); return {"feature": k, "coef": v}

    def get_top_neg(self, obj):
        neg = [(k, v) for k, v in (obj.coef_raw or {}).items() if v < 0]
        if not neg: return None
        k, v = min(neg, key=lambda kv: kv[1]); return {"feature": k, "coef": v}

    def get_config(self, obj):
        return {
            "training_days": obj.training_days,
            "testing_days": obj.testing_days,
            "enet_alpha": obj.enet_alpha,
            "enet_l1_ratio": obj.enet_l1_ratio,
            "oos_min_train_rows": getattr(obj, "oos_min_train_rows", None),
        }


class StockOOSMetricSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockOOSMetric
        fields = ["ticker", "r2_oos", "rmse_oos", "mae_oos", "mase_oos",
                  "diracc_oos", "predstd_oos", "n_oos"]
# Pooled Model Output Serializers
class AnalysisRunSerializer(serializers.ModelSerializer):
    """Serializer for analysis runs with comprehensive metrics"""
    
    duration_seconds = serializers.SerializerMethodField()
    total_predictions = serializers.SerializerMethodField()
    unique_stocks = serializers.SerializerMethodField()
    
    class Meta:
        model = AnalysisRun
        fields = [
            'id', 'run_name', 'model_type', 'horizon_days', 'created_at', 'completed_at', 'status',
            'mae', 'rmse', 'directional_accuracy', 'sample_size', 'r2_global', 'r2_fold_mean', 'r2_fold_weighted',
            'mae_ratio_global', 'mae_ratio_fold_mean', 'mae_ratio_fold_weighted',
            'duration_seconds', 'total_predictions', 'unique_stocks'
        ]
    
    def get_duration_seconds(self, obj):
        if obj.completed_at and obj.created_at:
            return (obj.completed_at - obj.created_at).total_seconds()
        return None
    
    def get_total_predictions(self, obj):
        return obj.predictions.count()
    
    def get_unique_stocks(self, obj):
        return obj.predictions.values('ticker').distinct().count()


class ModelCoefficientSerializer(serializers.ModelSerializer):
    """Serializer for model coefficients"""
    
    class Meta:
        model = ModelCoefficient
        fields = ['feature_name', 'coefficient_value']


class StockPredictionSerializer(serializers.ModelSerializer):
    """Serializer for individual stock predictions with all features"""
    
    class Meta:
        model = StockPrediction
        fields = [
            'ticker', 'prediction_date', 'final_prediction',
            'train_b', 'lag_train_b', 'ar1_corr_10d', 'ar1_corr_20d', 'ar1_corr_60d',
            'sign_persist_20d', 'sign_persist_60d', 'ret_1d', 'ret_5d', 'ret_20d',
            'vol_63d', 'vol_126d', 'vol_252d', 'vol_756d', 'z_ma_20d',
            'cs_rank_ret_1d', 'cs_rank_ret_5d', 'cs_rank_ret_20d', 'cs_rank_z_ma_20d',
            'cs_rank_vol_63d', 'cs_rank_vol_126d', 'cs_rank_vol_252d', 'cs_rank_vol_756d',
            'xsec_disp_30d'
        ]


class StockPredictionSummarySerializer(serializers.ModelSerializer):
    """Simplified serializer for stock prediction summaries"""
    
    class Meta:
        model = StockPrediction
        fields = ['ticker', 'prediction_date', 'final_prediction', 'train_b', 'ret_1d', 'vol_63d']


class StockPerformanceMetricsSerializer(serializers.ModelSerializer):
    """Serializer for per-stock performance metrics"""
    
    class Meta:
        model = StockPerformanceMetrics
        fields = [
            'ticker', 'r2_oos', 'rmse_oos', 'mae_oos', 'mase_oos', 
            'dir_acc_oos', 'pred_std_oos', 'n_obs_oos'
        ]


class OutOfSamplePredictionSerializer(serializers.ModelSerializer):
    """Serializer for out-of-sample predictions"""
    
    class Meta:
        model = OutOfSamplePrediction
        fields = [
            'ticker', 'date', 'y_pred', 'y_actual', 'prediction_error', 
            'abs_error', 'squared_error', 'fold_id'
        ]


class FoldStatisticsSerializer(serializers.ModelSerializer):
    """Serializer for cross-validation fold statistics"""
    
    class Meta:
        model = FoldStatistics
        fields = [
            'fold_id', 'fold_r2', 'fold_mae', 'fold_rmse', 'fold_directional_acc', 'fold_n_obs',
            'train_start_date', 'train_end_date', 'val_start_date', 'val_end_date'
        ]


class AnalysisRunDetailSerializer(AnalysisRunSerializer):
    """Detailed serializer with related data"""
    
    coefficients = ModelCoefficientSerializer(many=True, read_only=True)
    fold_statistics = FoldStatisticsSerializer(many=True, read_only=True)
    top_performers = serializers.SerializerMethodField()
    worst_performers = serializers.SerializerMethodField()
    
    class Meta(AnalysisRunSerializer.Meta):
        fields = AnalysisRunSerializer.Meta.fields + [
            'coefficients', 'fold_statistics', 'top_performers', 'worst_performers'
        ]
    
    def get_top_performers(self, obj):
        """Get top 10 stocks by directional accuracy"""
        top_stocks = obj.stock_metrics.order_by('-dir_acc_oos')[:10]
        return StockPerformanceMetricsSerializer(top_stocks, many=True).data
    
    def get_worst_performers(self, obj):
        """Get bottom 10 stocks by directional accuracy"""
        worst_stocks = obj.stock_metrics.order_by('dir_acc_oos')[:10]
        return StockPerformanceMetricsSerializer(worst_stocks, many=True).data


class DashboardSummarySerializer(serializers.Serializer):
    """Serializer for dashboard summary data"""
    
    total_runs = serializers.IntegerField()
    latest_run = AnalysisRunSerializer(allow_null=True)
    avg_directional_accuracy = serializers.FloatField()
    avg_r2 = serializers.FloatField()
    total_predictions = serializers.IntegerField()
    unique_stocks = serializers.IntegerField()
    recent_activity = serializers.ListField(child=AnalysisRunSerializer())


class StockAnalysisSerializer(serializers.Serializer):
    """Serializer for individual stock analysis across runs"""
    
    ticker = serializers.CharField()
    total_predictions = serializers.IntegerField()
    avg_prediction = serializers.FloatField()
    avg_performance = serializers.FloatField()
    best_r2 = serializers.FloatField()
    latest_prediction = serializers.FloatField(allow_null=True)
    latest_date = serializers.DateField(allow_null=True)
    recent_predictions = StockPredictionSummarySerializer(many=True)


class ModelComparisonAnalysisSerializer(serializers.Serializer):
    """Serializer for comparing different model runs"""
    
    model_a = AnalysisRunSerializer()
    model_b = AnalysisRunSerializer()
    performance_comparison = serializers.DictField()
    coefficient_differences = serializers.ListField(child=serializers.DictField())


class TimeSeriesAnalysisSerializer(serializers.Serializer):
    """Serializer for time series analysis data"""
    
    dates = serializers.ListField(child=serializers.DateField())
    predictions = serializers.ListField(child=serializers.FloatField())
    actuals = serializers.ListField(child=serializers.FloatField(allow_null=True))
    errors = serializers.ListField(child=serializers.FloatField(allow_null=True))
    cumulative_r2 = serializers.ListField(child=serializers.FloatField())


class PredictionDistributionSerializer(serializers.Serializer):
    """Serializer for prediction distribution analysis"""
    
    bins = serializers.ListField(child=serializers.FloatField())
    counts = serializers.ListField(child=serializers.IntegerField())
    percentiles = serializers.DictField(child=serializers.FloatField())
    statistics = serializers.DictField(child=serializers.FloatField())

