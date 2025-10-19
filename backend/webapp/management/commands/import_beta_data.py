"""
Django management command to import beta coefficient model output data.

Usage:
    python manage.py import_beta_data
    python manage.py import_beta_data --betas-file path/to/betas.csv
    python manage.py import_beta_data --forecast-file path/to/forecast.csv
"""

import csv
import os
from datetime import datetime
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from webapp.models import BetaRealized, ForecastEvaluation


class Command(BaseCommand):
    help = 'Import beta coefficient model output data from CSV files'

    def add_arguments(self, parser):
        parser.add_argument(
            '--betas-file',
            type=str,
            default=None,
            help='Path to betas_20d.csv file (default: outputs/betas_20d.csv)'
        )
        parser.add_argument(
            '--forecast-file',
            type=str,
            default=None,
            help='Path to forecast_eval_20d.csv file (default: outputs/forecast_eval_20d.csv)'
        )
        parser.add_argument(
            '--clear-existing',
            action='store_true',
            help='Clear existing data before importing'
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=1000,
            help='Batch size for bulk operations (default: 1000)'
        )

    def handle(self, *args, **options):
        # Default file paths
        if not options['betas_file']:
            options['betas_file'] = os.path.join(
                settings.BASE_DIR.parent, 'outputs', 'betas_20d.csv'
            )
        
        if not options['forecast_file']:
            options['forecast_file'] = os.path.join(
                settings.BASE_DIR.parent, 'outputs', 'forecast_eval_20d.csv'
            )

        if options['clear_existing']:
            self.stdout.write('Clearing existing data...')
            BetaRealized.objects.all().delete()
            ForecastEvaluation.objects.all().delete()
            self.stdout.write(self.style.SUCCESS('Existing data cleared.'))

        # Import beta realized data
        if os.path.exists(options['betas_file']):
            self.stdout.write(f'Importing beta realized data from {options["betas_file"]}...')
            beta_count = self.import_beta_realized(options['betas_file'], options['batch_size'])
            self.stdout.write(
                self.style.SUCCESS(f'Successfully imported {beta_count} beta realized records.')
            )
        else:
            self.stdout.write(
                self.style.WARNING(f'Beta file not found: {options["betas_file"]}')
            )

        # Import forecast evaluation data
        if os.path.exists(options['forecast_file']):
            self.stdout.write(f'Importing forecast evaluation data from {options["forecast_file"]}...')
            forecast_count = self.import_forecast_evaluation(options['forecast_file'], options['batch_size'])
            self.stdout.write(
                self.style.SUCCESS(f'Successfully imported {forecast_count} forecast evaluation records.')
            )
        else:
            self.stdout.write(
                self.style.WARNING(f'Forecast file not found: {options["forecast_file"]}')
            )

        self.stdout.write(
            self.style.SUCCESS('Beta coefficient data import completed successfully!')
        )

    def import_beta_realized(self, file_path, batch_size):
        """Import data from betas_20d.csv"""
        beta_objects = []
        imported_count = 0
        skipped_count = 0

        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            for row_num, row in enumerate(reader, 1):
                if not row.get('Date') or not row.get('ticker'):
                    skipped_count += 1
                    continue

                try:
                    # Parse date (handle different formats)
                    date_str = row['Date']
                    try:
                        date_obj = datetime.strptime(date_str, '%m/%d/%Y').date()
                    except ValueError:
                        try:
                            date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
                        except ValueError:
                            self.stdout.write(
                                self.style.WARNING(f'Invalid date format in row {row_num}: {date_str}')
                            )
                            skipped_count += 1
                            continue

                    # Helper function to parse float or return None
                    def parse_float(value):
                        if value and value.strip() and value.strip() != '0':
                            try:
                                return float(value)
                            except ValueError:
                                return None
                        return None

                    beta_obj = BetaRealized(
                        date=date_obj,
                        ticker=row['ticker'],
                        beta_realised=parse_float(row.get('beta_realised')),
                        r2_ols_x=parse_float(row.get('r2_ols_x')),
                        r2_ols_y=parse_float(row.get('r2_ols_y')),
                        p_value=parse_float(row.get('p_value')),
                        significance_score=parse_float(row.get('significance_score')),
                        beta_pred=parse_float(row.get('beta_pred')),
                        beta_true=parse_float(row.get('beta_true')),
                        band=parse_float(row.get('band')),
                        lo=parse_float(row.get('lo')),
                        hi=parse_float(row.get('hi')),
                    )
                    beta_objects.append(beta_obj)

                    # Bulk create when batch size is reached
                    if len(beta_objects) >= batch_size:
                        BetaRealized.objects.bulk_create(beta_objects, ignore_conflicts=True)
                        imported_count += len(beta_objects)
                        beta_objects = []
                        
                        if imported_count % 10000 == 0:
                            self.stdout.write(f'Imported {imported_count} beta records...')

                except Exception as e:
                    self.stdout.write(
                        self.style.WARNING(f'Error processing row {row_num}: {str(e)}')
                    )
                    skipped_count += 1
                    continue

            # Import remaining objects
            if beta_objects:
                BetaRealized.objects.bulk_create(beta_objects, ignore_conflicts=True)
                imported_count += len(beta_objects)

        if skipped_count > 0:
            self.stdout.write(
                self.style.WARNING(f'Skipped {skipped_count} invalid rows in beta file.')
            )

        return imported_count

    def import_forecast_evaluation(self, file_path, batch_size):
        """Import data from forecast_eval_20d.csv"""
        forecast_objects = []
        imported_count = 0
        skipped_count = 0

        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            for row_num, row in enumerate(reader, 1):
                try:
                    # Parse date
                    date_str = row['Date']
                    try:
                        date_obj = datetime.strptime(date_str, '%m/%d/%Y').date()
                    except ValueError:
                        try:
                            date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
                        except ValueError:
                            self.stdout.write(
                                self.style.WARNING(f'Invalid date format in row {row_num}: {date_str}')
                            )
                            skipped_count += 1
                            continue

                    forecast_obj = ForecastEvaluation(
                        date=date_obj,
                        ticker=row['ticker'],
                        r2_ols=float(row['r2_ols']),
                        p_value=float(row['p_value']),
                        significance_score=float(row['significance_score']),
                        beta_pred=float(row['beta_pred']),
                        beta_true=float(row['beta_true']),
                        band=float(row['band']),
                    )
                    forecast_objects.append(forecast_obj)

                    # Bulk create when batch size is reached
                    if len(forecast_objects) >= batch_size:
                        ForecastEvaluation.objects.bulk_create(forecast_objects, ignore_conflicts=True)
                        imported_count += len(forecast_objects)
                        forecast_objects = []
                        
                        if imported_count % 10000 == 0:
                            self.stdout.write(f'Imported {imported_count} forecast records...')

                except (ValueError, KeyError) as e:
                    self.stdout.write(
                        self.style.WARNING(f'Error processing row {row_num}: {str(e)}')
                    )
                    skipped_count += 1
                    continue

            # Import remaining objects
            if forecast_objects:
                ForecastEvaluation.objects.bulk_create(forecast_objects, ignore_conflicts=True)
                imported_count += len(forecast_objects)

        if skipped_count > 0:
            self.stdout.write(
                self.style.WARNING(f'Skipped {skipped_count} invalid rows in forecast file.')
            )

        return imported_count