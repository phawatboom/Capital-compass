from django.urls import path
from .views import (
    CSVUploadView,
    stock_list,
    stock_details,
    list_csv_uploads,
    download_csv,
    csrf, register_user,
    login_user,
    logout_user,
    me
)

# this is the URL configuration for the webapp app
urlpatterns = [
    path('upload-csv/', CSVUploadView.as_view(), name='upload-csv'),
    path('stocks/', stock_list, name ='stock-list'),
    path('stocks/<int:pk>/', stock_details, name='stock-details'),
    path('csv-uploads/', list_csv_uploads, name='list-csv-uploads'),
    path('csv-uploads/<int:pk>/download/', download_csv, name='download-csv'),
    #auth
    # Auth/session endpoints
    path('auth/csrf/', csrf, name='csrf'),
    path('auth/register/', register_user, name='register'),
    path('auth/login/', login_user, name='login'),
    path('auth/logout/', logout_user, name='logout'),
    path('auth/me/', me, name='me'),
]
