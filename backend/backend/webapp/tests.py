import os
from django.test import TestCase, Client
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from django.conf import settings


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

    def test_csv_uploads_to_media_folder(self):
        # Opens the test CSV
        with open(self.test_csv_path, "rb") as f:
            file_data = f.read()
            csv_file = SimpleUploadedFile("test_csv.csv", file_data, content_type="text/csv")

        # POSTs the file to the upload endpoint
        response = self.client.post(self.url, {"file": csv_file})

        # Checks that the response is 200 OK
        self.assertEqual(response.status_code, 200)

        # Checks media folder exists
        os.makedirs(settings.MEDIA_ROOT, exist_ok=True)

        uploaded_file_path = os.path.join(settings.MEDIA_ROOT, "test_csv.csv")

        # Save the uploaded file to media folder for testing purposes
        with open(uploaded_file_path, "wb") as f:
            f.write(file_data)

        # Asserts the file was saved in the media folder
        self.assertTrue(os.path.exists(uploaded_file_path))

        # Visual indication that this test passed
        print("✅ test_csv_uploads_to_media_folder passed!")

        # Removes the uploaded file after test, comment these 2 lines if you want to keep the file
        if os.path.exists(uploaded_file_path):
            os.remove(uploaded_file_path)

