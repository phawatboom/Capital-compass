# file: backend/webapp/views.py
import csv
import io
import os
from datetime import datetime

from django.contrib.auth import authenticate, login, logout
from django.views.decorators.csrf import ensure_csrf_cookie
from django.http import FileResponse
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Stock, StockData, CSVUploadRecord
from datetime import date, datetime
from django.http import FileResponse

from .serializers import (
    CSVUploadSerializer,
    StockSerializer,
    StockDataSerializer,
    CSVUploadRecordSerializer,
)

# --- CSRF bootstrap ---
@api_view(["GET"])
@ensure_csrf_cookie
@permission_classes([AllowAny])
def csrf(request):
    return Response({"detail": "CSRF cookie set"})

def _parse_date(date_str: str) -> date:
    date_str = date_str.strip()
    for fmt in ("%d-%b-%Y", "%d-%b-%y", "%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"time data '{date_str}' does not match expected formats")

class CSVUploadView(APIView):
    # permission_classes = [IsAuthenticated]
    def post(self, request, *args, **kwargs):
        serializer = CSVUploadSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        file = serializer.validated_data['file']

        try:
            decoded_file = file.read().decode('utf-8')
            io_string = io.StringIO(decoded_file)
            reader = csv.reader(io_string)
            for row in reader:
                cells = [c.strip().lower() for c in row]
                if len(cells) >= 2 and cells[0] == "line#" and cells[1] == "date":
                    header_row = [c.strip() for c in row]
                    break
            else:
                return Response({"error": "Header row 'Line#,Date,...' not found."}, status=400)

            stock_names = [c for c in header_row[2:] if c]

            stocks = {}
            for stock_name in stock_names:
                stock_obj, created = Stock.objects.get_or_create(name=stock_name)
                stocks[stock_name] = stock_obj

            for row in reader:
                date_str = row[1]
                try:
                    date_object = _parse_date(date_str)

                except ValueError as e:
                    return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

                for stock_name, value_str in zip(stock_names, row[2:]):
                    value = None
                    if value_str.strip() != "#N/A":
                        try:
                            value = float(value_str)
                        except (ValueError, IndexError):
                            # Skip this data point if the value is invalid
                            continue

                    stock_obj = stocks[stock_name]
                    StockData.objects.update_or_create(
                        stock=stock_obj,
                        date=date_object,
                        defaults={'value': value}
                    )

            upload_record = CSVUploadRecord.objects.create(filename=file)

            return Response({
                "message": "CSV Uploaded Successfully",
                "upload": {
                    "id": upload_record.id,
                    "filename": upload_record.filename,
                    "uploaded_at": upload_record.uploaded_at
                }
            }, status=status.HTTP_201_CREATED)

        except (StopIteration, IndexError) as e:
            # Correctly handle invalid CSV files as a client error (400)
            return Response({"error": "Invalid CSV file. Check header and row counts."},
                            status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            # Catch other unexpected errors and return a 500
            return Response({"error": f"An unexpected error occurred: {e}"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# List all stocks.
@api_view(['GET'])
# @permission_classes([AllowAny])
def stock_list(request):
    stocks = Stock.objects.all()
    serializer = StockSerializer(stocks, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


# Retrieve details and all data points for a specific stock.
@api_view(['GET'])
# @permission_classes([AllowAny])
def stock_details(request, pk):
    try:
        stock = Stock.objects.get(pk=pk)
    except Stock.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    stock_serializer = StockSerializer(stock)
    stock_data_list = StockData.objects.filter(stock=stock).order_by('date')
    stock_data_serializer = StockDataSerializer(stock_data_list, many=True)

    return Response({
        "stock_info": stock_serializer.data,
        "data_points": stock_data_serializer.data
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
# @permission_classes([IsAuthenticated])
def list_csv_uploads(request):
    records = CSVUploadRecord.objects.all().order_by('-uploaded_at')
    serializer = CSVUploadRecordSerializer(records, many=True)
    return Response(serializer.data)


@api_view(["GET"])
# @permission_classes([IsAuthenticated])
def download_csv(request, pk):
    try:
        upload = CSVUploadRecord.objects.get(pk=pk)
    except CSVUploadRecord.DoesNotExist:
        return Response({"error": "File not found"}, status=404)

    return FileResponse(upload.filename.open("rb"), as_attachment=True, filename=os.path.basename(upload.filename.name))





# 2. Authentication and Permissions



# # --- CSRF bootstrap ---
# @api_view(["GET"])
# @ensure_csrf_cookie
# @permission_classes([AllowAny])
# def csrf(request):
#     return Response({"detail": "CSRF cookie set"})
#
#
# # --- Login (creates server-side session + sets sessionid cookie) ---
# @api_view(["POST"])
# @permission_classes([AllowAny])
# def login_user(request):
#     username = request.data.get("username")
#     password = request.data.get("password")
#     if not username or not password:
#         return Response({"error": "Username and password are required"}, status=400)
#
#     user = authenticate(request, username=username, password=password)
#     if user is None:
#         return Response({"error": "Invalid credentials"}, status=401)
#
#     login(request, user)  # sets session
#     return Response({"detail": "ok"})
#
#
# # --- Logout (clears session) ---
# @api_view(["POST"])
# def logout_user(request):
#     logout(request)
#     return Response({"detail": "logged out"})
#
#
# # --- Who am I (for frontend to read role or user state) ---
# @api_view(["GET"])
# def me(request):
#     u = request.user
#     return Response({
#         "authenticated": u.is_authenticated,
#         "username": u.username if u.is_authenticated else None,
#         "is_staff": u.is_staff if u.is_authenticated else False,
#         "is_superuser": u.is_superuser if u.is_authenticated else False,
#         "is_moderator": (
#             u.groups.filter(name="mods").exists() or
#             u.has_perm("webapp.can_moderate")
#         ) if u.is_authenticated else False,
#     })
