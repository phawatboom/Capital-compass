from django.urls import path
from .views import CSVUploadView, stock_list, stock_details

# this is the URL configuration for the webapp app
urlpatterns = [
    path('upload-csv/', CSVUploadView.as_view(), name='upload-csv'),
    path('stocks/', stock_list, name ='stock-list'),
    path('stocks/<int:pk>/', stock_details, name='stock-details'),
]
