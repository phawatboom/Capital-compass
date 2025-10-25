/**
 * Type definitions for Capital Compass API
 * Mock data structure matching the backend specification
 */

export interface Upload {
  upload_id: string
  original_filename: string
  row_count: number
  status: "queued" | "processing" | "failed" | "done"
  error_text?: string
  created_at: string
  completed_at?: string
}

// Model type enumeration
export type ModelType = "mean-reversion" | "beta-forecasting"

// NEW: Unified analysis result that supports both model types
export interface UnifiedAnalysisResult {
  analysis_id: string
  model_type: ModelType
  ticker: string
  name?: string
  analysis_date: string
  
  // Common fields across both models
  recommendation: "BUY" | "SELL" | "HOLD"
  confidence: number  // 0-1 scale
  signal_strength: "Strong" | "Moderate" | "Weak"
  
  // Model-specific data (discriminated union)
  model_data: MeanReversionResult | BetaForecastResult
}

// Mean-Reversion Model Results (Legacy)
export interface MeanReversionResult {
  model_type: "mean-reversion"
  horizons: Array<{
    days: number
    probability: number  // Mean reversion probability
    expected_move: number
    confidence_interval: [number, number]
    label: "mean-reverting" | "trending" | "neutral"
  }>
  current_analysis: {
    zscore: number
    zscore_interpretation: string
    serial_correlation: number
    volatility: number
    cluster_id?: string
    market_percentile?: number
  }
  series_data: Array<{
    date: string
    price: number
    zscore?: number
    prediction?: number
    actual_move?: number
  }>
}

// Beta-Forecasting Model Results (Enhanced)
export interface BetaForecastResult {
  model_type: "beta-forecasting"
  latest_forecast: {
    Date: string
    ticker: string
    beta_pred: number
    beta_pred_ema?: number
    lo: number  // Lower confidence bound
    hi: number  // Upper confidence bound
    r2_ols: number
    p_value: number
    confidence_level: "High (p≤1%)" | "Medium (p≤5%)" | "Low (p>5%)"
    confidence_tier: string
    delta_beta_20d: number  // Change vs 1-year median
    conf_20d: number  // Confidence score [0,1]
    agree_adjacent: boolean  // Adjacent horizons agree
    term_unstable: boolean  // Term structure unstable
    action: "chase" | "fade" | "hold"
    hold_reason?: string  // Reason for hold if applicable
  }
  horizons_forecasts: Record<string, {
    beta_pred: number
    confidence: number
    action: "chase" | "fade" | "hold"
  }>  // Multi-horizon forecasts
  historical_performance: Array<{
    date: string
    horizon: string
    beta_pred: number
    beta_realized: number
    accuracy: number
  }>
  confidence_analysis: {
    current_tier: string
    p_value_trend: Array<{
      date: string
      p_value: number
      significance: boolean
    }>
    r2_trend: Array<{
      date: string
      r2: number
      quality: "High" | "Medium" | "Low"
    }>
  }
}

export interface AnalysisListItem {
  analysis_id: string
  ticker: string
  score: number
  label: "mean-reverting" | "trending" | "neutral"
  zscore_lb20: number
  serial_corr30: number
  serial_corr60?: number
  vol_20d: number
  cluster_id: string
  market_pctile: number
  cluster_pctile: number
  ci95_lower: number
  ci95_upper: number
  analysis_date: string
}

export interface AnalysisDetail {
  ticker: string
  name?: string
  analysis_date: string
  lookbacks: number[]
  zscores: Record<string, number>
  zscores_ci95?: Record<string, [number, number]>
  serial_corr: Record<string, number>
  serial_corr_ci95?: Record<string, [number, number]>
  vol: Record<string, number>
  vol_ci95?: Record<string, [number, number]>
  cluster: {
    id: string
    size: number
    label: string
    peers?: string[]
  }
  percentiles: {
    market: number
    cluster: number
  }
  score: number
  score_ci95: [number, number]
  label: "mean-reverting" | "trending" | "neutral"
  series: Array<{
    date: string
    adj_close: number
    ret?: number
    rolling_mean?: number
    zscore_10d?: number
    zscore_20d?: number
    zscore_60d?: number
  }>
  cluster_deviation?: number
  cluster_deviation_ci95?: [number, number]
  historical_percentiles?: Array<{
    date: string
    market_percentile: number
    cluster_percentile: number
  }>
  zscore_distribution?: Array<{
    zscore: number
    count: number
    isCurrentStock?: boolean
  }>
  cluster_comparison?: Array<{
    date: string
    stock_zscore: number
    cluster_avg_zscore: number
    cluster_deviation: number
  }>
  serial_correlation_trend?: Array<{
    date: string
    serial_corr_30d: number
    serial_corr_60d: number
    ci_lower_30d: number
    ci_upper_30d: number
    ci_lower_60d: number
    ci_upper_60d: number
  }>
  volatility_peers?: Array<{
    ticker: string
    volatility: number
    zscore: number
    isCurrentStock: boolean
  }>
}

export interface AnalysisFilters {
  signal?: "BUY" | "SELL" | "HOLD" | "all"
  cluster?: string | "all"
}

export interface ConfidenceInterval {
  value: number
  lower: number
  upper: number
}

export function formatCI(ci: ConfidenceInterval): string {
  return `${ci.value.toFixed(2)} (95% CI: ${ci.lower.toFixed(2)}–${ci.upper.toFixed(2)})`
}

export function getSignalFromScore(score: number): "BUY" | "SELL" | "HOLD" {
  if (score >= 0.7) return "BUY"
  if (score <= 0.3) return "SELL"
  return "HOLD"
}

export function getSignalLabel(signal: "BUY" | "SELL" | "HOLD"): string {
  switch (signal) {
    case "BUY":
      return "Strong Buy"
    case "SELL":
      return "Strong Sell"
    default:
      return "Hold"
  }
}

export function getSignalColor(signal: "BUY" | "SELL" | "HOLD"): string {
  switch (signal) {
    case "BUY":
      return "bg-blue-100 text-blue-800"
    case "SELL":
      return "bg-red-100 text-red-800"
    default:
      return "bg-yellow-100 text-yellow-800"
  }
}

export function getZScoreInterpretation(zscore: number): string {
  if (zscore <= -1.5) return "Very Cheap"
  if (zscore <= -0.5) return "Cheap"
  if (zscore >= 1.5) return "Very Expensive"
  if (zscore >= 0.5) return "Expensive"
  return "Fair Value"
}

export function getSerialCorrInterpretation(corr: number): string {
  if (corr <= -0.2) return "Strong Reversion"
  if (corr <= -0.1) return "Mean Reverting"
  if (corr >= 0.2) return "Strong Trending"
  if (corr >= 0.1) return "Trending"
  return "Neutral"
}

export function getVolatilityInterpretation(vol: number): string {
  if (vol >= 0.03) return "High Risk"
  if (vol >= 0.02) return "Moderate Risk"
  return "Low Risk"
}

export function getPercentileZone(percentile: number): {
  label: string
  color: string
  bgColor: string
} {
  if (percentile <= 0.2) return { label: "Very Cheap", color: "text-blue-800", bgColor: "bg-blue-100" }
  if (percentile <= 0.4) return { label: "Cheap", color: "text-blue-700", bgColor: "bg-blue-50" }
  if (percentile <= 0.6) return { label: "Fair Value", color: "text-gray-700", bgColor: "bg-gray-100" }
  if (percentile <= 0.8) return { label: "Expensive", color: "text-orange-700", bgColor: "bg-orange-50" }
  return { label: "Very Expensive", color: "text-red-800", bgColor: "bg-red-100" }
}

export function getScoreZone(score: number): {
  label: string
  color: string
  bgColor: string
  numeric: string
} {
  if (score >= 0.8)
    return {
      label: "Strong Buy",
      color: "text-blue-800",
      bgColor: "bg-blue-100",
      numeric: "9-10/10",
    }
  if (score >= 0.6)
    return {
      label: "Buy",
      color: "text-blue-700",
      bgColor: "bg-blue-50",
      numeric: "7-8/10",
    }
  if (score >= 0.4)
    return {
      label: "Hold",
      color: "text-gray-700",
      bgColor: "bg-gray-100",
      numeric: "5-6/10",
    }
  if (score >= 0.2)
    return {
      label: "Sell",
      color: "text-red-700",
      bgColor: "bg-red-50",
      numeric: "3-4/10",
    }
  return {
    label: "Strong Sell",
    color: "text-red-800",
    bgColor: "bg-red-100",
    numeric: "1-2/10",
  }
}

// UNIFIED: Model-agnostic helper functions
export function getModelTypeLabel(modelType: ModelType): string {
  switch (modelType) {
    case "mean-reversion":
      return "Mean-Reversion Analysis"
    case "beta-forecasting":
      return "β-Forecasting Analysis"
    default:
      return "Unknown Model"
  }
}

export function getModelTypeDescription(modelType: ModelType): string {
  switch (modelType) {
    case "mean-reversion":
      return "Statistical mean-reversion analysis with Z-score and serial correlation"
    case "beta-forecasting":
      return "Beta coefficient forecasting with confidence intervals and action signals"
    default:
      return ""
  }
}

export function getUnifiedRecommendationColor(recommendation: "BUY" | "SELL" | "HOLD"): string {
  switch (recommendation) {
    case "BUY":
      return "bg-green-100 text-green-800"
    case "SELL":
      return "bg-red-100 text-red-800"
    default:
      return "bg-gray-100 text-gray-800"
  }
}

export function getUnifiedConfidenceColor(confidence: number): string {
  if (confidence >= 0.8) return "text-green-600"
  if (confidence >= 0.6) return "text-yellow-600"
  return "text-red-600"
}

export function getSignalStrengthColor(strength: "Strong" | "Moderate" | "Weak"): string {
  switch (strength) {
    case "Strong":
      return "text-green-600"
    case "Moderate":
      return "text-yellow-600"
    default:
      return "text-red-600"
  }
}

// Mean-Reversion specific helpers
export function getMeanReversionActionFromZScore(zscore: number): "BUY" | "SELL" | "HOLD" {
  if (zscore <= -1.5) return "BUY"  // Very cheap, expect reversion up
  if (zscore >= 1.5) return "SELL"  // Very expensive, expect reversion down
  return "HOLD"
}

// Beta-Forecasting specific helpers
export function getBetaActionColor(action: "chase" | "fade" | "hold"): string {
  switch (action) {
    case "chase":
      return "bg-green-100 text-green-800"
    case "fade":
      return "bg-red-100 text-red-800"
    default:
      return "bg-gray-100 text-gray-800"
  }
}

export function getBetaActionLabel(action: "chase" | "fade" | "hold"): string {
  switch (action) {
    case "chase":
      return "Chase (Long)"
    case "fade":
      return "Fade (Short)"
    default:
      return "Hold"
  }
}

export function getBetaRecommendation(action: "chase" | "fade" | "hold"): "BUY" | "SELL" | "HOLD" {
  switch (action) {
    case "chase":
      return "BUY"
    case "fade":
      return "SELL"
    default:
      return "HOLD"
  }
}

export function formatBetaValue(beta: number): string {
  const sign = beta >= 0 ? "+" : ""
  return `${sign}${beta.toFixed(3)}`
}

export function formatPValue(pValue: number): string {
  if (pValue < 0.001) return "p < 0.001"
  if (pValue < 0.01) return `p = ${pValue.toFixed(3)}`
  return `p = ${pValue.toFixed(2)}`
}

export function getBetaMagnitudeInterpretation(beta: number): string {
  const abs_beta = Math.abs(beta)
  if (abs_beta >= 0.15) return "Very Strong"
  if (abs_beta >= 0.10) return "Strong"
  if (abs_beta >= 0.05) return "Moderate"
  return "Weak"
}

export function getConfidenceInterpretation(confLevel: string): string {
  switch (confLevel) {
    case "High (p≤1%)":
      return "Very Reliable"
    case "Medium (p≤5%)":
      return "Reliable"
    default:
      return "Uncertain"
  }
}

// Model comparison helpers
export function compareModelResults(
  meanRevResult: MeanReversionResult,
  betaResult: BetaForecastResult
): {
  agreement: "Strong" | "Weak" | "Conflicting"
  primary_recommendation: "BUY" | "SELL" | "HOLD"
  confidence_score: number
} {
  const mrRec = getMeanReversionActionFromZScore(meanRevResult.current_analysis.zscore)
  const betaRec = getBetaRecommendation(betaResult.latest_forecast.action)
  
  const agreement = mrRec === betaRec ? "Strong" : "Conflicting"
  const primary_recommendation = betaResult.latest_forecast.conf_20d > 0.6 ? betaRec : mrRec
  const confidence_score = agreement === "Strong" ? 0.8 : 0.4
  
  return { agreement, primary_recommendation, confidence_score }
}
