"use client"

import { useState, useEffect } from "react"
import Link from "next/link"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Download, Share2, Printer, ArrowLeft } from "lucide-react"
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  Area,
  BarChart,
  Bar,
  ReferenceLine,
  ScatterChart,
  Scatter,
  ErrorBar,
  ComposedChart,
} from "recharts"
import { getAnalysis, getPdfReportUrl } from "@/lib/mockApi"
import {
  type AnalysisDetail,
  getSignalFromScore,
  getZScoreInterpretation,
  getVolatilityInterpretation,
  getScoreZone,
} from "@/types/analysis"
import { useParams } from "next/navigation"

export default function StockReport() {
  const {analysisId } = useParams<{analysisId: string}>()
  const [analysis, setAnalysis] = useState<AnalysisDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedLookback, setSelectedLookback] = useState<string>("20")

  useEffect(() => {
    const fetchAnalysis = async () => {
      try {
        setLoading(true)
        const data = await getAnalysis(analysisId)
        setAnalysis(data)

        // Set default lookback to the first available
        if (data.lookbacks && data.lookbacks.length > 0) {
          setSelectedLookback(data.lookbacks[0].toString())
        }

        setError(null)
      } catch (err) {
        setError("Failed to load analysis. Please try again.")
      } finally {
        setLoading(false)
      }
    }

    fetchAnalysis()
  }, [analysisId])

  const handleDownloadPdf = () => {
    window.open(getPdfReportUrl(analysisId), "_blank")
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
          <p className="text-gray-600">Loading report...</p>
        </div>
      </div>
    )
  }

  if (error || !analysis) {
    return (
      <div className="min-h-screen bg-gray-50 p-8">
        <Card className="max-w-2xl mx-auto">
          <CardHeader>
            <CardTitle className="text-red-600">Error Loading Report</CardTitle>
          </CardHeader>
          <CardContent>
            <p>{error || "Failed to load analysis data."}</p>
            <Button className="mt-4" onClick={() => window.location.reload()}>
              Try Again
            </Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  // Prepare data for charts
  const priceZScoreData = analysis.series
    .filter((point) => point.adj_close && !isNaN(point.adj_close))
    .map((point) => ({
      date: point.date,
      price: point.adj_close,
      zscore: point.zscore_20d || 0,
      rolling_mean: point.rolling_mean || null,
    }))

  const multiLookbackData = analysis.lookbacks.map((lookback) => ({
    lookback: `${lookback}d`,
    zscore: analysis.zscores[lookback.toString()],
    ci_lower: analysis.zscores_ci95?.[lookback.toString()]?.[0] || 0,
    ci_upper: analysis.zscores_ci95?.[lookback.toString()]?.[1] || 0,
  }))

  const signal = getSignalFromScore(analysis.score)
  const scoreZone = getScoreZone(analysis.score)

  return (
    <div className="mx-auto max-w-7xl p-6 print:p-0 bg-gray-50 min-h-screen">
      {/* Header */}
      <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between mb-6">
        <div className="flex items-center gap-4">
          <Link href="/reports">
            <Button variant="outline" size="icon" className="print:hidden bg-white">
              <ArrowLeft className="h-4 w-4" />
            </Button>
          </Link>
          <div>
            <h1 className="text-3xl font-bold tracking-tight text-gray-900">
              {analysis.ticker} <span className="text-slate-500">— {analysis.name || "Stock Analysis"}</span>
            </h1>
            <p className="text-slate-600">
              Quantitative Analysis • As of{" "}
              {new Date(analysis.analysis_date).toLocaleDateString("en-US", {
                year: "numeric",
                month: "long",
                day: "numeric",
              })}
            </p>
          </div>
        </div>
        <div className="flex gap-2 print:hidden">
          <Button variant="outline" className="bg-white">
            <Share2 className="mr-2 h-4 w-4" />
            Share
          </Button>
          <Button variant="outline" onClick={() => window.print()} className="bg-white">
            <Printer className="mr-2 h-4 w-4" />
            Print
          </Button>
          <Button onClick={handleDownloadPdf}>
            <Download className="mr-2 h-4 w-4" />
            Export PDF
          </Button>
        </div>
      </div>

      {/* Bloomberg-style Grid Layout */}
      <div className="grid grid-cols-12 gap-6">
        {/* Top Row: Price/Z-Score Timeline (8 cols) + Market Percentile (4 cols) */}
        <Card className="col-span-12 lg:col-span-8 shadow-sm bg-white">
          <CardHeader className="pb-4">
            <div className="flex items-center justify-between">
              <CardTitle className="text-lg font-semibold">Price & Z-Score Timeline</CardTitle>
              <div className="flex gap-2">
                {analysis.lookbacks.map((lookback) => (
                  <Button
                    key={lookback}
                    variant={selectedLookback === lookback.toString() ? "default" : "outline"}
                    size="sm"
                    onClick={() => setSelectedLookback(lookback.toString())}
                  >
                    {lookback}d
                  </Button>
                ))}
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <div className="h-80 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={priceZScoreData} margin={{ top: 10, right: 60, bottom: 20, left: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis
                    dataKey="date"
                    tickFormatter={(date) => {
                      try {
                        return new Date(date).toLocaleDateString("en-US", { month: "short", day: "numeric" })
                      } catch {
                        return ""
                      }
                    }}
                    interval="preserveStartEnd"
                    tick={{ fontSize: 11 }}
                    stroke="#666"
                  />
                  <YAxis yAxisId="price" orientation="left" tick={{ fontSize: 11 }} stroke="#666" />
                  <YAxis yAxisId="zscore" orientation="right" tick={{ fontSize: 11 }} stroke="#666" />
                  <RechartsTooltip
                    formatter={(value: number, name: string) => [
                      name === "price" ? `$${value.toFixed(2)}` : `${value.toFixed(2)}σ`,
                      name === "price" ? "Price" : "Z-Score",
                    ]}
                    labelFormatter={(date) => {
                      try {
                        return new Date(date).toLocaleDateString("en-US", {
                          year: "numeric",
                          month: "long",
                          day: "numeric",
                        })
                      } catch {
                        return date
                      }
                    }}
                  />
                  {/* Z-Score reference lines */}
                  <ReferenceLine yAxisId="zscore" y={1.5} stroke="#ef4444" strokeDasharray="2 2" strokeWidth={1} />
                  <ReferenceLine yAxisId="zscore" y={-1.5} stroke="#3b82f6" strokeDasharray="2 2" strokeWidth={1} />
                  <ReferenceLine yAxisId="zscore" y={0} stroke="#6b7280" strokeDasharray="1 1" strokeWidth={1} />

                  <Line
                    yAxisId="price"
                    type="monotone"
                    dataKey="price"
                    stroke="#1f2937"
                    dot={false}
                    strokeWidth={2}
                    name="price"
                  />
                  <Line
                    yAxisId="zscore"
                    type="monotone"
                    dataKey="zscore"
                    stroke="#dc2626"
                    dot={false}
                    strokeWidth={2}
                    name="zscore"
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
            <div className="flex justify-center gap-6 mt-2 text-sm text-gray-600">
              <div className="flex items-center gap-2">
                <div className="w-4 h-0.5 bg-gray-800"></div>
                <span>Price (Left Axis)</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-4 h-0.5 bg-red-600"></div>
                <span>Z-Score (Right Axis)</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-4 h-0.5 bg-red-400 opacity-60" style={{ borderTop: "2px dashed" }}></div>
                <span>±1.5σ Bands</span>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="col-span-12 lg:col-span-4 shadow-sm bg-white">
          <CardHeader className="pb-4">
            <CardTitle className="text-lg font-semibold">Market Distribution</CardTitle>
            <p className="text-sm text-gray-600">Where this stock ranks vs all stocks</p>
          </CardHeader>
          <CardContent>
            <div className="h-80 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={analysis.zscore_distribution} margin={{ top: 10, right: 10, left: 10, bottom: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis
                    dataKey="zscore"
                    tick={{ fontSize: 10 }}
                    tickFormatter={(value) => `${value}σ`}
                    stroke="#666"
                  />
                  <YAxis tick={{ fontSize: 10 }} stroke="#666" />
                  <RechartsTooltip
                    formatter={(value: number) => [value, "Stock Count"]}
                    labelFormatter={(zscore) => `Z-Score: ${zscore}σ`}
                  />
                  <Bar
                    dataKey="count"
                    fill={(entry: any) => (entry.isCurrentStock ? "#dc2626" : "#e5e7eb")}
                    stroke="#9ca3af"
                    strokeWidth={0.5}
                  />
                  <ReferenceLine x={analysis.zscores[selectedLookback]} stroke="#dc2626" strokeWidth={2} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="mt-2 text-center">
              <Badge className="bg-red-100 text-red-800">
                {(analysis.percentiles.market * 100).toFixed(0)}th Percentile
              </Badge>
            </div>
          </CardContent>
        </Card>

        {/* Middle Row: Cluster Comparison (8 cols) + Multi-Lookback Z-Scores (4 cols) */}
        <Card className="col-span-12 lg:col-span-8 shadow-sm bg-white">
          <CardHeader className="pb-4">
            <CardTitle className="text-lg font-semibold">Z-Score vs Cluster Average</CardTitle>
            <p className="text-sm text-gray-600">Stock performance relative to {analysis.cluster.label} peers</p>
          </CardHeader>
          <CardContent>
            <div className="h-80 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={analysis.cluster_comparison} margin={{ top: 10, right: 30, bottom: 20, left: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis
                    dataKey="date"
                    tickFormatter={(date) => {
                      try {
                        return new Date(date).toLocaleDateString("en-US", { month: "short", day: "numeric" })
                      } catch {
                        return ""
                      }
                    }}
                    interval="preserveStartEnd"
                    tick={{ fontSize: 11 }}
                    stroke="#666"
                  />
                  <YAxis tick={{ fontSize: 11 }} stroke="#666" />
                  <RechartsTooltip
                    formatter={(value: number, name: string) => [
                      `${value.toFixed(2)}σ`,
                      name === "stock_zscore" ? `${analysis.ticker} Z-Score` : "Cluster Average",
                    ]}
                    labelFormatter={(date) => {
                      try {
                        return new Date(date).toLocaleDateString("en-US", {
                          year: "numeric",
                          month: "long",
                          day: "numeric",
                        })
                      } catch {
                        return date
                      }
                    }}
                  />
                  <ReferenceLine y={0} stroke="#6b7280" strokeDasharray="1 1" strokeWidth={1} />
                  <Line
                    type="monotone"
                    dataKey="stock_zscore"
                    stroke="#dc2626"
                    strokeWidth={2}
                    dot={false}
                    name="stock_zscore"
                  />
                  <Line
                    type="monotone"
                    dataKey="cluster_avg_zscore"
                    stroke="#3b82f6"
                    strokeWidth={2}
                    dot={false}
                    strokeDasharray="5 5"
                    name="cluster_avg_zscore"
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <div className="flex justify-center gap-6 mt-2 text-sm text-gray-600">
              <div className="flex items-center gap-2">
                <div className="w-4 h-0.5 bg-red-600"></div>
                <span>{analysis.ticker} Z-Score</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-4 h-0.5 bg-blue-600" style={{ borderTop: "2px dashed" }}></div>
                <span>Cluster Average</span>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="col-span-12 lg:col-span-4 shadow-sm bg-white">
          <CardHeader className="pb-4">
            <CardTitle className="text-lg font-semibold">Multi-Lookback Z-Scores</CardTitle>
            <p className="text-sm text-gray-600">Robustness across time windows</p>
          </CardHeader>
          <CardContent>
            <div className="h-80 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={multiLookbackData} margin={{ top: 20, right: 30, left: 20, bottom: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis dataKey="lookback" tick={{ fontSize: 11 }} stroke="#666" />
                  <YAxis tick={{ fontSize: 11 }} stroke="#666" />
                  <RechartsTooltip
                    formatter={(value: number) => [`${value.toFixed(2)}σ`, "Z-Score"]}
                    labelFormatter={(lookback) => `Lookback: ${lookback}`}
                  />
                  <ReferenceLine y={1.5} stroke="#ef4444" strokeDasharray="2 2" strokeWidth={1} />
                  <ReferenceLine y={-1.5} stroke="#3b82f6" strokeDasharray="2 2" strokeWidth={1} />
                  <ReferenceLine y={0} stroke="#6b7280" strokeDasharray="1 1" strokeWidth={1} />
                  <Bar dataKey="zscore" fill="#8884d8" stroke="#6366f1" strokeWidth={1}>
                    <ErrorBar dataKey={["ci_lower", "ci_upper"]} width={4} strokeWidth={2} stroke="#4f46e5" />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="mt-2 text-center text-xs text-gray-600">Error bars show 95% confidence intervals</div>
          </CardContent>
        </Card>

        {/* Bottom Row: Serial Correlation Trend (6 cols) + Volatility vs Peers (6 cols) */}
        <Card className="col-span-12 lg:col-span-6 shadow-sm bg-white">
          <CardHeader className="pb-4">
            <CardTitle className="text-lg font-semibold">Serial Correlation Trend</CardTitle>
            <p className="text-sm text-gray-600">Mean reversion vs trending behavior over time</p>
          </CardHeader>
          <CardContent>
            <div className="h-64 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart
                  data={analysis.serial_correlation_trend}
                  margin={{ top: 10, right: 30, bottom: 20, left: 10 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis
                    dataKey="date"
                    tickFormatter={(date) => {
                      try {
                        return new Date(date).toLocaleDateString("en-US", { month: "short" })
                      } catch {
                        return ""
                      }
                    }}
                    interval="preserveStartEnd"
                    tick={{ fontSize: 11 }}
                    stroke="#666"
                  />
                  <YAxis domain={[-0.8, 0.8]} tick={{ fontSize: 11 }} stroke="#666" />
                  <RechartsTooltip
                      formatter={(value: number, name: string) => {
                        if (name.startsWith("ci_")) return null; // hide confidence interval lines
                        return [
                          Number(value).toFixed(3),
                          name.includes("30d") ? "30d Serial Corr" : "60d Serial Corr",
                        ];
                      }}
                    />

                  <ReferenceLine y={0} stroke="#6b7280" strokeDasharray="1 1" strokeWidth={1} />
                  <ReferenceLine y={0.2} stroke="#ef4444" strokeDasharray="2 2" strokeWidth={1} />
                  <ReferenceLine y={-0.2} stroke="#3b82f6" strokeDasharray="2 2" strokeWidth={1} />
                  <Area type="monotone" dataKey="ci_upper_30d" stroke="none" fill="#3b82f6" fillOpacity={0.1} />
                  <Area type="monotone" dataKey="ci_lower_30d" stroke="none" fill="#ffffff" fillOpacity={1} />
                  <Line type="monotone" dataKey="serial_corr_30d" stroke="#3b82f6" strokeWidth={2} dot={false} />
                  <Line
                    type="monotone"
                    dataKey="serial_corr_60d"
                    stroke="#10b981"
                    strokeWidth={2}
                    dot={false}
                    strokeDasharray="5 5"
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <div className="flex justify-center gap-4 mt-2 text-sm text-gray-600">
              <div className="flex items-center gap-2">
                <div className="w-4 h-0.5 bg-blue-600"></div>
                <span>30d Window</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-4 h-0.5 bg-green-600" style={{ borderTop: "2px dashed" }}></div>
                <span>60d Window</span>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="col-span-12 lg:col-span-6 shadow-sm bg-white">
          <CardHeader className="pb-4">
            <CardTitle className="text-lg font-semibold">Volatility vs Peers</CardTitle>
            <p className="text-sm text-gray-600">Risk-return positioning within {analysis.cluster.label}</p>
          </CardHeader>
          <CardContent>
            <div className="h-64 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <ScatterChart data={analysis.volatility_peers} margin={{ top: 20, right: 20, bottom: 20, left: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis
                    type="number"
                    dataKey="zscore"
                    name="Z-Score"
                    tick={{ fontSize: 11 }}
                    stroke="#666"
                    tickFormatter={(value) => `${value.toFixed(1)}σ`}
                  />
                  <YAxis
                    type="number"
                    dataKey="volatility"
                    name="Volatility"
                    tick={{ fontSize: 11 }}
                    stroke="#666"
                    tickFormatter={(value) => `${(value * 100).toFixed(1)}%`}
                  />
                  <RechartsTooltip
                    formatter={(value: number, name: string) => [
                      name === "volatility" ? `${(value * 100).toFixed(1)}%` : `${value.toFixed(2)}σ`,
                      name === "volatility" ? "Volatility" : "Z-Score",
                    ]}
                    labelFormatter={(label, payload) => {
                      if (payload && payload[0]) {
                        return `${payload[0].payload.ticker}`
                      }
                      return ""
                    }}
                  />
                  <ReferenceLine x={0} stroke="#6b7280" strokeDasharray="1 1" strokeWidth={1} />
                  <Scatter
                    dataKey="volatility"
                    fill={(entry: any) => (entry.isCurrentStock ? "#dc2626" : "#3b82f6")}
                    stroke={(entry: any) => (entry.isCurrentStock ? "#991b1b" : "#1e40af")}
                    strokeWidth={2}
                  />
                </ScatterChart>
              </ResponsiveContainer>
            </div>
            <div className="flex justify-center gap-4 mt-2 text-sm text-gray-600">
              <div className="flex items-center gap-2">
                <div className="w-3 h-3 bg-red-600 rounded-full"></div>
                <span>{analysis.ticker}</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-3 h-3 bg-blue-600 rounded-full"></div>
                <span>Cluster Peers</span>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Score Summary Card */}
        <Card className="col-span-12 shadow-sm bg-white border-l-4 border-l-blue-600">
          <CardHeader>
            <CardTitle className="text-xl font-semibold">Investment Summary</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid md:grid-cols-4 gap-6">
              <div className="text-center">
                <div className="text-3xl font-bold text-blue-600 mb-2">{analysis.score.toFixed(2)}</div>
                <div className="text-sm text-gray-600 mb-1">Final Score</div>
                <Badge className={`${scoreZone.bgColor} ${scoreZone.color} border-0`}>{scoreZone.label}</Badge>
              </div>
              <div className="text-center">
                <div className="text-3xl font-bold text-gray-700 mb-2">
                  {analysis.zscores[selectedLookback].toFixed(2)}σ
                </div>
                <div className="text-sm text-gray-600 mb-1">Z-Score ({selectedLookback}d)</div>
                <Badge variant="outline">{getZScoreInterpretation(analysis.zscores[selectedLookback])}</Badge>
              </div>
              <div className="text-center">
                <div className="text-3xl font-bold text-gray-700 mb-2">
                  {(analysis.percentiles.market * 100).toFixed(0)}%
                </div>
                <div className="text-sm text-gray-600 mb-1">Market Percentile</div>
                <Badge variant="outline">
                  {analysis.percentiles.market <= 0.2
                    ? "Very Cheap"
                    : analysis.percentiles.market <= 0.4
                      ? "Cheap"
                      : analysis.percentiles.market <= 0.6
                        ? "Fair"
                        : analysis.percentiles.market <= 0.8
                          ? "Expensive"
                          : "Very Expensive"}
                </Badge>
              </div>
              <div className="text-center">
                <div className="text-3xl font-bold text-gray-700 mb-2">{(analysis.vol["20"] * 100).toFixed(1)}%</div>
                <div className="text-sm text-gray-600 mb-1">Volatility (20d)</div>
                <Badge variant="outline">{getVolatilityInterpretation(analysis.vol["20"])}</Badge>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Details tabs */}
      <Tabs defaultValue="metrics" className="mt-6">
        <TabsList className="grid w-full grid-cols-3">
          <TabsTrigger value="metrics">Key Metrics</TabsTrigger>
          <TabsTrigger value="peers">Peer Cluster</TabsTrigger>
          <TabsTrigger value="weights">Score Weights</TabsTrigger>
        </TabsList>
        <TabsContent value="metrics">
          <Card className="bg-white">
            <CardContent className="pt-6">
              <div className="grid gap-4 md:grid-cols-3">
                <Metric
                  label="Lookback Windows"
                  value={analysis.lookbacks.join(", ") + " days"}
                  hint="Used for Z-score calculation"
                />
                <Metric label="Z Threshold" value="±1.5σ" hint="Statistical significance zone" />
                <Metric label="Serial Corr Windows" value="30, 60 days" hint="Rolling correlation periods" />
                <Metric label="Vol Window" value="20 days" hint="Rolling volatility period" />
                <Metric
                  label="Analysis Date"
                  value={new Date(analysis.analysis_date).toLocaleDateString("en-US", {
                    year: "numeric",
                    month: "long",
                    day: "numeric",
                  })}
                  hint="Report generation date"
                />
                <Metric label="Model Version" value="v1.0" hint="Reproducibility" />
              </div>
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="peers">
          <Card className="bg-white">
            <CardContent className="flex flex-wrap gap-2 pt-6 text-sm">
              {analysis.cluster.peers ? (
                analysis.cluster.peers.map((peer) => (
                  <Badge key={peer} variant="secondary" className="rounded-2xl">
                    {peer}
                  </Badge>
                ))
              ) : (
                <p className="text-gray-500">No peer information available for this cluster.</p>
              )}
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="weights">
          <Card className="bg-white">
            <CardContent className="pt-6">
              <div className="space-y-4">
                <p className="text-sm text-gray-600">
                  The final score is calculated using a weighted combination of the following metrics:
                </p>
                <div className="grid gap-4 md:grid-cols-2">
                  <div className="rounded-lg border p-4">
                    <div className="text-sm font-medium">Z-Score (w1)</div>
                    <div className="text-2xl font-semibold">35%</div>
                    <div className="mt-1 text-xs text-gray-500">Lower Z-scores contribute positively</div>
                  </div>
                  <div className="rounded-lg border p-4">
                    <div className="text-sm font-medium">Serial Correlation 30d (w2)</div>
                    <div className="text-2xl font-semibold">20%</div>
                    <div className="mt-1 text-xs text-gray-500">Negative correlation contributes positively</div>
                  </div>
                  <div className="rounded-lg border p-4">
                    <div className="text-sm font-medium">Serial Correlation 60d (w3)</div>
                    <div className="text-2xl font-semibold">10%</div>
                    <div className="mt-1 text-xs text-gray-500">Longer-term patterns</div>
                  </div>
                  <div className="rounded-lg border p-4">
                    <div className="text-sm font-medium">Volatility 20d (w4)</div>
                    <div className="text-2xl font-semibold">15%</div>
                    <div className="mt-1 text-xs text-gray-500">Lower volatility contributes positively</div>
                  </div>
                  <div className="rounded-lg border p-4">
                    <div className="text-sm font-medium">Cluster Deviation (w5)</div>
                    <div className="text-2xl font-semibold">20%</div>
                    <div className="mt-1 text-xs text-gray-500">Cheaper than peers contributes positively</div>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      <p className="mt-6 text-center text-xs text-gray-500">
        Generated by Capital Compass v1.0 | Report ID: CC-{analysis.ticker}-{analysis.analysis_date}
      </p>
    </div>
  )
}

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-2xl border p-4">
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className="text-lg font-medium">{value}</div>
      {hint ? <div className="mt-1 text-xs text-slate-400">{hint}</div> : null}
    </div>
  )
}
