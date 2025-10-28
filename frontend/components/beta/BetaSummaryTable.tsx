'use client';

import React, { useEffect, useMemo, useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { TrendingUp, TrendingDown, Minus, BarChart3 } from 'lucide-react';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';

/**
 * A single row in the summary table. All fields that the table displays or sorts by
 * are represented here (mostly optional because some may not be present for every ticker).
 */
export interface BetaSummaryRow {
  ticker: string;

  // Dates
  created_at?: string | null;
  latest_date?: string | null;

  // Core metrics shown/sorted
  b_coefficient?: number | null;
  volatility?: number | null;

  // Factors / derived metrics
  train_b?: number | null;
  lag_train_b?: number | null;

  // AR(1) correlations
  ar1_corr_10d?: number | null;
  ar1_corr_20d?: number | null;
  ar1_corr_60d?: number | null;

  // Sign persistence
  sign_persist_20d?: number | null;
  sign_persist_60d?: number | null;

  // Returns
  ret_1d?: number | null;
  ret_5d?: number | null;
  ret_20d?: number | null;

  // Volatilities
  vol_63d?: number | null;
  vol_126d?: number | null;
  vol_252d?: number | null;
  vol_756d?: number | null;

  // Z score of moving average
  Z_ma_20d?: number | null;

  // Cross-sectional ranks
  cs_rank_ret_1d?: number | null;
  cs_rank_ret_5d?: number | null;
  cs_rank_ret_20d?: number | null;

  // Cross-sectional metrics
  xsec_disp_1d?: number | null;
  xsec_disp_30d?: number | null;

  // Horizon
  horizon_days?: number | null;

  // Optional meta used by filters but not necessarily displayed
  confidence_level?: string;
  avg_r2_ols?: number | null;
  prediction_accuracy?: number | null;
  forecast_count?: number | null;
  latest_beta_pred?: number | null;
  latest_beta_true?: number | null;

  r2_oos?: number | null;
  mae_oos?: number | null;
  rmse_oos?: number | null;
  diracc_oos?: number | null;
  predstd_oos?: number | null;
  n_oos?: number | null;
}

export interface BetaSummaryTableProps {
  data?: BetaSummaryRow[];
  loading?: boolean;
  onTickerSelect?: (ticker: string) => void;

  /** Table horizon filter (rendered in-table; state lives in parent) */
  horizons?: number[];
  selectedHorizons?: number[];
  onSelectedHorizonsChange?: (hs: number[]) => void;
}

// All sortable fields (must match keys in BetaSummaryRow)
type SortableField = keyof BetaSummaryRow;

export function BetaSummaryTable({
  data = [],
  loading = false,
  onTickerSelect,
  horizons,
  selectedHorizons,
  onSelectedHorizonsChange,
}: BetaSummaryTableProps) {
  const [filteredData, setFilteredData] = useState<BetaSummaryRow[]>(data);
  const [searchTicker, setSearchTicker] = useState('');
  const [confidenceFilter, setConfidenceFilter] = useState('all');
  const [sortField, setSortField] = useState<SortableField>('latest_date');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
  const [currentPage, setCurrentPage] = useState(1);

  // Rows per page selector
  const [rowsPerPage, setRowsPerPage] = useState<number | 'all'>(20);

  // Recompute filtered + sorted data whenever inputs change
  useEffect(() => {
    let working = [...data];

    // Search filter
    if (searchTicker) {
      const q = searchTicker.toLowerCase();
      working = working.filter((row) => row.ticker.toLowerCase().includes(q));
    }

    // Confidence filter (kept for future use)
    if (confidenceFilter !== 'all') {
      working = working.filter((row) => row.confidence_level === confidenceFilter);
    }

    // Sorting helpers
    const isStringField = (f: SortableField) => f === 'ticker';
    const isDateLikeField = (f: SortableField) => f === 'created_at' || f === 'latest_date';

    const toNumber = (row: BetaSummaryRow, f: SortableField): number => {
      if (isDateLikeField(f)) {
        const s = (row[f] as string | null | undefined) ?? null;
        return s ? new Date(s).getTime() : Number.NEGATIVE_INFINITY; // nulls/undefined last
      }
      const v = row[f] as number | null | undefined;
      return typeof v === 'number' ? v : Number.NEGATIVE_INFINITY;
    };

    working.sort((a, b) => {
      if (isStringField(sortField)) {
        const cmp = a.ticker.localeCompare(b.ticker);
        return sortOrder === 'asc' ? cmp : -cmp;
      }
      const av = toNumber(a, sortField);
      const bv = toNumber(b, sortField);
      return sortOrder === 'asc' ? av - bv : bv - av;
    });

    setFilteredData(working);
    setCurrentPage(1); // reset paging when filters/sort change
  }, [data, searchTicker, confidenceFilter, sortField, sortOrder]);

  // Reset to first page whenever rowsPerPage changes
  useEffect(() => {
    setCurrentPage(1);
  }, [rowsPerPage]);

  // Current page slice
  const paginatedData = useMemo(() => {
    if (rowsPerPage === 'all') return filteredData;
    const start = (currentPage - 1) * rowsPerPage;
    const end = currentPage * rowsPerPage;
    return filteredData.slice(start, end);
  }, [filteredData, currentPage, rowsPerPage]);

  const totalPages =
    rowsPerPage === 'all' ? 1 : Math.max(1, Math.ceil(filteredData.length / rowsPerPage));

  const handleSort = (field: SortableField) => {
    if (sortField === field) {
      setSortOrder((o) => (o === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortField(field);
      setSortOrder('desc');
    }
  };

  const formatNumber = (num: number | null | undefined, decimals = 3) => {
    if (num === null || num === undefined) return 'N/A';
    return num.toFixed(decimals);
  };

  // Checkbox horizon control wiring
  const allHorizons = horizons ?? [];
  const selectedHs = selectedHorizons ?? [];
  const canUseHorizonControl =
    allHorizons.length > 0 && onSelectedHorizonsChange !== undefined;

  const toggleHorizon = (h: number, checked: boolean) => {
    if (!onSelectedHorizonsChange) return;
    if (checked) {
      const next = Array.from(new Set([...selectedHs, h])).sort((a, b) => a - b);
      onSelectedHorizonsChange(next);
    } else {
      onSelectedHorizonsChange(selectedHs.filter((x) => x !== h));
    }
  };

  const selectAllHorizons = () => {
    if (!onSelectedHorizonsChange) return;
    onSelectedHorizonsChange([...allHorizons].sort((a, b) => a - b));
  };

  const clearAllHorizons = () => {
    if (!onSelectedHorizonsChange) return;
    onSelectedHorizonsChange([]);
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
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900" />
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
        <CardDescription>Latest beta predictions and performance metrics for all tracked stocks</CardDescription>
      </CardHeader>

      <CardContent>
        {/* Toolbar: grid makes alignment predictable across breakpoints */}
        <div className="grid gap-4 items-center mb-6 grid-cols-1 md:grid-cols-[minmax(260px,1fr)_auto_auto]">
          {/* Search (left, grows) */}
          <div className="min-w-[220px]">
            <Input
              placeholder="Search ticker…"
              value={searchTicker}
              onChange={(e) => setSearchTicker(e.target.value)}
              className="h-9"
            />
          </div>

          {/* Horizon checkboxes (center) */}
          {canUseHorizonControl ? (
            <div
              className="flex items-center gap-3 flex-wrap"
              role="group"
              aria-labelledby="hz-filter-label"
            >
              <span id="hz-filter-label" className="text-sm text-muted-foreground shrink-0">
                Horizon (table):
              </span>

              {/* All / None actions */}
              <div className="flex items-center gap-2 shrink-0">
                <Button type="button" variant="outline" size="sm" className="h-9" onClick={selectAllHorizons}>
                  All
                </Button>
                <Button type="button" variant="outline" size="sm" className="h-9" onClick={clearAllHorizons}>
                  None
                </Button>
              </div>

              {/* Checkbox list — inline, wraps neatly */}
              <div className="flex flex-wrap items-center gap-3 max-w-[68rem]">
                {allHorizons.map((h) => {
                  const id = `hz-${h}`;
                  const checked = selectedHs.includes(h);
                  return (
                    <div key={id} className="flex items-center gap-2">
                      <Checkbox
                        id={id}
                        checked={checked}
                        onCheckedChange={(v) => toggleHorizon(h, v === true)}
                        className="h-4 w-4"
                      />
                      <Label htmlFor={id} className="text-sm leading-none">
                        {h}d
                      </Label>
                    </div>
                  );
                })}
              </div>
            </div>
          ) : (
            <div />
          )}

          {/* Rows selector (right) */}
          <div className="flex items-center gap-2 justify-start md:justify-end">
            <span className="text-sm text-muted-foreground">Rows:</span>
            <Select
              value={rowsPerPage === 'all' ? 'all' : String(rowsPerPage)}
              onValueChange={(v) => setRowsPerPage(v === 'all' ? 'all' : Number(v))}
            >
              <SelectTrigger className="w-[120px] h-9">
                <SelectValue placeholder="Rows" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="20">20</SelectItem>
                <SelectItem value="50">50</SelectItem>
                <SelectItem value="100">100</SelectItem>
                <SelectItem value="all">All</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        {/* Results Summary */}
        <div className="mb-4 text-sm text-muted-foreground">
          Showing {rowsPerPage === 'all' ? filteredData.length : paginatedData.length} of {filteredData.length} filtered stocks
          {filteredData.length !== data.length ? ` (from ${data.length} total)` : ''}
        </div>

        {/* Table */}
        <div className="rounded-md border overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead
                  onClick={() => handleSort('ticker')}
                  className="sticky left-0 z-30 bg-background cursor-pointer hover:bg-gray-50 w-36 min-w-[9rem] border-r"
                >
                  Ticker {sortField === 'ticker' && (sortOrder === 'asc' ? '↑' : '↓')}
                </TableHead>

                <TableHead onClick={() => handleSort('created_at')} className="cursor-pointer hover:bg-gray-50">
                  Created At {sortField === 'created_at' && (sortOrder === 'asc' ? '↑' : '↓')}
                </TableHead>

                {/* Horizon immediately to the right of Created At */}
                <TableHead onClick={() => handleSort('horizon_days')} className="cursor-pointer hover:bg-gray-50">
                  Horizon (d) {sortField === 'horizon_days' && (sortOrder === 'asc' ? '↑' : '↓')}
                </TableHead>

                <TableHead onClick={() => handleSort('b_coefficient')} className="cursor-pointer hover:bg-gray-50">
                  β Coefficient {sortField === 'b_coefficient' && (sortOrder === 'asc' ? '↑' : '↓')}
                </TableHead>

                <TableHead>Trend</TableHead>

                <TableHead onClick={() => handleSort('r2_oos')} className="cursor-pointer hover:bg-gray-50">
                  R2 OOS {sortField === 'r2_oos' && (sortOrder === 'asc' ? '↑' : '↓')}
                </TableHead>

                {/* Next three right after R2 OOS */}
                <TableHead onClick={() => handleSort('rmse_oos')} className="cursor-pointer hover:bg-gray-50">
                  RMSE OOS {sortField === 'rmse_oos' && (sortOrder === 'asc' ? '↑' : '↓')}
                </TableHead>
                <TableHead onClick={() => handleSort('mae_oos')} className="cursor-pointer hover:bg-gray-50">
                  MAE OOS {sortField === 'mae_oos' && (sortOrder === 'asc' ? '↑' : '↓')}
                </TableHead>
                <TableHead onClick={() => handleSort('diracc_oos')} className="cursor-pointer hover:bg-gray-50">
                  DirAcc OOS {sortField === 'diracc_oos' && (sortOrder === 'asc' ? '↑' : '↓')}
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

                <TableHead onClick={() => handleSort('xsec_disp_1d')} className="cursor-pointer hover:bg-gray-50">
                  XSec 1d {sortField === 'xsec_disp_1d' && (sortOrder === 'asc' ? '↑' : '↓')}
                </TableHead>
                <TableHead onClick={() => handleSort('xsec_disp_30d')} className="cursor-pointer hover:bg-gray-50">
                  XSec 30d {sortField === 'xsec_disp_30d' && (sortOrder === 'asc' ? '↑' : '↓')}
                </TableHead>
              </TableRow>
            </TableHeader>

            <TableBody>
              {paginatedData.map((item) => {
                const rowKey = `${item.ticker}::${item.horizon_days ?? 'na'}::${item.created_at ?? ''}`;
                return (
                  <TableRow key={rowKey}>
                    <TableCell className="sticky left-0 z-20 bg-background w-36 min-w-[9rem] border-r">
                      <Button variant="outline" size="sm" onClick={() => onTickerSelect?.(item.ticker)}>
                        {item.ticker}
                      </Button>
                    </TableCell>

                    <TableCell>
                      {item.created_at ? new Date(item.created_at).toLocaleString() : '—'}
                    </TableCell>

                    {/* Horizon right after Created At */}
                    <TableCell className="font-mono">{item.horizon_days ?? '—'}</TableCell>

                    <TableCell className="font-mono">{formatNumber(item.b_coefficient)}</TableCell>

                    {/* Trend icon from β coefficient */}
                    <TableCell>
                      {item.b_coefficient === null || item.b_coefficient === undefined || item.b_coefficient === 0 ? (
                        <Minus className="h-4 w-4 text-gray-400" />
                      ) : item.b_coefficient > 0 ? (
                        <TrendingUp className="h-4 w-4 text-green-600" />
                      ) : (
                        <TrendingDown className="h-4 w-4 text-red-600" />
                      )}
                    </TableCell>

                    <TableCell className="font-mono">{formatNumber(item.r2_oos)}</TableCell>

                    {/* OOS metrics */}
                    <TableCell className="font-mono">{formatNumber(item.rmse_oos)}</TableCell>
                    <TableCell className="font-mono">{formatNumber(item.mae_oos)}</TableCell>
                    <TableCell className="font-mono">{formatNumber(item.diracc_oos)}</TableCell>

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

                    <TableCell className="font-mono">{formatNumber(item.xsec_disp_1d)}</TableCell>
                    <TableCell className="font-mono">{formatNumber(item.xsec_disp_30d)}</TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>

        {/* Pagination Controls */}
        {rowsPerPage !== 'all' && filteredData.length > rowsPerPage && (
          <div className="flex justify-center items-center gap-3 mt-4">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setCurrentPage((p) => Math.max(p - 1, 1))}
              disabled={currentPage === 1}
            >
              Previous
            </Button>

            <span className="text-sm text-muted-foreground">
              Page {currentPage} of {totalPages}
            </span>

            <Button
              variant="outline"
              size="sm"
              onClick={() => setCurrentPage((p) => Math.min(p + 1, totalPages))}
              disabled={currentPage === totalPages}
            >
              Next
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
