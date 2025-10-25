"use client"

import { useState } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import { Badge } from "@/components/ui/badge"
import { TrendingUp, BarChart3, Zap, Target, Brain, Calculator } from "lucide-react"
import type { ModelType } from "@/types/analysis"

interface ModelSelectionCardProps {
  selectedModel: ModelType
  onModelChange: (model: ModelType) => void
  className?: string
}

export default function ModelSelectionCard({ 
  selectedModel, 
  onModelChange, 
  className = "" 
}: ModelSelectionCardProps) {
  const modelOptions = [
    {
      value: "mean-reversion" as ModelType,
      title: "Mean-Reversion (MR-PROD)",
      description: "Per-stock, per-date mean-reversion likelihood analysis",
      icon: <TrendingUp className="h-5 w-5" />,
      features: [
        "Z-score analysis",
        "Conformal magnitude bands", 
        "Isotonic calibration",
        "Walk-forward backtesting"
      ],
      badge: "Legacy",
      badgeVariant: "secondary" as const,
      strengths: "Best for identifying price reversals and statistical arbitrage opportunities"
    },
    {
      value: "beta-forecasting" as ModelType,
      title: "β-Forecasting (No Market Dependency)",
      description: "Cross-sectional beta forecasting using price-only proxies",
      icon: <BarChart3 className="h-5 w-5" />,
      features: [
        "Ridge regression",
        "Cross-sectional features",
        "Conformal prediction intervals",
        "R² quality metrics"
      ],
      badge: "Enhanced",
      badgeVariant: "default" as const,
      strengths: "Optimal for beta prediction without market dependency, superior for risk management"
    }
  ]

  return (
    <Card className={className}>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Brain className="h-5 w-5" />
          <CardTitle>Model Selection</CardTitle>
        </div>
        <CardDescription>
          Choose the analytical model for your investment analysis
        </CardDescription>
      </CardHeader>
      <CardContent>
        <RadioGroup 
          value={selectedModel} 
          onValueChange={(value) => onModelChange(value as ModelType)}
          className="space-y-4"
        >
          {modelOptions.map((option) => (
            <div key={option.value} className="space-y-3">
              <div className="flex items-center space-x-2">
                <RadioGroupItem value={option.value} id={option.value} />
                <Label 
                  htmlFor={option.value} 
                  className="flex-1 cursor-pointer"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      {option.icon}
                      <span className="font-medium">{option.title}</span>
                      <Badge variant={option.badgeVariant}>{option.badge}</Badge>
                    </div>
                  </div>
                </Label>
              </div>
              
              {selectedModel === option.value && (
                <div className="ml-6 space-y-3 pl-4 border-l-2 border-primary">
                  <p className="text-sm text-muted-foreground">
                    {option.description}
                  </p>
                  
                  <div className="grid grid-cols-2 gap-2">
                    {option.features.map((feature, index) => (
                      <div key={index} className="flex items-center gap-2 text-sm">
                        <Zap className="h-3 w-3 text-primary" />
                        <span>{feature}</span>
                      </div>
                    ))}
                  </div>
                  
                  <div className="flex items-start gap-2 p-3 bg-muted rounded-lg">
                    <Target className="h-4 w-4 text-primary mt-0.5 flex-shrink-0" />
                    <p className="text-sm text-muted-foreground">
                      <strong>Best for:</strong> {option.strengths}
                    </p>
                  </div>
                </div>
              )}
            </div>
          ))}
        </RadioGroup>
        
        <div className="mt-6 p-4 bg-blue-50 rounded-lg border border-blue-200">
          <div className="flex items-center gap-2 mb-2">
            <Calculator className="h-4 w-4 text-blue-600" />
            <span className="text-sm font-medium text-blue-800">Dual-Model Architecture</span>
          </div>
          <p className="text-sm text-blue-700">
            You can compare both models after analysis completion to get comprehensive insights 
            from multiple analytical perspectives.
          </p>
        </div>
      </CardContent>
    </Card>
  )
}