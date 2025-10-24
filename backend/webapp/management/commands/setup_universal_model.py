# management/commands/setup_universal_model.py
"""
Django management command to set up Universal Beta Model
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from webapp.views_universal import UniversalModelDataImporter
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Set up Universal Beta Model by importing data from Pooled_Outputs_v6_Fixed'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--data-path',
            type=str,
            help='Path to Pooled_Outputs_v6_Fixed directory (optional)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Run without making database changes',
        )
    
    def handle(self, *args, **options):
        self.stdout.write(
            self.style.SUCCESS('🚀 Setting up Universal Beta Model...')
        )
        
        try:
            with transaction.atomic():
                # Initialize importer
                importer = UniversalModelDataImporter(options.get('data_path'))
                
                if options['dry_run']:
                    self.stdout.write(
                        self.style.WARNING('DRY RUN MODE - No database changes will be made')
                    )
                    return
                
                # Import all data
                self.stdout.write('📊 Importing universal model data...')
                results = importer.import_all_data()
                
                # Display results
                self.stdout.write(
                    self.style.SUCCESS(f'✅ Import completed successfully!')
                )
                self.stdout.write(f'   📈 Predictions imported: {results["predictions"]}')
                self.stdout.write(f'   🎯 Global metrics imported: {results["global_metrics"]}')
                self.stdout.write(f'   📊 Stock metrics imported: {results["stock_metrics"]}')
                
                if results['errors']:
                    self.stdout.write(
                        self.style.WARNING('⚠️  Some errors occurred:')
                    )
                    for error in results['errors']:
                        self.stdout.write(f'   - {error}')
                
                self.stdout.write(
                    self.style.SUCCESS('🎉 Universal Beta Model setup complete!')
                )
                
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'❌ Setup failed: {str(e)}')
            )
            raise