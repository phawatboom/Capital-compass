# FAQ and Troubleshooting Guide
## β-Forecasting Pipeline - Common Issues and Solutions

---

## 🚨 **Emergency Quick Fixes**

### **Pipeline Won't Start**
```bash
# Check Python environment
python --version  # Should be 3.8+
pip list | grep -E "(pandas|numpy|scikit-learn)"

# Install missing packages
pip install pandas numpy scikit-learn scipy matplotlib openpyxl

# Test basic imports
python -c "import pandas, numpy, sklearn; print('Dependencies OK')"
```

### **No Predictions Generated**
```python
# Quick diagnostic
python -c "
import pandas as pd
from pathlib import Path

# Check if any output files exist
outputs = list(Path('outputs').glob('betas_*.csv'))
if outputs:
    df = pd.read_csv(outputs[0])
    print(f'Found {len(df)} predictions in {outputs[0].name}')
else:
    print('No prediction files found - pipeline may have failed')
"
```

### **Memory/Performance Issues**
```bash
# Quick development run (fast)
python bcoefficient_production_level_code_patched.py --horizons 20 --train-years 2 --no-charts
```

---

## ❓ **Frequently Asked Questions**

### **Q1: What data format does the pipeline expect?**

**A**: Excel file with the following structure:
```
Column A: Date (YYYY-MM-DD format)
Column B-Z: Stock return data (one column per ticker)
Sheet name: Usually "Returns" or "Sheet1"
```

**Example**:
```csv
Date,AAPL,MSFT,GOOGL
2024-01-01,0.012,-0.005,0.008
2024-01-02,-0.003,0.015,0.002
2024-01-03,0.007,0.001,-0.010
```

### **Q2: How do I interpret the action recommendations?**

**A**: Three possible actions with business meaning:

| Action | Meaning | Business Implication |
|--------|---------|---------------------|
| **CHASE** | β predicted to increase | Stock will be more sensitive to market moves → Increase position if market positive |
| **FADE** | β predicted to decrease | Stock will be less sensitive to market moves → Reduce position if market positive |
| **HOLD** | Insufficient confidence | Wait for better signal → No position change |

### **Q3: What confidence levels should I trust?**

**A**: Confidence tier interpretation:

| Confidence | R² | P-value | Business Action |
|------------|----|---------| ----------------|
| **Very High** | ≥10% | ≤1% | Full position sizing |
| **High** | ≥5% | ≤5% | Standard position sizing |
| **Medium** | ≥2% | ≤10% | Reduced position sizing |
| **Low** | ≥1% | ≤20% | Watch list only |
| **Very Low** | <1% | >20% | No action |

### **Q4: How often should I run the pipeline?**

**A**: Recommended frequencies:
- **Daily**: For active trading (recommended)
- **Weekly**: For longer-term portfolio management
- **On-demand**: During market stress or significant events

### **Q5: What universe size can the pipeline handle?**

**A**: Performance guidelines:
- **Small** (≤50 stocks): 2-5 minutes
- **Medium** (≤200 stocks): 10-20 minutes
- **Large** (≤500 stocks): 30-60 minutes
- **Very Large** (>500 stocks): Consider chunking or overnight runs

### **Q6: How do I customize quality gates for my market?**

**A**: Market-specific configurations:

```python
# Emerging markets (more volatile, relax gates)
Config(r2_min=0.001, p_value_max=0.15, hi_vol_relax=25)

# Developed markets (more stable, stricter gates)  
Config(r2_min=0.02, p_value_max=0.05, hi_vol_relax=10)

# Small cap (higher noise, very relaxed)
Config(r2_min=0.0005, p_value_max=0.20, hi_vol_relax=30)

# Large cap (more predictable, stricter)
Config(r2_min=0.05, p_value_max=0.01, hi_vol_relax=5)
```

---

## 🔧 **Common Error Messages**

### **Configuration Errors**

#### **Error**: `ValueError: beta_window (20) must be >= min_obs (25)`
**Solution**:
```python
# Fix: Increase beta_window or decrease min_obs
cfg.beta_window = 60  # Increase window
# OR
cfg.min_obs = 15      # Decrease minimum observations
```

#### **Error**: `ValueError: horizons list cannot be empty`
**Solution**:
```python
cfg.horizons = [1, 5, 20]  # Set valid horizons
```

#### **Error**: `ValueError: Training period too short`
**Solution**:
```python
cfg.train_years = 3  # Increase training period
```

### **Data Errors**

#### **Error**: `FileNotFoundError: Excel file not found`
**Solutions**:
```bash
# Check file exists
ls -la *.xlsx

# Use absolute path
python bcoefficient_production_level_code_patched.py --excel "C:\full\path\to\MXUS_Data.xlsx"

# Check current directory
pwd
```

#### **Error**: `ValueError: No valid data columns found`
**Solutions**:
```python
# Debug Excel file structure
import pandas as pd
df = pd.read_excel("your_file.xlsx", sheet_name=None)  # Read all sheets
for sheet_name, data in df.items():
    print(f"Sheet: {sheet_name}")
    print(f"Columns: {list(data.columns)}")
    print(f"Shape: {data.shape}")
    print("---")
```

#### **Error**: `ValueError: No valid dates found in data`
**Solutions**:
```python
# Check date column format
df = pd.read_excel("your_file.xlsx")
print("Date column info:")
print(df.iloc[:, 0].head())  # First column should be dates
print(f"Data type: {df.iloc[:, 0].dtype}")

# Try different date parsing
df.iloc[:, 0] = pd.to_datetime(df.iloc[:, 0], errors='coerce')
```

### **Runtime Errors**

#### **Error**: `RuntimeError: No usable tickers for horizon X`
**Solutions**:
```python
# Relax quality gates
cfg.r2_min = 0.001
cfg.p_value_max = 0.20

# Check data availability
import pandas as pd
df = pd.read_excel("your_file.xlsx")
print(f"Data completeness: {(1 - df.isnull().mean()).describe()}")
```

#### **Error**: `MemoryError: Unable to allocate array`
**Solutions**:
```python
# Reduce universe size
tickers = tickers[:100]  # Process only first 100

# Increase stride to reduce data density
cfg.stride_days = 5

# Disable charts
cfg.make_charts = False

# Run garbage collection more frequently
import gc
gc.collect()
```

### **Output Errors**

#### **Error**: `KeyError: 'beta_pred'`
**Solutions**:
```python
# Check if predictions were generated
df = pd.read_csv("outputs/betas_20d.csv")
print("Available columns:", df.columns.tolist())

# If empty, check logs
with open("outputs/logs/run.log", "r") as f:
    logs = f.read()
    if "kept_rows" in logs:
        print("Quality gate pass rates found in logs")
    else:
        print("No predictions generated - check quality gates")
```

---

## 📊 **Performance Debugging**

### **Low Coverage Issues**

#### **Symptom**: Less than 5% of predictions generated
**Diagnosis**:
```python
# Check quality gate pass rates
with open("outputs/logs/run.log", "r") as f:
    for line in f:
        if "Pass rates" in line:
            print(line.strip())
```

**Solutions**:
```python
# Progressive relaxation
configs_to_try = [
    Config(r2_min=0.005, p_value_max=0.10),    # Moderate relaxation
    Config(r2_min=0.001, p_value_max=0.15),    # Significant relaxation  
    Config(r2_min=0.0005, p_value_max=0.20),   # Maximum relaxation
]

for cfg in configs_to_try:
    run_pipeline(cfg, log)
    # Check coverage after each attempt
```

### **Poor Accuracy Issues**

#### **Symptom**: Directional accuracy below 55%
**Diagnosis**:
```python
# Load evaluation results
eval_df = pd.read_csv("outputs/forecast_eval_20d.csv")

# Check prediction distribution
print("Prediction statistics:")
print(eval_df['beta_pred'].describe())

# Check for systematic bias
bias = (eval_df['beta_pred'] - eval_df['beta_true']).mean()
print(f"Systematic bias: {bias:.4f}")

# Check by market regime
eval_df['high_vol'] = eval_df['date'].apply(lambda x: check_high_volatility_period(x))
print("Accuracy by regime:")
print(eval_df.groupby('high_vol')['directional_accuracy'].mean())
```

**Solutions**:
```python
# Increase regularization to reduce overfitting
cfg.ridge_alphas = [1.0, 5.0, 10.0]  # Higher alpha values

# Extend training period for more stable estimates
cfg.train_years = 4

# Focus on longer horizons (less noise)
cfg.horizons = [10, 20]

# Add more features or remove noisy features
# (requires code modification)
```

### **Memory Usage Issues**

#### **Symptom**: Out of memory errors or very slow execution
**Diagnosis**:
```python
import psutil

def monitor_memory():
    process = psutil.Process()
    memory_mb = process.memory_info().rss / 1024 / 1024
    return f"{memory_mb:.1f} MB"

print(f"Current memory: {monitor_memory()}")

# Check data size
import pandas as pd
df = pd.read_excel("your_file.xlsx")
print(f"Data shape: {df.shape}")
print(f"Memory usage: {df.memory_usage(deep=True).sum() / 1024**2:.1f} MB")
```

**Solutions**:
```python
# Process in chunks
chunk_size = 50
tickers = df.columns[1:]  # Exclude date column
for i in range(0, len(tickers), chunk_size):
    ticker_chunk = tickers[i:i+chunk_size] 
    process_ticker_chunk(ticker_chunk)

# Reduce data density
cfg.stride_days = 5  # Process every 5th day instead of every day

# Use smaller data types
df = df.astype('float32')  # Instead of float64
```

---

## 🚀 **Optimization Tips**

### **Speed Optimization**
```python
# Development configuration (fast)
fast_config = Config(
    horizons=[20],              # Single horizon
    train_years=2,              # Shorter training
    stride_days=5,              # Less dense sampling
    make_charts=False,          # No visualization
    ridge_alphas=[1.0],         # Single regularization parameter
)

# Profile to find bottlenecks
import cProfile
cProfile.run('run_pipeline(cfg, log)', 'profile.prof')
```

### **Quality Optimization**
```python
# High-quality configuration (slower but better results)
quality_config = Config(
    r2_min=0.02,                # Stricter R² requirement
    p_value_max=0.01,           # Higher statistical confidence
    min_obs=40,                 # More data required
    train_years=4,              # Longer training period
    ridge_alphas=[0.1, 1.0, 10.0, 100.0],  # More regularization options
)
```

### **Coverage Optimization**
```python
# Maximum coverage configuration
coverage_config = Config(
    r2_min=0.0005,              # Very permissive
    p_value_max=0.25,           # Very relaxed significance
    hi_vol_relax=30,            # Maximum volatility adaptation
    min_obs=15,                 # Minimum data requirement
)
```

---

## 📈 **Monitoring and Maintenance**

### **Daily Health Checks**
```python
def daily_health_check():
    """Run daily health check and report status"""
    
    checks = {}
    
    # 1. Check output files exist
    expected_files = [f"outputs/betas_{h}d.csv" for h in [1,2,5,10,20]]
    checks['files_exist'] = all(Path(f).exists() for f in expected_files)
    
    # 2. Check recent predictions
    latest_file = "outputs/latest_beta_forecasts.csv"
    if Path(latest_file).exists():
        df = pd.read_csv(latest_file)
        checks['has_predictions'] = len(df) > 0
        checks['has_actions'] = (df['action'] != 'hold').any()
    else:
        checks['has_predictions'] = False
        checks['has_actions'] = False
    
    # 3. Check log for errors
    log_file = "outputs/logs/run.log"
    if Path(log_file).exists():
        with open(log_file, 'r') as f:
            log_content = f.read()
            checks['no_errors'] = 'ERROR' not in log_content
            checks['completed_successfully'] = 'PIPELINE COMPLETED' in log_content
    else:
        checks['no_errors'] = False
        checks['completed_successfully'] = False
    
    # Report status
    all_good = all(checks.values())
    status = "HEALTHY" if all_good else "ISSUES DETECTED"
    
    print(f"Pipeline Status: {status}")
    for check, result in checks.items():
        status_icon = "✅" if result else "❌"
        print(f"  {status_icon} {check}: {result}")
    
    return all_good

# Run daily
if __name__ == "__main__":
    daily_health_check()
```

### **Performance Monitoring**
```python
def monitor_performance_trends():
    """Track performance metrics over time"""
    
    # Load recent metrics
    metrics_files = list(Path("outputs").glob("metrics_*d.csv"))
    
    for metrics_file in metrics_files:
        horizon = metrics_file.stem.split('_')[1]  # Extract horizon
        df = pd.read_csv(metrics_file)
        
        if len(df) > 0:
            print(f"\nHorizon {horizon} Performance:")
            print(f"  Directional Accuracy: {df['directional_accuracy'].iloc[0]:.1%}")
            print(f"  Precision@Action: {df['precision_at_action'].iloc[0]:.1%}")
            print(f"  Coverage: {df['coverage_rate'].iloc[0]:.1%}")
            print(f"  Band Coverage: {df['coverage_90pct'].iloc[0]:.1%}")

# Run weekly
monitor_performance_trends()
```

---

## 📞 **Getting Help**

### **Self-Diagnosis Steps**
1. **Run function tests**: `python test_functions.py`
2. **Check logs**: Review `outputs/logs/run.log`
3. **Validate configuration**: Ensure all Config parameters are reasonable
4. **Check data quality**: Verify Excel file format and content
5. **Test with minimal config**: Use development configuration first

### **When to Contact Support**
- All function tests fail
- Pipeline consistently produces no predictions despite relaxed gates
- Memory usage exceeds available system RAM
- Runtime exceeds expected benchmarks by >5x
- Statistical results seem implausible (all βs > 3 or all < -3)

### **Information to Include in Support Requests**
```python
# Run this diagnostic and include output
print("=== DIAGNOSTIC INFORMATION ===")
print(f"Python version: {sys.version}")
print(f"Working directory: {os.getcwd()}")
print(f"Data file exists: {Path('MXUS_Data*.xlsx').exists()}")

# Package versions
import pandas as pd, numpy as np, sklearn
print(f"Pandas: {pd.__version__}")
print(f"NumPy: {np.__version__}")
print(f"Scikit-learn: {sklearn.__version__}")

# System info
import psutil
memory_gb = psutil.virtual_memory().total / (1024**3)
print(f"Total RAM: {memory_gb:.1f} GB")

# Recent error logs (last 20 lines)
log_file = "outputs/logs/run.log"
if Path(log_file).exists():
    with open(log_file, 'r') as f:
        lines = f.readlines()
        print("\n=== RECENT LOG ENTRIES ===")
        for line in lines[-20:]:
            print(line.strip())
```

---

**Document Version**: 1.0  
**Last Updated**: October 14, 2025  
**Target Audience**: All users (technical and non-technical)  
**Emergency Contact**: Development team lead