"use client";

import React from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Area, AreaChart } from 'recharts';
import { TrendingUp, TrendingDown, Minus, Calendar, AlertTriangle } from "lucide-react";

interface TemporalPoint {
  date: string;
  r2: number;
  mae: number;
  sample_size: number;
  market_regime?: 'bull' | 'bear' | 'volatile' | 'normal';
}

interface TemporalStabilityProps {
  data: TemporalPoint[];
  className?: string;
}

export function TemporalStabilityChart({ data, className }: TemporalStabilityProps) {
  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', { year: 'numeric', month: 'short' });
  };

  const formatPercent = (value: number) => `${(value * 100).toFixed(1)}%`;

  const getStabilityMetrics = () => {
    const r2Values = data.map(d => d.r2);
    const meanR2 = r2Values.reduce((sum, val) => sum + val, 0) / r2Values.length;
    const variance = r2Values.reduce((sum, val) => sum + Math.pow(val - meanR2, 2), 0) / r2Values.length;
    const volatility = Math.sqrt(variance);
    
    let stabilityLevel: 'high' | 'medium' | 'low';
    if (volatility < 0.02) stabilityLevel = 'high';
    else if (volatility < 0.05) stabilityLevel = 'medium';
    else stabilityLevel = 'low';

    return { meanR2, volatility, stabilityLevel };
  };

  const getRegimeColor = (regime?: string) => {
    switch (regime) {
      case 'bull': return 'bg-green-100 text-green-800';
      case 'bear': return 'bg-red-100 text-red-800';
      case 'volatile': return 'bg-yellow-100 text-yellow-800';
      default: return 'bg-blue-100 text-blue-800';
    }
  };

  const stability = getStabilityMetrics();

  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      const data = payload[0].payload;
      return (
        <div className="bg-background border rounded-lg p-3 shadow-lg">
          <p className="font-medium">{formatDate(label)}</p>
          <p className="text-sm">
            <span className="text-blue-600">R²:</span> {formatPercent(data.r2)}
          </p>
          <p className="text-sm">
            <span className="text-purple-600">MAE:</span> {data.mae.toFixed(3)}
          </p>
          <p className="text-sm">
            <span className="text-gray-600">Samples:</span> {data.sample_size}
          </p>
          {data.market_regime && (
            <Badge className={`${getRegimeColor(data.market_regime)} mt-1`}>
              {data.market_regime}
            </Badge>
          )}
        </div>
      );
    }
    return null;
  };

  const getStabilityIcon = (level: string) => {
    switch (level) {
      case 'high': return <TrendingUp className="h-4 w-4 text-green-600" />;
      case 'medium': return <Minus className="h-4 w-4 text-yellow-600" />;
      case 'low': return <TrendingDown className="h-4 w-4 text-red-600" />;
      default: return <Minus className="h-4 w-4 text-gray-600" />;
    }
  };

  return (
    <div className={`space-y-4 ${className}`}>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Calendar className="h-5 w-5" />
            Model Performance Over Time
          </CardTitle>
          <CardDescription>
            Temporal stability and regime-dependent performance analysis
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Stability Summary */}
          <div className="grid grid-cols-3 gap-4 p-4 bg-muted/50 rounded-lg">
            <div className="text-center">
              <div className="flex items-center justify-center gap-2 mb-1">
                {getStabilityIcon(stability.stabilityLevel)}
                <span className="text-sm font-medium">Stability</span>
              </div>
              <div className="text-lg font-bold capitalize">{stability.stabilityLevel}</div>
              <div className="text-xs text-muted-foreground">
                Volatility: {formatPercent(stability.volatility)}
              </div>
            </div>
            <div className="text-center">
              <div className="text-lg font-bold text-blue-600">
                {formatPercent(stability.meanR2)}
              </div>
              <div className="text-xs text-muted-foreground">Average R²</div>
            </div>
            <div className="text-center">
              <div className="text-lg font-bold text-purple-600">
                {data.length}
              </div>
              <div className="text-xs text-muted-foreground">Time Periods</div>
            </div>
          </div>

          {/* Performance Chart */}
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={data}>
                <CartesianGrid strokeDasharray="3 3" className="opacity-30" />
                <XAxis 
                  dataKey="date" 
                  tickFormatter={formatDate}
                  className="text-xs"
                />
                <YAxis 
                  tickFormatter={formatPercent}
                  className="text-xs"
                />
                <Tooltip content={<CustomTooltip />} />
                <Area
                  type="monotone"
                  dataKey="r2"
                  stroke="#3b82f6"
                  fill="#3b82f6"
                  fillOpacity={0.2}
                  strokeWidth={2}
                />
                <Line
                  type="monotone"
                  dataKey="r2"
                  stroke="#3b82f6"
                  strokeWidth={2}
                  dot={{ fill: '#3b82f6', strokeWidth: 2, r: 3 }}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          {/* Key Insights */}
          <div className="space-y-3">
            <h4 className="font-medium flex items-center gap-2">
              <AlertTriangle className="h-4 w-4" />
              Key Insights
            </h4>
            
            <div className="grid gap-3">
              {stability.stabilityLevel === 'low' && (
                <div className="flex items-start gap-3 p-3 bg-red-50 rounded-lg">
                  <TrendingDown className="h-5 w-5 text-red-600 mt-0.5" />
                  <div>
                    <div className="font-medium text-sm text-red-800">High Temporal Volatility</div>
                    <div className="text-xs text-red-700">
                      Model performance varies significantly over time. Consider regime-specific calibration or shorter lookback windows.
                    </div>
                  </div>
                </div>
              )}

              {stability.meanR2 < 0.02 && (
                <div className="flex items-start gap-3 p-3 bg-yellow-50 rounded-lg">
                  <AlertTriangle className="h-5 w-5 text-yellow-600 mt-0.5" />
                  <div>
                    <div className="font-medium text-sm text-yellow-800">Limited Predictive Power</div>
                    <div className="text-xs text-yellow-700">
                      Consistently low R² suggests fundamental challenges in beta prediction. Consider ensemble methods or alternative features.
                    </div>
                  </div>
                </div>
              )}

              {stability.stabilityLevel === 'high' && stability.meanR2 > 0.05 && (
                <div className="flex items-start gap-3 p-3 bg-green-50 rounded-lg">
                  <TrendingUp className="h-5 w-5 text-green-600 mt-0.5" />
                  <div>
                    <div className="font-medium text-sm text-green-800">Stable Performance</div>
                    <div className="text-xs text-green-700">
                      Consistent predictive power across time periods. Model can be used with confidence for the given horizon.
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Market Regime Analysis */}
          {data.some(d => d.market_regime) && (
            <div className="space-y-2">
              <h4 className="font-medium text-sm">Performance by Market Regime</h4>
              <div className="flex flex-wrap gap-2">
                {['bull', 'bear', 'volatile', 'normal'].map(regime => {
                  const regimeData = data.filter(d => d.market_regime === regime);
                  if (regimeData.length === 0) return null;
                  
                  const avgR2 = regimeData.reduce((sum, d) => sum + d.r2, 0) / regimeData.length;
                  return (
                    <Badge key={regime} className={getRegimeColor(regime)}>
                      {regime}: {formatPercent(avgR2)} ({regimeData.length} periods)
                    </Badge>
                  );
                })}
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}