"use client";

import React, { useState, useEffect } from "react";
import { BetaSummaryTable } from "@/components/beta/BetaSummaryTable";
import { BetaTimeSeriesChart } from "@/components/beta/BetaTimeSeriesChart";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AlertCircle } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";

/** API base URL - adjust based on your backend configuration */
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

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

/** Shared stats shape: known scalars plus "coef_*" entries */
type SharedStats = {
  r2_global?: number;
  volatility_coeff?: number;
  y_intercept?: number;
  /** All factor coefficients look like "coef_<name>" */
  [key: `coef_${string}`]: number | null | undefined;
};

/** Type guard to narrow unknown → number */
const isFiniteNumber = (v: unknown): v is number =>
  typeof v === "number" && Number.isFinite(v);

export function BetaDashboard() {
  const [summaryData, setSummaryData] = useState<BetaSummary[]>([]);
  const [timeSeriesData, setTimeSeriesData] = useState<BetaTimeSeriesData | null>(null);
  const [selectedTicker, setSelectedTicker] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [timeSeriesLoading, setTimeSeriesLoading] = useState(false);
  const [error, setError] = useState<string>("");
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [sharedStats, setSharedStats] = useState<SharedStats | null>(null);

  /** Load shared/global factor stats */
  useEffect(() => {
    fetch(`${API_BASE}/api/factors/shared/`)
      .then((res) => res.json())
      .then(setSharedStats)
      .catch(() => {
        /* silently ignore */
      });
  }, []);

  const fetchSummaryData = async () => {
    setLoading(true);
    setError("");

    try {
      const response = await fetch(`${API_BASE}/api/factors/summary/`, {
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
        },
      });

      if (!response.ok) {
        throw new Error(`Failed to fetch summary data: ${response.statusText}`);
      }

      const data = await response.json();
      setSummaryData(data.summary || []);
      setLastUpdated(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch summary data");
      console.error("Error fetching summary data:", err);
    } finally {
      setLoading(false);
    }
  };

  const fetchTimeSeriesData = async (ticker: string) => {
    if (!ticker) return;

    setTimeSeriesLoading(true);

    try {
      const response = await fetch(`${API_BASE}/api/beta/timeseries/${ticker}/`, {
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
        },
      });

      if (!response.ok) {
        throw new Error(`Failed to fetch time series data: ${response.statusText}`);
      }

      const data = await response.json();
      setTimeSeriesData(data as BetaTimeSeriesData);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch time series data");
      console.error("Error fetching time series data:", err);
    } finally {
      setTimeSeriesLoading(false);
    }
  };

  const handleTickerSelect = (ticker: string) => {
    setSelectedTicker(ticker);
    fetchTimeSeriesData(ticker);
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
      </div>

      {/* Error Alert */}
      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* Global Factor Stats Cards */}
      {sharedStats && (
        <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
          {/* Global R² */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Global R² Score</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {sharedStats.r2_global?.toFixed(4) ?? "N/A"}
              </div>
              <p className="text-xs text-muted-foreground">Model fit quality across all tickers</p>
            </CardContent>
          </Card>

          {/* Volatility Coefficient */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Volatility Coefficient</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {sharedStats.volatility_coeff?.toFixed(4) ?? "N/A"}
              </div>
              <p className="text-xs text-muted-foreground">ElasticNet intercept term for volatility</p>
            </CardContent>
          </Card>

          {/* Y-Intercept */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Y-Intercept</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {sharedStats.y_intercept?.toFixed(32) ?? "N/A"}
              </div>
              <p className="text-xs text-muted-foreground">
                Model baseline term (average intercept across all tickers)
              </p>
            </CardContent>
          </Card>

          {/* Strongest Positive Coefficient */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Top Positive Factor</CardTitle>
            </CardHeader>
            <CardContent>
              {(() => {
                const coefEntries = Object.entries(sharedStats ?? {}).filter(
                  (e): e is [string, number] => e[0].startsWith("coef_") && isFiniteNumber(e[1])
                );

                if (coefEntries.length === 0) {
                  return <div className="text-sm text-gray-500">N/A</div>;
                }

                const top = [...coefEntries].sort((a, b) => b[1] - a[1])[0];
                return (
                  <>
                    <div className="text-2xl font-bold">{top[0].replace("coef_", "")}</div>
                    <p className="text-xs text-muted-foreground">Weight: {top[1].toFixed(4)}</p>
                  </>
                );
              })()}
            </CardContent>
          </Card>

          {/* Strongest Negative Coefficient */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Top Negative Factor</CardTitle>
            </CardHeader>
            <CardContent>
              {(() => {
                const coefEntries = Object.entries(sharedStats ?? {}).filter(
                  (e): e is [string, number] => e[0].startsWith("coef_") && isFiniteNumber(e[1])
                );

                if (coefEntries.length === 0) {
                  return <div className="text-sm text-gray-500">N/A</div>;
                }

                const bottom = [...coefEntries].sort((a, b) => a[1] - b[1])[0];
                return (
                  <>
                    <div className="text-2xl font-bold">{bottom[0].replace("coef_", "")}</div>
                    <p className="text-xs text-muted-foreground">Weight: {bottom[1].toFixed(4)}</p>
                  </>
                );
              })()}
            </CardContent>
          </Card>
        </div>
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
            <BetaTimeSeriesChart data={timeSeriesData} loading={timeSeriesLoading} />
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
    </div>
  );
}
