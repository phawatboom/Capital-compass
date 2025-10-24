# views_universal.py
"""
Views for Universal Beta Model
Designed to extend existing views with minimal changes
"""

import os
import pandas as pd
from django.http import JsonResponse
from django.db.models import Avg, Count, Max, Min
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.views import View
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models_universal import UniversalBetaPrediction, UniversalModelMetrics, StockUniversalMetrics
import logging

logger = logging.getLogger(__name__)

class UniversalModelDataImporter:
    """
    Data importer for Universal Model results from Pooled_Outputs_v6_Fixed/
    """
    
    def __init__(self, base_path=None):
        if base_path is None:
            # Default to Data Analysis folder
            self.base_path = os.path.join(settings.BASE_DIR.parent, "Data Analysis", "Pooled_Outputs_v6_Fixed")
        else:
            self.base_path = base_path
    
    def import_all_data(self):
        """Import all universal model data"""
        results = {
            'predictions': 0,
            'global_metrics': 0,
            'stock_metrics': 0,
            'errors': []
        }
        
        try:
            # Import predictions for each horizon
            for horizon in [1, 5, 10, 20]:
                count = self.import_predictions(horizon)
                results['predictions'] += count
            
            # Import global metrics
            results['global_metrics'] = self.import_global_metrics()
            
            # Import per-stock metrics
            results['stock_metrics'] = self.import_stock_metrics()
            
        except Exception as e:
            results['errors'].append(str(e))
            logger.error(f"Import error: {str(e)}")
        
        return results
    
    def import_predictions(self, horizon_days):
        """Import predictions for specific horizon"""
        folder_path = os.path.join(self.base_path, f"POOLED_MODEL_{horizon_days}d")
        file_path = os.path.join(folder_path, "final_predictions.csv")
        
        if not os.path.exists(file_path):
            logger.warning(f"Predictions file not found: {file_path}")
            return 0
        
        try:
            df = pd.read_csv(file_path)
            
            # Clear existing data for this horizon
            UniversalBetaPrediction.objects.filter(horizon_days=horizon_days).delete()
            
            predictions = []
            for _, row in df.iterrows():
                pred = UniversalBetaPrediction(
                    ticker=row['Ticker'],
                    date=pd.to_datetime(row['Date']).date(),
                    horizon_days=horizon_days,
                    final_prediction=row['final_prediction'],
                    train_b=row.get('train_b', 0),
                    lag_train_b=row.get('lag_train_b'),
                    ar1_corr_10d=row.get('ar1_corr_10d'),
                    ar1_corr_20d=row.get('ar1_corr_20d'),
                    ar1_corr_60d=row.get('ar1_corr_60d'),
                    sign_persist_20d=row.get('sign_persist_20d'),
                    sign_persist_60d=row.get('sign_persist_60d'),
                    ret_1d=row.get('ret_1d'),
                    ret_5d=row.get('ret_5d'),
                    ret_20d=row.get('ret_20d'),
                    vol_63d=row.get('vol_63d'),
                    vol_126d=row.get('vol_126d'),
                    vol_252d=row.get('vol_252d'),
                    vol_756d=row.get('vol_756d'),
                    z_ma_20d=row.get('Z_ma_20d'),
                    cs_rank_ret_1d=row.get('cs_rank_ret_1d'),
                    cs_rank_ret_5d=row.get('cs_rank_ret_5d'),
                    cs_rank_ret_20d=row.get('cs_rank_ret_20d'),
                    cs_rank_z_ma_20d=row.get('cs_rank_z_ma_20d'),
                    cs_rank_vol_63d=row.get('cs_rank_vol_63d'),
                    cs_rank_vol_126d=row.get('cs_rank_vol_126d'),
                    cs_rank_vol_252d=row.get('cs_rank_vol_252d'),
                    cs_rank_vol_756d=row.get('cs_rank_vol_756d'),
                    xsec_disp_30d=row.get('xsec_disp_30d'),
                )
                predictions.append(pred)
            
            # Batch create for efficiency
            UniversalBetaPrediction.objects.bulk_create(predictions, batch_size=1000)
            
            logger.info(f"Imported {len(predictions)} predictions for {horizon_days}d horizon")
            return len(predictions)
            
        except Exception as e:
            logger.error(f"Error importing predictions for {horizon_days}d: {str(e)}")
            return 0
    
    def import_global_metrics(self):
        """Import global model metrics"""
        
        # Import metrics for each horizon
        count = 0
        UniversalModelMetrics.objects.all().delete()
        
        for horizon in [1, 5, 10, 20]:
            folder_path = os.path.join(self.base_path, f"POOLED_MODEL_{horizon}d")
            file_path = os.path.join(folder_path, "oos_metrics.csv")
            
            if not os.path.exists(file_path):
                logger.warning(f"Global metrics file not found: {file_path}")
                continue
            
            try:
                df = pd.read_csv(file_path)
                
                # The file has only one row with global metrics
                row = df.iloc[0]
                
                UniversalModelMetrics.objects.create(
                    horizon_days=horizon,
                    mae=row['MAE'],
                    rmse=row['RMSE'],
                    r2_global=row['R2_global'],
                    r2_fold_mean=row['R2_fold_mean'],
                    r2_fold_weighted=row['R2_fold_weighted'],
                    directional_accuracy=row['DirectionalAcc'],
                    n_predictions=int(row['N']),
                    mae_ratio_global=row['MAE_ratio_global'],
                )
                count += 1
                
            except Exception as e:
                logger.error(f"Error importing global metrics for {horizon}d: {str(e)}")
        
        logger.info(f"Imported {count} global metric records")
        return count
    
    def import_stock_metrics(self):
        """Import per-stock metrics"""
        
        # Clear existing metrics
        StockUniversalMetrics.objects.all().delete()
        
        total_count = 0
        for horizon in [1, 5, 10, 20]:
            folder_path = os.path.join(self.base_path, f"POOLED_MODEL_{horizon}d")
            file_path = os.path.join(folder_path, "per_stock_oos_metrics.csv")
            
            if not os.path.exists(file_path):
                logger.warning(f"Stock metrics file not found: {file_path}")
                continue
            
            try:
                df = pd.read_csv(file_path)
                
                metrics = []
                for _, row in df.iterrows():
                    metric = StockUniversalMetrics(
                        ticker=row['Ticker'],
                        horizon_days=horizon,
                        r2_oos=row['R2_OOS'],
                        rmse_oos=row['RMSE_OOS'],
                        mae_oos=row['MAE_OOS'],
                        mase_oos=row['MASE_OOS'],
                        dir_acc_oos=row['DirAcc_OOS'],
                        pred_std_oos=row['PredStd_OOS'],
                        n_oos=int(row['N_OOS']),
                    )
                    metrics.append(metric)
                
                StockUniversalMetrics.objects.bulk_create(metrics, batch_size=1000)
                total_count += len(metrics)
                
            except Exception as e:
                logger.error(f"Error importing stock metrics for {horizon}d: {str(e)}")
        
        logger.info(f"Imported {total_count} stock metric records")
        return total_count


@method_decorator(csrf_exempt, name='dispatch')
class ImportUniversalDataView(View):
    """Import universal model data endpoint"""
    
    def post(self, request):
        """Import all universal model data"""
        try:
            importer = UniversalModelDataImporter()
            results = importer.import_all_data()
            
            return JsonResponse({
                'status': 'success',
                'message': 'Universal model data imported successfully',
                'summary': results
            })
            
        except Exception as e:
            logger.error(f"Import failed: {str(e)}")
            return JsonResponse({
                'status': 'error',
                'message': f'Import failed: {str(e)}'
            }, status=500)


class UniversalBetaDashboardView(APIView):
    """
    Enhanced dashboard view for Universal Beta Model
    Designed for fund managers making daily trading decisions
    """
    
    def get(self, request):
        """Get comprehensive dashboard data"""
        try:
            # Get query parameters
            horizon = request.GET.get('horizon', '10')
            limit = int(request.GET.get('limit', '50'))
            
            # Global model performance
            global_metrics = UniversalModelMetrics.objects.filter(
                horizon_days=horizon
            ).first()
            
            # Recent predictions (for trading today)
            latest_predictions = UniversalBetaPrediction.objects.filter(
                horizon_days=horizon
            ).order_by('-date', '-final_prediction')[:limit]
            
            # High-confidence trading opportunities
            high_confidence_trades = UniversalBetaPrediction.objects.filter(
                horizon_days=horizon,
                confidence_tier='HIGH'
            ).exclude(prediction_direction='STABLE').order_by('-date', '-final_prediction')[:20]
            
            # Performance by direction
            direction_stats = UniversalBetaPrediction.objects.filter(
                horizon_days=horizon
            ).values('prediction_direction').annotate(
                count=Count('id'),
                avg_prediction=Avg('final_prediction')
            )
            
            # Top performers (stocks with best prediction accuracy)
            top_performers = StockUniversalMetrics.objects.filter(
                horizon_days=horizon,
                performance_tier__in=['EXCELLENT', 'GOOD']
            ).order_by('-r2_oos')[:10]
            
            return Response({
                'status': 'success',
                'data': {
                    'model_info': {
                        'type': 'Universal Pooled Model',
                        'version': 'v1',
                        'description': 'Cross-sectional learning across entire stock universe',
                        'sample_size': '518 stocks',
                        'features': '23 engineered features',
                        'horizon_days': horizon
                    },
                    'global_performance': {
                        'r2_global': global_metrics.r2_global if global_metrics else None,
                        'directional_accuracy': global_metrics.directional_accuracy if global_metrics else None,
                        'mae': global_metrics.mae if global_metrics else None,
                        'n_predictions': global_metrics.n_predictions if global_metrics else None,
                    } if global_metrics else None,
                    'latest_predictions': [
                        {
                            'ticker': pred.ticker,
                            'date': pred.date.isoformat(),
                            'final_prediction': round(pred.final_prediction, 4),
                            'direction': pred.prediction_direction,
                            'confidence': pred.confidence_tier,
                            'current_vol': round(pred.vol_63d or 0, 4),
                            'momentum_1d': round(pred.ret_1d or 0, 4),
                            'cross_sectional_rank': round(pred.cs_rank_ret_5d or 0, 2)
                        }
                        for pred in latest_predictions
                    ],
                    'trading_opportunities': [
                        {
                            'ticker': trade.ticker,
                            'prediction': round(trade.final_prediction, 4),
                            'direction': trade.prediction_direction,
                            'confidence': trade.confidence_tier,
                            'signal_strength': abs(trade.final_prediction),
                            'volatility_rank': round(trade.cs_rank_vol_63d or 0, 2),
                            'momentum_rank': round(trade.cs_rank_ret_5d or 0, 2)
                        }
                        for trade in high_confidence_trades
                    ],
                    'direction_breakdown': list(direction_stats),
                    'top_performing_stocks': [
                        {
                            'ticker': stock.ticker,
                            'r2_oos': round(stock.r2_oos, 4),
                            'directional_accuracy': round(stock.dir_acc_oos, 3),
                            'performance_tier': stock.performance_tier,
                            'n_observations': stock.n_oos
                        }
                        for stock in top_performers
                    ]
                }
            })
            
        except Exception as e:
            logger.error(f"Dashboard error: {str(e)}")
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=500)


class UniversalBetaTimeSeriesView(APIView):
    """Time series data for universal model predictions"""
    
    def get(self, request):
        """Get time series data for specific ticker"""
        try:
            ticker = request.GET.get('ticker', '').upper()
            horizon = request.GET.get('horizon', '10')
            
            if not ticker:
                return Response({
                    'status': 'error',
                    'message': 'Ticker parameter required'
                }, status=400)
            
            # Get predictions for this ticker
            predictions = UniversalBetaPrediction.objects.filter(
                ticker=ticker,
                horizon_days=horizon
            ).order_by('date')
            
            # Get stock-specific metrics
            stock_metrics = StockUniversalMetrics.objects.filter(
                ticker=ticker,
                horizon_days=horizon
            ).first()
            
            return Response({
                'status': 'success',
                'data': {
                    'ticker': ticker,
                    'horizon_days': horizon,
                    'stock_performance': {
                        'r2_oos': stock_metrics.r2_oos if stock_metrics else None,
                        'directional_accuracy': stock_metrics.dir_acc_oos if stock_metrics else None,
                        'performance_tier': stock_metrics.performance_tier if stock_metrics else None,
                        'n_observations': stock_metrics.n_oos if stock_metrics else None,
                    } if stock_metrics else None,
                    'time_series': [
                        {
                            'date': pred.date.isoformat(),
                            'prediction': round(pred.final_prediction, 4),
                            'direction': pred.prediction_direction,
                            'confidence': pred.confidence_tier,
                            'volatility_63d': round(pred.vol_63d or 0, 4),
                            'return_1d': round(pred.ret_1d or 0, 4),
                            'return_5d': round(pred.ret_5d or 0, 4),
                            'cross_sectional_dispersion': round(pred.xsec_disp_30d or 0, 4)
                        }
                        for pred in predictions
                    ]
                }
            })
            
        except Exception as e:
            logger.error(f"Time series error: {str(e)}")
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=500)


class UniversalModelSummaryView(APIView):
    """Summary statistics for universal model across all horizons"""
    
    def get(self, request):
        """Get comprehensive model summary"""
        try:
            # Get metrics for all horizons
            all_metrics = UniversalModelMetrics.objects.all().order_by('horizon_days')
            
            # Stock universe stats
            unique_stocks = UniversalBetaPrediction.objects.values('ticker').distinct().count()
            total_predictions = UniversalBetaPrediction.objects.count()
            
            # Performance distribution
            performance_distribution = StockUniversalMetrics.objects.values(
                'performance_tier'
            ).annotate(count=Count('id'))
            
            # Latest prediction date
            latest_date = UniversalBetaPrediction.objects.aggregate(
                latest=Max('date')
            )['latest']
            
            return Response({
                'status': 'success',
                'data': {
                    'model_overview': {
                        'name': 'Universal Beta Forecasting Model',
                        'methodology': 'Pooled cross-sectional learning with elastic net regularization',
                        'total_stocks': unique_stocks,
                        'total_predictions': total_predictions,
                        'latest_prediction_date': latest_date.isoformat() if latest_date else None,
                        'features': [
                            'Historical beta coefficients (AR layer)',
                            'Technical indicators (autocorrelation, persistence)',
                            'Return momentum (multi-horizon)',
                            'Volatility features (63d to 756d)',
                            'Cross-sectional rankings',
                            'Market regime indicators'
                        ]
                    },
                    'performance_by_horizon': [
                        {
                            'horizon_days': metric.horizon_days,
                            'r2_global': round(metric.r2_global, 4),
                            'directional_accuracy': round(metric.directional_accuracy, 3),
                            'mae': round(metric.mae, 4),
                            'rmse': round(metric.rmse, 4),
                            'n_predictions': metric.n_predictions,
                            'performance_vs_naive': round(1 - metric.mae_ratio_global, 3)
                        }
                        for metric in all_metrics
                    ],
                    'stock_performance_distribution': list(performance_distribution),
                    'advantages': [
                        'Leverages information from entire stock universe',
                        'Robust to individual stock noise',
                        'Consistent performance across market regimes',
                        'Incorporates cross-sectional effects',
                        'Automated confidence assessment'
                    ]
                }
            })
            
        except Exception as e:
            logger.error(f"Summary error: {str(e)}")
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=500)