# views_integrated.py
"""
Django views for integrated universal model workflow
Handles: Upload -> Process -> Train -> Predict -> Display
"""

import os
import json
import logging
import traceback
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
# from .views_universal import UniversalModelDataImporter
from .models import CSVUploadRecord
# from .models_universal import UniversalBetaPrediction, UniversalModelMetrics, StockUniversalMetrics
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
            
            # Validate file type - support CSV and Excel files
            file_extension = uploaded_file.name.lower().split('.')[-1]
            if file_extension not in ['csv', 'xlsx', 'xls']:
                return Response({
                    'status': 'error',
                    'message': 'Only CSV and Excel files (.csv, .xlsx, .xls) are supported'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Save file
            filename = f"{client_id}_{uploaded_file.name}"
            file_path = default_storage.save(f'client_uploads/{filename}', ContentFile(uploaded_file.read()))
            full_path = os.path.join(settings.MEDIA_ROOT, file_path)
            
            # Quick validation - check if file can be read and get basic info
            try:
                if file_extension == 'csv':
                    df = pd.read_csv(full_path, nrows=5)
                    n_rows = len(pd.read_csv(full_path))
                    n_cols = len(df.columns)
                    sample_columns = df.columns.tolist()[:10]
                else:  # Excel files
                    # For Excel, try to read with robust logic similar to load_mxus_returns
                    df = pd.read_excel(full_path, nrows=5)
                    full_df = pd.read_excel(full_path)
                    n_rows = len(full_df)
                    n_cols = len(df.columns)
                    sample_columns = df.columns.tolist()[:10]
            except Exception as e:
                # Clean up failed upload
                try:
                    default_storage.delete(file_path)
                except:
                    pass
                return Response({
                    'status': 'error',
                    'message': f'Invalid file format: {str(e)}'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Create upload record with the actual file path
            upload_record = CSVUploadRecord.objects.create(
                filename=file_path,  # Store the relative path in the database
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


def run_model_background(client_id, file_path, horizon_days, advanced_params=None, user_id=None):
    """Background task to run the universal model"""
    try:
        if advanced_params is None:
            advanced_params = {}
            
        # Get user for database operations
        user = None
        if user_id:
            try:
                from django.contrib.auth.models import User
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                logger.warning(f"User with ID {user_id} not found, using system user")
        
        # Update status to processing
        ClientModelStatus.set_status(client_id, {
            **ClientModelStatus.get_status(client_id),
            'status': 'processing',
            'stage': 'initializing',
            'progress': 0,
            'config': advanced_params
        })
        
        # Initialize model with advanced parameters
        model = IntegratedUniversalBetaModel(
            output_dir=os.path.join(settings.MEDIA_ROOT, 'client_results'),
            alpha=advanced_params.get('alpha', 0.01),
            l1_ratio=advanced_params.get('l1_ratio', 0.5)
        )
        
        # Update status
        ClientModelStatus.set_status(client_id, {
            **ClientModelStatus.get_status(client_id),
            'stage': 'processing_data',
            'progress': 25
        })
        
        # Run the full pipeline with database integration
        result = model.run_full_pipeline(
            csv_file_path=file_path,
            horizon_days=horizon_days,
            client_id=client_id,
            advanced_params=advanced_params,
            user=user  # Pass user for database operations
        )
        
        if result['success']:
            # Update status
            ClientModelStatus.set_status(client_id, {
                **ClientModelStatus.get_status(client_id),
                'stage': 'saving_to_database',
                'progress': 85
            })
            
            # Save results directly to database with comprehensive analysis results
            try:
                from django.contrib.auth.models import User
                from .models import AnalysisRun, ModelCoefficient, StockPrediction, StockPerformanceMetrics
                from django.utils import timezone
                import pandas as pd
                
                # Get or create a system user for background tasks
                user, created = User.objects.get_or_create(
                    username='system_model_runner',
                    defaults={'email': 'system@example.com', 'is_active': True}
                )
                
                # Extract comprehensive results from model output
                output_dir = result['output_directory']
                summary = result['summary']
                
                # Get the first horizon result (usually the main one)
                horizon_results = summary.get('results', [])
                if not horizon_results:
                    raise ValueError("No horizon results found in model output")
                
                main_result = horizon_results[0]  # Take first/primary horizon
                actual_horizon = main_result.get('horizon', horizon_days)
                
                # Extract comprehensive performance metrics
                oos_metrics = main_result.get('oos_metrics', {})
                per_stock_metrics = main_result.get('per_stock_metrics', [])
                model_coefficients = main_result.get('enet_coefficients', {})
                final_predictions = main_result.get('final_predictions', [])
                model_equation = main_result.get('model_equation', '')
                model_params = main_result.get('params', {})
                
                # Create comprehensive analysis run record
                analysis_run = AnalysisRun.objects.create(
                    user=user,
                    run_name=f"Universal_Beta_Model_{client_id}_{actual_horizon}d_{timezone.now().strftime('%Y%m%d_%H%M')}",
                    model_type='universal_beta_elasticnet',
                    horizon_days=actual_horizon,
                    status='completed',
                    completed_at=timezone.now(),
                    # Core performance metrics from OOS evaluation
                    mae=oos_metrics.get('mae'),
                    rmse=oos_metrics.get('rmse'),
                    directional_accuracy=oos_metrics.get('dir_acc'),
                    sample_size=oos_metrics.get('n_obs'),
                    r2_global=oos_metrics.get('r2'),
                    r2_fold_mean=oos_metrics.get('r2_mean'),
                    r2_fold_weighted=oos_metrics.get('r2_weighted'),
                    mae_ratio_global=oos_metrics.get('mae_ratio', 1.0),
                    mae_ratio_fold_mean=oos_metrics.get('mae_ratio_mean', 1.0),
                    mae_ratio_fold_weighted=oos_metrics.get('mae_ratio_weighted', 1.0)
                )
                
                logger.info(f"Created AnalysisRun {analysis_run.id}: {analysis_run.run_name}")
                
                # Save model coefficients (feature importance)
                coefficient_count = 0
                if model_coefficients:
                    coefficient_objects = []
                    for feature_name, coeff_value in model_coefficients.items():
                        coefficient_objects.append(ModelCoefficient(
                            analysis_run=analysis_run,
                            feature_name=feature_name,
                            coefficient_value=float(coeff_value)
                        ))
                    
                    if coefficient_objects:
                        ModelCoefficient.objects.bulk_create(coefficient_objects, batch_size=1000)
                        coefficient_count = len(coefficient_objects)
                        logger.info(f"Saved {coefficient_count} model coefficients")
                
                # Save per-stock performance metrics
                performance_count = 0
                if per_stock_metrics:
                    try:
                        performance_objects = []
                        for stock_metric in per_stock_metrics:
                            try:
                                performance_objects.append(StockPerformanceMetrics(
                                    analysis_run=analysis_run,
                                    ticker=stock_metric.get('ticker', ''),
                                    mae=stock_metric.get('mae'),
                                    rmse=stock_metric.get('rmse'),
                                    r2=stock_metric.get('r2'),
                                    directional_accuracy=stock_metric.get('dir_acc'),
                                    sample_size=stock_metric.get('n_obs', 0),
                                    mase=stock_metric.get('mase'),
                                    # Additional metrics if available
                                    mean_prediction=stock_metric.get('mean_pred'),
                                    std_prediction=stock_metric.get('std_pred'),
                                    prediction_range=stock_metric.get('pred_range'),
                                    confidence_score=stock_metric.get('confidence', 0.5)
                                ))
                            except Exception as metric_error:
                                logger.warning(f"Failed to process performance metric for {stock_metric.get('ticker', 'unknown')}: {metric_error}")
                                continue
                        
                        if performance_objects:
                            StockPerformanceMetrics.objects.bulk_create(performance_objects, batch_size=1000)
                            performance_count = len(performance_objects)
                            logger.info(f"Saved {performance_count} stock performance metrics")
                    except Exception as perf_error:
                        logger.warning(f"Failed to save performance metrics: {perf_error}")
                
                # Save detailed predictions with all features
                prediction_count = 0
                if final_predictions:
                    prediction_objects = []
                    for prediction in final_predictions:
                        try:
                            # Extract prediction date
                            pred_date = prediction.get('date')
                            if pred_date:
                                if isinstance(pred_date, str):
                                    pred_date = pd.to_datetime(pred_date).date()
                                elif hasattr(pred_date, 'date'):
                                    pred_date = pred_date.date()
                            else:
                                pred_date = timezone.now().date()
                            
                            prediction_objects.append(StockPrediction(
                                analysis_run=analysis_run,
                                ticker=prediction.get('ticker', ''),
                                prediction_date=pred_date,
                                final_prediction=float(prediction.get('prediction', 0)),
                                # Beta features
                                train_b=prediction.get('train_b'),
                                lag_train_b=prediction.get('lag_train_b'),
                                # Autocorrelation features
                                ar1_corr_10d=prediction.get('ar1_corr_10d'),
                                ar1_corr_20d=prediction.get('ar1_corr_20d'),
                                ar1_corr_60d=prediction.get('ar1_corr_60d'),
                                # Persistence features  
                                sign_persist_20d=prediction.get('sign_persist_20d'),
                                sign_persist_60d=prediction.get('sign_persist_60d'),
                                # Return features
                                ret_1d=prediction.get('ret_1d'),
                                ret_5d=prediction.get('ret_5d'),
                                ret_20d=prediction.get('ret_20d'),
                                # Volatility features
                                vol_63d=prediction.get('vol_63d'),
                                vol_126d=prediction.get('vol_126d'),
                                vol_252d=prediction.get('vol_252d'),
                                vol_756d=prediction.get('vol_756d'),
                                # Z-score features
                                z_ma_20d=prediction.get('Z_ma_20d'),
                                # Cross-sectional rank features
                                cs_rank_ret_1d=prediction.get('cs_rank_ret_1d'),
                                cs_rank_ret_5d=prediction.get('cs_rank_ret_5d'),
                                cs_rank_ret_20d=prediction.get('cs_rank_ret_20d'),
                                cs_rank_z_ma_20d=prediction.get('cs_rank_z_ma_20d'),
                                cs_rank_vol_63d=prediction.get('cs_rank_vol_63d'),
                                cs_rank_vol_126d=prediction.get('cs_rank_vol_126d'),
                                cs_rank_vol_252d=prediction.get('cs_rank_vol_252d'),
                                cs_rank_vol_756d=prediction.get('cs_rank_vol_756d'),
                                # Market dispersion
                                xsec_disp_30d=prediction.get('xsec_disp_30d')
                            ))
                        except Exception as pred_error:
                            logger.warning(f"Failed to process prediction for {prediction.get('ticker', 'unknown')}: {pred_error}")
                            continue
                    
                    if prediction_objects:
                        StockPrediction.objects.bulk_create(prediction_objects, batch_size=1000)
                        prediction_count = len(prediction_objects)
                        logger.info(f"Saved {prediction_count} stock predictions")
                
                # Enhanced status update with comprehensive results and insights
                ClientModelStatus.set_status(client_id, {
                    **ClientModelStatus.get_status(client_id),
                    'status': 'completed',
                    'stage': 'completed',
                    'progress': 100,
                    'analysis_run_id': analysis_run.id,
                    'run_name': analysis_run.run_name,
                    'completion_time': datetime.now().isoformat(),
                    'results': {
                        'model_performance': {
                            'mae': oos_metrics.get('mae'),
                            'rmse': oos_metrics.get('rmse'),
                            'r2': oos_metrics.get('r2'),
                            'directional_accuracy': oos_metrics.get('dir_acc'),
                            'sample_size': oos_metrics.get('n_obs'),
                            'performance_summary': f"R² = {oos_metrics.get('r2', 0):.3f}, MAE = {oos_metrics.get('mae', 0):.4f}"
                        },
                        'model_insights': {
                            'total_stocks_analyzed': len(final_predictions),
                            'total_features_used': len(model_coefficients),
                            'horizon_days': actual_horizon,
                            'model_equation': model_equation[:200] + ('...' if len(model_equation) > 200 else ''),
                            'top_features': dict(list(sorted(model_coefficients.items(), 
                                                           key=lambda x: abs(x[1]), reverse=True))[:5]) if model_coefficients else {},
                            'model_params': {
                                'alpha': model_params.get('enet_alpha'),
                                'l1_ratio': model_params.get('enet_l1_ratio'),
                                'min_train_rows': model_params.get('oos_min_train_rows_fixed')
                            }
                        },
                        'database_summary': {
                            'analysis_run_id': analysis_run.id,
                            'coefficients_saved': coefficient_count,
                            'predictions_saved': prediction_count,
                            'performance_metrics_saved': performance_count,
                            'run_name': analysis_run.run_name
                        },
                        'artifacts': main_result.get('artifacts', {}),
                        'quality_indicators': {
                            'model_significance': 'High' if oos_metrics.get('r2', 0) > 0.1 else 'Medium' if oos_metrics.get('r2', 0) > 0.05 else 'Low',
                            'prediction_accuracy': 'Good' if oos_metrics.get('dir_acc', 0) > 0.55 else 'Fair' if oos_metrics.get('dir_acc', 0) > 0.5 else 'Poor',
                            'sample_adequacy': 'Sufficient' if oos_metrics.get('n_obs', 0) > 1000 else 'Limited'
                        }
                    }
                })
                
                logger.info(f"Successfully completed comprehensive universal beta analysis for client {client_id}")
                logger.info(f"Analysis Run ID: {analysis_run.id} | Performance: R²={oos_metrics.get('r2', 0):.4f}, MAE={oos_metrics.get('mae', 0):.4f}")
                logger.info(f"Saved: {prediction_count} predictions, {coefficient_count} coefficients, {performance_count} stock metrics")
                
            except Exception as db_error:
                logger.error(f"Database save failed for client {client_id}: {str(db_error)}")
                logger.error(traceback.format_exc())
                # Still mark as completed, but note the save issue
                ClientModelStatus.set_status(client_id, {
                    **ClientModelStatus.get_status(client_id),
                    'status': 'completed_with_warnings',
                    'stage': 'completed',
                    'progress': 100,
                    'results': result['summary'],
                    'save_error': str(db_error),
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
            
            # Extract advanced model parameters
            advanced_params = {
                'sector_filter': request.data.get('sector_filter', 'all'),
                'alpha': float(request.data.get('alpha', 0.01)),
                'l1_ratio': float(request.data.get('l1_ratio', 0.5)),
                'training_days': int(request.data.get('training_days', 252)),
                'testing_days': int(request.data.get('testing_days', 63)),
                'multi_period': bool(request.data.get('multi_period', False)),
                # Additional fund manager params (for logging/tracking)
                'risk_tolerance': request.data.get('risk_tolerance', 'medium'),
                'minimum_confidence': float(request.data.get('minimum_confidence', 0.6)),
                'lookback_period': int(request.data.get('lookback_period', 60)),
                'volatility_adjustment': bool(request.data.get('volatility_adjustment', True)),
                'cross_sectional_ranking': bool(request.data.get('cross_sectional_ranking', True))
            }
            
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
            user_id = request.user.id if request.user.is_authenticated else None
            executor.submit(run_model_background, client_id, file_path, horizon_days, advanced_params, user_id)
            
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
            
            # from .views_universal import UniversalBetaDashboardView
            # dashboard_view = UniversalBetaDashboardView()
            
            # Get the standard dashboard response
            # mock_request = type('MockRequest', (), {
            #     'GET': {'horizon': horizon, 'limit': str(limit)}
            # })()
            
            # For now, return placeholder data since UniversalBetaDashboardView doesn't exist
            return JsonResponse({
                'status': 'success',
                'data': {
                    'predictions': [],
                    'metrics': {},
                    'message': 'Dashboard functionality temporarily disabled'
                }
            })
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