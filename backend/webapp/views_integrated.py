# views_integrated.py
"""
Django views for integrated universal model workflow
Handles: Upload -> Process -> Train -> Predict -> Display
"""

import os
import json
import logging
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.views import View
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser
from .integrated_universal_model import IntegratedUniversalBetaModel
from .views_universal import UniversalModelDataImporter
from .models import CSVUploadRecord
from .models_universal import UniversalBetaPrediction, UniversalModelMetrics, StockUniversalMetrics
import pandas as pd
from datetime import datetime
import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading

logger = logging.getLogger(__name__)

class ClientModelStatus:
    """Track the status of client model runs"""
    _status = {}
    _lock = threading.Lock()
    
    @classmethod
    def set_status(cls, client_id, status_data):
        with cls._lock:
            cls._status[client_id] = status_data
    
    @classmethod
    def get_status(cls, client_id):
        with cls._lock:
            return cls._status.get(client_id, {'status': 'not_found'})
    
    @classmethod
    def clear_status(cls, client_id):
        with cls._lock:
            cls._status.pop(client_id, None)


class IntegratedUploadView(APIView):
    """
    Enhanced upload view that handles client data uploads
    and prepares for universal model processing
    """
    parser_classes = (MultiPartParser, FormParser)
    
    def post(self, request):
        try:
            if 'file' not in request.FILES:
                return Response({
                    'status': 'error',
                    'message': 'No file provided'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            uploaded_file = request.FILES['file']
            client_id = request.data.get('client_id', f'client_{datetime.now().strftime("%Y%m%d_%H%M%S")}')
            
            # Validate file type
            if not uploaded_file.name.endswith('.csv'):
                return Response({
                    'status': 'error',
                    'message': 'Only CSV files are supported'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Save file
            filename = f"{client_id}_{uploaded_file.name}"
            file_path = default_storage.save(f'client_uploads/{filename}', ContentFile(uploaded_file.read()))
            full_path = os.path.join(settings.MEDIA_ROOT, file_path)
            
            # Quick validation - check if file can be read
            try:
                df = pd.read_csv(full_path, nrows=5)
                n_rows = len(pd.read_csv(full_path))
                n_cols = len(df.columns)
                sample_columns = df.columns.tolist()[:10]
            except Exception as e:
                return Response({
                    'status': 'error',
                    'message': f'Invalid CSV file: {str(e)}'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Create upload record
            upload_record = CSVUploadRecord.objects.create(
                filename=uploaded_file.name,
                file_size=uploaded_file.size,
                user=request.user if request.user.is_authenticated else None
            )
            
            # Initialize client status
            ClientModelStatus.set_status(client_id, {
                'status': 'uploaded',
                'upload_id': upload_record.id,
                'file_path': full_path,
                'filename': uploaded_file.name,
                'n_rows': n_rows,
                'n_cols': n_cols,
                'sample_columns': sample_columns,
                'upload_time': datetime.now().isoformat()
            })
            
            return Response({
                'status': 'success',
                'message': 'File uploaded successfully',
                'data': {
                    'client_id': client_id,
                    'upload_id': upload_record.id,
                    'filename': uploaded_file.name,
                    'file_size': uploaded_file.size,
                    'n_rows': n_rows,
                    'n_cols': n_cols,
                    'sample_columns': sample_columns,
                    'next_step': 'Call /api/integrated/run-model/ to process data'
                }
            })
            
        except Exception as e:
            logger.error(f"Upload error: {str(e)}")
            return Response({
                'status': 'error',
                'message': f'Upload failed: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def run_model_background(client_id, file_path, horizon_days):
    """Background task to run the universal model"""
    try:
        # Update status to processing
        ClientModelStatus.set_status(client_id, {
            **ClientModelStatus.get_status(client_id),
            'status': 'processing',
            'stage': 'initializing',
            'progress': 0
        })
        
        # Initialize model
        model = IntegratedUniversalBetaModel(
            output_dir=os.path.join(settings.MEDIA_ROOT, 'client_results')
        )
        
        # Update status
        ClientModelStatus.set_status(client_id, {
            **ClientModelStatus.get_status(client_id),
            'stage': 'processing_data',
            'progress': 25
        })
        
        # Run the full pipeline
        result = model.run_full_pipeline(
            csv_file_path=file_path,
            horizon_days=horizon_days,
            client_id=client_id
        )
        
        if result['success']:
            # Update status
            ClientModelStatus.set_status(client_id, {
                **ClientModelStatus.get_status(client_id),
                'stage': 'importing_to_database',
                'progress': 75
            })
            
            # Import results to database for frontend display
            try:
                # Create a custom importer for this client's results
                output_dir = result['output_directory']
                
                # Import the results using our existing importer logic
                # But first, we need to structure it properly
                
                # Create horizon-specific directory structure
                horizon_dir = os.path.join(output_dir, f"POOLED_MODEL_{horizon_days}d")
                os.makedirs(horizon_dir, exist_ok=True)
                
                # Copy files to expected structure
                import shutil
                if os.path.exists(os.path.join(output_dir, "final_predictions.csv")):
                    shutil.copy2(
                        os.path.join(output_dir, "final_predictions.csv"),
                        os.path.join(horizon_dir, "final_predictions.csv")
                    )
                if os.path.exists(os.path.join(output_dir, "oos_metrics.csv")):
                    shutil.copy2(
                        os.path.join(output_dir, "oos_metrics.csv"),
                        os.path.join(output_dir, "oos_metrics.csv")
                    )
                if os.path.exists(os.path.join(output_dir, "per_stock_oos_metrics.csv")):
                    shutil.copy2(
                        os.path.join(output_dir, "per_stock_oos_metrics.csv"),
                        os.path.join(output_dir, "per_stock_oos_metrics.csv")
                    )
                
                # Import to database
                importer = UniversalModelDataImporter(output_dir)
                import_results = importer.import_all_data()
                
                # Final status update
                ClientModelStatus.set_status(client_id, {
                    **ClientModelStatus.get_status(client_id),
                    'status': 'completed',
                    'stage': 'completed',
                    'progress': 100,
                    'results': result['summary'],
                    'import_results': import_results,
                    'completion_time': datetime.now().isoformat()
                })
                
            except Exception as import_error:
                logger.error(f"Database import failed for client {client_id}: {str(import_error)}")
                # Still mark as completed, but note the import issue
                ClientModelStatus.set_status(client_id, {
                    **ClientModelStatus.get_status(client_id),
                    'status': 'completed_with_warnings',
                    'stage': 'completed',
                    'progress': 100,
                    'results': result['summary'],
                    'import_error': str(import_error),
                    'completion_time': datetime.now().isoformat()
                })
        else:
            # Model run failed
            ClientModelStatus.set_status(client_id, {
                **ClientModelStatus.get_status(client_id),
                'status': 'failed',
                'error': result['error'],
                'completion_time': datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Background model run failed for client {client_id}: {str(e)}")
        ClientModelStatus.set_status(client_id, {
            **ClientModelStatus.get_status(client_id),
            'status': 'failed',
            'error': str(e),
            'completion_time': datetime.now().isoformat()
        })


class RunModelView(APIView):
    """
    Trigger the universal model to run on uploaded client data
    """
    
    def post(self, request):
        try:
            client_id = request.data.get('client_id')
            horizon_days = int(request.data.get('horizon_days', 10))
            
            if not client_id:
                return Response({
                    'status': 'error',
                    'message': 'client_id is required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Check if client exists and has uploaded data
            client_status = ClientModelStatus.get_status(client_id)
            if client_status['status'] == 'not_found':
                return Response({
                    'status': 'error',
                    'message': 'Client not found. Please upload data first.'
                }, status=status.HTTP_404_NOT_FOUND)
            
            if client_status['status'] != 'uploaded':
                return Response({
                    'status': 'error',
                    'message': f'Client is in {client_status["status"]} state. Cannot run model.'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            file_path = client_status['file_path']
            if not os.path.exists(file_path):
                return Response({
                    'status': 'error',
                    'message': 'Uploaded file not found'
                }, status=status.HTTP_404_NOT_FOUND)
            
            # Start background processing
            executor = ThreadPoolExecutor(max_workers=1)
            executor.submit(run_model_background, client_id, file_path, horizon_days)
            
            return Response({
                'status': 'success',
                'message': 'Model processing started in background',
                'data': {
                    'client_id': client_id,
                    'horizon_days': horizon_days,
                    'status': 'processing',
                    'estimated_time': '2-5 minutes',
                    'status_endpoint': f'/api/integrated/status/{client_id}/'
                }
            })
            
        except Exception as e:
            logger.error(f"Run model error: {str(e)}")
            return Response({
                'status': 'error',
                'message': f'Failed to start model: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ClientStatusView(APIView):
    """
    Check the status of a client's model run
    """
    
    def get(self, request, client_id):
        try:
            status_data = ClientModelStatus.get_status(client_id)
            
            if status_data['status'] == 'not_found':
                return Response({
                    'status': 'error',
                    'message': 'Client not found'
                }, status=status.HTTP_404_NOT_FOUND)
            
            return Response({
                'status': 'success',
                'data': status_data
            })
            
        except Exception as e:
            logger.error(f"Status check error: {str(e)}")
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ClientResultsView(APIView):
    """
    Get the dashboard data for a specific client's results
    """
    
    def get(self, request, client_id):
        try:
            # Check if client has completed results
            client_status = ClientModelStatus.get_status(client_id)
            
            if client_status['status'] not in ['completed', 'completed_with_warnings']:
                return Response({
                    'status': 'error',
                    'message': f'Results not ready. Current status: {client_status["status"]}'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Get horizon from query params
            horizon = request.GET.get('horizon', '10')
            limit = int(request.GET.get('limit', '50'))
            
            # Use the same logic as UniversalBetaDashboardView but filter for recent data
            # Since this is client-specific, we'll show their recent results
            
            from .views_universal import UniversalBetaDashboardView
            dashboard_view = UniversalBetaDashboardView()
            
            # Get the standard dashboard response
            mock_request = type('MockRequest', (), {
                'GET': {'horizon': horizon, 'limit': str(limit)}
            })()
            
            response = dashboard_view.get(mock_request)
            
            if response.status_code == 200:
                # Add client-specific information
                response.data['client_info'] = {
                    'client_id': client_id,
                    'status': client_status['status'],
                    'results_summary': client_status.get('results', {}),
                    'completion_time': client_status.get('completion_time'),
                    'is_client_data': True
                }
            
            return response
            
        except Exception as e:
            logger.error(f"Client results error: {str(e)}")
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ClientListView(APIView):
    """
    List all client model runs and their statuses
    """
    
    def get(self, request):
        try:
            # Get all client statuses
            all_statuses = {}
            for client_id in ClientModelStatus._status.keys():
                status_data = ClientModelStatus.get_status(client_id)
                all_statuses[client_id] = {
                    'client_id': client_id,
                    'status': status_data['status'],
                    'upload_time': status_data.get('upload_time'),
                    'completion_time': status_data.get('completion_time'),
                    'filename': status_data.get('filename'),
                    'n_stocks': status_data.get('results', {}).get('total_stocks', 0)
                }
            
            return Response({
                'status': 'success',
                'data': {
                    'total_clients': len(all_statuses),
                    'clients': list(all_statuses.values())
                }
            })
            
        except Exception as e:
            logger.error(f"Client list error: {str(e)}")
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)