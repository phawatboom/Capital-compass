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
