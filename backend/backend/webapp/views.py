import csv
import io
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .serializers import CSVUploadSerializer

class CSVUploadView(APIView):
    def post(self, request, *args, **kwargs):
        serializer = CSVUploadSerializer(data=request.data)
        if serializer.is_valid():
            file = serializer.validated_data['file']

            # Read CSV file
            decoded_file = file.read().decode('utf-8')
            io_string = io.StringIO(decoded_file)
            reader = csv.reader(io_string)

            # Skip first 3 lines
            for _ in range(3):
                next(reader)

            # Header row with 'Line#', 'Date', stock names
            header_row = next(reader)
            stock_names = header_row[2:]  # skip 'Line#' and 'Date'

            # Collect data starting from row 6
            data_rows = list(reader)
            structured_data = []

            for row in data_rows:
                date = row[1]  # Column B
                row_data = {"date": date}
                for stock, value in zip(stock_names, row[2:]):
                    # Convert #N/A to None, numbers to float
                    if value.strip() == "#N/A":
                        row_data[stock] = None
                    else:
                        try:
                            row_data[stock] = float(value)
                        except ValueError:
                            row_data[stock] = value
                structured_data.append(row_data)

            return Response({
                "stock_names": stock_names,
                "data": structured_data
            }, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
