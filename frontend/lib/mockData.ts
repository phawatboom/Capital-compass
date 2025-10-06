/**
 * Mock data for Capital Compass
 * Matches the API specification structure
 */

import type { Upload, AnalysisListItem, AnalysisDetail } from "@/types/analysis"

// Generate realistic price series with Z-score data
function generatePriceSeriesWithZScore(
  basePrice: number,
  days = 90,
): Array<{
  date: string
  adj_close: number
  ret?: number
  rolling_mean?: number
  zscore_10d?: number
  zscore_20d?: number
  zscore_60d?: number
}> {
  const series = []
  let price = basePrice
  const startDate = new Date()
  startDate.setDate(startDate.getDate() - days)

  // Store prices for rolling calculations
  const prices: number[] = []

  for (let i = 0; i < days; i++) {
    const date = new Date(startDate)
    date.setDate(date.getDate() + i)

    // Generate realistic price movement with some trend and volatility
    const trendComponent = Math.sin(i / 20) * 0.001 // Long-term trend
    const volatilityComponent = (Math.random() - 0.5) * 0.03 // Daily volatility ±1.5%
    const meanReversionComponent = i > 20 ? (prices[i - 1] - price) * 0.001 : 0 // Mean reversion

    const dailyReturn = trendComponent + volatilityComponent + meanReversionComponent
    price = price * (1 + dailyReturn)

    prices.push(price)

    // Calculate rolling means and Z-scores
    let rollingMean20 = price
    let zscore10d = 0
    let zscore20d = 0
    let zscore60d = 0

    if (i >= 19) {
      const last20Prices = prices.slice(i - 19, i + 1)
      rollingMean20 = last20Prices.reduce((sum, p) => sum + p, 0) / 20
      const std20 = Math.sqrt(last20Prices.reduce((sum, p) => sum + Math.pow(p - rollingMean20, 2), 0) / 20)
      zscore20d = std20 > 0 ? (price - rollingMean20) / std20 : 0
    }

    if (i >= 9) {
      const last10Prices = prices.slice(i - 9, i + 1)
      const mean10 = last10Prices.reduce((sum, p) => sum + p, 0) / 10
      const std10 = Math.sqrt(last10Prices.reduce((sum, p) => sum + Math.pow(p - mean10, 2), 0) / 10)
      zscore10d = std10 > 0 ? (price - mean10) / std10 : 0
    }

    if (i >= 59) {
      const last60Prices = prices.slice(i - 59, i + 1)
      const mean60 = last60Prices.reduce((sum, p) => sum + p, 0) / 60
      const std60 = Math.sqrt(last60Prices.reduce((sum, p) => sum + Math.pow(p - mean60, 2), 0) / 60)
      zscore60d = std60 > 0 ? (price - mean60) / std60 : 0
    }

    series.push({
      date: date.toISOString().split("T")[0],
      adj_close: Number(price.toFixed(2)),
      ret: dailyReturn,
      rolling_mean: Number(rollingMean20.toFixed(2)),
      zscore_10d: Number(zscore10d.toFixed(3)),
      zscore_20d: Number(zscore20d.toFixed(3)),
      zscore_60d: Number(zscore60d.toFixed(3)),
    })
  }

  return series
}

// Generate market distribution data (for percentile histogram)
function generateMarketDistribution(
  currentZScore: number,
): Array<{ zscore: number; count: number; isCurrentStock?: boolean }> {
  const data = []
  const bins = []

  // Create bins from -3 to +3
  for (let i = -3; i <= 3; i += 0.2) {
    bins.push(i)
  }

  // Generate normal distribution-like data
  bins.forEach((bin) => {
    const distance = Math.abs(bin)
    const count = Math.max(1, Math.round(100 * Math.exp((-distance * distance) / 2)))
    data.push({
      zscore: Number(bin.toFixed(1)),
      count: count + Math.floor(Math.random() * 20), // Add some noise
      isCurrentStock: Math.abs(bin - currentZScore) < 0.1, // Highlight current stock
    })
  })

  return data
}

// Generate cluster comparison data
function generateClusterComparison(
  currentZScore: number,
  clusterSize: number,
): Array<{
  date: string
  stock_zscore: number
  cluster_avg_zscore: number
  cluster_deviation: number
}> {
  const data = []
  const startDate = new Date()
  startDate.setDate(startDate.getDate() - 60)

  for (let i = 0; i < 60; i++) {
    const date = new Date(startDate)
    date.setDate(date.getDate() + i)

    // Generate cluster average that's generally more stable
    const clusterAvg = Math.sin(i / 15) * 0.5 + (Math.random() - 0.5) * 0.3

    // Stock Z-score evolves toward current value
    const stockZScore = currentZScore * (i / 60) + (Math.random() - 0.5) * 0.4

    const deviation = stockZScore - clusterAvg

    data.push({
      date: date.toISOString().split("T")[0],
      stock_zscore: Number(stockZScore.toFixed(3)),
      cluster_avg_zscore: Number(clusterAvg.toFixed(3)),
      cluster_deviation: Number(deviation.toFixed(3)),
    })
  }

  return data
}

// Generate serial correlation trend data
function generateSerialCorrelationTrend(): Array<{
  date: string
  serial_corr_30d: number
  serial_corr_60d: number
  ci_lower_30d: number
  ci_upper_30d: number
  ci_lower_60d: number
  ci_upper_60d: number
}> {
  const data = []
  const startDate = new Date()
  startDate.setDate(startDate.getDate() - 90)

  for (let i = 0; i < 90; i += 7) {
    // Weekly data points
    const date = new Date(startDate)
    date.setDate(date.getDate() + i)

    // Generate trending serial correlation
    const baseCorr30 = -0.2 + Math.sin(i / 20) * 0.3
    const baseCorr60 = -0.1 + Math.sin(i / 25) * 0.2

    const noise30 = (Math.random() - 0.5) * 0.1
    const noise60 = (Math.random() - 0.5) * 0.08

    const corr30 = Math.max(-0.8, Math.min(0.8, baseCorr30 + noise30))
    const corr60 = Math.max(-0.8, Math.min(0.8, baseCorr60 + noise60))

    data.push({
      date: date.toISOString().split("T")[0],
      serial_corr_30d: Number(corr30.toFixed(3)),
      serial_corr_60d: Number(corr60.toFixed(3)),
      ci_lower_30d: Number((corr30 - 0.08).toFixed(3)),
      ci_upper_30d: Number((corr30 + 0.08).toFixed(3)),
      ci_lower_60d: Number((corr60 - 0.06).toFixed(3)),
      ci_upper_60d: Number((corr60 + 0.06).toFixed(3)),
    })
  }

  return data
}

// Generate volatility vs peers data
function generateVolatilityPeers(
  currentVol: number,
  currentZScore: number,
): Array<{
  ticker: string
  volatility: number
  zscore: number
  isCurrentStock: boolean
}> {
  const peers = ["AAPL", "MSFT", "GOOGL", "META", "NFLX", "NVDA", "TSLA", "AMZN"]

  return peers.map((ticker, i) => ({
    ticker,
    volatility: currentVol + (Math.random() - 0.5) * 0.02,
    zscore: currentZScore + (Math.random() - 0.5) * 1.5,
    isCurrentStock: i === 0, // First one is current stock
  }))
}

// Generate historical percentile data (6 months)
function generateHistoricalPercentiles(
  currentMarketPctile: number,
  currentClusterPctile: number,
): Array<{
  date: string
  market_percentile: number
  cluster_percentile: number
}> {
  const data = []
  const startDate = new Date()
  startDate.setMonth(startDate.getMonth() - 6)

  for (let i = 0; i < 180; i += 7) {
    // Weekly data points
    const date = new Date(startDate)
    date.setDate(date.getDate() + i)

    // Generate realistic percentile evolution
    const marketTrend = (currentMarketPctile - 0.5) * (i / 180) + 0.5
    const marketNoise = (Math.random() - 0.5) * 0.2
    const marketPercentile = Math.max(0, Math.min(1, marketTrend + marketNoise))

    const clusterTrend = (currentClusterPctile - 0.5) * (i / 180) + 0.5
    const clusterNoise = (Math.random() - 0.5) * 0.15
    const clusterPercentile = Math.max(0, Math.min(1, clusterTrend + clusterNoise))

    data.push({
      date: date.toISOString().split("T")[0],
      market_percentile: Number(marketPercentile.toFixed(3)),
      cluster_percentile: Number(clusterPercentile.toFixed(3)),
    })
  }

  return data
}

// Mock uploads
export const mockUploads: Record<string, Upload> = {
  "upload-1": {
    upload_id: "upload-1",
    original_filename: "SP500_sample.csv",
    row_count: 12540,
    status: "done",
    created_at: "2025-08-19T10:30:00Z",
    completed_at: "2025-08-19T10:32:15Z",
  },
  "upload-2": {
    upload_id: "upload-2",
    original_filename: "tech_stocks.csv",
    row_count: 8760,
    status: "done",
    created_at: "2025-08-18T14:15:00Z",
    completed_at: "2025-08-18T14:17:30Z",
  },
}

// Mock analysis list items
export const mockAnalyses: AnalysisListItem[] = [
  {
    analysis_id: "analysis-aapl",
    ticker: "AAPL",
    score: 0.71,
    label: "mean-reverting",
    zscore_lb20: -1.45,
    serial_corr30: -0.18,
    serial_corr60: -0.1,
    vol_20d: 0.021,
    cluster_id: "C7",
    market_pctile: 0.12,
    cluster_pctile: 0.09,
    ci95_lower: 0.58,
    ci95_upper: 0.83,
    analysis_date: "2025-08-27",
  },
  {
    analysis_id: "analysis-msft",
    ticker: "MSFT",
    score: 0.65,
    label: "mean-reverting",
    zscore_lb20: -1.85,
    serial_corr30: -0.32,
    serial_corr60: -0.15,
    vol_20d: 0.016,
    cluster_id: "C7",
    market_pctile: 0.08,
    cluster_pctile: 0.05,
    ci95_lower: 0.52,
    ci95_upper: 0.78,
    analysis_date: "2025-08-27",
  },
  {
    analysis_id: "analysis-googl",
    ticker: "GOOGL",
    score: 0.25,
    label: "trending",
    zscore_lb20: 1.9,
    serial_corr30: 0.4,
    serial_corr60: 0.25,
    vol_20d: 0.019,
    cluster_id: "C7",
    market_pctile: 0.88,
    cluster_pctile: 0.91,
    ci95_lower: 0.18,
    ci95_upper: 0.32,
    analysis_date: "2025-08-27",
  },
  {
    analysis_id: "analysis-tsla",
    ticker: "TSLA",
    score: 0.15,
    label: "trending",
    zscore_lb20: 2.31,
    serial_corr30: 0.28,
    serial_corr60: 0.18,
    vol_20d: 0.045,
    cluster_id: "C2",
    market_pctile: 0.92,
    cluster_pctile: 0.78,
    ci95_lower: 0.08,
    ci95_upper: 0.22,
    analysis_date: "2025-08-27",
  },
  {
    analysis_id: "analysis-nvda",
    ticker: "NVDA",
    score: 0.82,
    label: "mean-reverting",
    zscore_lb20: -2.15,
    serial_corr30: -0.45,
    serial_corr60: -0.28,
    vol_20d: 0.038,
    cluster_id: "C2",
    market_pctile: 0.03,
    cluster_pctile: 0.12,
    ci95_lower: 0.75,
    ci95_upper: 0.89,
    analysis_date: "2025-08-27",
  },
  {
    analysis_id: "analysis-amzn",
    ticker: "AMZN",
    score: 0.45,
    label: "neutral",
    zscore_lb20: 0.12,
    serial_corr30: 0.08,
    serial_corr60: 0.05,
    vol_20d: 0.024,
    cluster_id: "C5",
    market_pctile: 0.48,
    cluster_pctile: 0.52,
    ci95_lower: 0.38,
    ci95_upper: 0.52,
    analysis_date: "2025-08-27",
  },
]

// Mock detailed analyses with enhanced data
export const mockDetailedAnalyses: Record<string, AnalysisDetail> = {
  "analysis-aapl": {
    ticker: "AAPL",
    name: "Apple Inc.",
    analysis_date: "2025-08-27",
    lookbacks: [10, 20, 60],
    zscores: { "10": -1.2, "20": -1.45, "60": -0.9 },
    zscores_ci95: {
      "10": [-1.35, -1.05],
      "20": [-1.62, -1.28],
      "60": [-1.08, -0.72],
    },
    serial_corr: { "30": -0.18, "60": -0.1 },
    serial_corr_ci95: {
      "30": [-0.25, -0.11],
      "60": [-0.18, -0.02],
    },
    vol: { "20": 0.021 },
    vol_ci95: { "20": [0.018, 0.024] },
    cluster: {
      id: "C7",
      size: 23,
      label: "Large-cap Tech",
      peers: ["MSFT", "GOOGL", "META", "NFLX"],
    },
    percentiles: { market: 0.12, cluster: 0.09 },
    score: 0.71,
    score_ci95: [0.58, 0.83],
    label: "mean-reverting",
    series: generatePriceSeriesWithZScore(175.43, 90),
    cluster_deviation: -0.85,
    cluster_deviation_ci95: [-1.02, -0.68],
    historical_percentiles: generateHistoricalPercentiles(0.12, 0.09),
    zscore_distribution: generateMarketDistribution(-1.45),
    cluster_comparison: generateClusterComparison(-1.45, 23),
    serial_correlation_trend: generateSerialCorrelationTrend(),
    volatility_peers: generateVolatilityPeers(0.021, -1.45),
  },
  "analysis-msft": {
    ticker: "MSFT",
    name: "Microsoft Corporation",
    analysis_date: "2025-08-27",
    lookbacks: [10, 20, 60],
    zscores: { "10": -1.6, "20": -1.85, "60": -1.25 },
    zscores_ci95: {
      "10": [-1.75, -1.45],
      "20": [-2.1, -1.6],
      "60": [-1.48, -1.02],
    },
    serial_corr: { "30": -0.32, "60": -0.15 },
    serial_corr_ci95: {
      "30": [-0.42, -0.22],
      "60": [-0.25, -0.05],
    },
    vol: { "20": 0.016 },
    vol_ci95: { "20": [0.014, 0.018] },
    cluster: {
      id: "C7",
      size: 23,
      label: "Large-cap Tech",
      peers: ["AAPL", "GOOGL", "META", "NFLX"],
    },
    percentiles: { market: 0.08, cluster: 0.05 },
    score: 0.65,
    score_ci95: [0.52, 0.78],
    label: "mean-reverting",
    series: generatePriceSeriesWithZScore(378.85, 90),
    cluster_deviation: -1.12,
    cluster_deviation_ci95: [-1.35, -0.89],
    historical_percentiles: generateHistoricalPercentiles(0.08, 0.05),
    zscore_distribution: generateMarketDistribution(-1.85),
    cluster_comparison: generateClusterComparison(-1.85, 23),
    serial_correlation_trend: generateSerialCorrelationTrend(),
    volatility_peers: generateVolatilityPeers(0.016, -1.85),
  },
  "analysis-googl": {
    ticker: "GOOGL",
    name: "Alphabet Inc.",
    analysis_date: "2025-08-27",
    lookbacks: [10, 20, 60],
    zscores: { "10": 2.1, "20": 1.9, "60": 1.45 },
    zscores_ci95: {
      "10": [1.85, 2.35],
      "20": [1.68, 2.12],
      "60": [1.22, 1.68],
    },
    serial_corr: { "30": 0.4, "60": 0.25 },
    serial_corr_ci95: {
      "30": [0.32, 0.48],
      "60": [0.18, 0.32],
    },
    vol: { "20": 0.019 },
    vol_ci95: { "20": [0.017, 0.021] },
    cluster: {
      id: "C7",
      size: 23,
      label: "Large-cap Tech",
      peers: ["AAPL", "MSFT", "META", "NFLX"],
    },
    percentiles: { market: 0.88, cluster: 0.91 },
    score: 0.25,
    score_ci95: [0.18, 0.32],
    label: "trending",
    series: generatePriceSeriesWithZScore(142.65, 90),
    cluster_deviation: 1.45,
    cluster_deviation_ci95: [1.22, 1.68],
    historical_percentiles: generateHistoricalPercentiles(0.88, 0.91),
    zscore_distribution: generateMarketDistribution(1.9),
    cluster_comparison: generateClusterComparison(1.9, 23),
    serial_correlation_trend: generateSerialCorrelationTrend(),
    volatility_peers: generateVolatilityPeers(0.019, 1.9),
  },
  "analysis-tsla": {
    ticker: "TSLA",
    name: "Tesla Inc.",
    analysis_date: "2025-08-27",
    lookbacks: [10, 20, 60],
    zscores: { "10": 2.5, "20": 2.31, "60": 1.88 },
    zscores_ci95: {
      "10": [2.25, 2.75],
      "20": [2.05, 2.57],
      "60": [1.65, 2.11],
    },
    serial_corr: { "30": 0.28, "60": 0.18 },
    serial_corr_ci95: {
      "30": [0.18, 0.38],
      "60": [0.08, 0.28],
    },
    vol: { "20": 0.045 },
    vol_ci95: { "20": [0.041, 0.049] },
    cluster: {
      id: "C2",
      size: 15,
      label: "High Volatility Growth",
      peers: ["NVDA", "AMD", "PLTR", "ARKK"],
    },
    percentiles: { market: 0.92, cluster: 0.78 },
    score: 0.15,
    score_ci95: [0.08, 0.22],
    label: "trending",
    series: generatePriceSeriesWithZScore(248.5, 90),
    cluster_deviation: 0.88,
    cluster_deviation_ci95: [0.65, 1.11],
    historical_percentiles: generateHistoricalPercentiles(0.92, 0.78),
    zscore_distribution: generateMarketDistribution(2.31),
    cluster_comparison: generateClusterComparison(2.31, 15),
    serial_correlation_trend: generateSerialCorrelationTrend(),
    volatility_peers: generateVolatilityPeers(0.045, 2.31),
  },
  "analysis-nvda": {
    ticker: "NVDA",
    name: "NVIDIA Corporation",
    analysis_date: "2025-08-27",
    lookbacks: [10, 20, 60],
    zscores: { "10": -2.4, "20": -2.15, "60": -1.68 },
    zscores_ci95: {
      "10": [-2.65, -2.15],
      "20": [-2.45, -1.85],
      "60": [-1.92, -1.44],
    },
    serial_corr: { "30": -0.45, "60": -0.28 },
    serial_corr_ci95: {
      "30": [-0.55, -0.35],
      "60": [-0.38, -0.18],
    },
    vol: { "20": 0.038 },
    vol_ci95: { "20": [0.034, 0.042] },
    cluster: {
      id: "C2",
      size: 15,
      label: "High Volatility Growth",
      peers: ["TSLA", "AMD", "PLTR", "ARKK"],
    },
    percentiles: { market: 0.03, cluster: 0.12 },
    score: 0.82,
    score_ci95: [0.75, 0.89],
    label: "mean-reverting",
    series: generatePriceSeriesWithZScore(875.3, 90),
    cluster_deviation: -1.68,
    cluster_deviation_ci95: [-1.92, -1.44],
    historical_percentiles: generateHistoricalPercentiles(0.03, 0.12),
    zscore_distribution: generateMarketDistribution(-2.15),
    cluster_comparison: generateClusterComparison(-2.15, 15),
    serial_correlation_trend: generateSerialCorrelationTrend(),
    volatility_peers: generateVolatilityPeers(0.038, -2.15),
  },
  "analysis-amzn": {
    ticker: "AMZN",
    name: "Amazon.com Inc.",
    analysis_date: "2025-08-27",
    lookbacks: [10, 20, 60],
    zscores: { "10": 0.08, "20": 0.12, "60": 0.15 },
    zscores_ci95: {
      "10": [-0.08, 0.24],
      "20": [-0.05, 0.29],
      "60": [-0.08, 0.38],
    },
    serial_corr: { "30": 0.08, "60": 0.05 },
    serial_corr_ci95: {
      "30": [-0.02, 0.18],
      "60": [-0.08, 0.18],
    },
    vol: { "20": 0.024 },
    vol_ci95: { "20": [0.021, 0.027] },
    cluster: {
      id: "C5",
      size: 18,
      label: "E-commerce & Cloud",
      peers: ["SHOP", "CRM", "ADBE", "NOW"],
    },
    percentiles: { market: 0.48, cluster: 0.52 },
    score: 0.45,
    score_ci95: [0.38, 0.52],
    label: "neutral",
    series: generatePriceSeriesWithZScore(185.2, 90),
    cluster_deviation: 0.05,
    cluster_deviation_ci95: [-0.12, 0.22],
    historical_percentiles: generateHistoricalPercentiles(0.48, 0.52),
    zscore_distribution: generateMarketDistribution(0.12),
    cluster_comparison: generateClusterComparison(0.12, 18),
    serial_correlation_trend: generateSerialCorrelationTrend(),
    volatility_peers: generateVolatilityPeers(0.024, 0.12),
  },
}

// Mock upload by ID mapping
export const mockUploadAnalyses: Record<string, string[]> = {
  "upload-1": ["analysis-aapl", "analysis-msft", "analysis-googl", "analysis-tsla", "analysis-nvda"],
  "upload-2": ["analysis-amzn"],
}
