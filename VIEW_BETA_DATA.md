# 📊 How to View Beta Analysis Data

## Option 1: Web Dashboard (Recommended) 

### Step 1: Setup the Application
```bash
# Follow QUICK_SETUP.md to get backend and frontend running
cd backend
python manage.py runserver  # Terminal 1

cd frontend  
pnpm run dev  # Terminal 2
```

### Step 2: Import Beta Data to Database
```bash
# In backend directory
python manage.py import_beta_data

# You should see output like:
# Importing from: outputs/betas_20d.csv
# Importing from: outputs/forecast_eval_20d.csv
# Successfully imported X beta records
# Successfully imported Y forecast evaluation records
```

### Step 3: Access the Dashboard
1. Open browser to: `http://localhost:3000/beta`
2. You'll see interactive charts and tables with:
   - Beta coefficient predictions vs actual values
   - Forecast accuracy metrics  
   - Time series charts for individual stocks
   - Summary statistics and performance metrics

## Option 2: Raw Data Files

### Direct CSV Access
- **Main data**: `outputs/betas_20d.csv` (1M+ rows)
- **Evaluation metrics**: `outputs/forecast_eval_20d.csv` (94K+ rows)

### Open with Excel/Google Sheets
```bash
# View first 100 rows in terminal
head -n 100 outputs/betas_20d.csv

# Or open in Excel
start outputs/betas_20d.csv  # Windows
open outputs/betas_20d.csv   # Mac
```

## Option 3: API Access (For Developers)

### Get Summary Data
```bash
curl http://localhost:8000/api/beta/summary/
```

### Get Time Series for Specific Stock
```bash
curl http://localhost:8000/api/beta/timeseries/AAPL/
```

### Filter by Date Range
```bash
curl "http://localhost:8000/api/beta/realized/?start_date=2024-01-01&end_date=2024-12-31"
```

## What You'll See in the Data

### Beta Realized Data (`betas_20d.csv`)
- **Date**: Trading date
- **ticker**: Stock symbol (e.g., AAPL UW, MSFT UN)
- **beta_realised**: Actual calculated beta
- **beta_pred**: Model's predicted beta
- **r2_ols_x/y**: R-squared values for model fit
- **p_value**: Statistical significance
- **significance_score**: Confidence score (0-1)
- **band/lo/hi**: Confidence interval bounds

### Forecast Evaluation (`forecast_eval_20d.csv`)
- **Date**: Forecast date
- **ticker**: Stock symbol  
- **r2_ols**: Model R-squared performance
- **p_value**: Statistical significance
- **beta_pred vs beta_true**: Prediction vs actual comparison
- **band**: Confidence interval width

## Dashboard Features

### 📈 Interactive Charts
- Time series plots showing predictions vs actuals
- Confidence bands around predictions
- Hover tooltips with detailed metrics

### 📊 Summary Tables  
- Sortable/filterable stock performance
- Latest predictions and accuracy scores
- Statistical significance indicators

### 🎯 Performance Metrics
- Overall model accuracy
- Prediction coverage rates
- R-squared distribution across stocks

## Troubleshooting

### "No data available" in dashboard
- **Fix**: Run `python manage.py import_beta_data` first
- **Check**: Ensure `outputs/` folder contains CSV files

### API returns empty results
- **Fix**: Check if backend is running on port 8000
- **Fix**: Verify data import completed successfully

### CSV files too large for Excel
- **Fix**: Use `head -n 1000 filename.csv > sample.csv` for smaller sample
- **Fix**: Use programming tools (Python pandas, R) for analysis