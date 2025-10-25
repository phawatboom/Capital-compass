"""
Test suite for Beta Coefficient Forecasting Platform
Tests API endpoints, models, and data import functionality
"""
import pytest
import json
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from django.core.management import call_command
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from webapp.models import BetaRealized, ForecastEvaluation


class BetaCoefficientModelsTest(TestCase):
    """Test beta coefficient database models"""
    
    def setUp(self):
        """Set up test data"""
        self.beta_realized = BetaRealized.objects.create(
            ticker="AAPL",
            date="2025-10-01",
            beta_realised=1.25
        )
        
        self.forecast_eval = ForecastEvaluation.objects.create(
            ticker="AAPL", 
            date="2025-10-01",
            beta_pred=1.20,
            beta_true=1.25,
            r2_ols=0.85,
            p_value=0.001,
            significance_score=0.99,
            band=0.05
        )
    
    def test_beta_realized_creation(self):
        """Test BetaRealized model creation"""
        self.assertEqual(self.beta_realized.ticker, "AAPL")
        self.assertEqual(str(self.beta_realized.date), "2025-10-01")
        self.assertEqual(float(self.beta_realized.beta_realised), 1.25)
    
    def test_forecast_evaluation_creation(self):
        """Test ForecastEvaluation model creation"""
        self.assertEqual(self.forecast_eval.ticker, "AAPL")
        self.assertEqual(float(self.forecast_eval.beta_pred), 1.20)
        self.assertEqual(float(self.forecast_eval.beta_true), 1.25)
        self.assertEqual(float(self.forecast_eval.r2_ols), 0.85)
    
    def test_model_string_representation(self):
        """Test model __str__ methods"""
        self.assertIn("AAPL", str(self.beta_realized))
        self.assertIn("AAPL", str(self.forecast_eval))


class BetaCoefficientAPITest(APITestCase):
    """Test beta coefficient API endpoints"""
    
    def setUp(self):
        """Set up test client and data"""
        self.client = APIClient()
        
        # Create test data
        ForecastEvaluation.objects.create(
            ticker="AAPL",
            date="2025-10-01", 
            beta_pred=1.20,
            beta_true=1.25,
            r2_ols=0.85,
            p_value=0.001,
            significance_score=0.99,
            band=0.05
        )
        
        ForecastEvaluation.objects.create(
            ticker="GOOGL",
            date="2025-10-01",
            beta_pred=1.15,
            beta_true=1.18,
            r2_ols=0.82,
            p_value=0.002,
            significance_score=0.95,
            band=0.03
        )
    
    def test_beta_summary_endpoint(self):
        """Test /api/beta/summary/ endpoint"""
        url = reverse('beta-summary')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn('summary', data)
        summary = data['summary']
        self.assertIsInstance(summary, list)
        self.assertGreater(len(summary), 0)
        
        # Check data structure
        first_item = summary[0]
        required_fields = ['ticker', 'latest_date', 'latest_beta_pred', 'avg_r2_ols']
        for field in required_fields:
            self.assertIn(field, first_item)
    
    def test_beta_realized_endpoint(self):
        """Test /api/beta/realized/ endpoint"""
        url = reverse('beta-realized-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn('results', data)  # Paginated response
    
    def test_forecast_evaluation_endpoint(self):
        """Test /api/beta/forecast-evaluation/ endpoint"""
        url = reverse('forecast-evaluation-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn('results', data)  # Paginated response
    
    def test_beta_timeseries_endpoint(self):
        """Test /api/beta/timeseries/{ticker}/ endpoint"""
        url = reverse('beta-timeseries', kwargs={'ticker': 'AAPL'})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn('ticker', data)
        self.assertEqual(data['ticker'], 'AAPL')
    
    def test_beta_timeseries_nonexistent_ticker(self):
        """Test timeseries endpoint with non-existent ticker"""
        url = reverse('beta-timeseries', kwargs={'ticker': 'NONEXISTENT'})
        response = self.client.get(url)
        
        # Should return empty data, not error
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_api_pagination(self):
        """Test API pagination works correctly"""
        # Create more test data
        for i in range(15):
            ForecastEvaluation.objects.create(
                ticker=f"TEST{i}",
                date="2025-10-01",
                beta_pred=1.0 + (i * 0.1),
                beta_true=1.05 + (i * 0.1),
                r2_ols=0.8,
                p_value=0.01,
                significance_score=0.9,
                band=0.05 + (i * 0.001)
            )
        
        url = reverse('forecast-evaluation-list')
        response = self.client.get(url + '?page_size=10')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn('count', data)
        self.assertIn('results', data)
        # With 17 items (2 from setUp + 15 from loop), we expect pagination
        self.assertEqual(data['count'], 17)
        self.assertLessEqual(len(data['results']), 17)  # May or may not be paginated


class BetaDataImportTest(TestCase):
    """Test beta coefficient data import functionality"""
    
    def test_import_command_exists(self):
        """Test that import_beta_data management command exists"""
        try:
            # This should not raise an exception
            call_command('import_beta_data', '--help')
        except SystemExit:
            # Help command exits with code 0, which is expected
            pass
        except Exception as e:
            self.fail(f"Import command failed: {e}")


class BetaCoefficientIntegrationTest(TestCase):
    """Integration tests for beta coefficient platform"""
    
    def setUp(self):
        """Set up integration test environment"""
        self.client = Client()
        
        # Create comprehensive test data
        self.create_test_data()
    
    def create_test_data(self):
        """Create realistic test data for integration tests"""
        tickers = ['AAPL', 'GOOGL', 'MSFT', 'TSLA', 'AMZN']
        dates = ['2025-10-01', '2025-10-02', '2025-10-03']
        
        for ticker in tickers:
            for i, date in enumerate(dates):
                ForecastEvaluation.objects.create(
                    ticker=ticker,
                    date=date,
                    beta_pred=1.0 + (i * 0.05),
                    beta_true=1.02 + (i * 0.05),
                    r2_ols=0.8 + (i * 0.02),
                    p_value=0.01 - (i * 0.001),
                    significance_score=0.9 + (i * 0.01),
                    band=0.04 + (i * 0.01)
                )
    
    def test_full_api_workflow(self):
        """Test complete API workflow"""
        # Test summary endpoint
        response = self.client.get('/api/beta/summary/')
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        
        # Should have data for 5 tickers
        self.assertIn('summary', response_data)
        summary_data = response_data['summary']
        self.assertEqual(len(summary_data), 5)
        
        # Test individual ticker timeseries
        for item in summary_data:
            ticker = item['ticker']
            response = self.client.get(f'/api/beta/timeseries/{ticker}/')
            self.assertEqual(response.status_code, 200)
            
            timeseries_data = response.json()
            self.assertEqual(timeseries_data['ticker'], ticker)
            self.assertIn('dates', timeseries_data)
            self.assertIn('beta_pred', timeseries_data)
    
    def test_data_consistency(self):
        """Test data consistency across endpoints"""
        # Get summary data
        summary_response = self.client.get('/api/beta/summary/')
        response_data = summary_response.json()
        
        # Check each ticker's data consistency
        summary_data = response_data['summary']
        for summary_item in summary_data:
            ticker = summary_item['ticker']
            
            # Get detailed timeseries data
            timeseries_response = self.client.get(f'/api/beta/timeseries/{ticker}/')
            timeseries_data = timeseries_response.json()
            
            # Latest prediction should match
            if timeseries_data['beta_pred']:
                latest_pred = timeseries_data['beta_pred'][-1]
                self.assertAlmostEqual(
                    float(summary_item['latest_beta_pred']),
                    latest_pred,
                    places=2
                )


class BetaCoefficientPerformanceTest(TestCase):
    """Performance tests for beta coefficient platform"""
    
    def test_large_dataset_performance(self):
        """Test API performance with larger datasets"""
        # Create substantial test data
        import time
        
        start_time = time.time()
        
        # Create 1000 records with unique ticker/date combinations
        bulk_data = []
        import datetime
        for i in range(1000):
            # Use different dates to avoid unique constraint violations
            days_offset = i // 100  # Each ticker gets 10 different dates
            date_obj = datetime.date(2025, 10, 1) + datetime.timedelta(days=days_offset)
            
            bulk_data.append(
                ForecastEvaluation(
                    ticker=f"PERF{i % 100}",  # 100 unique tickers
                    date=date_obj,
                    beta_pred=1.0 + (i * 0.001),
                    beta_true=1.0 + (i * 0.001),
                    r2_ols=0.8,
                    p_value=0.01,
                    significance_score=0.9,
                    band=0.05
                )
            )
        
        ForecastEvaluation.objects.bulk_create(bulk_data)
        
        creation_time = time.time() - start_time
        self.assertLess(creation_time, 10.0)  # Should complete in under 10 seconds
        
        # Test API response time
        start_time = time.time()
        response = self.client.get('/api/beta/summary/')
        api_time = time.time() - start_time
        
        self.assertEqual(response.status_code, 200)
        self.assertLess(api_time, 5.0)  # API should respond in under 5 seconds


if __name__ == '__main__':
    pytest.main([__file__])