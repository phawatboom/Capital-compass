from django.urls import path
from .views import CSVUploadView

# this is the URL configuration for the webapp app
urlpatterns = [
    path('upload-csv/', CSVUploadView.as_view(), name='upload-csv'),
]
