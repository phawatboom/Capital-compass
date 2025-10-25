"use client";

import React, { useState, useEffect } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { TrendingUp, TrendingDown, Minus, BarChart3 } from "lucide-react";

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

interface BetaSummaryTableProps {
  data?: BetaSummary[];
  loading?: boolean;
  onTickerSelect?: (ticker: string) => void;
}

export function BetaSummaryTable({ data = [], loading = false, onTickerSelect }: BetaSummaryTableProps) {
  const [filteredData, setFilteredData] = useState<BetaSummary[]>(data);
  const [searchTicker, setSearchTicker] = useState('');
  const [confidenceFilter, setConfidenceFilter] = useState('all');
  const [sortField, setSortField] = useState<keyof BetaSummary>('latest_date');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');

  useEffect(() => {
    let filtered = [...data];

    // Apply search filter
    if (searchTicker) {
      filtered = filtered.filter(item => 
        item.ticker.toLowerCase().includes(searchTicker.toLowerCase())
      );
    }

    // Apply confidence filter
    if (confidenceFilter !== 'all') {
      filtered = filtered.filter(item => item.confidence_level === confidenceFilter);
    }

    // Apply sorting
    filtered.sort((a, b) => {
      const aVal = a[sortField];
      const bVal = b[sortField];
      
      if (aVal === null || aVal === undefined) return 1;
      if (bVal === null || bVal === undefined) return -1;
      
      if (sortOrder === 'asc') {
        return aVal < bVal ? -1 : aVal > bVal ? 1 : 0;
      } else {
        return aVal > bVal ? -1 : aVal < bVal ? 1 : 0;
      }
    });

    setFilteredData(filtered);
  }, [data, searchTicker, confidenceFilter, sortField, sortOrder]);

  const handleSort = (field: keyof BetaSummary) => {
    if (sortField === field) {
      setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortOrder('desc');
    }
  };

  const getConfidenceBadgeVariant = (level: string) => {
    switch (level) {
      case 'High': return 'default';
      case 'Medium': return 'secondary';
      case 'Low': return 'destructive';
      default: return 'outline';
    }
  };

  const getBetaTrendIcon = (betaPred: number, betaTrue: number | null) => {
    if (betaTrue === null) return <Minus className="h-4 w-4 text-gray-400" />;
    
    const diff = betaPred - betaTrue;
    if (Math.abs(diff) < 0.05) return <Minus className="h-4 w-4 text-gray-500" />;
    
    return diff > 0 
      ? <TrendingUp className="h-4 w-4 text-green-600" />
      : <TrendingDown className="h-4 w-4 text-red-600" />;
  };

  const formatNumber = (num: number | null, decimals = 3) => {
    if (num === null || num === undefined) return 'N/A';
    return num.toFixed(decimals);
  };

  const formatAccuracy = (accuracy: number | null) => {
    if (accuracy === null) return 'N/A';
    return `${(accuracy * 100).toFixed(1)}%`;
  };

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Beta Coefficient Summary</CardTitle>
          <CardDescription>Loading beta prediction data...</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-center h-48">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900"></div>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <BarChart3 className="h-5 w-5" />
          Beta Coefficient Summary
        </CardTitle>
        <CardDescription>
          Latest beta predictions and performance metrics for all tracked stocks
        </CardDescription>
      </CardHeader>
      <CardContent>
        {/* Filters */}
        <div className="flex gap-4 mb-6">
          <div className="flex-1">
            <Input
              placeholder="Search ticker..."
              value={searchTicker}
              onChange={(e) => setSearchTicker(e.target.value)}
              className="max-w-sm"
            />
          </div>
          <Select value={confidenceFilter} onValueChange={setConfidenceFilter}>
            <SelectTrigger className="w-[180px]">
              <SelectValue placeholder="Confidence Level" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Confidence</SelectItem>
              <SelectItem value="High">High Confidence</SelectItem>
              <SelectItem value="Medium">Medium Confidence</SelectItem>
              <SelectItem value="Low">Low Confidence</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* Results Summary */}
        <div className="mb-4 text-sm text-gray-600">
          Showing {filteredData.length} of {data.length} stocks
        </div>

        {/* Table */}
        <div className="rounded-md border overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead 
                  className="cursor-pointer hover:bg-gray-50"
                  onClick={() => handleSort('ticker')}
                >
                  Ticker {sortField === 'ticker' && (sortOrder === 'asc' ? '↑' : '↓')}
                </TableHead>
                <TableHead 
                  className="cursor-pointer hover:bg-gray-50"
                  onClick={() => handleSort('latest_date')}
                >
                  Latest Date {sortField === 'latest_date' && (sortOrder === 'asc' ? '↑' : '↓')}
                </TableHead>
                <TableHead 
                  className="cursor-pointer hover:bg-gray-50"
                  onClick={() => handleSort('latest_beta_pred')}
                >
                  Beta Pred {sortField === 'latest_beta_pred' && (sortOrder === 'asc' ? '↑' : '↓')}
                </TableHead>
                <TableHead>Beta True</TableHead>
                <TableHead>Trend</TableHead>
                <TableHead 
                  className="cursor-pointer hover:bg-gray-50"
                  onClick={() => handleSort('avg_r2_ols')}
                >
                  Avg R² {sortField === 'avg_r2_ols' && (sortOrder === 'asc' ? '↑' : '↓')}
                </TableHead>
                <TableHead>Accuracy</TableHead>
                <TableHead>Confidence</TableHead>
                <TableHead 
                  className="cursor-pointer hover:bg-gray-50"
                  onClick={() => handleSort('forecast_count')}
                >
                  Forecasts {sortField === 'forecast_count' && (sortOrder === 'asc' ? '↑' : '↓')}
                </TableHead>
                <TableHead>Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredData.map((item) => (
                <TableRow key={item.ticker}>
                  <TableCell className="font-medium">{item.ticker}</TableCell>
                  <TableCell>{new Date(item.latest_date).toLocaleDateString()}</TableCell>
                  <TableCell className="font-mono">{formatNumber(item.latest_beta_pred)}</TableCell>
                  <TableCell className="font-mono">{formatNumber(item.latest_beta_true)}</TableCell>
                  <TableCell>
                    {getBetaTrendIcon(item.latest_beta_pred, item.latest_beta_true)}
                  </TableCell>
                  <TableCell className="font-mono">{formatNumber(item.avg_r2_ols)}</TableCell>
                  <TableCell>{formatAccuracy(item.prediction_accuracy)}</TableCell>
                  <TableCell>
                    <Badge variant={getConfidenceBadgeVariant(item.confidence_level)}>
                      {item.confidence_level}
                    </Badge>
                  </TableCell>
                  <TableCell>{item.forecast_count}</TableCell>
                  <TableCell>
                    <Button 
                      variant="outline" 
                      size="sm"
                      onClick={() => onTickerSelect?.(item.ticker)}
                    >
                      Details
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>

        {filteredData.length === 0 && (
          <div className="text-center py-8 text-gray-500">
            No data available for the selected filters.
          </div>
        )}
      </CardContent>
    </Card>
  );
}