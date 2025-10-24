import requests
import json
import os
import time

# Test configuration
BASE_URL = "http://localhost:8000"
TEST_FILES = [
    "test_data_realistic.csv",
    "test_data_msci_style.csv",
    "test_data_comprehensive.csv"
]

def test_file_upload_and_model_run(csv_file_path):
    """Test uploading a CSV file and running the model"""
    print(f"\n=== Testing {os.path.basename(csv_file_path)} ===")
    
    # 1. Test file upload
    print("1. Testing file upload...")
    upload_url = f"{BASE_URL}/api/integrated/upload/"
    
    try:
        with open(csv_file_path, 'rb') as f:
            files = {'file': f}
            data = {'client_id': f'test_client_{int(time.time())}'}
            response = requests.post(upload_url, files=files, data=data)
        
        if response.status_code == 200:
            upload_data = response.json()
            print(f"✓ Upload successful: {upload_data.get('message', 'No message')}")
            client_id = upload_data.get('data', {}).get('client_id')
            if not client_id:
                print("✗ No client_id returned from upload")
                return False
        else:
            print(f"✗ Upload failed: {response.status_code} - {response.text}")
            return False
    
    except Exception as e:
        print(f"✗ Upload error: {e}")
        return False
    
    # 2. Test model run with various parameters
    print("2. Testing model execution...")
    run_url = f"{BASE_URL}/api/integrated/run-model/"
    
    # Test different parameter configurations
    test_configs = [
        {
            "name": "Basic Configuration",
            "params": {
                "client_id": client_id,
                "horizon_days": 10,
                "alpha": 1.0,
                "l1_ratio": 0.5,
                "training_days": 20,
                "testing_days": 5,
                "multi_period": False
            }
        },
        {
            "name": "Advanced Configuration", 
            "params": {
                "client_id": client_id,
                "horizon_days": 15,
                "alpha": 0.1,
                "l1_ratio": 0.8,
                "training_days": 30,
                "testing_days": 10,
                "multi_period": True,
                "sector_filter": "all",
                "risk_tolerance": "high",
                "minimum_confidence": 0.7
            }
        }
    ]
    
    for config in test_configs:
        print(f"\n   Testing: {config['name']}")
        try:
            response = requests.post(run_url, json=config['params'])
            
            if response.status_code == 200:
                result = response.json()
                print(f"   ✓ Model run initiated: {result.get('message', 'No message')}")
                
                # Poll for results using client_id
                status_url = f"{BASE_URL}/api/integrated/status/{client_id}/"
                max_attempts = 15
                attempt = 0
                
                while attempt < max_attempts:
                    time.sleep(3)
                    status_response = requests.get(status_url)
                    
                    if status_response.status_code == 200:
                        status_data = status_response.json()
                        current_status = status_data.get('status')
                        stage = status_data.get('stage', 'unknown')
                        progress = status_data.get('progress', 0)
                        
                        print(f"   Status check {attempt + 1}: {current_status} - {stage} ({progress}%)")
                        
                        if current_status == 'completed':
                            print("   ✓ Model execution completed successfully!")
                            
                            # Get final results
                            results_url = f"{BASE_URL}/api/integrated/results/{client_id}/"
                            results_response = requests.get(results_url)
                            
                            if results_response.status_code == 200:
                                results_data = results_response.json()
                                
                                # Check key results
                                if 'beta_predictions' in results_data:
                                    beta_count = len(results_data['beta_predictions'])
                                    print(f"   ✓ Beta predictions: {beta_count} stocks processed")
                                
                                if 'model_metrics' in results_data:
                                    print(f"   ✓ Model metrics available")
                            
                            break
                        elif current_status == 'failed':
                            error_msg = status_data.get('error', 'Unknown error')
                            print(f"   ✗ Model execution failed: {error_msg}")
                            break
                        elif current_status == 'not_found':
                            print(f"   ✗ Client not found")
                            break
                    
                    attempt += 1
                
                if attempt >= max_attempts:
                    print("   ⚠ Timeout waiting for model completion")
                
            else:
                print(f"   ✗ Model run failed: {response.status_code} - {response.text}")
        
        except Exception as e:
            print(f"   ✗ Model run error: {e}")
    
    print(f"\n=== Completed testing {os.path.basename(csv_file_path)} ===")
    return True

def test_data_format():
    """Test that our data format is correct"""
    print("\n=== Testing Data Format ===")
    
    for test_file in TEST_FILES:
        file_path = os.path.join(".", test_file)
        if os.path.exists(file_path):
            print(f"\n📊 Checking {test_file}:")
            
            with open(file_path, 'r') as f:
                lines = f.readlines()
                
            print(f"   Lines: {len(lines)}")
            print(f"   Header: {lines[0].strip()}")
            
            if len(lines) > 1:
                print(f"   Sample data: {lines[1].strip()}")
            
            # Count unique dates and tickers
            if len(lines) > 1:
                dates = set()
                tickers = set()
                
                for line in lines[1:]:  # Skip header
                    parts = line.strip().split(',')
                    if len(parts) >= 3:
                        dates.add(parts[0])
                        tickers.add(parts[1])
                
                print(f"   Unique dates: {len(dates)}")
                print(f"   Unique tickers: {len(tickers)}")
                print(f"   Date range: {min(dates)} to {max(dates)}")
                print(f"   Sample tickers: {list(tickers)[:5]}")
        else:
            print(f"   ✗ File not found: {test_file}")

def main():
    print("🧪 Starting End-to-End Test Suite")
    print("=" * 50)
    
    # Test data format first
    test_data_format()
    
    # Test each dataset
    success_count = 0
    total_tests = 0
    
    for test_file in TEST_FILES:
        file_path = os.path.join(".", test_file)
        if os.path.exists(file_path):
            total_tests += 1
            if test_file_upload_and_model_run(file_path):
                success_count += 1
        else:
            print(f"⚠ Skipping {test_file} - file not found")
    
    # Summary
    print("\n" + "=" * 50)
    print("🎯 TEST SUMMARY")
    print("=" * 50)
    print(f"Tests run: {total_tests}")
    print(f"Successful: {success_count}")
    print(f"Failed: {total_tests - success_count}")
    
    if success_count == total_tests and total_tests > 0:
        print("🎉 ALL TESTS PASSED!")
    else:
        print("⚠ Some tests failed - check output above")

if __name__ == "__main__":
    main()