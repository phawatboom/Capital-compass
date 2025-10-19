# Dual-Model Architecture Implementation

## Overview

This document describes the implementation of a dual-model architecture that supports both:
1. **Mean-Reversion (MR-PROD) Model** - Per-stock, per-date mean-reversion likelihood analysis
2. **β-forecasting Model** - Cross-sectional beta forecasting without market dependency

## Architecture Components

### 1. Machine Learning Models

#### Mean-Reversion Model (`main_model_file_stable_2_extended_future_prediciton.py`)
- **Purpose**: Calculates mean-reversion likelihood scores for individual stocks
- **Output**: Probability scores, conformal magnitude bands, isotonic calibration
- **Features**: Walk-forward backtest, multiple confidence intervals
- **Dependencies**: pandas, numpy, scikit-learn, openpyxl, joblib, matplotlib, tqdm

#### β-forecasting Model (`bcoef_forecast_v_4_no_market.py`)
- **Purpose**: Forecasts beta coefficients using cross-sectional price-only proxies
- **Output**: Beta predictions, conformal prediction intervals, R² metrics
- **Features**: Ridge regression, cross-sectional analysis, no market dependency
- **Dependencies**: pandas, numpy, scikit-learn, matplotlib

### 2. TypeScript Type System

#### Unified Types (`frontend/types/analysis.ts`)
```typescript
// Model selection
export type ModelType = "mean-reversion" | "beta-forecasting"

// Unified result interface
export interface UnifiedAnalysisResult {
  analysis_id: string
  model_type: ModelType
  ticker: string
  name: string
  analysis_date: string
  recommendation: "BUY" | "SELL" | "HOLD"
  confidence: number
  model_data: MeanReversionResult | BetaForecastResult
}
```

#### Model-Specific Interfaces
- `MeanReversionResult`: Z-scores, mean reversion probabilities, magnitude bands
- `BetaForecastResult`: Beta predictions, R² values, conformal intervals, action recommendations

### 3. Frontend API Layer

#### Unified API Functions (`frontend/lib/mockApi.ts`)
- `runUnifiedAnalysis(uploadId, modelType)`: Execute analysis with model selection
- `getUnifiedAnalysis(ticker, modelType)`: Get results for specific ticker and model
- `getAllUnifiedResults(modelType)`: Get all results for a model type
- `compareModels(ticker)`: Compare both models for a single ticker

#### Model Comparison Features
```typescript
export interface ModelComparison {
  mean_reversion: UnifiedAnalysisResult
  beta_forecasting: UnifiedAnalysisResult
  comparison: {
    agreement: "Strong" | "Weak" | "Conflicting"
    primary_recommendation: "BUY" | "SELL" | "HOLD"
    confidence_score: number
  }
}
```

### 4. Mock Data Structure (`frontend/lib/mockData.ts`)

#### Unified Mock Results
```typescript
export const mockUnifiedResults: Record<string, UnifiedAnalysisResult> = {
  "AAPL-MR": { /* Mean-Reversion result for AAPL */ },
  "AAPL-BETAFORECASTING": { /* β-forecasting result for AAPL */ },
  // ... more results
}
```

## Key Features

### 1. Model Selection Flexibility
- Client can choose between Mean-Reversion and β-forecasting models
- Each model optimized for different analysis scenarios
- Unified interface for consistent user experience

### 2. Comparative Analysis
- Side-by-side model comparison for individual stocks
- Agreement/conflict detection between models
- Confidence-weighted primary recommendations

### 3. Backward Compatibility
- Legacy API functions maintained for existing integrations
- Gradual migration path from single-model to dual-model
- Consistent data structures across model types

### 4. Type Safety
- Strong TypeScript typing for all model interfaces
- Compile-time validation of model data structures
- Helper functions for type-safe model operations

## Implementation Benefits

### 1. Client Flexibility
- Choose appropriate model based on market conditions
- Compare different analytical approaches
- Make informed decisions with multiple perspectives

### 2. Technical Robustness
- Unified error handling across models
- Consistent API patterns
- Type-safe development environment

### 3. Scalability
- Easy to add new models following established patterns
- Modular architecture for independent model updates
- Flexible configuration for different deployment scenarios

## Usage Examples

### Model Selection
```typescript
// Run Mean-Reversion analysis
const mrResult = await runUnifiedAnalysis(uploadId, "mean-reversion")

// Run β-forecasting analysis  
const betaResult = await runUnifiedAnalysis(uploadId, "beta-forecasting")

// Compare both models
const comparison = await compareModels("AAPL")
```

### Result Processing
```typescript
// Get model-specific results
const mrData = await getUnifiedAnalysis("AAPL", "mean-reversion")
const betaData = await getUnifiedAnalysis("AAPL", "beta-forecasting")

// Check model type and process accordingly
if (result.model_type === "mean-reversion") {
  const mrResult = result.model_data as MeanReversionResult
  // Process mean-reversion specific data
} else {
  const betaResult = result.model_data as BetaForecastResult
  // Process beta-forecasting specific data
}
```

## Next Steps

1. **Backend Integration**: Update Django models and serializers for dual-model support
2. **Frontend Components**: Modify existing components to handle both model types
3. **Testing**: Comprehensive testing of dual-model workflow
4. **Documentation**: Update user guides for model selection options
5. **Deployment**: Deploy dual-model architecture to production

## Technical Validation

✅ TypeScript compilation successful  
✅ Frontend build successful  
✅ Mock data structure validated  
✅ API functions tested  
✅ Type safety verified  

The dual-model architecture is ready for integration and provides a robust foundation for supporting multiple analytical approaches in the Capital Compass platform.