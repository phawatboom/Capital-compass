import os
from django.test import TestCase, Client
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from .models import Stock, StockData
from datetime import date


class CSVUploadTest(TestCase):
    def setUp(self):
        self.client = Client()
        # Path to the test CSV file
        self.test_csv_path = os.path.join(
            os.path.dirname(__file__), "test_data", "test_excel - Prices.csv"
        )
        self.url = reverse("upload-csv")

    def test_csv_upload(self):
        # Get the number of Stock and StockData objects before the upload
        initial_stock_count = Stock.objects.count()
        initial_stock_data_count = StockData.objects.count()
        print(f"Initial Stock count: {initial_stock_count}")
        print(f"Initial StockData count: {initial_stock_data_count}")

        # Opens the test CSV
        with open(self.test_csv_path, "rb") as f:
            file_data = f.read()
            csv_file = SimpleUploadedFile("test_excel - Prices.csv", file_data, content_type="text/csv")

        # POSTs the file to the upload endpoint
        response = self.client.post(self.url, {"file": csv_file})

        # Checks that the response is 201 CREATED
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["message"], "File uploaded and processed successfully.")

        # Checks that JSON contains keys 'stock_names' and 'data'
        self.assertEqual(Stock.objects.count(), initial_stock_count + 3)
        self.assertTrue(Stock.objects.filter(name="LYB UN").exists())
        self.assertTrue(Stock.objects.filter(name="AXP UN").exists())
        self.assertTrue(Stock.objects.filter(name="VZ UN").exists())

        # Verify that new StockData objects were created
        self.assertEqual(StockData.objects.count(), initial_stock_data_count + 93)

        # Check a few specific data points
        lyb_stock = Stock.objects.get(name="LYB UN")
        lyb_data = StockData.objects.get(stock=lyb_stock, date=date(2010, 7, 30))
        self.assertTrue(lyb_data.value, "nan") # This value is 'N/A' in the CSV

        axp_stock = Stock.objects.get(name="AXP UN")
        axp_data_na = StockData.objects.get(stock=axp_stock, date=date(2010, 8, 2))
        self.assertTrue(axp_data_na.value, 36.36)


    def test_invalid_csv_upload(self):
        # Test with an invalid CSV file
        invalid_csv = SimpleUploadedFile("invalid.csv", b"not,a,valid,csv", content_type="text/csv")
        response = self.client.post(self.url, {"file": invalid_csv})

        # Check that the response is 500 BAD REQUEST
        self.assertEqual(response.status_code, 500)
        self.assertIn("error", response.json())

class StockAPITests(TestCase):
    def setUp(self):
        self.client = Client()
        self.upload_url = reverse("upload-csv")
        self.list_url = reverse("stock-list")
        self.detail_url = "stock-details"  # We'll use this with reverse() later

        # First, upload a valid CSV to populate the database for subsequent tests
        self.test_csv_path = os.path.join(
            os.path.dirname(__file__), "test_data", "test_excel - Returns.csv"
        )
        with open(self.test_csv_path, "rb") as f:
            file_data = f.read()
            csv_file = SimpleUploadedFile("test_example - Returns.csv", file_data, content_type="text/csv")
        self.client.post(self.upload_url, {"file": csv_file})

        # Store a known stock object for later use
        self.stock_lyb = Stock.objects.get(name="LYB UN")

    def test_stock_list_view(self):
        # Tests that the stock_list view returns a list of stocks.
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 3)  # Expect 3 stocks from the CSV
        self.assertIn("LYB UN", [stock['name'] for stock in response.json()])
        self.assertIn("AXP UN", [stock['name'] for stock in response.json()])
        self.assertIn("VZ UN", [stock['name'] for stock in response.json()])

    def test_stock_details_view_success(self):
        # Tests that the stock_details view returns details for a specific stock.
        # Build the URL with the pk of the stock we know exists
        url = reverse(self.detail_url, kwargs={'pk': self.stock_lyb.pk})
        response = self.client.get(url)

        import os
        from django.test import TestCase, Client
        from django.urls import reverse
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .models import Stock, StockData
        from datetime import date

        class CSVUploadTest(TestCase):
            def setUp(self):
                self.client = Client()
                # Path to the test CSV file
                self.test_csv_path = os.path.join(
                    os.path.dirname(__file__), "test_data", "test_excel - Prices.csv"
                )
                self.url = reverse("upload-csv")

            def test_csv_upload(self):
                # Get the number of Stock and StockData objects before the upload
                initial_stock_count = Stock.objects.count()
                initial_stock_data_count = StockData.objects.count()
                print(f"Initial Stock count: {initial_stock_count}")
                print(f"Initial StockData count: {initial_stock_data_count}")

                # Opens the test CSV
                with open(self.test_csv_path, "rb") as f:
                    file_data = f.read()
                    csv_file = SimpleUploadedFile("test_excel - Prices.csv", file_data, content_type="text/csv")

                # POSTs the file to the upload endpoint
                response = self.client.post(self.url, {"file": csv_file})

                # Checks that the response is 201 CREATED
                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.json()["message"], "File uploaded and processed successfully.")

                # Checks that JSON contains keys 'stock_names' and 'data'
                self.assertEqual(Stock.objects.count(), initial_stock_count + 3)
                self.assertTrue(Stock.objects.filter(name="LYB UN").exists())
                self.assertTrue(Stock.objects.filter(name="AXP UN").exists())
                self.assertTrue(Stock.objects.filter(name="VZ UN").exists())

                # Verify that new StockData objects were created
                self.assertEqual(StockData.objects.count(), initial_stock_data_count + 93)

                # Check a few specific data points
                lyb_stock = Stock.objects.get(name="LYB UN")
                lyb_data = StockData.objects.get(stock=lyb_stock, date=date(2010, 7, 30))
                self.assertTrue(lyb_data.value, "nan")  # This value is 'N/A' in the CSV

                axp_stock = Stock.objects.get(name="AXP UN")
                axp_data_na = StockData.objects.get(stock=axp_stock, date=date(2010, 8, 2))
                self.assertTrue(axp_data_na.value, 36.36)

            def test_invalid_csv_upload(self):
                # Test with an invalid CSV file
                invalid_csv = SimpleUploadedFile("invalid.csv", b"not,a,valid,csv", content_type="text/csv")
                response = self.client.post(self.url, {"file": invalid_csv})

                # Check that the response is 500 BAD REQUEST
                self.assertEqual(response.status_code, 500)
                self.assertIn("error", response.json())

        class StockAPITests(TestCase):
            def setUp(self):
                self.client = Client()
                self.upload_url = reverse("upload-csv")
                self.list_url = reverse("stock-list")
                self.detail_url = "stock-details"  # We'll use this with reverse() later

                # First, upload a valid CSV to populate the database for subsequent tests
                self.test_csv_path = os.path.join(
                    os.path.dirname(__file__), "test_data", "test_excel - Returns.csv"
                )
                with open(self.test_csv_path, "rb") as f:
                    file_data = f.read()
                    csv_file = SimpleUploadedFile("test_example - Returns.csv", file_data, content_type="text/csv")
                self.client.post(self.upload_url, {"file": csv_file})

                # Store a known stock object for later use
                self.stock_lyb = Stock.objects.get(name="LYB UN")

            def test_stock_list_view(self):
                # Tests that the stock_list view returns a list of stocks.
                response = self.client.get(self.list_url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(response.json()), 3)  # Expect 3 stocks from the CSV
                self.assertIn("LYB UN", [stock['name'] for stock in response.json()])
                self.assertIn("AXP UN", [stock['name'] for stock in response.json()])
                self.assertIn("VZ UN", [stock['name'] for stock in response.json()])

            def test_stock_details_view_success(self):
                # Tests that the stock_details view returns details for a specific stock.
                # Build the URL with the pk of the stock we know exists
                url = reverse(self.detail_url, kwargs={'pk': self.stock_lyb.pk})
                response = self.client.get(url)

                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertIn("id", data)
                self.assertIn("name", data)
                self.assertIn("data", data)
                self.assertEqual(data['name'], "LYB UN")
                self.assertEqual(len(data['data']), 31)  # LYB has 31 data points

                # Check a specific data point from the response
                first_data_point = data['data'][0]
                self.assertEqual(first_data_point['date'], "2010-07-30")
                self.assertIsNone(first_data_point['price'])  # empty cell in the csv

            def test_stock_details_view_not_found(self):
                # Tests that the stock_details view returns 404 for a non-existent stock.
                # Use a primary key that does not exist in the database
                non_existent_pk = 999
                url = reverse(self.detail_url, kwargs={'pk': non_existent_pk})
                response = self.client.get(url)

                self.assertEqual(response.status_code, 404)

        # LYB has 31 data points

        # Check a specific data point from the response
        first_data_point = response.json()['data_points'][0]
        self.assertEqual(first_data_point['date'], "2010-07-30")
        self.assertAlmostEqual(first_data_point['value'], None) #empty cell in the csv

    def test_stock_details_view_not_found(self):
        # Tests that the stock_details view returns 404 for a non-existent stock.
        # Use a primary key that does not exist in the database
        non_existent_pk = 999
        url = reverse(self.detail_url, kwargs={'pk': non_existent_pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)


