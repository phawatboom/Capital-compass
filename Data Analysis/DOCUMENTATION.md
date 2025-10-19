# β-Forecasting Pipeline Documentation
## Complete Technical Guide for Development Team

---

## 📋 **Table of Contents**
1. [Executive Summary](#executive-summary)
2. [Architecture Overview](#architecture-overview)
3. [Statistical Foundation](#statistical-foundation)
4. [Code Structure](#code-structure)
5. [Configuration Guide](#configuration-guide)
6. [Running the Pipeline](#running-the-pipeline)
7. [Output Files](#output-files)
8. [Quality Gates & Thresholds](#quality-gates--thresholds)
9. [Business Logic](#business-logic)
10. [Troubleshooting](#troubleshooting)
11. [Development Guide](#development-guide)

---

## 🎯 **Executive Summary**

The β-forecasting pipeline predicts stock beta coefficients 1-20 days ahead using only historical price data. It provides fund managers with:
- **Directional guidance**: Should I chase momentum or fade it?
- **Risk management**: How will this stock behave relative to the market?
- **Confidence quantification**: How certain are these predictions?

**Key Features:**
- ✅ Self-contained (no external market data required)
- ✅ Statistically rigorous with adaptive quality gates
- ✅ Production-ready with comprehensive monitoring
- ✅ Business-aligned action recommendations

---

## 🏗️ **Architecture Overview**

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────────┐
│   Excel Data   │───▶│ Feature Engineer │───▶│   Quality Gates     │
│  (Price Only)  │    │  (13 Features)   │    │ (R²/P-val/Regime)   │
└─────────────────┘    └──────────────────┘    └─────────────────────┘
                                                           │
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────────┐
│ Client Actions  │◀───│  Ridge Regression │◀───│  Walk-Forward CV    │
│ (Chase/Fade)    │    │  + Conformal CI   │    │   (Time Series)     │
└─────────────────┘    └──────────────────┘    └─────────────────────┘
```

### **Pipeline Stages:**
1. **Data Loading**: Robust Excel parsing with error handling
2. **Feature Engineering**: 13 price-only technical indicators
3. **Quality Gating**: Multi-layer statistical validation
4. **Model Training**: Ridge regression with time-series CV
5. **Prediction**: Out-of-sample forecasts with uncertainty
6. **Action Generation**: Chase/Fade/Hold recommendations

---

## 📊 **Statistical Foundation**

### **Beta Estimation**
```python
# Core relationship: Predict future β from current returns
y[t] = r[t+horizon]  # Future return (target)
x[t] = r[t]          # Current return (predictor)
β[t] = Cov(x,y) / Var(x)  # Rolling beta coefficient
```

**Key Insight**: We predict how a stock's future market sensitivity will change based on current behavior patterns.

### **Feature Engineering (13 Features)**
| Category | Features | Purpose |
|----------|----------|---------|
| **Momentum** | `LAG_BETA_1`, `MOM_30`, `MOM_PCTL_30` | Trend persistence |
| **Volatility** | `VOL_30`, `VOL_PCTL_30`, `DD_60`, `HL_RANGE_252` | Risk regime detection |
| **Mean Reversion** | `PRICE_Z20`, `AR1_20` | Contrarian signals |
| **Quality** | `R2_60` | Model reliability |
| **Regime** | `XSEC_DISP_30`, `SKEW_20`, `KURT_20` | Market condition |

### **Quality Gates (Sequential)**
1. **Sample Size**: `n >= min_obs` (basic data availability)
2. **Information**: `Sxx >= sxx_min` (regressor variability)  
3. **Fit Quality**: `R² >= r2_min` (explanatory power)
4. **Significance**: `p-value <= p_max` (statistical confidence)
5. **Adaptive Relaxation**: Fallback when coverage too low

### **Horizon-Adaptive Thresholds**
```python
# Shorter horizons = more noise = relaxed standards
H=1d:  r2_min=0.001, p_max=0.25  # Very permissive
H=5d:  r2_min=0.005, p_max=0.15  # Moderate
H=20d: r2_min=0.010, p_max=0.05  # Stricter
```

---

## 🔧 **Code Structure**

### **Main Components**

```python
# Core Configuration
@dataclass Config:
    # Quality gates
    r2_min: float = 0.01              # R² threshold
    p_value_max: float = 0.05         # Statistical significance
    sxx_min: float = 1e-8             # Information threshold
    hi_vol_relax: int = 15            # Regime adaptation
    
    # Operational parameters  
    horizons: List[int] = [1,2,5,10,20]  # Forecast horizons
    beta_window: int = 60              # Rolling window size
    train_years: int = 3               # Walk-forward training
    val_years: int = 1                 # Validation period
```

### **Key Functions**

#### 1. **Data Pipeline**
```python
def load_returns_wide(excel_path, sheet_name) -> pd.DataFrame:
    """Load and clean return data with robust error handling"""
    
def build_feature_panel_for_horizon(wide, horizon, cfg) -> pd.DataFrame:
    """Generate features and apply quality gates for specific horizon"""
```

#### 2. **Statistical Core**
```python
def _rolling_ols_xy(x, y, window, min_obs) -> Tuple[arrays]:
    """Vectorized rolling OLS with p-value calculation"""
    
def rolling_beta_stats(ret, horizon, window, min_obs, stride) -> pd.DataFrame:
    """Calculate rolling beta statistics for given horizon"""
```

#### 3. **Model & Prediction**
```python
def fit_ridge_with_cv(X, y, dates, cfg) -> Pipeline:
    """Ridge regression with time-series cross-validation"""
    
def conformal_band_pooled(residuals_list, alpha=0.10) -> float:
    """Pooled conformal prediction bands for uncertainty"""
```

#### 4. **Business Logic**
```python
def unified_action_rule(row) -> Tuple[str, str]:
    """Generate Chase/Fade/Hold recommendations with reasons"""
    
def write_client_summary_20d(out_dir, filename):
    """Create executive summary with actionable insights"""
```

### **Execution Flow**
```python
def run_pipeline(cfg: Config, log: logging.Logger):
    """Master orchestrator function"""
    1. Load and validate data
    2. For each horizon:
       a. Build features with quality gates
       b. Run walk-forward cross-validation
       c. Generate predictions with confidence bands
       d. Calculate comprehensive metrics
    3. Generate client summary and charts
    4. Log configuration impact
```

---

## ⚙️ **Configuration Guide**

### **Quality Gate Configuration**
```python
# Conservative (higher quality, lower coverage)
Config(
    r2_min=0.05,           # Stricter R² requirement
    p_value_max=0.01,      # 99% confidence required
    hi_vol_relax=5,        # Less regime adaptation
)

# Aggressive (lower quality, higher coverage)  
Config(
    r2_min=0.001,          # Very permissive R²
    p_value_max=0.10,      # 90% confidence OK
    hi_vol_relax=20,       # More regime adaptation
)

# Production (balanced - current default)
Config(
    r2_min=0.01,           # Moderate R² requirement
    p_value_max=0.05,      # 95% confidence
    hi_vol_relax=15,       # Balanced adaptation
)
```

### **Operational Parameters**
```python
# Fast development run
Config(
    horizons=[5, 20],      # Limited horizons
    train_years=2,         # Shorter training
    stride_days=5,         # Skip more days
    make_charts=False,     # No visualization
)

# Full production run
Config(
    horizons=[1,2,5,10,20], # All horizons
    train_years=3,          # Full training
    stride_days=2,          # Dense sampling
    make_charts=True,       # Full visualization
)
```

---

## 🚀 **Running the Pipeline**

### **Command Line Interface**
```bash
# Basic run with defaults
python bcoefficient_production_level_code_patched.py

# Custom configuration
python bcoefficient_production_level_code_patched.py \
    --excel "MXUS_Data_2024.xlsx" \
    --sheet "Returns" \
    --out-dir "./results_2024" \
    --horizons 1 5 20 \
    --r2-gate 0.005 \
    --p-value-max 0.10

# Quick development run
python bcoefficient_production_level_code_patched.py \
    --horizons 20 \
    --no-charts \
    --train-years 2
```

### **Programmatic Usage**
```python
from bcoefficient_production_level_code_patched import run_pipeline, Config, setup_logger

# Custom configuration
cfg = Config(
    excel_path=Path("data/MXUS_Data.xlsx"),
    out_dir=Path("./results"),
    horizons=[5, 10, 20],
    r2_min=0.005,
    p_value_max=0.10
)

# Run pipeline
log = setup_logger(cfg.out_dir)
run_pipeline(cfg, log)
```

### **Expected Runtime**
- **Small universe** (50 stocks): ~2-5 minutes
- **Medium universe** (200 stocks): ~10-20 minutes  
- **Large universe** (500+ stocks): ~30-60 minutes

**Memory usage**: ~50-200MB depending on universe size

---

## 📁 **Output Files**

### **Core Prediction Files**
```
outputs/
├── betas_1d.csv          # 1-day horizon predictions
├── betas_2d.csv          # 2-day horizon predictions  
├── betas_5d.csv          # 5-day horizon predictions
├── betas_10d.csv         # 10-day horizon predictions
├── betas_20d.csv         # 20-day horizon predictions
```

**File Structure:**
```csv
Date,ticker,beta_realised,beta_pred,lo,hi,r2_ols,p_value
2024-01-15,AAPL,1.23,1.18,0.95,1.41,0.045,0.032
2024-01-15,MSFT,0.87,0.92,0.71,1.13,0.038,0.048
```

### **Evaluation & Metrics**
```
outputs/
├── forecast_eval_1d.csv   # Out-of-sample validation results
├── forecast_eval_2d.csv   # Contains: Date, ticker, beta_pred, beta_true, band
├── ...
├── metrics_1d.csv         # Overall performance metrics
├── metrics_2d.csv         # Contains: directional_accuracy, mae, rmse, etc.
├── ...
├── metrics_1d_folds.csv   # Fold-by-fold performance
├── metrics_1d_per_ticker.csv  # Per-stock performance
```

### **Model Interpretability**
```
outputs/
├── feature_coefs_1d.csv   # Ridge regression coefficients
├── feature_coefs_2d.csv   # Shows feature importance by horizon
├── ...
```

### **Client Deliverables**
```
outputs/
├── latest_beta_forecasts.csv  # Executive summary (H=20d)
├── pipeline_configuration_summary.csv  # Run configuration record
```

**Client Summary Structure:**
```csv
ticker,beta_pred,beta_pred_ema,confidence_level,action,hold_reason
AAPL,1.18,1.15,"High (p≤1%)","chase","all_checks_passed"
MSFT,0.92,0.89,"Medium (p≤5%)","hold","low_confidence"
```

### **Visualization**
```
outputs/charts/
├── AAPL/
│   ├── beta_history_1d.png    # Historical vs predicted β
│   ├── beta_history_2d.png
│   ├── ...
│   └── term_structure.png     # β across horizons
├── feature_importance_1d.png  # Feature coefficients
├── ...
```

### **Logs & Monitoring**
```
outputs/logs/
└── run.log                    # Complete execution log
```

**Log Content:**
```
2024-10-14 14:35:22 | INFO | 🚀 β-FORECASTING PIPELINE STARTING
2024-10-14 14:35:22 | INFO | [Master Config] Quality Gate Configuration:
2024-10-14 14:35:22 | INFO |   • Base R² threshold: 0.010000 (floor: 0.020)
...
2024-10-14 14:45:18 | INFO | [Metrics H=20d] Directional accuracy: 67.3%
```

---

## 🚪 **Quality Gates & Thresholds**

### **Gate Hierarchy (Applied Sequentially)**

#### **1. Sample Size Gate**
```python
n_min = cfg.min_obs  # Default: 25
# High volatility relaxation
n_min_dynamic = max(10, n_min - cfg.hi_vol_relax)  # Can go down to 10
```
**Purpose**: Ensure sufficient data for reliable estimation
**Business impact**: Prevents predictions based on too few observations

#### **2. Information Gate** 
```python
sxx_gate = stats["sxx_d"] >= cfg.sxx_min  # Default: 1e-8
```
**Purpose**: Require minimum variability in predictor (stock returns)
**Business impact**: Avoids β estimates for stocks that barely moved

#### **3. R² Gate (Dynamic)**
```python
r2_floor = stats["r2"].rolling(21).quantile(cfg.r2_pctl_floor)  # Adaptive
r2_gate = stats["r2"] >= max(r2_min, r2_floor)
```
**Purpose**: Ensure model explains meaningful variance
**Business impact**: Filters out predictions with poor explanatory power

#### **4. P-value Gate (Regime-Aware)**
```python
p_max_dynamic = p_value_max * (relax_factor if high_volatility else 1.0)
p_gate = stats["p_value"] <= p_max_dynamic
```
**Purpose**: Statistical significance validation
**Business impact**: Ensures predictions aren't just noise

#### **5. Adaptive Relaxation**
```python
if total_predictions < minimum_required:
    # Progressive relaxation: 2x, 5x, 10x, 20x
    for relax_factor in [2, 5, 10, 20]:
        # Apply relaxed thresholds
        if sufficient_coverage: break
```
**Purpose**: Ensure actionable coverage during difficult periods
**Business impact**: Provides guidance when needed most

### **Threshold Interpretation**

| Threshold | Conservative | Balanced (Default) | Aggressive |
|-----------|--------------|-------------------|------------|
| `r2_min` | 0.05 | 0.01 | 0.001 |
| `p_value_max` | 0.01 | 0.05 | 0.10 |
| `hi_vol_relax` | 5 | 15 | 25 |
| **Coverage** | ~5-10% | ~15-25% | ~30-50% |
| **Quality** | Very High | High | Medium |

---

## 💼 **Business Logic**

### **Action Rule Engine**

```python
def unified_action_rule(row) -> Tuple[str, str]:
    """
    Decision hierarchy (checked in order):
    1. Data quality (R², p-value)
    2. Confidence (band width)  
    3. Horizon agreement (consistency)
    4. Signal strength (|β| > threshold)
    """
```

#### **Decision Tree:**
```
1. R² < 0.01? → HOLD (low_r2)
2. p-value > 0.05? → HOLD (not_significant)  
3. Confidence < 60%? → HOLD (low_confidence)
4. Horizons disagree? → HOLD (horizon_disagreement)
5. Term structure unstable? → HOLD (term_unstable)
6. |β| ≤ 0.05? → HOLD (weak_signal)
7. β > 0.05? → CHASE (all_checks_passed)
8. β < -0.05? → FADE (all_checks_passed)
```

### **Confidence Tier System**
| Tier | R² | P-value | Business Meaning |
|------|----|---------|--------------------|
| **Very High** | ≥0.10 | ≤0.01 | High conviction trades |
| **High** | ≥0.05 | ≤0.05 | Standard position sizing |
| **Medium** | ≥0.02 | ≤0.10 | Reduced position size |
| **Low** | ≥0.01 | ≤0.20 | Watch list only |
| **Very Low** | <0.01 | >0.20 | No action |

### **Fund Manager Applications**

#### **Position Sizing**
```python
# Traditional approach
position_size = target_risk / (price * historical_beta * market_vol)

# Enhanced approach  
position_size = target_risk / (price * predicted_beta * market_vol * confidence_adj)
```

#### **Portfolio Rebalancing**
```python
# Trigger rebalancing when:
# 1. Predicted β significantly different from target
# 2. High confidence in prediction (avoid noise)
# 3. Horizon agreement (consistent signal)

rebalance_flag = (
    abs(predicted_beta - target_beta) > threshold AND
    confidence_tier in ["High", "Very High"] AND  
    horizon_agreement == True
)
```

#### **Risk Management**
```python
# Stress test using predicted βs
stressed_portfolio_beta = sum(
    weight[i] * predicted_beta[i] for i in positions
)

# Adjust hedge ratio
hedge_ratio = stressed_portfolio_beta * hedge_efficiency
```

---

## 🔧 **Troubleshooting**

### **Common Issues**

#### **1. Low Coverage (<10% predictions)**
**Symptoms**: Very few predictions generated
**Causes**: 
- Thresholds too strict for data quality
- Market regime change (high volatility)
- Data issues (missing returns, short history)

**Solutions**:
```python
# Relax thresholds
cfg.r2_min = 0.001      # From 0.01  
cfg.p_value_max = 0.15  # From 0.05
cfg.hi_vol_relax = 25   # From 15

# Or check data quality
data.isnull().sum()     # Missing data
data.std().describe()   # Volatility distribution
```

#### **2. Poor Directional Accuracy (<55%)**
**Symptoms**: Model predictions wrong direction frequently
**Causes**:
- Overfitting to noise
- Feature engineering issues  
- Wrong horizon for market regime

**Solutions**:
```python
# Increase ridge regularization
cfg.ridge_alphas = [1.0, 2.0, 5.0]  # Higher penalties

# Extend training period
cfg.train_years = 4     # More stable estimates

# Focus on longer horizons
cfg.horizons = [10, 20] # Less noise
```

#### **3. Memory Issues**
**Symptoms**: Out of memory errors, slow execution
**Causes**: Large universe (>500 stocks), long history

**Solutions**:
```python
# Reduce universe size for testing
tickers = tickers[:100]  

# Increase stride to reduce density
cfg.stride_days = 5     # Skip more days

# Disable charts for large runs
cfg.make_charts = False
```

#### **4. Model Not Updating**
**Symptoms**: Predictions seem stale
**Causes**: Caching, wrong date parsing, stride issues

**Solutions**:
```python
# Check date parsing
print(df["Date"].dtypes)    # Should be datetime64
print(df["Date"].min(), df["Date"].max())  # Range check

# Verify stride logic
print(f"Stride: {cfg.stride_days}, Total dates: {len(dates)}")
print(f"Effective dates: {len(dates) // cfg.stride_days}")
```

### **Error Messages**

#### **Configuration Errors**
```
ValueError: beta_window (20) must be >= min_obs (25)
→ Fix: cfg.beta_window = 60  # Increase window size

ValueError: horizons list cannot be empty  
→ Fix: cfg.horizons = [1, 5, 20]  # Set valid horizons

ValueError: Training period too short relative to beta estimation window
→ Fix: cfg.train_years = 3  # Increase training period
```

#### **Data Errors**
```
FileNotFoundError: Excel file not found
→ Fix: Place MXUS_Data*.xlsx in working directory or use --excel path

ValueError: No valid data columns found
→ Fix: Check Excel sheet has numeric return data

ValueError: No valid dates found in data  
→ Fix: Ensure Date column is properly formatted
```

#### **Runtime Errors**
```
RuntimeError: No usable tickers for horizon X
→ Fix: Relax quality gates or check data availability for that horizon

MemoryError: Unable to allocate array
→ Fix: Reduce universe size or increase system memory
```

### **Performance Monitoring**

#### **Log Analysis**
```python
# Check coverage by horizon
grep "kept_rows" outputs/logs/run.log

# Monitor quality gate pass rates  
grep "Pass rates" outputs/logs/run.log

# Track relaxation triggers
grep "Relaxation" outputs/logs/run.log
```

#### **Metrics Validation**
```python
# Load metrics for analysis
metrics = pd.read_csv("outputs/metrics_20d.csv")
print(f"Directional accuracy: {metrics['directional_accuracy'].iloc[0]:.1%}")
print(f"Precision@action: {metrics['precision_at_action'].iloc[0]:.1%}")

# Check per-ticker performance
per_ticker = pd.read_csv("outputs/metrics_20d_per_ticker.csv")
print(per_ticker.sort_values('directional_accuracy', ascending=False).head())
```

---

## 🚀 **Development Guide**

### **Setting Up Development Environment**

```bash
# Install dependencies
pip install pandas numpy scikit-learn scipy matplotlib openpyxl

# Clone and setup
git clone <repository>
cd capstone-project-s2-2025-team-11/Data\ Analysis/

# Run tests
python test_functions.py

# Run code review
python code_review_diagnostic.py
```

### **Making Changes**

#### **1. Adding New Features**
```python
# In build_feature_panel_for_horizon()
# Add new feature calculation
NEW_FEATURE_mat = df_w.rolling(window).apply(your_function)

# Add to features DataFrame
feats = pd.DataFrame({
    # ... existing features ...
    "NEW_FEATURE": NEW_FEATURE_mat[tkr],
})

# Update FEATURES list at top of file
FEATURES = [
    "LAG_BETA_1", "R2_60",
    # ... existing features ...
    "NEW_FEATURE",  # Add here
]
```

#### **2. Modifying Quality Gates**
```python
# In build_feature_panel_for_horizon()
# Add new gate logic
new_gate = your_condition_here
gate_ok = (stats["ok"].to_numpy() & 
          r2_gate.to_numpy() & 
          p_gate & 
          new_gate &  # Add here
          ok_info)
```

#### **3. Adding New Metrics**
```python
# In run_for_horizon() evaluation section
overall_metrics.update({
    "your_new_metric": calculate_your_metric(eval_df),
})
```

### **Testing Changes**

#### **Unit Tests**
```python
# Add to test_functions.py
def test_your_new_feature():
    """Test your new feature calculation"""
    # Your test logic here
    assert expected_result == actual_result
```

#### **Integration Tests**  
```python
# Quick pipeline test with small dataset
cfg = Config(
    horizons=[20],          # Single horizon
    train_years=1,          # Short training
    make_charts=False,      # No visualization
)
run_pipeline(cfg, log)
```

#### **Performance Testing**
```python
import time
start_time = time.time()
run_pipeline(cfg, log)
runtime = time.time() - start_time
print(f"Runtime: {runtime:.1f} seconds")
```

### **Code Quality Standards**

#### **Docstrings**
```python
def your_function(param1: type, param2: type) -> return_type:
    """
    Brief description of what function does.
    
    Args:
        param1: Description of first parameter
        param2: Description of second parameter
        
    Returns:
        Description of return value
        
    Raises:
        ValueError: When validation fails
    """
```

#### **Error Handling**
```python
try:
    risky_operation()
except SpecificError as e:
    log.warning(f"Expected error occurred: {e}")
    # Handle gracefully
except Exception as e:
    log.error(f"Unexpected error: {e}")
    raise  # Re-raise for debugging
```

#### **Logging**
```python
# Use structured logging
log.info(f"[Component] Operation: metric={value:.3f} | status=success")

# Include context for debugging  
log.debug(f"Processing ticker {ticker}: {len(data)} observations")

# Log configuration impact
log.info(f"[Config] threshold={threshold:.6f} → coverage={coverage:.1%}")
```

### **Performance Optimization**

#### **Vectorization**
```python
# Instead of loops
result = []
for i in range(len(data)):
    result.append(calculate_something(data[i]))

# Use vectorized operations
result = data.apply(calculate_something)
# or
result = np.vectorize(calculate_something)(data)
```

#### **Memory Management**
```python
# For large datasets, process in chunks
chunk_size = 1000
for i in range(0, len(data), chunk_size):
    chunk = data[i:i+chunk_size]
    process_chunk(chunk)
    
# Clean up temporary variables
del large_temporary_array
```

#### **Caching**
```python
from functools import lru_cache

@lru_cache(maxsize=128)
def expensive_calculation(param):
    """Cache results of expensive calculations"""
    return complex_computation(param)
```

---

## 📚 **Additional Resources**

### **Statistical References**
- **Conformal Prediction**: Shafer & Vovk (2008) - "A Tutorial on Conformal Prediction" 
- **Rolling Regression**: Harvey (1990) - "Econometric Analysis of Time Series"
- **Beta Estimation**: Fama & French (1992) - "The Cross-Section of Expected Stock Returns"

### **Code References**
- **Scikit-learn**: `Ridge`, `TimeSeriesSplit`, `StandardScaler`
- **Pandas**: `rolling()`, `ewm()`, `groupby()` operations
- **NumPy**: Vectorized statistical calculations

### **Business References**
- **Risk Management**: Jorion (2006) - "Value at Risk" 
- **Portfolio Theory**: Markowitz (1952) - "Portfolio Selection"
- **Factor Models**: Fama & French (2015) - "A Five-Factor Asset Pricing Model"

---

## 📞 **Support & Contact**

### **For Technical Issues**
1. Check logs: `outputs/logs/run.log`
2. Run diagnostics: `python code_review_diagnostic.py`
3. Validate functions: `python test_functions.py`

### **For Statistical Questions**
- Review statistical foundation section
- Check configuration impact in logs
- Validate against academic literature

### **For Business Logic**
- Review action rule engine
- Check client summary outputs
- Validate against fund management practices

---

**Document Version**: 1.0  
**Last Updated**: October 14, 2025  
**Pipeline Version**: Production-ready with comprehensive evaluation  
**Status**: ✅ Validated and tested