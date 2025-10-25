"use client";

import React, { useState, useMemo } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Search, TrendingUp, TrendingDown, Minus, ArrowUpDown } from "lucide-react";

interface StockPerformance {
  ticker: string;
  avg_r2: number;
  prediction_bias: number;
  volatility: number;
  sample_size: number;
  recommendation: 'strong' | 'moderate' | 'caution' | 'avoid';
  sector?: string;
}

interface StockPerformanceHeatmapProps {
  stocks: StockPerformance[];
  className?: string;
}

type SortField = 'ticker' | 'avg_r2' | 'prediction_bias' | 'volatility' | 'sample_size';
type SortDirection = 'asc' | 'desc';

export function StockPerformanceHeatmap({ stocks, className }: StockPerformanceHeatmapProps) {
  const [searchTerm, setSearchTerm] = useState('');
  const [filterRecommendation, setFilterRecommendation] = useState<string>('all');
  const [sortField, setSortField] = useState<SortField>('avg_r2');
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');

  const getRecommendationColor = (recommendation: string) => {
    switch (recommendation) {
      case 'strong': return 'bg-green-500 text-white';
      case 'moderate': return 'bg-blue-500 text-white';
      case 'caution': return 'bg-yellow-500 text-black';
      case 'avoid': return 'bg-red-500 text-white';
      default: return 'bg-gray-500 text-white';
    }
  };

  const getR2Color = (r2: number) => {
    if (r2 > 0.1) return 'bg-green-100 text-green-800';
    if (r2 > 0.05) return 'bg-yellow-100 text-yellow-800';
    if (r2 > 0.02) return 'bg-orange-100 text-orange-800';
    return 'bg-red-100 text-red-800';
  };

  const getBiasIcon = (bias: number) => {
    if (Math.abs(bias) < 0.02) return <Minus className="h-4 w-4 text-gray-500" />;
    return bias > 0 ? <TrendingUp className="h-4 w-4 text-red-500" /> : <TrendingDown className="h-4 w-4 text-blue-500" />;
  };

  const filteredAndSortedStocks = useMemo(() => {
    let filtered = stocks.filter(stock => {
      const matchesSearch = stock.ticker.toLowerCase().includes(searchTerm.toLowerCase());
      const matchesFilter = filterRecommendation === 'all' || stock.recommendation === filterRecommendation;
      return matchesSearch && matchesFilter;
    });

    filtered.sort((a, b) => {
      const aValue = a[sortField];
      const bValue = b[sortField];
      const comparison = typeof aValue === 'string' ? aValue.localeCompare(bValue as string) : (aValue as number) - (bValue as number);
      return sortDirection === 'asc' ? comparison : -comparison;
    });

    return filtered;
  }, [stocks, searchTerm, filterRecommendation, sortField, sortDirection]);

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDirection('desc');
    }
  };

  const SortableHeader = ({ field, children }: { field: SortField; children: React.ReactNode }) => (
    <Button
      variant="ghost"
      size="sm"
      onClick={() => handleSort(field)}
      className="h-auto p-1 font-medium"
    >
      {children}
      <ArrowUpDown className="ml-1 h-3 w-3" />
    </Button>
  );

  return (
    <div className={`space-y-4 ${className}`}>
      <Card>
        <CardHeader>
          <CardTitle>Stock-Level Performance Analysis</CardTitle>
          <CardDescription>
            Model effectiveness per security - use for position sizing and selection
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Filters */}
          <div className="flex gap-4 items-center">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search stocks..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="pl-9"
              />
            </div>
            <Select value={filterRecommendation} onValueChange={setFilterRecommendation}>
              <SelectTrigger className="w-40">
                <SelectValue placeholder="Filter by rec." />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Recommendations</SelectItem>
                <SelectItem value="strong">Strong</SelectItem>
                <SelectItem value="moderate">Moderate</SelectItem>
                <SelectItem value="caution">Caution</SelectItem>
                <SelectItem value="avoid">Avoid</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Summary Stats */}
          <div className="grid grid-cols-4 gap-4 p-4 bg-muted/50 rounded-lg">
            <div className="text-center">
              <div className="text-lg font-bold text-green-600">
                {filteredAndSortedStocks.filter(s => s.recommendation === 'strong').length}
              </div>
              <div className="text-xs text-muted-foreground">Strong Signals</div>
            </div>
            <div className="text-center">
              <div className="text-lg font-bold text-blue-600">
                {filteredAndSortedStocks.filter(s => s.recommendation === 'moderate').length}
              </div>
              <div className="text-xs text-muted-foreground">Moderate</div>
            </div>
            <div className="text-center">
              <div className="text-lg font-bold text-yellow-600">
                {filteredAndSortedStocks.filter(s => s.recommendation === 'caution').length}
              </div>
              <div className="text-xs text-muted-foreground">Caution</div>
            </div>
            <div className="text-center">
              <div className="text-lg font-bold text-red-600">
                {filteredAndSortedStocks.filter(s => s.recommendation === 'avoid').length}
              </div>
              <div className="text-xs text-muted-foreground">Avoid</div>
            </div>
          </div>

          {/* Table */}
          <div className="border rounded-lg">
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-muted/50">
                  <tr className="border-b">
                    <th className="text-left p-3">
                      <SortableHeader field="ticker">Stock</SortableHeader>
                    </th>
                    <th className="text-center p-3">
                      <SortableHeader field="avg_r2">Predictive Power</SortableHeader>
                    </th>
                    <th className="text-center p-3">Prediction Bias</th>
                    <th className="text-center p-3">
                      <SortableHeader field="volatility">Volatility</SortableHeader>
                    </th>
                    <th className="text-center p-3">
                      <SortableHeader field="sample_size">Sample Size</SortableHeader>
                    </th>
                    <th className="text-center p-3">Recommendation</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredAndSortedStocks.map((stock, index) => (
                    <tr key={stock.ticker} className={`border-b hover:bg-muted/25 ${index % 2 === 0 ? 'bg-background' : 'bg-muted/10'}`}>
                      <td className="p-3">
                        <div className="font-mono font-medium">{stock.ticker}</div>
                        {stock.sector && (
                          <div className="text-xs text-muted-foreground">{stock.sector}</div>
                        )}
                      </td>
                      <td className="text-center p-3">
                        <Badge className={getR2Color(stock.avg_r2)}>
                          {(stock.avg_r2 * 100).toFixed(1)}%
                        </Badge>
                      </td>
                      <td className="text-center p-3">
                        <div className="flex items-center justify-center gap-1">
                          {getBiasIcon(stock.prediction_bias)}
                          <span className="text-xs font-mono">
                            {stock.prediction_bias > 0 ? '+' : ''}{(stock.prediction_bias * 100).toFixed(1)}%
                          </span>
                        </div>
                      </td>
                      <td className="text-center p-3">
                        <span className="text-sm font-mono">
                          {(stock.volatility * 100).toFixed(1)}%
                        </span>
                      </td>
                      <td className="text-center p-3">
                        <span className="text-sm">{stock.sample_size}</span>
                      </td>
                      <td className="text-center p-3">
                        <Badge className={getRecommendationColor(stock.recommendation)}>
                          {stock.recommendation.charAt(0).toUpperCase() + stock.recommendation.slice(1)}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {filteredAndSortedStocks.length === 0 && (
            <div className="text-center py-8 text-muted-foreground">
              No stocks match your current filters
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}