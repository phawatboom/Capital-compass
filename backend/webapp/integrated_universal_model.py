# integrated_universal_model.py
"""
Integrated Universal Beta Model for client data uploads using optimized model_no_csv.py
This allows clients to upload their own data and run the universal model with database integration
"""

import os
import sys
import logging
import pandas as pd
import numpy as np
import traceback
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, List

# Django imports
from django.conf import settings
from django.utils import timezone
from django.contrib.auth.models import User

# Import database models
from .models import (
    AnalysisRun, ModelCoefficient, StockPrediction, 
    StockPerformanceMetrics, OutOfSamplePrediction, FoldStatistics
)

logger = logging.getLogger(__name__)

def _coerce_date(df: pd.DataFrame, col="Date") -> pd.DataFrame:
    """Convert date column to datetime and clean the dataframe"""
    out = df.copy()
    out[col] = pd.to_datetime(out[col], errors="coerce", infer_datetime_format=True)
    out = out.dropna(subset=[col]).sort_values(col).reset_index(drop=True)
    return out

def _clean_numeric(x):
    """Clean numeric values, handling percentages and string formatting"""
    if isinstance(x, str):
        s = x.strip().replace(",", "")
        if s == "": 
            return np.nan
        if s.endswith("%"):
            try: 
                return float(s[:-1]) / 100.0
            except: 
                return np.nan
        try: 
            return float(s)
        except: 
            return np.nan
    return x

def load_mxus_returns(xlsx_path: str, sheet: str = "Returns") -> pd.DataFrame:
    """
    Robust loader for MXUS_Data.xlsx / 'Returns' where the true header row may be below row 1.
    - Finds the first row containing 'Date' (case-insensitive) and uses it as header.
    - Converts percent strings like '0.79%' → 0.0079
    """
    raw = pd.read_excel(xlsx_path, sheet_name=sheet, header=None, dtype=object)

    header_row = None
    scan_rows = min(50, len(raw))
    for i in range(scan_rows):
        row = raw.iloc[i].astype(str).str.strip()
        if row.str.lower().eq("date").any():
            header_row = i
            break
    if header_row is None:
        raise KeyError("Could not find a header row containing 'Date' in the sheet.")

    cols = raw.iloc[header_row].astype(str).str.strip().tolist()
    df = raw.iloc[header_row + 1:].copy()
    df.columns = cols
    df = df.loc[:, ~(df.isna().all())]

    # find/rename Date
    date_col = None
    for c in df.columns:
        if str(c).strip().lower() == "date":
            date_col = c
            break
    if date_col is None:
        for c in df.columns:
            if "date" in str(c).strip().lower():
                date_col = c
                break
    if date_col is None:
        raise KeyError("Found header row but no column named 'Date'.")

    if date_col != "Date":
        df = df.rename(columns={date_col: "Date"})

    # convert values
    for c in df.columns:
        if c != "Date":
            df[c] = df[c].map(_clean_numeric)

    return _coerce_date(df, "Date")

# Add the data-analysis directory to Python path for model access
sys.path.append(os.path.join(settings.BASE_DIR.parent, "data-analysis"))

# Try to import optimized model functions
try:
    from model_no_csv import (
        _coerce_date,
        load_mxus_returns, 
        run_pipeline_for_horizon,
        aggregate_to_period_returns,
        rich_features_from_returns,
        _cs_percentile_rank_wide,
        add_cross_sectional_ranks
    )
    MODEL_AVAILABLE = True
    logger.info("Successfully imported optimized model functions from model_no_csv.py")
except ImportError as e:
    MODEL_AVAILABLE = False
    logger.error(f"Failed to import optimized model functions: {e}")
    logger.error("Will use fallback mode - limited functionality available")


class IntegratedUniversalBetaModel:
    """
    Universal Beta Model that can run on client-uploaded data using the optimized model_no_csv.py
    Integrates data processing, model training, prediction generation, and database storage
    """
    
    def __init__(self, output_dir=None, alpha=0.01, l1_ratio=0.5):
        self.output_dir = output_dir or os.path.join(settings.MEDIA_ROOT, 'model_outputs')
        self.alpha = alpha
        self.l1_ratio = l1_ratio
        
        # Fixed parameters for the optimized model (matching model_no_csv.py defaults)
        # UPDATED: Changed base_test_len_days from 252 to 256 as requested
        self.fixed_params = {
            'base_train_len_days': 756,   # ~3 years
            'base_test_len_days': 256,    # ~1 year (updated to 256 days)
            'enet_alpha': alpha,
            'enet_l1_ratio': l1_ratio,
            'oos_min_train_rows_fixed': 5000
        }
        
        # Ensure output directory exists
        os.makedirs(self.output_dir, exist_ok=True)
    
    def process_uploaded_data(self, csv_file_path, sector_filter='all'):
        """
        Process client-uploaded data (CSV or Excel) into the format expected by the optimized model
        Handles both wide format (Date + ticker columns) and long format (Date, Ticker, Price)
        Supports CSV files and Excel files with MXUS-style formatting
        Returns: processed DataFrame in wide format (Date + ticker columns)
        """
        try:
            # Read uploaded data with multiple encoding attempts and file type detection
            logger.info(f"Processing uploaded data: {csv_file_path}")
            
            file_extension = csv_file_path.lower().split('.')[-1]
            
            if file_extension == 'csv':
                # CSV file processing
                try:
                    df = pd.read_csv(csv_file_path, encoding='utf-8')
                except UnicodeDecodeError:
                    try:
                        df = pd.read_csv(csv_file_path, encoding='latin-1')
                    except UnicodeDecodeError:
                        df = pd.read_csv(csv_file_path, encoding='cp1252')

            elif file_extension in ['xlsx', 'xls']:
                # Excel file processing with robust MXUS-style loading
                try:
                    # Always prefer MXUS-style loader first for 'Returns' sheet
                    df = load_mxus_returns(csv_file_path, sheet="Returns")
                    logger.info("MXUS-style Returns loader used successfully")
                except Exception as e:
                    logger.info(f"MXUS loader failed ({e}), trying standard Excel read")
                    try:
                        df = pd.read_excel(csv_file_path)
                        logger.info("Standard Excel read successful")
                    except Exception as e2:
                        logger.info(f"Standard Excel read failed ({e2}), trying first sheet fallback")
                        raw = pd.read_excel(csv_file_path, header=None, dtype=object)
                        header_row = None
                        for i in range(min(10, len(raw))):
                            row = raw.iloc[i].astype(str).str.strip()
                            if any(word in row.str.lower().values for word in ['date', 'time', 'period']):
                                header_row = i
                                break
                        if header_row is None:
                            raise ValueError("Could not find valid header row in Excel file")
                        cols = raw.iloc[header_row].astype(str).str.strip().tolist()
                        df = raw.iloc[header_row + 1:].copy()
                        df.columns = cols
                        for c in df.columns:
                            if c.lower() != 'date':
                                df[c] = df[c].map(_clean_numeric)
                    except Exception as e2:
                        logger.info(f"MXUS Returns sheet failed, trying first sheet: {e2}")
                        # Fallback: try first sheet with robust header detection
                        raw = pd.read_excel(csv_file_path, header=None, dtype=object)
                        header_row = None
                        scan_rows = min(10, len(raw))
                        for i in range(scan_rows):
                            row = raw.iloc[i].astype(str).str.strip()
                            if any(word in row.str.lower().values for word in ['date', 'time', 'period']):
                                header_row = i
                                break
                        
                        if header_row is not None:
                            cols = raw.iloc[header_row].astype(str).str.strip().tolist()
                            df = raw.iloc[header_row + 1:].copy()
                            df.columns = cols
                            df = df.loc[:, ~(df.isna().all())]
                            # Clean numeric columns
                            for c in df.columns:
                                if not any(word in str(c).lower() for word in ['date', 'time', 'period']):
                                    df[c] = df[c].map(_clean_numeric)
                        else:
                            raise ValueError("Could not find valid header row in Excel file")
            else:
                raise ValueError(f"Unsupported file format: {file_extension}")
            
            logger.info(f"Loaded data with {len(df)} rows and columns: {df.columns.tolist()}")
            
            # Basic validation
            if len(df) == 0:
                raise ValueError("Empty dataset uploaded")
            
            if len(df.columns) < 2:
                raise ValueError("Dataset must have at least 2 columns")
            
            # Show sample of first few rows for debugging
            logger.info("Sample data (first 3 rows):")
            for i in range(min(3, len(df))):
                row_sample = {k: v for k, v in df.iloc[i].head(10).to_dict().items()}
                logger.info(f"  Row {i}: {row_sample}")
            
            # Detect format and process accordingly
            result = self._detect_and_process_format(df, sector_filter)
            
            if result is None or result.empty:
                raise ValueError("No valid data after processing - format detection failed")
            
            logger.info(f"Successfully processed data: {len(result)} rows, {len(result.columns)} columns")
            return result
            
        except Exception as e:
            logger.error(f"Error processing uploaded data: {str(e)}")
            logger.error(traceback.format_exc())
            
            # Provide more specific error messages
            if "No Date column found" in str(e):
                available_cols = df.columns.tolist()[:10] if 'df' in locals() and df is not None else "unknown"
                error_msg = f"No date column found. Available columns: {available_cols}. Please ensure your data has a Date column or the first column contains dates."
            elif "Could not parse date column" in str(e):
                error_msg = f"Cannot parse dates in the date column. Please ensure dates are in a standard format (YYYY-MM-DD, MM/DD/YYYY, etc.)"
            elif "Empty dataset" in str(e):
                error_msg = "The uploaded file appears to be empty or contains no valid data."
            else:
                error_msg = f"Data processing failed: {str(e)}"
            
            raise ValueError(error_msg)

    def _detect_and_process_format(self, df, sector_filter):
        """Helper method to detect data format and process accordingly"""
        # Standardize column names (case-insensitive)
        df.columns = df.columns.str.strip()
        col_mapping = {}
        
        # Check if this is long format data with more flexible column detection
        has_date_col = False
        has_ticker_col = False
        has_price_col = False
        
        for col in df.columns:
            col_lower = col.lower().strip()
            # More flexible date column detection
            if any(date_word in col_lower for date_word in ['date', 'time', 'period']):
                col_mapping[col] = 'Date'
                has_date_col = True
            # More flexible ticker column detection  
            elif any(ticker_word in col_lower for ticker_word in ['ticker', 'symbol', 'stock', 'company', 'name']):
                col_mapping[col] = 'Ticker'
                has_ticker_col = True
            # More flexible price column detection
            elif any(price_word in col_lower for price_word in ['price', 'close', 'adj_close', 'adjusted_close', 'value', 'return']):
                col_mapping[col] = 'Price'
                has_price_col = True
            elif any(sector_word in col_lower for sector_word in ['sector', 'industry', 'category']):
                col_mapping[col] = 'Sector'
        
        logger.info(f"Column detection results: Date={has_date_col}, Ticker={has_ticker_col}, Price={has_price_col}")
        logger.info(f"Column mapping: {col_mapping}")
        logger.info(f"Total columns: {len(df.columns)}")
        
        # For datasets with many columns (>100), assume it's wide format with tickers as columns
        if len(df.columns) > 100:
            logger.warning(f"Large column count ({len(df.columns)}) detected - likely wide format with tickers as columns")
            
            # For very wide datasets, assume it's already in wide format (Date + ticker columns)
            # This is common for financial datasets where each column represents a different stock
            if has_date_col:
                logger.info("Wide format detected with date column - processing as ticker columns")
                return self._process_wide_format(df, sector_filter)
            else:
                # Assume first column is date for wide format
                logger.info("Wide format detected without explicit date column - assuming first column is date")
                return self._process_wide_format(df, sector_filter)
        
        # If we have all three columns, this is long format
        if has_date_col and has_ticker_col and has_price_col:
            logger.info("Detected long format data (Date, Ticker, Price)")
            return self._process_long_format(df, col_mapping, sector_filter)
        else:
            # For wide format, we need at least a date column and some numeric columns
            if has_date_col or len(df.columns) > 100:  # Wide format with explicit date or many columns
                logger.info("Detected wide format data (Date + ticker columns)")
                return self._process_wide_format(df, sector_filter)
            else:
                # Fallback: assume first column is date if no explicit date column found
                logger.warning("No clear date column found, assuming first column is date")
                return self._process_wide_format(df, sector_filter)
    
    def _process_long_format(self, df, col_mapping, sector_filter):
        """Process long format data (Date, Ticker, Price)"""
        df = df.rename(columns=col_mapping)
        
        # Validate required columns
        if 'Date' not in df.columns:
            raise ValueError("No Date column found in long format data")
        if 'Ticker' not in df.columns:
            raise ValueError("No Ticker column found in long format data")
        if 'Price' not in df.columns:
            raise ValueError("No Price column found in long format data")
        
        # Convert Date column
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        df = df.dropna(subset=['Date']).sort_values('Date').reset_index(drop=True)
        
        # Convert Price to numeric
        df['Price'] = pd.to_numeric(df['Price'], errors='coerce')
        df = df.dropna(subset=['Price'])
        
        # Apply sector filter if specified and available
        if sector_filter != 'all' and 'Sector' in df.columns:
            df = df[df['Sector'].str.lower() == sector_filter.lower()]
            logger.info(f"Applied sector filter '{sector_filter}', {len(df)} rows remaining")
        
        # Calculate returns from prices
        df = df.sort_values(['Ticker', 'Date']).reset_index(drop=True)
        df['Return'] = df.groupby('Ticker')['Price'].pct_change()
        df = df.dropna(subset=['Return'])
        
        # Convert to wide format (Date + ticker columns with returns)
        wide_returns = df.pivot(index='Date', columns='Ticker', values='Return').reset_index()
        wide_returns = wide_returns.sort_values('Date').reset_index(drop=True)
        
        # Fill missing values with 0 (assuming no trading = 0 return)
        ticker_cols = [col for col in wide_returns.columns if col != 'Date']
        wide_returns[ticker_cols] = wide_returns[ticker_cols].fillna(0)
        
        logger.info(f"Processed long format data: {len(wide_returns)} dates, {len(ticker_cols)} tickers")
        return wide_returns
    
    def _process_wide_format(self, df, sector_filter):
        """Process wide format data (Date + ticker columns with prices/returns)"""
        # Look for date column (case insensitive)
        date_col = None
        for col in df.columns:
            if col.lower() in ['date', 'dates', 'time', 'timestamp']:
                date_col = col
                break
        
        if date_col is None:
            # If no date column found, assume first column is date
            date_col = df.columns[0]
            logger.warning(f"No clear date column found, using first column '{date_col}' as date")
        
        # Convert date column
        try:
            df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
            df = df.dropna(subset=[date_col]).sort_values(date_col).reset_index(drop=True)
        except:
            raise ValueError(f"Could not parse date column '{date_col}'")
        
        # Rename date column to standard name
        if date_col != 'Date':
            df = df.rename(columns={date_col: 'Date'})
        
        # Get ticker columns (all non-date columns, but exclude obvious metadata columns)
        potential_ticker_cols = [col for col in df.columns if col != 'Date']
        
        # Filter out non-numeric columns that are clearly not stock data
        ticker_cols = []
        excluded_cols = []
        
        for col in potential_ticker_cols:
            col_lower = col.lower().strip()
            # Skip obvious metadata columns
            if any(meta_word in col_lower for meta_word in ['id', 'name', 'description', 'sector', 'industry', 'market', 'exchange', 'currency', 'index']):
                excluded_cols.append(col)
                continue
            
            # Try to convert a sample to see if it's numeric
            sample_values = df[col].dropna().head(10)
            if len(sample_values) == 0:
                excluded_cols.append(col)
                continue
                
            # Check if values can be converted to numeric
            try:
                numeric_sample = pd.to_numeric(sample_values, errors='coerce')
                if numeric_sample.notna().sum() > len(sample_values) * 0.5:  # At least 50% numeric
                    ticker_cols.append(col)
                else:
                    excluded_cols.append(col)
            except:
                excluded_cols.append(col)
        
        logger.info(f"Identified {len(ticker_cols)} potential ticker columns from {len(potential_ticker_cols)} total columns")
        if excluded_cols:
            logger.info(f"Excluded non-numeric columns: {excluded_cols[:10]}{'...' if len(excluded_cols) > 10 else ''}")
        
        if len(ticker_cols) == 0:
            # Provide detailed diagnostic information
            logger.error("=" * 50)
            logger.error("DETAILED DIAGNOSTIC INFORMATION")
            logger.error("=" * 50)
            logger.error(f"Total columns analyzed: {len(potential_ticker_cols)}")
            logger.error(f"Date column: {date_col}")
            logger.error(f"Potential ticker columns: {potential_ticker_cols[:20]}...")  # First 20
            
            # Show sample data from first few columns
            for i, col in enumerate(potential_ticker_cols[:5]):
                sample = df[col].dropna().head(5).tolist()
                logger.error(f"Column {col}: {sample}")
            
            logger.error(f"Excluded columns (first 20): {excluded_cols[:20]}")
            logger.error("This suggests the data might be in long format but was misdetected as wide format.")
            logger.error("For wide format, expected: Date column + numeric ticker columns")
            logger.error("For long format, expected: Date, Ticker, Price columns")
            logger.error("=" * 50)
            
            raise ValueError(f"No valid ticker columns found in wide format data. "
                           f"Analyzed {len(potential_ticker_cols)} columns, all appear to be non-numeric or metadata. "
                           f"With {len(df.columns)} total columns, this might be long format data misdetected as wide format. "
                           f"Please check the data structure: expected either 3 columns (Date,Ticker,Price) or "
                           f"Date + <100 numeric ticker columns.")
        
        # Convert ticker columns to numeric with better error handling
        logger.info(f"Converting {len(ticker_cols)} ticker columns to numeric: {ticker_cols[:5]}...")
        
        numeric_conversion_success = {}
        for col in ticker_cols:
            original_type = df[col].dtype
            df[col] = pd.to_numeric(df[col], errors='coerce')
            non_null_count = df[col].notna().sum()
            numeric_conversion_success[col] = non_null_count
            logger.debug(f"Column {col}: {original_type} -> numeric, {non_null_count} valid values")
        
        # Check if any columns have valid numeric data
        total_valid_values = sum(numeric_conversion_success.values())
        if total_valid_values == 0:
            logger.error("No valid numeric data found after conversion. Column details:")
            for col in ticker_cols[:10]:  # Show first 10 columns
                sample_values = df[col].head().tolist()
                logger.error(f"  {col}: {sample_values}")
            raise ValueError(f"No valid numeric data found in ticker columns. Checked {len(ticker_cols)} columns.")
        
        logger.info(f"Successfully converted to numeric with {total_valid_values} total valid values")
        
        # Check if data looks like prices (generally increasing) or returns (around 0)
        # Simple heuristic: if most values are between -1 and 1, assume returns
        sample_data = df[ticker_cols].values.flatten()
        sample_data = sample_data[~pd.isna(sample_data)]
        
        if len(sample_data) > 0:
            pct_in_return_range = np.mean((sample_data >= -1) & (sample_data <= 1))
            
            if pct_in_return_range > 0.8:
                logger.info("Data appears to be returns, using directly")
                # Data is already returns
                wide_returns = df.copy()
            else:
                logger.info("Data appears to be prices, calculating returns")
                # Data is prices, calculate returns
                wide_returns = df.copy()
                for col in ticker_cols:
                    wide_returns[col] = df[col].pct_change()
                # Drop first row with NaN returns
                wide_returns = wide_returns.dropna(subset=ticker_cols, how='all')
        else:
            raise ValueError(f"No valid numeric data found in ticker columns after processing {len(ticker_cols)} columns")
        
        # Fill missing values with 0
        wide_returns[ticker_cols] = wide_returns[ticker_cols].fillna(0)
        
        logger.info(f"Processed wide format data: {len(wide_returns)} dates, {len(ticker_cols)} tickers")
        logger.info(f"Sample ticker columns: {ticker_cols[:10] if len(ticker_cols) > 10 else ticker_cols}")
        logger.info(f"Date range: {wide_returns['Date'].min()} to {wide_returns['Date'].max()}")
        
        # Check for any obvious data quality issues
        total_non_null = wide_returns[ticker_cols].notna().sum().sum()
        total_cells = len(wide_returns) * len(ticker_cols)
        data_completeness = total_non_null / total_cells if total_cells > 0 else 0
        logger.info(f"Data completeness: {data_completeness:.1%} ({total_non_null:,} non-null values out of {total_cells:,})")
        
        return wide_returns
    
    def create_market_features(self, wide_returns):
        """
        Create market-wide features from the returns data
        """
        try:
            market_features = pd.DataFrame(index=wide_returns['Date'])
            market_features.index.name = "Date"
            
            # Cross-sectional dispersion (30d rolling average of daily cross-sectional std)
            ticker_cols = [col for col in wide_returns.columns if col != 'Date']
            
            if len(ticker_cols) > 1:
                xsec_disp_1d = wide_returns[ticker_cols].std(axis=1)
                xsec_disp_30d = xsec_disp_1d.rolling(30, min_periods=10).mean()
                market_features['xsec_disp_30d'] = xsec_disp_30d.values
            else:
                # If only one ticker, set to zero
                market_features['xsec_disp_30d'] = 0.0
            
            market_features = market_features.reset_index()
            logger.info(f"Created market features with {len(market_features)} rows")
            return market_features
            
        except Exception as e:
            logger.error(f"Error creating market features: {str(e)}")
            raise
    
    def run_model_pipeline(self, wide_returns, market_features, horizon_days=10):
        """
        Run the optimized model pipeline for a single horizon
        Returns dictionary with model results ready for database storage
        """
        if not MODEL_AVAILABLE:
            raise RuntimeError("Optimized model functions not available. Check import errors.")
        
        try:
            ticker_cols = [col for col in wide_returns.columns if col != 'Date']
            logger.info(f"Running model pipeline for {len(ticker_cols)} tickers, horizon {horizon_days}d")
            
            # Run the optimized pipeline
            result = run_pipeline_for_horizon(
                horizon=horizon_days,
                mxus_returns_data=wide_returns,
                market_features_data=market_features,
                all_tickers=ticker_cols,
                max_workers_data_prep=2,  # Reduced for server environment
                fixed_params=self.fixed_params
            )
            
            if 'error' in result:
                raise RuntimeError(f"Model pipeline failed: {result['error']}")
            
            logger.info(f"Model pipeline completed successfully for horizon {horizon_days}d")
            return result
            
        except Exception as e:
            logger.error(f"Error in model pipeline: {str(e)}")
            logger.error(traceback.format_exc())
            raise
    
    def save_results_to_database(self, model_results, user=None, run_name=None):
        """
        Save model results directly to database using Django models
        """
        try:
            if user is None:
                # Get or create system user for background tasks
                user, created = User.objects.get_or_create(
                    username='system_model_runner',
                    defaults={'email': 'system@example.com', 'is_active': True}
                )
            
            horizon = model_results.get('horizon', 10)
            if run_name is None:
                run_name = f"Universal_Model_{horizon}d_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            # Extract metrics from model results
            oos_metrics = model_results.get('oos_metrics', {})
            
            # Create analysis run record
            analysis_run = AnalysisRun.objects.create(
                user=user,
                run_name=run_name,
                model_type='universal_enet_optimized',
                horizon_days=horizon,
                status='completed',
                completed_at=timezone.now(),
                # Overall metrics
                mae=oos_metrics.get('MAE'),
                rmse=oos_metrics.get('RMSE'),
                directional_accuracy=oos_metrics.get('DirectionalAcc'),
                sample_size=oos_metrics.get('N'),
                r2_global=oos_metrics.get('R2_global'),
                r2_fold_mean=oos_metrics.get('R2_fold_mean'),
                r2_fold_weighted=oos_metrics.get('R2_fold_weighted'),
                mae_ratio_global=oos_metrics.get('MAE_ratio_global'),
                mae_ratio_fold_mean=oos_metrics.get('MAE_ratio_fold_mean'),
                mae_ratio_fold_weighted=oos_metrics.get('MAE_ratio_fold_weighted')
            )
            
            # Save model coefficients
            enet_coefficients = model_results.get('enet_coefficients', {})
            if enet_coefficients:
                coefficient_objects = []
                for feature_name, coeff_value in enet_coefficients.items():
                    coefficient_objects.append(ModelCoefficient(
                        analysis_run=analysis_run,
                        feature_name=feature_name,
                        coefficient_value=float(coeff_value)
                    ))
                if coefficient_objects:
                    ModelCoefficient.objects.bulk_create(coefficient_objects, batch_size=1000)
                    logger.info(f"Saved {len(coefficient_objects)} model coefficients")
            
            # Save final predictions
            final_predictions = model_results.get('final_predictions', [])
            if final_predictions:
                prediction_objects = []
                for pred_data in final_predictions:
                    prediction_objects.append(StockPrediction(
                        analysis_run=analysis_run,
                        ticker=pred_data.get('ticker', ''),
                        prediction_date=pd.to_datetime(pred_data.get('date')).date() if pred_data.get('date') else timezone.now().date(),
                        final_prediction=float(pred_data.get('final_prediction', 0)),
                        # Include all available features
                        train_b=pred_data.get('train_b'),
                        lag_train_b=pred_data.get('lag_train_b'),
                        ar1_corr_10d=pred_data.get('ar1_corr_10d'),
                        ar1_corr_20d=pred_data.get('ar1_corr_20d'),
                        ar1_corr_60d=pred_data.get('ar1_corr_60d'),
                        sign_persist_20d=pred_data.get('sign_persist_20d'),
                        sign_persist_60d=pred_data.get('sign_persist_60d'),
                        ret_1d=pred_data.get('ret_1d'),
                        ret_5d=pred_data.get('ret_5d'),
                        ret_20d=pred_data.get('ret_20d'),
                        vol_63d=pred_data.get('vol_63d'),
                        vol_126d=pred_data.get('vol_126d'),
                        vol_252d=pred_data.get('vol_252d'),
                        vol_756d=pred_data.get('vol_756d'),
                        z_ma_20d=pred_data.get('Z_ma_20d'),
                        cs_rank_ret_1d=pred_data.get('cs_rank_ret_1d'),
                        cs_rank_ret_5d=pred_data.get('cs_rank_ret_5d'),
                        cs_rank_ret_20d=pred_data.get('cs_rank_ret_20d'),
                        cs_rank_z_ma_20d=pred_data.get('cs_rank_z_ma_20d'),
                        cs_rank_vol_63d=pred_data.get('cs_rank_vol_63d'),
                        cs_rank_vol_126d=pred_data.get('cs_rank_vol_126d'),
                        cs_rank_vol_252d=pred_data.get('cs_rank_vol_252d'),
                        cs_rank_vol_756d=pred_data.get('cs_rank_vol_756d'),
                        xsec_disp_30d=pred_data.get('xsec_disp_30d')
                    ))
                
                if prediction_objects:
                    StockPrediction.objects.bulk_create(prediction_objects, batch_size=1000)
                    logger.info(f"Saved {len(prediction_objects)} stock predictions")
            
            # Save per-stock performance metrics
            per_stock_metrics = model_results.get('per_stock_metrics', [])
            if per_stock_metrics:
                performance_objects = []
                for stock_metric in per_stock_metrics:
                    performance_objects.append(StockPerformanceMetrics(
                        analysis_run=analysis_run,
                        ticker=stock_metric.get('Ticker', ''),
                        r2_oos=stock_metric.get('R2_OOS'),
                        rmse_oos=stock_metric.get('RMSE_OOS'),
                        mae_oos=stock_metric.get('MAE_OOS'),
                        mase_oos=stock_metric.get('MASE_OOS'),
                        directional_accuracy_oos=stock_metric.get('DirAcc_OOS'),
                        prediction_std_oos=stock_metric.get('PredStd_OOS'),
                        n_observations_oos=stock_metric.get('N_OOS')
                    ))
                
                if performance_objects:
                    StockPerformanceMetrics.objects.bulk_create(performance_objects, batch_size=1000)
                    logger.info(f"Saved {len(performance_objects)} per-stock performance metrics")
            
            logger.info(f"Successfully saved analysis run {analysis_run.id} to database")
            return {
                'success': True,
                'analysis_run_id': analysis_run.id,
                'run_name': run_name,
                'model_results': model_results
            }
            
        except Exception as e:
            logger.error(f"Error saving results to database: {str(e)}")
            logger.error(traceback.format_exc())
            raise
    
    def run_full_pipeline(self, csv_file_path, horizon_days=10, client_id=None, advanced_params=None, user=None):
        """
        Run the complete optimized pipeline from uploaded data to database storage
        Uses the optimized model_no_csv.py for better performance and integration
        """
        if advanced_params is None:
            advanced_params = {}
            
        try:
            logger.info("Starting Optimized Universal Beta Model pipeline...")
            logger.info(f"File: {csv_file_path}, Horizon: {horizon_days}d")
            logger.info(f"Advanced parameters: {advanced_params}")
            
            # Update model parameters from advanced_params
            if 'alpha' in advanced_params:
                self.fixed_params['enet_alpha'] = float(advanced_params['alpha'])
            if 'l1_ratio' in advanced_params:
                self.fixed_params['enet_l1_ratio'] = float(advanced_params['l1_ratio'])
            if 'training_days' in advanced_params:
                self.fixed_params['base_train_len_days'] = int(advanced_params['training_days'])
            if 'testing_days' in advanced_params:
                # Ensure testing days is at least 256 as requested
                testing_days = max(256, int(advanced_params['testing_days']))
                self.fixed_params['base_test_len_days'] = testing_days
                logger.info(f"Updated testing days to {testing_days} (minimum 256)")
            
            # Step 1: Process uploaded data
            logger.info("Step 1: Processing uploaded data...")
            wide_returns = self.process_uploaded_data(
                csv_file_path, 
                sector_filter=advanced_params.get('sector_filter', 'all')
            )
            
            if wide_returns is None or wide_returns.empty:
                raise ValueError("No valid data after processing uploaded file")
            
            # Step 2: Create market features
            logger.info("Step 2: Creating market features...")
            market_features = self.create_market_features(wide_returns)
            
            # Step 3: Run optimized model pipeline
            logger.info("Step 3: Running optimized model pipeline...")
            model_results = self.run_model_pipeline(
                wide_returns=wide_returns,
                market_features=market_features,
                horizon_days=horizon_days
            )
            
            if 'error' in model_results:
                raise RuntimeError(f"Model pipeline failed: {model_results['error']}")
            
            # Step 4: Save results directly to database
            logger.info("Step 4: Saving results to database...")
            run_name = f"Client_{client_id}_{horizon_days}d" if client_id else None
            db_result = self.save_results_to_database(
                model_results=model_results,
                user=user,
                run_name=run_name
            )
            
            # Step 5: Handle multi-period analysis if requested
            multi_period_results = {}
            if advanced_params.get('multi_period', False):
                logger.info("Step 5: Running multi-period analysis...")
                for period in [1, 5, 10, 20]:
                    if period != horizon_days:  # Don't repeat the main horizon
                        try:
                            logger.info(f"Running {period}-day analysis...")
                            period_results = self.run_model_pipeline(
                                wide_returns=wide_returns,
                                market_features=market_features,
                                horizon_days=period
                            )
                            
                            if 'error' not in period_results:
                                # Save to database
                                period_run_name = f"Client_{client_id}_{period}d" if client_id else None
                                period_db_result = self.save_results_to_database(
                                    model_results=period_results,
                                    user=user,
                                    run_name=period_run_name
                                )
                                multi_period_results[f'{period}d'] = {
                                    'model_results': period_results,
                                    'db_result': period_db_result
                                }
                                logger.info(f"Completed {period}-day analysis")
                            else:
                                logger.warning(f"Failed {period}-day analysis: {period_results['error']}")
                                
                        except Exception as e:
                            logger.error(f"Error in {period}-day analysis: {str(e)}")
                            multi_period_results[f'{period}d'] = {'error': str(e)}
            
            # Prepare summary for frontend
            summary = {
                'success': True,
                'horizon_days': horizon_days,
                'total_stocks': len([col for col in wide_returns.columns if col != 'Date']),
                'model_performance': model_results.get('oos_metrics', {}),
                'feature_importance': model_results.get('enet_coefficients', {}),
                'analysis_run_id': db_result.get('analysis_run_id'),
                'run_name': db_result.get('run_name'),
                'multi_period_count': len(multi_period_results)
            }
            
            if multi_period_results:
                summary['multi_period_results'] = multi_period_results
            
            logger.info("Universal Beta Model pipeline completed successfully!")
            return {
                'success': True,
                'summary': summary,
                'output_directory': self.output_dir,
                'model_results': model_results,
                'db_result': db_result
            }
            
        except Exception as e:
            logger.error(f"Pipeline failed: {str(e)}")
            logger.error(traceback.format_exc())
            return {
                'success': False,
                'error': str(e),
                'summary': {
                    'success': False,
                    'error': str(e),
                    'horizon_days': horizon_days,
                    'total_stocks': 0,
                    'model_performance': {}
                }
            }