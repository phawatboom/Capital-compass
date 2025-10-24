"use client";

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { AlertCircle, Download, RefreshCw, TrendingUp, TrendingDown, Activity } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";

interface UniversalModelData {
  model_info: {
    type: string;
    version: string;
    description: string;
    sample_size: string;
    features: string;
    horizon_days: string;
  };
  global_performance: {
    r2_global: number;
    directional_accuracy: number;
    mae: number;
    n_predictions: number;
  } | null;
  latest_predictions: Array<{
    ticker: string;
    date: string;
    final_prediction: number;
    direction: string;
    confidence: string;
    current_vol: number;
    momentum_1d: number;
    cross_sectional_rank: number;
  }>;
  trading_opportunities: Array<{
    ticker: string;
    prediction: number;
    direction: string;
    confidence: string;
    signal_strength: number;
    volatility_rank: number;
    momentum_rank: number;
  }>;
  direction_breakdown: Array<{
    prediction_direction: string;
    count: number;
    avg_prediction: number;
  }>;
  top_performing_stocks: Array<{
    ticker: string;
    r2_oos: number;
    directional_accuracy: number;
    performance_tier: string;
    n_observations: number;
  }>;
}

interface TimeSeriesData {
  ticker: string;
  horizon_days: string;
  stock_performance: {
    r2_oos: number;
    directional_accuracy: number;
    performance_tier: string;
    n_observations: number;
  } | null;
  time_series: Array<{
    date: string;
    prediction: number;
    direction: string;
    confidence: string;
    volatility_63d: number;
    return_1d: number;
    return_5d: number;
    cross_sectional_dispersion: number;
  }>;
}

export function UniversalBetaDashboard() {
  const [dashboardData, setDashboardData] = useState<UniversalModelData | null>(null);
  const [timeSeriesData, setTimeSeriesData] = useState<TimeSeriesData | null>(null);
  const [selectedTicker, setSelectedTicker] = useState<string>('');
  const [selectedHorizon, setSelectedHorizon] = useState<string>('10');
  const [loading, setLoading] = useState(false);
  const [timeSeriesLoading, setTimeSeriesLoading] = useState(false);
  const [error, setError] = useState<string>('');
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  // API base URL
  const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

  const fetchDashboardData = async () => {
    setLoading(true);
    setError('');
    
    try {
      const response = await fetch(`${API_BASE}/api/universal/dashboard/?horizon=${selectedHorizon}&limit=50`, {
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        throw new Error(`Failed to fetch dashboard data: ${response.statusText}`);
      }

      const result = await response.json();
      setDashboardData(result.data);
      setLastUpdated(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch dashboard data');
      console.error('Error fetching dashboard data:', err);
    } finally {
      setLoading(false);
    }
  };

  const fetchTimeSeriesData = async (ticker: string) => {
    if (!ticker) return;
    
    setTimeSeriesLoading(true);
    
    try {
      const response = await fetch(`${API_BASE}/api/universal/timeseries/?ticker=${ticker}&horizon=${selectedHorizon}`, {
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        throw new Error(`Failed to fetch time series data: ${response.statusText}`);
      }

      const result = await response.json();
      setTimeSeriesData(result.data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch time series data');
      console.error('Error fetching time series data:', err);
    } finally {
      setTimeSeriesLoading(false);
    }
  };

  const handleTickerSelect = (ticker: string) => {
    setSelectedTicker(ticker);
    fetchTimeSeriesData(ticker);
  };

  const handleImportData = async () => {
    setLoading(true);
    setError('');

    try {
      const response = await fetch(`${API_BASE}/api/universal/import/`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        throw new Error(`Failed to import data: ${response.statusText}`);
      }

      const result = await response.json();
      
      // Refresh dashboard data after import
      await fetchDashboardData();
      
      console.log('Import successful:', result);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to import data');
      console.error('Error importing data:', err);
    } finally {
      setLoading(false);
    }
  };

  const getDirectionIcon = (direction: string) => {
    switch (direction) {
      case 'INCREASE': return <TrendingUp className="h-4 w-4 text-green-600" />;
      case 'DECREASE': return <TrendingDown className="h-4 w-4 text-red-600" />;
      default: return <Activity className="h-4 w-4 text-blue-600" />;
    }
  };

  const getConfidenceBadge = (confidence: string) => {
    const variants = {
      'HIGH': 'default',
      'MEDIUM': 'secondary',
      'LOW': 'outline'
    } as const;
    
    return (
      <Badge variant={variants[confidence as keyof typeof variants] || 'outline'}>
        {confidence}
      </Badge>
    );
  };

  // Load dashboard data on component mount and horizon change
  useEffect(() => {
    fetchDashboardData();
  }, [selectedHorizon]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex justify-between items-start">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Universal Beta Model Dashboard</h1>
          <p className="text-muted-foreground mt-2">
            Advanced cross-sectional beta forecasting for fund managers
          </p>
          <div className="flex items-center gap-4 mt-2">
            {dashboardData?.model_info && (
              <p className="text-sm text-blue-600 font-medium">
                {dashboardData.model_info.sample_size} • {dashboardData.model_info.features}
              </p>
            )}
            {lastUpdated && (
              <p className="text-sm text-gray-500">
                Last updated: {lastUpdated.toLocaleString()}
              </p>
            )}
          </div>
        </div>
        <div className="flex gap-2">
          <Select value={selectedHorizon} onValueChange={setSelectedHorizon}>
            <SelectTrigger className="w-32">
              <SelectValue placeholder="Horizon" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="1">1 Day</SelectItem>
              <SelectItem value="5">5 Days</SelectItem>
              <SelectItem value="10">10 Days</SelectItem>
              <SelectItem value="20">20 Days</SelectItem>
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            onClick={fetchDashboardData}
            disabled={loading}
            className="flex items-center gap-2"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
          <Button
            onClick={handleImportData}
            disabled={loading}
            className="flex items-center gap-2"
          >
            <Download className="h-4 w-4" />
            Import Data
          </Button>
        </div>
      </div>

      {/* Error Alert */}
      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* Model Performance Cards */}
      {dashboardData?.global_performance && (
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Global R²</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {dashboardData.global_performance.r2_global.toFixed(4)}
              </div>
              <p className="text-xs text-muted-foreground">
                Model explanatory power
              </p>
            </CardContent>
          </Card>
          
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Directional Accuracy</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {(dashboardData.global_performance.directional_accuracy * 100).toFixed(1)}%
              </div>
              <p className="text-xs text-muted-foreground">
                Correct direction calls
              </p>
            </CardContent>
          </Card>
          
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Mean Abs Error</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {dashboardData.global_performance.mae.toFixed(4)}
              </div>
              <p className="text-xs text-muted-foreground">
                Prediction accuracy
              </p>
            </CardContent>
          </Card>
          
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Sample Size</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {dashboardData.global_performance.n_predictions.toLocaleString()}
              </div>
              <p className="text-xs text-muted-foreground">
                Out-of-sample predictions
              </p>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Main Content */}
      <Tabs defaultValue="opportunities" className="space-y-4">
        <TabsList>
          <TabsTrigger value="opportunities">Trading Opportunities</TabsTrigger>
          <TabsTrigger value="predictions">Latest Predictions</TabsTrigger>
          <TabsTrigger value="performers">Top Performers</TabsTrigger>
          <TabsTrigger value="timeseries" disabled={!selectedTicker}>
            Time Series {selectedTicker && `(${selectedTicker})`}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="opportunities" className="space-y-4">
          {/* Fund Manager Metrics Overview */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
            <Card>
              <CardContent className="p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-gray-600">High Conviction Signals</p>
                    <p className="text-2xl font-bold">
                      {dashboardData?.trading_opportunities.filter(t => parseFloat(t.confidence) > 0.7).length || 0}
                    </p>
                  </div>
                  <TrendingUp className="h-8 w-8 text-green-600" />
                </div>
              </CardContent>
            </Card>
            
            <Card>
              <CardContent className="p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-gray-600">Avg Signal Strength</p>
                    <p className="text-2xl font-bold">
                      {dashboardData?.trading_opportunities.length > 0 
                        ? (dashboardData.trading_opportunities.reduce((sum, t) => sum + t.signal_strength, 0) / dashboardData.trading_opportunities.length).toFixed(3)
                        : '0.000'
                      }
                    </p>
                  </div>
                  <Activity className="h-8 w-8 text-blue-600" />
                </div>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Top Trading Signals</CardTitle>
              <CardDescription>
                High-confidence signals from the model
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-2">
                {dashboardData?.trading_opportunities.slice(0, 30).map((trade, index) => (
                  <div
                    key={`${trade.ticker}-${index}`}
                    className="flex items-center justify-between p-2 border rounded hover:bg-gray-50 cursor-pointer"
                    onClick={() => handleTickerSelect(trade.ticker)}
                  >
                    <div className="flex items-center gap-3">
                      {getDirectionIcon(trade.direction)}
                      <Link href={`/stocks/${trade.ticker}`} className="font-medium">
                        {trade.ticker}
                      </Link>
                      <span className="text-sm text-gray-500">β = {trade.prediction.toFixed(4)}</span>
                    </div>
                    <div className="flex items-center gap-3">
                      {getConfidenceBadge(trade.confidence)}
                      <Badge variant="outline" className="text-xs">{trade.direction === 'up' ? 'LONG' : 'SHORT'}</Badge>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="predictions" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Latest Beta Predictions</CardTitle>
              <CardDescription>
                Most recent predictions across the stock universe
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-2">
                {dashboardData?.latest_predictions.slice(0, 30).map((pred, index) => (
                  <div
                    key={`${pred.ticker}-${index}`}
                    className="flex items-center justify-between p-2 border rounded hover:bg-gray-50 cursor-pointer"
                    onClick={() => handleTickerSelect(pred.ticker)}
                  >
                    <div className="flex items-center gap-3">
                      {getDirectionIcon(pred.direction)}
                      <Link href={`/stocks/${pred.ticker}`} className="font-medium">{pred.ticker}</Link>
                      <span className="text-sm text-gray-500">{pred.date}</span>
                    </div>
                    <div className="flex items-center gap-3">
                      <div className="text-right font-mono text-sm">
                        <p>β = {pred.final_prediction.toFixed(4)}</p>
                        <p className="text-xs text-gray-500">
                          Mom: {(pred.momentum_1d * 100).toFixed(1)}%
                        </p>
                      </div>
                      {getConfidenceBadge(pred.confidence)}
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="performers" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Top Performing Stocks</CardTitle>
              <CardDescription>
                Stocks with highest model accuracy for this horizon
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-2">
                {dashboardData?.top_performing_stocks.map((stock, index) => (
                  <div
                    key={`${stock.ticker}-${index}`}
                    className="flex items-center justify-between p-3 border rounded hover:bg-gray-50 cursor-pointer"
                    onClick={() => handleTickerSelect(stock.ticker)}
                  >
                    <div className="flex items-center gap-3">
                      <span className="text-sm text-gray-500">#{index + 1}</span>
                      <Link href={`/stocks/${stock.ticker}`} className="font-medium">{stock.ticker}</Link>
                      <Badge variant="outline">{stock.performance_tier}</Badge>
                    </div>
                    <div className="text-right">
                      <p className="font-medium">R² = {stock.r2_oos.toFixed(4)}</p>
                      <p className="text-sm text-gray-500">
                        Dir Acc: {(stock.directional_accuracy * 100).toFixed(1)}%
                      </p>
                      <p className="text-xs text-gray-500">
                        {stock.n_observations} observations
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="timeseries" className="space-y-4">
          {selectedTicker && timeSeriesData ? (
            <Card>
              <CardHeader>
                <CardTitle>Time Series Analysis - {selectedTicker}</CardTitle>
                <CardDescription>
                  {timeSeriesData.stock_performance && (
                    <>
                      Performance: {timeSeriesData.stock_performance.performance_tier} • 
                      R² = {timeSeriesData.stock_performance.r2_oos.toFixed(4)} • 
                      Dir Acc = {(timeSeriesData.stock_performance.directional_accuracy * 100).toFixed(1)}%
                    </>
                  )}
                </CardDescription>
              </CardHeader>
              <CardContent>
                {timeSeriesLoading ? (
                  <div className="flex items-center justify-center h-48">
                    <RefreshCw className="h-6 w-6 animate-spin" />
                  </div>
                ) : (
                  <div className="space-y-4">
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                      <Card>
                        <CardHeader className="pb-2">
                          <CardTitle className="text-sm">Latest Prediction</CardTitle>
                        </CardHeader>
                        <CardContent>
                          <div className="text-lg font-mono">
                            {timeSeriesData.time_series[0]?.prediction.toFixed(4) || 'N/A'}
                          </div>
                        </CardContent>
                      </Card>
                      <Card>
                        <CardHeader className="pb-2">
                          <CardTitle className="text-sm">Recent Volatility</CardTitle>
                        </CardHeader>
                        <CardContent>
                          <div className="text-lg font-mono">
                            {((timeSeriesData.time_series[0]?.volatility_63d || 0) * 100).toFixed(2)}%
                          </div>
                        </CardContent>
                      </Card>
                      <Card>
                        <CardHeader className="pb-2">
                          <CardTitle className="text-sm">5-Day Return</CardTitle>
                        </CardHeader>
                        <CardContent>
                          <div className="text-lg font-mono">
                            {((timeSeriesData.time_series[0]?.return_5d || 0) * 100).toFixed(2)}%
                          </div>
                        </CardContent>
                      </Card>
                    </div>
                    <div className="space-y-2 max-h-96 overflow-y-auto">
                      {timeSeriesData.time_series.map((point, index) => (
                        <div key={index} className="flex items-center justify-between p-2 border rounded text-sm">
                          <span>{point.date}</span>
                          <div className="flex items-center gap-3">
                            {getDirectionIcon(point.direction)}
                            <span className="font-mono">β = {point.prediction.toFixed(4)}</span>
                            {getConfidenceBadge(point.confidence)}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardHeader>
                <CardTitle>Time Series Analysis</CardTitle>
                <CardDescription>
                  Select a ticker from any tab to view detailed time series analysis
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="flex items-center justify-center h-48 text-gray-500">
                  No ticker selected
                </div>
              </CardContent>
            </Card>
          )}
        </TabsContent>
      </Tabs>

      {/* Direction Breakdown */}
      {dashboardData?.direction_breakdown && (
        <Card>
          <CardHeader>
            <CardTitle>Market Direction Breakdown</CardTitle>
            <CardDescription>
              Distribution of beta predictions across market directions
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {dashboardData.direction_breakdown.map((direction, index) => (
                <div key={index} className="text-center p-4 border rounded-lg">
                  <div className="flex items-center justify-center mb-2">
                    {getDirectionIcon(direction.prediction_direction)}
                  </div>
                  <p className="font-medium">{direction.prediction_direction}</p>
                  <p className="text-2xl font-bold">{direction.count}</p>
                  <p className="text-sm text-gray-500">
                    Avg β = {direction.avg_prediction.toFixed(4)}
                  </p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}