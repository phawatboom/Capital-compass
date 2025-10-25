"use client";

import React from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, ReferenceLine } from 'recharts';
import { TrendingUp, Activity, Target } from "lucide-react";

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

interface BetaTimeSeriesChartProps {
  data?: BetaTimeSeriesData;
  loading?: boolean;
}

export function BetaTimeSeriesChart({ data, loading = false }: BetaTimeSeriesChartProps) {
  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Beta Coefficient Time Series</CardTitle>
          <CardDescription>Loading time series data...</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-center h-96">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900"></div>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (!data || data.dates.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Beta Coefficient Time Series</CardTitle>
          <CardDescription>No time series data available</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-center h-96 text-gray-500">
            Select a ticker to view time series data
          </div>
        </CardContent>
      </Card>
    );
  }

  // Transform data for recharts
  const chartData = data.dates.map((date, index) => ({
    date: new Date(date).toLocaleDateString(),
    fullDate: date,
    beta_pred: data.beta_pred[index],
    beta_true: data.beta_true[index],
    confidence_lower: data.confidence_bands[index]?.lower,
    confidence_upper: data.confidence_bands[index]?.upper,
  }));

  // Calculate statistics
  const latestBetaPred = data.beta_pred[data.beta_pred.length - 1];
  const latestBetaTrue = data.beta_true[data.beta_true.length - 1];
  const avgBetaPred = data.beta_pred.reduce((sum, val) => sum + val, 0) / data.beta_pred.length;
  
  // Calculate prediction accuracy where we have true values
  const validPredictions = data.beta_pred
    .map((pred, idx) => ({ pred, true: data.beta_true[idx] }))
    .filter(item => item.true !== null);
  
  const avgAccuracy = validPredictions.length > 0
    ? validPredictions.reduce((sum, item) => sum + (1 - Math.abs(item.pred - item.true!) / Math.abs(item.true!)), 0) / validPredictions.length
    : null;

  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      return (
        <div className="bg-white p-3 border rounded-lg shadow-lg">
          <p className="font-medium">{`Date: ${label}`}</p>
          {payload.map((entry: any, index: number) => (
            <p key={index} style={{ color: entry.color }}>
              {`${entry.dataKey === 'beta_pred' ? 'Beta Predicted' : 
                 entry.dataKey === 'beta_true' ? 'Beta True' :
                 entry.dataKey === 'confidence_lower' ? 'Confidence Lower' :
                 entry.dataKey === 'confidence_upper' ? 'Confidence Upper' : entry.dataKey}: ${entry.value?.toFixed(3)}`}
            </p>
          ))}
        </div>
      );
    }
    return null;
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Activity className="h-5 w-5" />
          Beta Coefficient Time Series - {data.ticker}
        </CardTitle>
        <CardDescription>
          Predicted vs actual beta coefficients over time with confidence intervals
        </CardDescription>
        
        {/* Summary Stats */}
        <div className="flex gap-4 mt-4">
          <div className="flex items-center gap-2">
            <Target className="h-4 w-4 text-blue-600" />
            <span className="text-sm">
              Latest Pred: <span className="font-mono font-medium">{latestBetaPred.toFixed(3)}</span>
            </span>
          </div>
          {latestBetaTrue !== null && (
            <div className="flex items-center gap-2">
              <Target className="h-4 w-4 text-green-600" />
              <span className="text-sm">
                Latest True: <span className="font-mono font-medium">{latestBetaTrue.toFixed(3)}</span>
              </span>
            </div>
          )}
          <div className="flex items-center gap-2">
            <TrendingUp className="h-4 w-4 text-purple-600" />
            <span className="text-sm">
              Avg Pred: <span className="font-mono font-medium">{avgBetaPred.toFixed(3)}</span>
            </span>
          </div>
          {avgAccuracy !== null && (
            <Badge variant="outline">
              Accuracy: {(avgAccuracy * 100).toFixed(1)}%
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent>
        <div className="h-96">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis 
                dataKey="date" 
                tick={{ fontSize: 12 }}
                angle={-45}
                textAnchor="end"
                height={60}
              />
              <YAxis 
                tick={{ fontSize: 12 }}
                label={{ value: 'Beta Coefficient', angle: -90, position: 'insideLeft' }}
              />
              <Tooltip content={<CustomTooltip />} />
              <Legend />
              
              {/* Reference line at beta = 1 */}
              <ReferenceLine y={1} stroke="#666" strokeDasharray="2 2" />
              
              {/* Confidence bands */}
              <Line
                type="monotone"
                dataKey="confidence_lower"
                stroke="#e5e7eb"
                strokeWidth={1}
                dot={false}
                name="Confidence Lower"
                strokeDasharray="2 2"
              />
              <Line
                type="monotone"
                dataKey="confidence_upper"
                stroke="#e5e7eb"
                strokeWidth={1}
                dot={false}
                name="Confidence Upper"
                strokeDasharray="2 2"
              />
              
              {/* Main lines */}
              <Line
                type="monotone"
                dataKey="beta_pred"
                stroke="#3b82f6"
                strokeWidth={2}
                dot={{ r: 3 }}
                name="Beta Predicted"
              />
              <Line
                type="monotone"
                dataKey="beta_true"
                stroke="#10b981"
                strokeWidth={2}
                dot={{ r: 3 }}
                name="Beta True"
                connectNulls={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
        
        {/* Data Summary */}
        <div className="mt-4 text-sm text-gray-600">
          <p>Showing {chartData.length} data points from {chartData[0]?.date} to {chartData[chartData.length - 1]?.date}</p>
          <p>Gray dashed line represents β = 1.0 (market beta)</p>
        </div>
      </CardContent>
    </Card>
  );
}