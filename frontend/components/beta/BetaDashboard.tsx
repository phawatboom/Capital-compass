"use client";

import React, { useState, useEffect } from 'react';
import { BetaSummaryTable } from '@/components/beta/BetaSummaryTable';
import { BetaTimeSeriesChart } from '@/components/beta/BetaTimeSeriesChart';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AlertCircle, Download, RefreshCw } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";

interface BetaSummary {
  ticker: string;
  latest_date: string;
  latest_beta_pred: number;
  latest_beta_true: number | null;
  avg_r2_ols: number;
  prediction_accuracy: number | null;
  forecast_count: number;
  confidence_level: string;
}

interface BetaTimeSeriesData {
  ticker: string;
  dates: string[];
  beta_pred: number[];
  beta_true: (number | null)[];
  confidence_bands: Array<{
    lower: number;
    upper: number;
  }>;
}

export function BetaDashboard() {
  const [summaryData, setSummaryData] = useState<BetaSummary[]>([]);
  const [timeSeriesData, setTimeSeriesData] = useState<BetaTimeSeriesData | null>(null);
  const [selectedTicker, setSelectedTicker] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [timeSeriesLoading, setTimeSeriesLoading] = useState(false);
  const [error, setError] = useState<string>('');
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  // API base URL - adjust based on your backend configuration
  const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

  const fetchSummaryData = async () => {
    setLoading(true);
    setError('');
    
    try {
      const response = await fetch(`${API_BASE}/api/beta/summary/`, {
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        throw new Error(`Failed to fetch summary data: ${response.statusText}`);
      }

      const data = await response.json();
      setSummaryData(data.summary || []);
      setLastUpdated(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch summary data');
      console.error('Error fetching summary data:', err);
    } finally {
      setLoading(false);
    }
  };

  const fetchTimeSeriesData = async (ticker: string) => {
    if (!ticker) return;
    
    setTimeSeriesLoading(true);
    
    try {
      const response = await fetch(`${API_BASE}/api/beta/timeseries/${ticker}/`, {
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        throw new Error(`Failed to fetch time series data: ${response.statusText}`);
      }

      const data = await response.json();
      setTimeSeriesData(data);
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
      const response = await fetch(`${API_BASE}/api/beta/import/`, {
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
      
      // Refresh summary data after import
      await fetchSummaryData();
      
      // Show success message (you might want to use a toast notification here)
      console.log('Import successful:', result);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to import data');
      console.error('Error importing data:', err);
    } finally {
      setLoading(false);
    }
  };

  // Load summary data on component mount
  useEffect(() => {
    fetchSummaryData();
  }, []);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex justify-between items-start">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Beta Coefficient Dashboard</h1>
          <p className="text-muted-foreground mt-2">
            Monitor and analyze beta coefficient predictions across your stock portfolio
          </p>
          {lastUpdated && (
            <p className="text-sm text-gray-500 mt-1">
              Last updated: {lastUpdated.toLocaleString()}
            </p>
          )}
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={fetchSummaryData}
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
            Import Latest Data
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

      {/* Main Content */}
      <Tabs defaultValue="summary" className="space-y-4">
        <TabsList>
          <TabsTrigger value="summary">Summary Table</TabsTrigger>
          <TabsTrigger value="timeseries" disabled={!selectedTicker}>
            Time Series {selectedTicker && `(${selectedTicker})`}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="summary" className="space-y-4">
          <BetaSummaryTable
            data={summaryData}
            loading={loading}
            onTickerSelect={handleTickerSelect}
          />
        </TabsContent>

        <TabsContent value="timeseries" className="space-y-4">
          {selectedTicker ? (
            <BetaTimeSeriesChart
              data={timeSeriesData}
              loading={timeSeriesLoading}
            />
          ) : (
            <Card>
              <CardHeader>
                <CardTitle>Time Series Analysis</CardTitle>
                <CardDescription>
                  Select a ticker from the summary table to view detailed time series analysis
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

      {/* Stats Cards */}
      {summaryData.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Total Stocks</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{summaryData.length}</div>
              <p className="text-xs text-muted-foreground">
                Active predictions
              </p>
            </CardContent>
          </Card>
          
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">High Confidence</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {summaryData.filter(s => s.confidence_level === 'High').length}
              </div>
              <p className="text-xs text-muted-foreground">
                Strong predictions
              </p>
            </CardContent>
          </Card>
          
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Avg R² Score</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {(summaryData.reduce((sum, s) => sum + s.avg_r2_ols, 0) / summaryData.length).toFixed(3)}
              </div>
              <p className="text-xs text-muted-foreground">
                Model fit quality
              </p>
            </CardContent>
          </Card>
          
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Total Forecasts</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {summaryData.reduce((sum, s) => sum + s.forecast_count, 0).toLocaleString()}
              </div>
              <p className="text-xs text-muted-foreground">
                Historical predictions
              </p>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}