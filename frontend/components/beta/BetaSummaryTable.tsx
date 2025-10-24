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
        <div className="rounded-md border overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead onClick={() => handleSort('ticker')} className="cursor-pointer hover:bg-gray-50">
                  Ticker {sortField === 'ticker' && (sortOrder === 'asc' ? '↑' : '↓')}
                </TableHead>
                <TableHead onClick={() => handleSort('created_at')} className="cursor-pointer hover:bg-gray-50">
                  Created At {sortField === 'created_at' && (sortOrder === 'asc' ? '↑' : '↓')}
                </TableHead>
                <TableHead onClick={() => handleSort('b_coefficient')} className="cursor-pointer hover:bg-gray-50">
                  β Coefficient {sortField === 'b_coefficient' && (sortOrder === 'asc' ? '↑' : '↓')}
                </TableHead>
                <TableHead>Trend</TableHead>
                <TableHead onClick={() => handleSort('y_intercept')} className="cursor-pointer hover:bg-gray-50">
                  Y-Intercept {sortField === 'y_intercept' && (sortOrder === 'asc' ? '↑' : '↓')}
                </TableHead>
                <TableHead onClick={() => handleSort('volatility')} className="cursor-pointer hover:bg-gray-50">
                  Volatility {sortField === 'volatility' && (sortOrder === 'asc' ? '↑' : '↓')}
                </TableHead>

                {/* Core factors */}
                <TableHead onClick={() => handleSort('train_b')} className="cursor-pointer hover:bg-gray-50">
                  Train β {sortField === 'train_b' && (sortOrder === 'asc' ? '↑' : '↓')}
                </TableHead>
                <TableHead onClick={() => handleSort('lag_train_b')} className="cursor-pointer hover:bg-gray-50">
                  Lag Train β {sortField === 'lag_train_b' && (sortOrder === 'asc' ? '↑' : '↓')}
                </TableHead>

                {/* AR(1) */}
                <TableHead onClick={() => handleSort('ar1_corr_10d')} className="cursor-pointer hover:bg-gray-50">
                  AR(1) Corr 10d {sortField === 'ar1_corr_10d' && (sortOrder === 'asc' ? '↑' : '↓')}
                </TableHead>
                <TableHead onClick={() => handleSort('ar1_corr_20d')} className="cursor-pointer hover:bg-gray-50">
                  AR(1) Corr 20d {sortField === 'ar1_corr_20d' && (sortOrder === 'asc' ? '↑' : '↓')}
                </TableHead>
                <TableHead onClick={() => handleSort('ar1_corr_60d')} className="cursor-pointer hover:bg-gray-50">
                  AR(1) Corr 60d {sortField === 'ar1_corr_60d' && (sortOrder === 'asc' ? '↑' : '↓')}
                </TableHead>

                {/* Sign persistence */}
                <TableHead onClick={() => handleSort('sign_persist_20d')} className="cursor-pointer hover:bg-gray-50">
                  Sign Persist 20d {sortField === 'sign_persist_20d' && (sortOrder === 'asc' ? '↑' : '↓')}
                </TableHead>
                <TableHead onClick={() => handleSort('sign_persist_60d')} className="cursor-pointer hover:bg-gray-50">
                  Sign Persist 60d {sortField === 'sign_persist_60d' && (sortOrder === 'asc' ? '↑' : '↓')}
                </TableHead>

                {/* Returns */}
                <TableHead onClick={() => handleSort('ret_1d')} className="cursor-pointer hover:bg-gray-50">
                  Return 1d {sortField === 'ret_1d' && (sortOrder === 'asc' ? '↑' : '↓')}
                </TableHead>
                <TableHead onClick={() => handleSort('ret_5d')} className="cursor-pointer hover:bg-gray-50">
                  Return 5d {sortField === 'ret_5d' && (sortOrder === 'asc' ? '↑' : '↓')}
                </TableHead>
                <TableHead onClick={() => handleSort('ret_20d')} className="cursor-pointer hover:bg-gray-50">
                  Return 20d {sortField === 'ret_20d' && (sortOrder === 'asc' ? '↑' : '↓')}
                </TableHead>

                {/* Volatilities */}
                <TableHead onClick={() => handleSort('vol_63d')} className="cursor-pointer hover:bg-gray-50">
                  Vol 63d {sortField === 'vol_63d' && (sortOrder === 'asc' ? '↑' : '↓')}
                </TableHead>
                <TableHead onClick={() => handleSort('vol_126d')} className="cursor-pointer hover:bg-gray-50">
                  Vol 126d {sortField === 'vol_126d' && (sortOrder === 'asc' ? '↑' : '↓')}
                </TableHead>
                <TableHead onClick={() => handleSort('vol_252d')} className="cursor-pointer hover:bg-gray-50">
                  Vol 252d {sortField === 'vol_252d' && (sortOrder === 'asc' ? '↑' : '↓')}
                </TableHead>
                <TableHead onClick={() => handleSort('vol_756d')} className="cursor-pointer hover:bg-gray-50">
                  Vol 756d {sortField === 'vol_756d' && (sortOrder === 'asc' ? '↑' : '↓')}
                </TableHead>

                {/* Z score of MA */}
                <TableHead onClick={() => handleSort('Z_ma_20d')} className="cursor-pointer hover:bg-gray-50">
                  Z-MA 20d {sortField === 'Z_ma_20d' && (sortOrder === 'asc' ? '↑' : '↓')}
                </TableHead>

                {/* Cross-sectional ranks */}
                <TableHead onClick={() => handleSort('cs_rank_ret_1d')} className="cursor-pointer hover:bg-gray-50">
                  Rank Return 1d {sortField === 'cs_rank_ret_1d' && (sortOrder === 'asc' ? '↑' : '↓')}
                </TableHead>
                <TableHead onClick={() => handleSort('cs_rank_ret_5d')} className="cursor-pointer hover:bg-gray-50">
                  Rank Return 5d {sortField === 'cs_rank_ret_5d' && (sortOrder === 'asc' ? '↑' : '↓')}
                </TableHead>
                <TableHead onClick={() => handleSort('cs_rank_ret_20d')} className="cursor-pointer hover:bg-gray-50">
                  Rank Return 20d {sortField === 'cs_rank_ret_20d' && (sortOrder === 'asc' ? '↑' : '↓')}
                </TableHead>

                <TableHead>Actions</TableHead>
              </TableRow>
            </TableHeader>

            <TableBody>
              {filteredData.map((item) => (
                <TableRow key={item.ticker}>
                  <TableCell className="font-medium">{item.ticker}</TableCell>
                  <TableCell>{item.created_at ? new Date(item.created_at).toLocaleString() : '—'}</TableCell>

                  <TableCell className="font-mono">{formatNumber(item.b_coefficient)}</TableCell>

                  {/* Trend Icon using Lucide */}
                  <TableCell>
                    {item.b_coefficient === null || item.b_coefficient === 0 ? (
                      <Minus className="h-4 w-4 text-gray-400" />
                    ) : item.b_coefficient > 0 ? (
                      <TrendingUp className="h-4 w-4 text-green-600" />
                    ) : (
                      <TrendingDown className="h-4 w-4 text-red-600" />
                    )}
                  </TableCell>

                  <TableCell className="font-mono">{formatNumber(item.y_intercept)}</TableCell>
                  <TableCell className="font-mono">{formatNumber(item.volatility)}</TableCell>

                  <TableCell className="font-mono">{formatNumber(item.train_b)}</TableCell>
                  <TableCell className="font-mono">{formatNumber(item.lag_train_b)}</TableCell>

                  <TableCell className="font-mono">{formatNumber(item.ar1_corr_10d)}</TableCell>
                  <TableCell className="font-mono">{formatNumber(item.ar1_corr_20d)}</TableCell>
                  <TableCell className="font-mono">{formatNumber(item.ar1_corr_60d)}</TableCell>

                  <TableCell className="font-mono">{formatNumber(item.sign_persist_20d)}</TableCell>
                  <TableCell className="font-mono">{formatNumber(item.sign_persist_60d)}</TableCell>

                  <TableCell className="font-mono">{formatNumber(item.ret_1d)}</TableCell>
                  <TableCell className="font-mono">{formatNumber(item.ret_5d)}</TableCell>
                  <TableCell className="font-mono">{formatNumber(item.ret_20d)}</TableCell>

                  <TableCell className="font-mono">{formatNumber(item.vol_63d)}</TableCell>
                  <TableCell className="font-mono">{formatNumber(item.vol_126d)}</TableCell>
                  <TableCell className="font-mono">{formatNumber(item.vol_252d)}</TableCell>
                  <TableCell className="font-mono">{formatNumber(item.vol_756d)}</TableCell>

                  <TableCell className="font-mono">{formatNumber(item.Z_ma_20d)}</TableCell>

                  <TableCell className="font-mono">{formatNumber(item.cs_rank_ret_1d)}</TableCell>
                  <TableCell className="font-mono">{formatNumber(item.cs_rank_ret_5d)}</TableCell>
                  <TableCell className="font-mono">{formatNumber(item.cs_rank_ret_20d)}</TableCell>

                  <TableCell>
                    <Button variant="outline" size="sm" onClick={() => onTickerSelect?.(item.ticker)}>
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