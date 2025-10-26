#!/usr/bin/env python
import os
import sys
import django

# Add the backend directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Set up Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()

# Now import and run the data importer
from webapp.views_universal import UniversalModelDataImporter

def main():
    print("🚀 Starting Universal Model Data Import...")
    
    # Initialize the importer with the correct path
    data_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "data-analysis",
        "Pooled_Outputs_v6_Fixed"
    )
    
    print(f"📂 Data path: {data_path}")
    
    if not os.path.exists(data_path):
        print(f"❌ Error: Data path does not exist: {data_path}")
        return
    
    importer = UniversalModelDataImporter(data_path)
    
    print("📊 Importing all universal model data...")
    results = importer.import_all_data()
    
    print("\n✅ Import Results:")
    print(f"   📈 Predictions imported: {results['predictions']}")
    print(f"   🎯 Global metrics imported: {results['global_metrics']}")
    print(f"   📊 Stock metrics imported: {results['stock_metrics']}")
    
    if results['errors']:
        print("\n⚠️  Errors encountered:")
        for error in results['errors']:
            print(f"   - {error}")
    else:
        print("\n🎉 Import completed successfully with no errors!")

if __name__ == "__main__":
    main()