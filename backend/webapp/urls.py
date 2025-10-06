from django.urls import path
from django.conf.urls.static import static
from django.conf import settings
from .views import analyze_upload


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
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)