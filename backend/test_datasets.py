#!/usr/bin/env python3
"""
Test script to validate the new realistic test datasets match expected model input format.
"""

import pandas as pd
import sys
import os

# Add the backend path to sys.path
backend_path = os.path.dirname(os.path.abspath(__file__))
sys.path.append(backend_path)

from webapp.integrated_universal_model import IntegratedUniversalBetaModel

def test_dataset(file_path, description):
    """Test a dataset with the model"""
    print(f"\n=== Testing {description} ===")
    print(f"File: {file_path}")
    
    try:
        # Load the dataset
        df = pd.read_csv(file_path)
        print(f"Dataset shape: {df.shape}")
        print(f"Columns: {list(df.columns)}")
        print(f"Date range: {df['Date'].min()} to {df['Date'].max()}")
        print(f"Unique tickers: {df['Ticker'].nunique()}")
        print(f"Tickers: {sorted(df['Ticker'].unique())}")
        
        # Test with the model
        model = IntegratedUniversalBetaModel()
        processed_data = model.process_uploaded_data(file_path)
        
        if processed_data is not None:
            print(f"✅ Successfully processed! Shape: {processed_data.shape}")
            print(f"Feature columns: {list(processed_data.columns)}")
            return True
        else:
            print("❌ Failed to process data")
            return False
            
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return False

def main():
    """Test all realistic datasets"""
    test_files = [
        ("test_data_realistic.csv", "Realistic January 2022 data (200 rows, 10 stocks)"),
        ("test_data_extended.csv", "Extended June 2022 data (255 rows, 15 stocks)"),
        ("test_data_basic.csv", "Basic test data (existing)"),
    ]
    
    results = {}
    for file_name, description in test_files:
        file_path = os.path.join(backend_path, file_name)
        if os.path.exists(file_path):
            results[file_name] = test_dataset(file_path, description)
        else:
            print(f"\n=== {description} ===")
            print(f"❌ File not found: {file_path}")
            results[file_name] = False
    
    # Summary
    print(f"\n{'='*50}")
    print("TEST SUMMARY")
    print(f"{'='*50}")
    for file_name, success in results.items():
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{file_name}: {status}")
    
    total_tests = len(results)
    passed_tests = sum(results.values())
    print(f"\nPassed: {passed_tests}/{total_tests}")

if __name__ == "__main__":
    main()