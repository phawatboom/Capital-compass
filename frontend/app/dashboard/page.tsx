"use client"

import { useState, useEffect } from "react"
import Link from "next/link"
import { TrendingUp, TrendingDown, Minus, FileText, Download, Search, Calendar, Filter } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { SemanticSlider } from "@/components/ui/semantic-slider"
import { FilterCard } from "@/components/ui/filter-card"
import { listAnalyses } from "@/lib/mockApi"
import { type AnalysisListItem, getSignalFromScore, getSignalColor } from "@/types/analysis"

interface DashboardFilters {
  search: string
  signal: "all" | "BUY" | "SELL" | "HOLD"
  cluster: string
  scoreRange: [number, number]
  zscoreRange: [number, number]
  volatilityRange: [number, number]
  marketPercentileRange: [number, number]
  serialCorrRange: [number, number]
}

export default function DashboardPage() {
  const [analyses, setAnalyses] = useState<AnalysisListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showAdvancedFilters, setShowAdvancedFilters] = useState(false)

  const [filters, setFilters] = useState<DashboardFilters>({
    search: "",
    signal: "all",
    cluster: "all",
    scoreRange: [0, 1],
    zscoreRange: [-3, 3],
    volatilityRange: [0, 0.1],
    marketPercentileRange: [0, 1],
    serialCorrRange: [-1, 1],
  })

  useEffect(() => {
    const fetchAnalyses = async () => {
      try {
        setLoading(true)
        const response = await listAnalyses(undefined, 100, "-analysis_date")
        setAnalyses(response.items)
        setError(null)
      } catch (err) {
        setError("Failed to load analyses. Please try again.")
      } finally {
        setLoading(false)
      }
    }

    fetchAnalyses()
  }, [])

  const getSignalIcon = (score: number) => {
    const signal = getSignalFromScore(score)
    switch (signal) {
      case "BUY":
        return <TrendingUp className="h-4 w-4 text-blue-600" />
      case "SELL":
        return <TrendingDown className="h-4 w-4 text-red-600" />
      default:
        return <Minus className="h-4 w-4 text-yellow-600" />
    }
  }

  const filteredAnalyses = analyses.filter((analysis) => {
    const matchesSearch = analysis.ticker.toLowerCase().includes(filters.search.toLowerCase())

    const signal = getSignalFromScore(analysis.score)
    const matchesSignal = filters.signal === "all" || signal === filters.signal

    const matchesCluster = filters.cluster === "all" || analysis.cluster_id === filters.cluster

    const matchesScore = analysis.score >= filters.scoreRange[0] && analysis.score <= filters.scoreRange[1]

    const matchesZScore =
      analysis.zscore_lb20 >= filters.zscoreRange[0] && analysis.zscore_lb20 <= filters.zscoreRange[1]

    const matchesVolatility =
      analysis.vol_20d >= filters.volatilityRange[0] && analysis.vol_20d <= filters.volatilityRange[1]

    const matchesMarketPercentile =
      analysis.market_pctile >= filters.marketPercentileRange[0] &&
      analysis.market_pctile <= filters.marketPercentileRange[1]

    const matchesSerialCorr =
      analysis.serial_corr30 >= filters.serialCorrRange[0] && analysis.serial_corr30 <= filters.serialCorrRange[1]

    return (
      matchesSearch &&
      matchesSignal &&
      matchesCluster &&
      matchesScore &&
      matchesZScore &&
      matchesVolatility &&
      matchesMarketPercentile &&
      matchesSerialCorr
    )
  })

  const uniqueClusters = [...new Set(analyses.map((a) => a.cluster_id))]

  const summary = {
    totalStocks: filteredAnalyses.length,
    buySignals: filteredAnalyses.filter((a) => getSignalFromScore(a.score) === "BUY").length,
    sellSignals: filteredAnalyses.filter((a) => getSignalFromScore(a.score) === "SELL").length,
    holdSignals: filteredAnalyses.filter((a) => getSignalFromScore(a.score) === "HOLD").length,
    avgScore:
      filteredAnalyses.length > 0
        ? (filteredAnalyses.reduce((sum, a) => sum + a.score, 0) / filteredAnalyses.length).toFixed(2)
        : "N/A",
    avgConfidence:
      filteredAnalyses.length > 0
        ? (
            filteredAnalyses.reduce((sum, a) => sum + (a.ci95_upper - a.ci95_lower), 0) / filteredAnalyses.length
          ).toFixed(3)
        : "N/A",
  }

  const resetFilters = () => {
    setFilters({
      search: "",
      signal: "all",
      cluster: "all",
      scoreRange: [0, 1],
      zscoreRange: [-3, 3],
      volatilityRange: [0, 0.1],
      marketPercentileRange: [0, 1],
      serialCorrRange: [-1, 1],
    })
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
          <p className="text-gray-600">Loading dashboard...</p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="min-h-screen bg-gray-50 p-8">
        <Card className="max-w-2xl mx-auto">
          <CardHeader>
            <CardTitle className="text-red-600">Error Loading Dashboard</CardTitle>
          </CardHeader>
          <CardContent>
            <p>{error}</p>
            <Button className="mt-4" onClick={() => window.location.reload()}>
              Try Again
            </Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="container mx-auto px-4 py-8">
        <div className="flex items-center justify-between mb-8">
          <h1 className="text-3xl font-bold text-gray-900">Dashboard</h1>
          <div className="flex items-center space-x-2">
            <Badge variant="secondary">
              <Calendar className="h-3 w-3 mr-1" />
              Last Updated:{" "}
              {new Date().toLocaleDateString("en-US", {
                year: "numeric",
                month: "long",
                day: "numeric",
              })}
            </Badge>
            <Button variant="outline">
              <Download className="h-4 w-4 mr-2" />
              Export Report
            </Button>
            <Link href="/upload">
              <Button>Upload New Data</Button>
            </Link>
          </div>
        </div>

        {/* Enhanced Summary Cards - Simplified Colors */}
        <div className="grid md:grid-cols-6 gap-4 mb-8">
          <Card className="border-l-4 border-l-gray-400 shadow-sm hover:shadow-md transition-shadow">
            <CardHeader className="pb-2">
              <CardDescription className="text-xs font-medium text-gray-500 uppercase tracking-wide">
                Total Stocks
              </CardDescription>
              <CardTitle className="text-3xl font-bold text-gray-900">{summary.totalStocks}</CardTitle>
            </CardHeader>
          </Card>
          <Card className="border-l-4 border-l-green-500 shadow-sm hover:shadow-md transition-shadow">
            <CardHeader className="pb-2">
              <CardDescription className="text-xs font-medium text-gray-500 uppercase tracking-wide">
                Buy Signals
              </CardDescription>
              <CardTitle className="text-3xl font-bold text-green-600">{summary.buySignals}</CardTitle>
              <div className="text-xs text-gray-500">
                {summary.totalStocks > 0 ? ((summary.buySignals / summary.totalStocks) * 100).toFixed(0) : 0}% of total
              </div>
            </CardHeader>
          </Card>
          <Card className="border-l-4 border-l-red-500 shadow-sm hover:shadow-md transition-shadow">
            <CardHeader className="pb-2">
              <CardDescription className="text-xs font-medium text-gray-500 uppercase tracking-wide">
                Sell Signals
              </CardDescription>
              <CardTitle className="text-3xl font-bold text-red-600">{summary.sellSignals}</CardTitle>
              <div className="text-xs text-gray-500">
                {summary.totalStocks > 0 ? ((summary.sellSignals / summary.totalStocks) * 100).toFixed(0) : 0}% of total
              </div>
            </CardHeader>
          </Card>
          <Card className="border-l-4 border-l-yellow-500 shadow-sm hover:shadow-md transition-shadow">
            <CardHeader className="pb-2">
              <CardDescription className="text-xs font-medium text-gray-500 uppercase tracking-wide">
                Hold Signals
              </CardDescription>
              <CardTitle className="text-3xl font-bold text-yellow-600">{summary.holdSignals}</CardTitle>
              <div className="text-xs text-gray-500">
                {summary.totalStocks > 0 ? ((summary.holdSignals / summary.totalStocks) * 100).toFixed(0) : 0}% of total
              </div>
            </CardHeader>
          </Card>
          <Card className="border-l-4 border-l-gray-400 shadow-sm hover:shadow-md transition-shadow">
            <CardHeader className="pb-2">
              <CardDescription className="text-xs font-medium text-gray-500 uppercase tracking-wide">
                Avg Score
              </CardDescription>
              <CardTitle className="text-3xl font-bold text-gray-700">{summary.avgScore}</CardTitle>
              <div className="text-xs text-gray-500">Investment strength</div>
            </CardHeader>
          </Card>
          <Card className="border-l-4 border-l-gray-400 shadow-sm hover:shadow-md transition-shadow">
            <CardHeader className="pb-2">
              <CardDescription className="text-xs font-medium text-gray-500 uppercase tracking-wide">
                Avg CI Width
              </CardDescription>
              <CardTitle className="text-3xl font-bold text-gray-700">{summary.avgConfidence}</CardTitle>
              <div className="text-xs text-gray-500">Model confidence</div>
            </CardHeader>
          </Card>
        </div>

        {/* Enhanced Main Filters */}
        <Card className="mb-6 border-gray-200 shadow-sm">
          <CardHeader className="bg-gradient-to-r from-blue-50 to-indigo-50 rounded-t-lg">
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="text-lg font-semibold text-gray-900">Search & Filter</CardTitle>
                <p className="text-sm text-gray-600 mt-1">Find stocks matching your investment criteria</p>
              </div>
              <div className="flex items-center space-x-3">
                <Badge variant="outline" className="bg-white border-gray-300">
                  {filteredAnalyses.length} Results
                </Badge>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setShowAdvancedFilters(!showAdvancedFilters)}
                  className="bg-white hover:bg-gray-50"
                >
                  <Filter className="h-4 w-4 mr-2" />
                  {showAdvancedFilters ? "Hide" : "Show"} Advanced
                </Button>
                <Button variant="outline" size="sm" onClick={resetFilters} className="bg-white hover:bg-gray-50">
                  Reset All
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent className="pt-6">
            {/* Basic Filters */}
            <div className="flex flex-col md:flex-row gap-4">
              <div className="flex-1">
                <div className="relative">
                  <Search className="absolute left-3 top-3 h-4 w-4 text-gray-400" />
                  <Input
                    placeholder="Search by ticker symbol..."
                    value={filters.search}
                    onChange={(e) => setFilters({ ...filters, search: e.target.value })}
                    className="pl-10 border-gray-300 focus:border-blue-500 focus:ring-blue-500"
                  />
                </div>
              </div>
              <Select
                value={filters.signal}
                onValueChange={(value) => setFilters({ ...filters, signal: value as any })}
              >
                <SelectTrigger className="w-full md:w-48 border-gray-300 focus:border-blue-500">
                  <SelectValue placeholder="Signal Type" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Signals</SelectItem>
                  <SelectItem value="BUY">🟢 Buy Signals</SelectItem>
                  <SelectItem value="SELL">🔴 Sell Signals</SelectItem>
                  <SelectItem value="HOLD">🟡 Hold Signals</SelectItem>
                </SelectContent>
              </Select>
              <Select value={filters.cluster} onValueChange={(value) => setFilters({ ...filters, cluster: value })}>
                <SelectTrigger className="w-full md:w-48 border-gray-300 focus:border-blue-500">
                  <SelectValue placeholder="Cluster" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Clusters</SelectItem>
                  {uniqueClusters.map((cluster) => (
                    <SelectItem key={cluster} value={cluster}>
                      {cluster}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </CardContent>
        </Card>

        {/* Advanced Filters - Enhanced UI */}
        {showAdvancedFilters && (
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4 pt-6 border-t border-gray-200">
            <FilterCard
              title="Investment Score"
              description="Higher scores indicate stronger buy signals"
              badge="0-1 Scale"
              badgeColor="bg-green-100 text-green-800"
            >
              <div className="space-y-3">
                <SemanticSlider
                  semanticType="score"
                  value={filters.scoreRange}
                  onValueChange={(value) => setFilters({ ...filters, scoreRange: value as [number, number] })}
                  max={1}
                  min={0}
                  step={0.01}
                  leftLabel="Sell"
                  rightLabel="Buy"
                />
                <div className="flex justify-between text-xs font-mono text-gray-600">
                  <span>{filters.scoreRange[0].toFixed(2)}</span>
                  <span>{filters.scoreRange[1].toFixed(2)}</span>
                </div>
              </div>
            </FilterCard>

            <FilterCard
              title="Z-Score Range"
              description="Standard deviations from mean price"
              badge="±3σ"
              badgeColor="bg-blue-100 text-blue-800"
            >
              <div className="space-y-3">
                <SemanticSlider
                  semanticType="zscore"
                  value={filters.zscoreRange}
                  onValueChange={(value) => setFilters({ ...filters, zscoreRange: value as [number, number] })}
                  max={3}
                  min={-3}
                  step={0.1}
                  leftLabel="Cheap"
                  rightLabel="Expensive"
                />
                <div className="flex justify-between text-xs font-mono text-gray-600">
                  <span>{filters.zscoreRange[0].toFixed(1)}σ</span>
                  <span>{filters.zscoreRange[1].toFixed(1)}σ</span>
                </div>
              </div>
            </FilterCard>

            <FilterCard
              title="Volatility Range"
              description="Annualized price volatility"
              badge="Risk Level"
              badgeColor="bg-orange-100 text-orange-800"
            >
              <div className="space-y-3">
                <SemanticSlider
                  semanticType="volatility"
                  value={[filters.volatilityRange[0] * 100, filters.volatilityRange[1] * 100]}
                  onValueChange={(value) =>
                    setFilters({
                      ...filters,
                      volatilityRange: [value[0] / 100, value[1] / 100] as [number, number],
                    })
                  }
                  max={10}
                  min={0}
                  step={0.1}
                  leftLabel="Low Risk"
                  rightLabel="High Risk"
                />
                <div className="flex justify-between text-xs font-mono text-gray-600">
                  <span>{(filters.volatilityRange[0] * 100).toFixed(1)}%</span>
                  <span>{(filters.volatilityRange[1] * 100).toFixed(1)}%</span>
                </div>
              </div>
            </FilterCard>

            <FilterCard
              title="Market Percentile"
              description="Ranking vs all stocks in market"
              badge="0-100%"
              badgeColor="bg-purple-100 text-purple-800"
            >
              <div className="space-y-3">
                <SemanticSlider
                  semanticType="percentile"
                  value={[filters.marketPercentileRange[0] * 100, filters.marketPercentileRange[1] * 100]}
                  onValueChange={(value) =>
                    setFilters({
                      ...filters,
                      marketPercentileRange: [value[0] / 100, value[1] / 100] as [number, number],
                    })
                  }
                  max={100}
                  min={0}
                  step={1}
                  leftLabel="Cheap"
                  rightLabel="Expensive"
                />
                <div className="flex justify-between text-xs font-mono text-gray-600">
                  <span>{(filters.marketPercentileRange[0] * 100).toFixed(0)}%</span>
                  <span>{(filters.marketPercentileRange[1] * 100).toFixed(0)}%</span>
                </div>
              </div>
            </FilterCard>

            <FilterCard
              title="Serial Correlation"
              description="Tendency to trend or mean-revert"
              badge="±1.0"
              badgeColor="bg-indigo-100 text-indigo-800"
            >
              <div className="space-y-3">
                <SemanticSlider
                  semanticType="correlation"
                  value={filters.serialCorrRange}
                  onValueChange={(value) => setFilters({ ...filters, serialCorrRange: value as [number, number] })}
                  max={1}
                  min={-1}
                  step={0.01}
                  leftLabel="Mean Revert"
                  rightLabel="Trending"
                />
                <div className="flex justify-between text-xs font-mono text-gray-600">
                  <span>{filters.serialCorrRange[0].toFixed(2)}</span>
                  <span>{filters.serialCorrRange[1].toFixed(2)}</span>
                </div>
              </div>
            </FilterCard>

            <FilterCard
              title="Filter Summary"
              description="Active filter count"
              badge={`${
                Object.values(filters).filter(
                  (v) =>
                    (Array.isArray(v) && (v[0] !== 0 || v[1] !== 1)) ||
                    (typeof v === "string" && v !== "all" && v !== ""),
                ).length
              } Active`}
              badgeColor="bg-gray-100 text-gray-800"
            >
              <div className="space-y-2">
                <div className="text-sm text-gray-600">
                  Showing <span className="font-semibold text-gray-900">{filteredAnalyses.length}</span> of{" "}
                  <span className="font-semibold text-gray-900">{analyses.length}</span> stocks
                </div>
                <div className="flex gap-2">
                  <Button variant="outline" size="sm" onClick={resetFilters} className="text-xs bg-transparent">
                    Reset All
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => setShowAdvancedFilters(false)} className="text-xs">
                    Hide Filters
                  </Button>
                </div>
              </div>
            </FilterCard>
          </div>
        )}

        {/* Results Info */}
        <div className="mb-4 text-sm text-gray-600">
          Showing {filteredAnalyses.length} of {analyses.length} stocks
          {filteredAnalyses.length !== analyses.length && " (filtered)"}
        </div>

        {/* Stock Analysis Table */}
        <Card>
          <CardHeader>
            <CardTitle>Stock Analysis Results</CardTitle>
            <CardDescription>Click on any stock to view detailed analysis report</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Stock</TableHead>
                    <TableHead>Score (95% CI)</TableHead>
                    <TableHead>Z-Score (20d)</TableHead>
                    <TableHead>Serial Corr (30d)</TableHead>
                    <TableHead>Serial Corr (60d)</TableHead>
                    <TableHead>Volatility (20d)</TableHead>
                    <TableHead>Cluster</TableHead>
                    <TableHead>Market %ile</TableHead>
                    <TableHead>Cluster %ile</TableHead>
                    <TableHead>Signal</TableHead>
                    <TableHead>Action</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredAnalyses.map((analysis) => {
                    const signal = getSignalFromScore(analysis.score)
                    return (
                      <TableRow key={analysis.analysis_id} className="hover:bg-gray-50">
                        <TableCell>
                          <div className="font-medium">{analysis.ticker}</div>
                        </TableCell>
                        <TableCell>
                          <TooltipProvider>
                            <Tooltip>
                              <TooltipTrigger className="text-left font-mono">
                                {analysis.score.toFixed(2)}
                                <span className="text-gray-500 text-xs">
                                  {` (${analysis.ci95_lower.toFixed(2)}–${analysis.ci95_upper.toFixed(2)})`}
                                </span>
                              </TooltipTrigger>
                              <TooltipContent>
                                <p>Score with 95% confidence interval</p>
                              </TooltipContent>
                            </Tooltip>
                          </TooltipProvider>
                        </TableCell>
                        <TableCell
                          className={`font-mono ${
                            analysis.zscore_lb20 < -1.5
                              ? "text-blue-600"
                              : analysis.zscore_lb20 > 1.5
                                ? "text-red-600"
                                : "text-gray-900"
                          }`}
                        >
                          {analysis.zscore_lb20.toFixed(2)}
                        </TableCell>
                        <TableCell className="font-mono">{analysis.serial_corr30.toFixed(2)}</TableCell>
                        <TableCell className="font-mono">{analysis.serial_corr60?.toFixed(2) || "N/A"}</TableCell>
                        <TableCell className="font-mono">{(analysis.vol_20d * 100).toFixed(1)}%</TableCell>
                        <TableCell>
                          <Badge variant="outline">{analysis.cluster_id}</Badge>
                        </TableCell>
                        <TableCell className="font-mono">{(analysis.market_pctile * 100).toFixed(0)}%</TableCell>
                        <TableCell className="font-mono">{(analysis.cluster_pctile * 100).toFixed(0)}%</TableCell>
                        <TableCell>
                          <Badge className={getSignalColor(signal)}>
                            <div className="flex items-center space-x-1">
                              {getSignalIcon(analysis.score)}
                              <span>{signal}</span>
                            </div>
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <Link href={`/reports/${analysis.analysis_id}`}>
                            <Button variant="outline" size="sm">
                              <FileText className="h-4 w-4 mr-1" />
                              View Report
                            </Button>
                          </Link>
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
