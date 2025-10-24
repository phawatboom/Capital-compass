from django.contrib import admin
from .models_universal import UniversalBetaPrediction, UniversalModelMetrics, StockUniversalMetrics

# Universal Beta Model Admin
@admin.register(UniversalBetaPrediction)
class UniversalBetaPredictionAdmin(admin.ModelAdmin):
    list_display = ('ticker', 'date', 'horizon_days', 'final_prediction', 'prediction_direction', 'confidence_tier')
    list_filter = ('horizon_days', 'prediction_direction', 'confidence_tier', 'date')
    search_fields = ('ticker',)
    ordering = ('-date', 'ticker')
    date_hierarchy = 'date'

@admin.register(UniversalModelMetrics)
class UniversalModelMetricsAdmin(admin.ModelAdmin):
    list_display = ('horizon_days', 'r2_global', 'directional_accuracy', 'n_predictions', 'last_updated')
    ordering = ('horizon_days',)

@admin.register(StockUniversalMetrics)
class StockUniversalMetricsAdmin(admin.ModelAdmin):
    list_display = ('ticker', 'horizon_days', 'r2_oos', 'dir_acc_oos', 'performance_tier')
    list_filter = ('horizon_days', 'performance_tier')
    search_fields = ('ticker',)
    ordering = ('-r2_oos',)
