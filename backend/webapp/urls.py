from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    upload_status,
    FileUploadView,
    stock_list,
    stock_details,
    list_csv_uploads,
    download_csv,
    csrf, register_user,
    login_user,
    logout_user,
    me,
    delete_csv_upload,
    information_file,
    profile_view,
    profile_avatar,
    change_password,
    factor_shared,
    factor_summary,
    analyze_upload,
    beta_timeseries,
    # Pooled Model API views
    AnalysisRunViewSet,
    dashboard_summary,
    stock_analysis,
    time_series_analysis,
    prediction_distribution,
    save_analysis_results,
    factor_stats_latest_summary,
    factor_stats_summary,
    factor_stats_oos_table,
)


# Integrated workflow imports
from .views_integrated import (
    IntegratedUploadView,
    RunModelView,
    ClientStatusView,
    ClientResultsView,
    ClientListView,
)

# Create router for ViewSets
router = DefaultRouter()
router.register(r'analysis-runs', AnalysisRunViewSet, basename='analysis-run')

urlpatterns = [
    # Data & files
    path("upload-csv/", FileUploadView.as_view(), name="upload-csv"),
    path("uploads/<int:pk>/status/", upload_status, name="upload-status"),
    path('stocks/', stock_list, name='stock-list'),
    path('stocks/<int:pk>/', stock_details, name='stock-details'),
    path('csv-uploads/', list_csv_uploads, name='list-csv-uploads'),
    path('csv-uploads/<int:pk>/download/', download_csv, name='download-csv'),
    path('csv-uploads/<int:pk>/', delete_csv_upload, name='delete-csv'),
    path('csv-uploads/<int:pk>/meta/', information_file, name='info-file'),

    # Auth/session
    path('auth/csrf/', csrf, name='csrf'),
    path('auth/register/', register_user, name='register'),
    path('auth/login/', login_user, name='login'),
    path('auth/logout/', logout_user, name='logout'),
    path('auth/me/', me, name='me'),

    # Profile & password
    path('auth/profile/', profile_view, name='profile'),
    path('auth/profile/avatar/', profile_avatar, name='profile-avatar'),
    path('auth/change-password/', change_password, name='change-password'),

    # Model analysis
    path('csv-uploads/<int:pk>/analyze/', analyze_upload, name='analyze-upload'),
    
    # Trey's factor endpoints (from his implementation)
    path("factors/summary/", factor_summary, name="factor-summary"),
    path("factors/shared/", factor_shared, name="factor-shared"),
    path("beta/timeseries/<str:ticker>/", beta_timeseries, name="beta_timeseries"),

    
    # Integrated Client Workflow endpoints (Upload -> Process -> View)
    path('integrated/upload/', IntegratedUploadView.as_view(), name='integrated-upload'),
    path('integrated/run-model/', RunModelView.as_view(), name='integrated-run-model'),
    path('integrated/status/<str:client_id>/', ClientStatusView.as_view(), name='integrated-status'),
    path('integrated/results/<str:client_id>/', ClientResultsView.as_view(), name='integrated-results'),
    path('integrated/clients/', ClientListView.as_view(), name='integrated-clients'),
    
    # Pooled Model API endpoints
    path('', include(router.urls)),  # ViewSet routes (includes analysis-runs/)
    path('dashboard-summary/', dashboard_summary, name='dashboard-summary'),
    path('stock-analysis/<str:ticker>/', stock_analysis, name='stock-analysis'),
    path('time-series/<int:run_id>/<str:ticker>/', time_series_analysis, name='time-series-analysis'),
    path('prediction-distribution/<int:run_id>/', prediction_distribution, name='prediction-distribution'),

    path('save-analysis/', save_analysis_results, name='save-analysis-results'),
    path("factor-stats/<int:pk>/summary/", factor_stats_summary, name="factor-stats-summary"),
    path("factor-stats/<int:pk>/oos/", factor_stats_oos_table, name="factor-stats-oos"),
    path("factor-stats/latest/summary/", factor_stats_latest_summary),
    
]
