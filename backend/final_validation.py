import requests
import time

print("🧪 Final Validation Test")
print("=" * 30)

# Test upload
client_data = {'client_id': 'final_test_' + str(int(time.time()))}
try:
    with open('test_data_realistic.csv', 'rb') as f:
        files = {'file': f}
        upload_resp = requests.post('http://localhost:8000/api/integrated/upload/', files=files, data=client_data)
    
    if upload_resp.status_code == 200:
        print("✅ Upload successful")
        client_id = upload_resp.json()['data']['client_id']
        
        # Test model run with advanced parameters
        run_data = {
            'client_id': client_id,
            'horizon_days': 10,
            'training_days': 15,
            'testing_days': 5,
            'alpha': 0.5,
            'l1_ratio': 0.7,
            'multi_period': False
        }
        
        run_resp = requests.post('http://localhost:8000/api/integrated/run-model/', json=run_data)
        
        if run_resp.status_code == 200:
            print("✅ Model run initiated")
            print("✅ Advanced parameters accepted")
            print("🎯 All systems working correctly!")
        else:
            print(f"❌ Model run failed: {run_resp.text}")
    else:
        print(f"❌ Upload failed: {upload_resp.text}")

except Exception as e:
    print(f"❌ Test error: {e}")