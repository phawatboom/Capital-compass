from django.urls import path
from django.conf.urls.static import static
from django.conf import settings

from .views import (
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
    # Dual-model architecture views
    #UnifiedAnalysisView,
    #UnifiedAnalysisResultView,
    #ModelComparisonView,
    # Beta coefficient model output views
    #BetaRealizedListView,
    #ForecastEvaluationListView,
    #BetaCoefficientSummaryView,
    #BetaCoefficientTimeSeriesView,
    #ImportBetaDataView,
)

# Universal model imports
from .views_universal import (
    ImportUniversalDataView,
    UniversalBetaDashboardView,
    UniversalBetaTimeSeriesView,
    UniversalModelSummaryView,
)

# Integrated workflow imports
from .views_integrated import (
    IntegratedUploadView,
    RunModelView,
    ClientStatusView,
    ClientResultsView,
    ClientListView,
)

urlpatterns = [
    # Data & files
    path('upload-csv/', FileUploadView.as_view(), name='upload-csv'),
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
    
    # Universal Beta Model endpoints (PRIMARY for client use)
    path('universal/import/', ImportUniversalDataView.as_view(), name='universal-import'),
    path('universal/dashboard/', UniversalBetaDashboardView.as_view(), name='universal-dashboard'),
    path('universal/timeseries/', UniversalBetaTimeSeriesView.as_view(), name='universal-timeseries'),
    path('universal/summary/', UniversalModelSummaryView.as_view(), name='universal-summary'),
    
    # Integrated Client Workflow endpoints (Upload -> Process -> View)
    path('integrated/upload/', IntegratedUploadView.as_view(), name='integrated-upload'),
    path('integrated/run-model/', RunModelView.as_view(), name='integrated-run-model'),
    path('integrated/status/<str:client_id>/', ClientStatusView.as_view(), name='integrated-status'),
    path('integrated/results/<str:client_id>/', ClientResultsView.as_view(), name='integrated-results'),
    path('integrated/clients/', ClientListView.as_view(), name='integrated-clients'),
]
