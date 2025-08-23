# file: backend/webapp/views.py
import csv
import io
import os
from datetime import datetime

from django.http import FileResponse
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Stock, StockData, CSVUploadRecord
from .serializers import (
    CSVUploadSerializer,
    StockSerializer,
    StockDataSerializer,
    CSVUploadRecordSerializer,
)

class CSVUploadView(APIView):
    def post(self, request, *args, **kwargs):
        serializer = CSVUploadSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        file = serializer.validated_data['file']

        try:
            decoded_file = file.read().decode('utf-8')
            io_string = io.StringIO(decoded_file)
            reader = csv.reader(io_string)
            # Remove empty rows
            reader = (row for row in reader if any(cell.strip() for cell in row))

            # Skip first 3 lines
            for _ in range(3):
                next(reader)

            # Header row with 'Line#', 'Date', stock names
            header_row = [cell.strip() for cell in next(reader)]
            stock_names = [cell.strip() for cell in header_row[2:]]

            stocks = {}
            for stock_name in stock_names:
                stock_obj, created = Stock.objects.get_or_create(name=stock_name)
                stocks[stock_name] = stock_obj

            for row in reader:
                date_str = row[1]
                date_object = datetime.strptime(date_str, '%d-%b-%Y').date()

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
def stock_list(request):
    stocks = Stock.objects.all()
    serializer = StockSerializer(stocks, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


# Retrieve details and all data points for a specific stock.
@api_view(['GET'])
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
def list_csv_uploads(request):
    records = CSVUploadRecord.objects.all().order_by('-uploaded_at')
    serializer = CSVUploadRecordSerializer(records, many=True)
    return Response(serializer.data)


@api_view(["GET"])
def download_csv(request, pk):
    try:
        upload = CSVUploadRecord.objects.get(pk=pk)
    except CSVUploadRecord.DoesNotExist:
        return Response({"error": "File not found"}, status=404)

    return FileResponse(upload.filename.open("rb"), as_attachment=True, filename=os.path.basename(upload.filename.name))



# 2. Authentication and Permissions

@api_view(['POST'])
def register_user(request):
    '''
    Register a new user with username, password, and optional email.
    '''
    username = request.data.get('username')
    password = request.data.get('password')
    email = request.data.get('email', '')

    if not username or not password:
        return Response({"error": "Username and password are required"},
                        status=status.HTTP_400_BAD_REQUEST)

    if User.objects.filter(username=username).exists():
        return Response({"error": "Username already exists"},
                        status=status.HTTP_400_BAD_REQUEST)

    try:
        validate_password(password)
        User.objects.create_user(username=username, password=password, email=email)
        return Response({"success": "User created successfully"},
                        status=status.HTTP_201_CREATED)
    except ValidationError as e:
        return Response({"error": e.messages}, status=status.HTTP_400_BAD_REQUEST)



api_view(['POST'])
def login_user(request):
    '''
    Authenticate a user with username and password.
    Returns a token if successful.
    '''
    username = request.data.get('username')
    password = request.data.get('password')

    if not username or not password:
        return Response({"error": "Username and password are required"},
                        status=status.HTTP_400_BAD_REQUEST)

    user = authenticate(request, username=username, password=password)
    if user is not None:
        token, created = Token.objects.get_or_create(user=user)
        return Response({"token": token.key}, status=status.HTTP_200_OK)
    else:
        return Response({"error": "Invalid credentials"},
                        status=status.HTTP_401_UNAUTHORIZED)