import os
from django.test import TestCase, Client
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile

class CSVUploadTest(TestCase):
    def setUp(self):
        self.client = Client()
        # Path to the test CSV file
        self.test_csv_path = os.path.join(
            os.path.dirname(__file__), "test_data", "test_csv.csv"
        )
        self.url = reverse("upload-csv")

    def test_csv_upload(self):
        # Opens the test CSV
        with open(self.test_csv_path, "rb") as f:
            file_data = f.read()
            print("=== CSV content ===\n")
            print(file_data.decode("utf-8"))
            print("\n===================\n")
            csv_file = SimpleUploadedFile("test_csv.csv", file_data, content_type="text/csv")

        # POSTs the file to the upload endpoint
        response = self.client.post(self.url, {"file": csv_file})

        # Checks that the response is 200 OK
        self.assertEqual(response.status_code, 200)

        # Checks that JSON contains keys 'stock_names' and 'data'
        self.assertIn("stock_names", response.json())
        self.assertIn("data", response.json())

        # Checks first row of data
        data_row = response.json()["data"][0]
        self.assertIn("date", data_row)
        self.assertIn("LYB UN", data_row)
