"use client";

import React, { useState, useEffect } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { TrendingUp, TrendingDown, Target, Shield, AlertTriangle, CheckCircle } from "lucide-react";

interface ModelMetrics {
  avg_r2: number;
  mae: number;
  coverage: number;
  temporal_stability: 'high' | 'medium' | 'low';
  sample_size: number;
  forecast_horizon: string;
}

interface FeatureImportance {
  feature: string;
  coefficient: number;
  description: string;
  impact: 'high' | 'medium' | 'low';
}

interface ModelInsightsPanelProps {
  metrics: ModelMetrics;
  topFeatures: FeatureImportance[];
  className?: string;
}

export function ModelInsightsPanel({ metrics, topFeatures, className }: ModelInsightsPanelProps) {
  const getConfidenceLevel = (r2: number): { level: string; color: string; description: string } => {
    if (r2 > 0.1) return { 
      level: 'High', 
      color: 'bg-green-500', 
      description: 'Strong predictive signal detected' 
    };
    if (r2 > 0.02) return { 
      level: 'Medium', 
      color: 'bg-yellow-500', 
      description: 'Moderate signal with careful application recommended' 
    };
    return { 
      level: 'Conservative', 
      color: 'bg-red-500', 
      description: 'Limited predictive power - use with extreme caution' 
    };
  };

  const confidence = getConfidenceLevel(metrics.avg_r2);

  const getFeatureIcon = (coefficient: number) => {
    return coefficient > 0 ? <TrendingUp className="h-4 w-4 text-green-600" /> : <TrendingDown className="h-4 w-4 text-red-600" />;
  };

  const formatPercent = (value: number) => `${(value * 100).toFixed(1)}%`;

  return (
    <div className={`space-y-6 ${className}`}>
      {/* Model Confidence Overview */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Shield className="h-5 w-5" />
            Model Confidence & Reliability
          </CardTitle>
          <CardDescription>
            {metrics.forecast_horizon} forecast performance based on {metrics.sample_size.toLocaleString()} historical predictions
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">Confidence Level</span>
            <Badge variant="outline" className={`${confidence.color} text-white`}>
              {confidence.level}
            </Badge>
          </div>
          
          <div className="space-y-2">
            <div className="flex justify-between text-sm">
              <span>Predictive Power (R²)</span>
              <span className="font-mono">{formatPercent(metrics.avg_r2)}</span>
            </div>
            <Progress value={Math.max(0, metrics.avg_r2 * 500)} className="h-2" />
          </div>

          <div className="grid grid-cols-2 gap-4 pt-2">
            <div className="text-center">
              <div className="text-2xl font-bold text-blue-600">{formatPercent(metrics.coverage)}</div>
              <div className="text-xs text-muted-foreground">Coverage Rate</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-purple-600">{metrics.mae.toFixed(3)}</div>
              <div className="text-xs text-muted-foreground">Avg Error (MAE)</div>
            </div>
          </div>

          <div className="pt-2 border-t">
            <p className="text-sm text-muted-foreground">{confidence.description}</p>
          </div>
        </CardContent>
      </Card>

      {/* Key Market Drivers */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Target className="h-5 w-5" />
            Key Market Drivers
          </CardTitle>
          <CardDescription>
            Main factors influencing {metrics.forecast_horizon} beta predictions
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {topFeatures.map((feature, index) => (
              <div key={index} className="flex items-center justify-between p-3 bg-muted/50 rounded-lg">
                <div className="flex items-center gap-3">
                  {getFeatureIcon(feature.coefficient)}
                  <div>
                    <div className="font-medium text-sm">{feature.feature}</div>
                    <div className="text-xs text-muted-foreground">{feature.description}</div>
                  </div>
                </div>
                <div className="text-right">
                  <div className="font-mono text-sm">
                    {feature.coefficient > 0 ? '+' : ''}{feature.coefficient.toFixed(3)}
                  </div>
                  <Badge variant="outline" className="text-xs">
                    {feature.impact} impact
                  </Badge>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Economic Interpretation */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <CheckCircle className="h-5 w-5" />
            Economic Interpretation
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-start gap-3 p-3 bg-blue-50 rounded-lg">
            <TrendingUp className="h-5 w-5 text-blue-600 mt-0.5" />
            <div>
              <div className="font-medium text-sm">Mean Reversion Signal</div>
              <div className="text-xs text-muted-foreground">
                Model identifies when stocks are likely to revert to their fundamental beta over {metrics.forecast_horizon}
              </div>
            </div>
          </div>
          
          <div className="flex items-start gap-3 p-3 bg-yellow-50 rounded-lg">
            <AlertTriangle className="h-5 w-5 text-yellow-600 mt-0.5" />
            <div>
              <div className="font-medium text-sm">Risk Considerations</div>
              <div className="text-xs text-muted-foreground">
                {metrics.avg_r2 < 0.05 ? 
                  "Low R² suggests high uncertainty. Use as one input among many for portfolio decisions." :
                  "Moderate predictive power detected. Consider position sizing and risk management."
                }
              </div>
            </div>
          </div>

          <div className="flex items-start gap-3 p-3 bg-green-50 rounded-lg">
            <Target className="h-5 w-5 text-green-600 mt-0.5" />
            <div>
              <div className="font-medium text-sm">Practical Application</div>
              <div className="text-xs text-muted-foreground">
                Best used for relative ranking of securities rather than absolute beta forecasts. 
                Consider combining with fundamental analysis.
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}