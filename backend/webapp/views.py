import csv
import io
from rest_framework.decorators import api_view
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .serializers import CSVUploadSerializer, StockSerializer, StockDataSerializer
from .models import Stock, StockData
from datetime import datetime


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

            # Skip first 3 lines
            for _ in range(3):
                next(reader)

            # Header row with 'Line#', 'Date', stock names
            header_row = next(reader)
            stock_names = header_row[2:]

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
            return Response({"message": "CSV Uploaded Successfully"}, status=status.HTTP_201_CREATED)

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