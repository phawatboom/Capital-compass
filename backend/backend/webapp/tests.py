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


# This test simulates uploading a CSV from outside the project directory(e.g. your Downloads folder).
# To test it, replace the placeholder path with a real path to a CSV file on your computer and uncomment the test.

# class ExternalCSVUploadTest(TestCase):
#     def setUp(self):
#         self.client = Client()
#         self.url = reverse("upload-csv")

#     def test_upload_csv_from_outside_project(self):
#         # Replace this with a real CSV file path on your device
#         outside_csv_path = r"<drive>\\Users\\<User>\\Downloads\\<your-test-csv>.csv"

#         with open(outside_csv_path, "rb") as f:
#             csv_file = SimpleUploadedFile("test_csv.csv", f.read(), content_type="text/csv")

#         response = self.client.post(self.url, {"file": csv_file})

#         # Check that the upload succeeded
#         self.assertEqual(response.status_code, 200)
#         self.assertIn("stock_names", response.json())
#         self.assertIn("data", response.json())
#         print("test_upload_csv_from_outside_project passed!")

#         # Show the first row of data
#         print ("First row of uploaded CSV data:", response.json()["data"][0])

#     def test_save_to_media_from_outside_project(self):
#         # Replace this with a real CSV file path on your device
#         outside_csv_path = r"<drive>\\Users\\<User>\\Downloads\\<your-test-csv>.csv"

#         with open(outside_csv_path, "rb") as f:
#             csv_file = SimpleUploadedFile("test_csv.csv", f.read(), content_type="text/csv")

#         response = self.client.post(self.url, {"file": csv_file})
#         self.assertEqual(response.status_code, 200)

#         # Save the uploaded file to the media folder
#         media_folder = settings.MEDIA_ROOT
#         os.makedirs(media_folder, exist_ok=True)
#         uploaded_file_path = os.path.join(media_folder, "test_csv.csv")
#         with open(uploaded_file_path, "wb") as out_f:
#             out_f.write(csv_file.read())

#         # Verify the file exists
#         self.assertTrue(os.path.exists(uploaded_file_path))
#         print("test_save_to_media_from_outside_project passed!")

#         # Removes the uploaded file after test, comment these 2 lines if you want to keep the file
#         if os.path.exists(uploaded_file_path):
#             os.remove(uploaded_file_path)

