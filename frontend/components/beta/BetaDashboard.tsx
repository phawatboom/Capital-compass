"use client";

import React, { useState, useEffect, useMemo } from "react";
import { BetaSummaryTable } from "@/components/beta/BetaSummaryTable";
import { BetaTimeSeriesChart } from "@/components/beta/BetaTimeSeriesChart";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { AlertCircle, Info } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectTrigger,
  SelectContent,
  SelectItem,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";

/** API base URL – configure in frontend/.env.local: NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000 */
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "/api";
const usingDefaultApiBase = (API_BASE || "").trim() === "/api";

/** Join a base (absolute or relative) with a resource path safely. */
const api = (path: string) => {
  const base = (API_BASE || "").replace(/\/+$/, "");
  const p = (path || "").replace(/^\/+/, "");
  return `${base}/${p}`;
};

/** Safely encode path segments like tickers. */
const seg = (s: string) => encodeURIComponent(String(s).trim());

/** Horizons we’ll probe on the public FactorSharedStats endpoint, in case user runs are missing or auth-gated. */
const HORIZON_GUESSES = [1, 5, 10, 20, 30, 60, 63, 90, 126, 252] as const;

interface BetaSummary {
  ticker: string;
  latest_date: string;
  latest_beta_pred: number;
  latest_beta_true: number | null;
  avg_r2_ols: number;
  prediction_accuracy: number | null;
  forecast_count: number;
  confidence_level: string;

  r2_oos?: number | null;
  mae_oos?: number | null;
  rmse_oos?: number | null;
  diracc_oos?: number | null;
  predstd_oos?: number | null;
  n_oos?: number | null;
  horizon_days?: number | null;
}

interface BetaTimeSeriesData {
  ticker: string;
  horizon?: number | null;
  dates: string[];
  beta_pred: number[];
  beta_true: (number | null)[];
  confidence_bands: Array<{ lower: number; upper: number }>;
}

type RunSummary = {
  id: number;
  run_name?: string;
  horizon_days?: number;
  created_at?: string;
};

type NumericLike = number | `${number}`;

type SharedStats = {
  id?: number;
  horizon_days?: number;
  r2_global?: number;
  volatility_coeff?: number;
  y_intercept?: number;
  model_equation?: string;
  training_days?: number;
  testing_days?: number;
  enet_alpha?: number;
  enet_l1_ratio?: number;
  run_params?: Record<string, unknown>;

  [key: `coef_${string}`]: NumericLike | null | undefined;
  [key: `avg_${string}`]: NumericLike | null | undefined;
};

const isFiniteNumber = (v: unknown): v is number =>
  typeof v === "number" && Number.isFinite(v);

function fmtNum(v: unknown) {
  const n = Number(v);
  if (!Number.isFinite(n)) return "N/A";
  const a = Math.abs(n);
  if (a > 0 && a < 1e-4) return n.toExponential(2);
  return n.toFixed(4);
}

const prettyKey = (k: string) =>
  k.replace(/^avg_/, "Average ").replace(/^coef_/, "Coefficient ").replace(/_/g, " ");

const EPS = 1e-12;
const fmtWeight = (v: number) => (Math.abs(v) < EPS ? "N/A" : v.toFixed(4));
const isNonZero = (v: unknown) =>
  Number.isFinite(Number(v)) && Math.abs(Number(v as number)) > EPS;

const FEATURE_ORDER = [
  "ret_1d",
  "ret_5d",
  "ret_20d",
  "train_b",
  "lag_train_b",
  "ar1_corr_10d",
  "ar1_corr_20d",
  "ar1_corr_60d",
  "sign_persist_20d",
  "sign_persist_60d",
  "vol_63d",
  "vol_126d",
  "vol_252d",
  "vol_756d",
  "Z_ma_20d",
  "xsec_disp_1d",
  "xsec_disp_30d",
  "cs_rank_ret_1d",
  "cs_rank_ret_5d",
  "cs_rank_ret_20d",
  "cs_rank_vol_63d",
  "cs_rank_vol_126d",
  "cs_rank_vol_252d",
  "cs_rank_vol_756d",
  "cs_rank_z_ma_20d",
];

function buildEquationFromShared(shared: SharedStats) {
  const intercept = Number(shared.y_intercept ?? 0);
  const pieces: string[] = [];
  for (const f of FEATURE_ORDER) {
    const key = `coef_${f}` as const;
    const raw = shared[key];
    const val = Number(raw ?? 0);
    if (!Number.isFinite(val) || Math.abs(val) < EPS) continue;
    const sign = val >= 0 ? "+" : "-";
    pieces.push(` ${sign}${Math.abs(val).toFixed(6)}·${f}`);
  }
  if (pieces.length === 0) return `y = ${intercept.toFixed(6)}`;
  return `y = ${intercept.toFixed(6)}${pieces.join("")}`;
}

/* ===== Duplicate-ticker fix (table-only) ===== */

const ZW = "\u200B";
const STRIP_ZW_RE = /[\u200B\u200C\u200D\uFEFF]/g;

function stripZeroWidth(s: string) {
  return s.replace(STRIP_ZW_RE, "");
}

function makeTableSafeRows(rows: BetaSummary[]): BetaSummary[] {
  const groups = new Map<string, BetaSummary[]>();
  for (const r of rows) {
    const base = stripZeroWidth(r.ticker);
    if (!groups.has(base)) groups.set(base, []);
    groups.get(base)!.push(r);
  }
  const out: BetaSummary[] = [];
  for (const [base, arr] of groups) {
    if (arr.length === 1) {
      out.push({ ...arr[0], ticker: base });
      continue;
    }
    const sorted = [...arr].sort((a, b) => {
      const ha = a.horizon_days ?? Number.POSITIVE_INFINITY;
      const hb = b.horizon_days ?? Number.POSITIVE_INFINITY;
      if (ha !== hb) return ha - hb;
      const da = a.latest_date ?? "";
      const db = b.latest_date ?? "";
      if (da !== db) return da.localeCompare(db);
      return Number(a.latest_beta_pred) - Number(b.latest_beta_pred);
    });
    sorted.forEach((row, idx) => {
      const uniqueTicker = base + ZW.repeat(idx + 1);
      out.push({ ...row, ticker: uniqueTicker });
    });
  }
  return out;
}

export function BetaDashboard() {
  const [summaryData, setSummaryData] = useState<BetaSummary[]>([]);
  const [timeSeriesData, setTimeSeriesData] = useState<BetaTimeSeriesData | null>(null);
  const [selectedTicker, setSelectedTicker] = useState<string>("");

  const [loading, setLoading] = useState(false);
  const [timeSeriesLoading, setTimeSeriesLoading] = useState(false);
  const [error, setError] = useState<string>("");
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const [sharedStats, setSharedStats] = useState<SharedStats | null>(null);
  const [showMore, setShowMore] = useState(false);

  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);

  const [availableHorizons, setAvailableHorizons] = useState<number[]>([]);
  const [horizon, setHorizon] = useState<number | null>(null);

  /** Horizons shown in the table (filter lives visually inside the table) */
  const [selectedTableHorizons, setSelectedTableHorizons] = useState<number[]>([]);

  const [isDialogOpen, setIsDialogOpen] = useState(false);

  const selectedRun = useMemo(
    () => runs.find((r) => r.id === selectedRunId) || null,
    [runs, selectedRunId]
  );

  const horizonCounts = useMemo(() => {
    const m = new Map<number, number>();
    for (const r of runs) {
      if (typeof r.horizon_days === "number") {
        m.set(r.horizon_days, (m.get(r.horizon_days) ?? 0) + 1);
      }
    }
    return m;
  }, [runs]);

  useEffect(() => {
    let cancelled = false;

    async function fetchRuns(): Promise<RunSummary[]> {
      try {
        const res = await fetch(api("analysis-runs/"), {
          credentials: "include",
          headers: { "Content-Type": "application/json" },
        });
        if (!res.ok) throw new Error(`runs ${res.status} ${res.statusText}`);
        return (await res.json()) as RunSummary[];
      } catch {
        return [];
      }
    }

    async function probeHorizon(h: number): Promise<boolean> {
      try {
        const r = await fetch(api(`factor-stats/latest/summary/?horizon=${h}`), {
          credentials: "include",
          headers: { "Content-Type": "application/json" },
        });
        return r.ok;
      } catch {
        return false;
      }
    }

    (async () => {
      const [runData, probeFlags] = await Promise.all([
        fetchRuns(),
        Promise.all(HORIZON_GUESSES.map((h) => probeHorizon(h))),
      ]);

      if (cancelled) return;

      setRuns(runData || []);
      if (runData?.length) setSelectedRunId(runData[0].id);

      const fromRuns = (runData || [])
        .map((r) => r.horizon_days)
        .filter((x): x is number => typeof x === "number");
      const fromProbes = HORIZON_GUESSES.filter((_, i) => probeFlags[i]);

      const merged = Array.from(new Set([...fromRuns, ...fromProbes])).sort(
        (a, b) => a - b
      );

      setAvailableHorizons(merged);

      if (merged.length) {
        if (horizon == null || !merged.includes(horizon)) setHorizon(merged[0]);
        setSelectedTableHorizons(merged);
      }
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (selectedRun && typeof selectedRun.horizon_days === "number") {
      setHorizon((prev) => (prev == null ? selectedRun.horizon_days! : prev));
    }
  }, [selectedRunId, selectedRun]);

  useEffect(() => {
    let cancelled = false;

    async function fetchShared(h: number) {
      const res = await fetch(api(`factor-stats/latest/summary/?horizon=${h}`), {
        credentials: "include",
        headers: { "Content-Type": "application/json" },
      });
      if (res.status === 404) return { ok: false as const, status: 404, payload: null };
      if (!res.ok) return { ok: false as const, status: res.status, payload: await res.text() };
      return { ok: true as const, status: 200, payload: (await res.json()) as SharedStats };
    }

    (async () => {
      try {
        if (horizon == null) {
          setSharedStats(null);
          return;
        }
        const r = await fetchShared(horizon);
        if (cancelled) return;
        if (r.ok && r.payload) {
          setSharedStats(r.payload);
        } else {
          setSharedStats(null);
          setError((prev) => prev || `shared ${r.status} Not Found`);
        }
      } catch (e: any) {
        if (!cancelled) {
          setSharedStats(null);
          setError((prev) => prev || e?.message || "Failed to fetch shared stats");
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [horizon]);

  useEffect(() => {
    const sharedId = (sharedStats as any)?.id as number | undefined;
    const sharedH = (sharedStats as any)?.horizon_days as number | undefined;
    if (!sharedId || !sharedH) return;
    if (summaryData.length === 0) return;

    (async () => {
      try {
        const res = await fetch(api(`factor-stats/${sharedId}/oos/?min_n=10`), {
          credentials: "include",
          headers: { "Content-Type": "application/json" },
        });
        if (!res.ok) throw new Error(`oos ${res.status} ${res.statusText}`);
        const oos = (await res.json()) as Array<{
          ticker: string;
          r2_oos: number | null;
          rmse_oos?: number | null;
          mae_oos?: number | null;
          diracc_oos?: number | null;
          predstd_oos?: number | null;
          n_oos?: number | null;
        }>;
        const byTicker = new Map(oos.map((r) => [r.ticker, r]));
        setSummaryData((prev) =>
          prev.map((row) => {
            if (row.horizon_days !== sharedH) return row;
            const m = byTicker.get(row.ticker);
            return m
              ? {
                  ...row,
                  r2_oos: m.r2_oos ?? null,
                  rmse_oos: m.rmse_oos ?? null,
                  mae_oos: m.mae_oos ?? null,
                  diracc_oos: m.diracc_oos ?? null,
                  predstd_oos: m.predstd_oos ?? row.predstd_oos ?? null,
                  n_oos: m.n_oos ?? row.n_oos ?? null,
                }
              : row;
          })
        );
      } catch (e: any) {
        setError((prev) => prev || e?.message || "Failed to fetch OOS metrics");
      }
    })();
  }, [sharedStats, summaryData.length]);

  /** Fetch and merge summary rows for the horizons selected in the table control */
  useEffect(() => {
    const fetchSummaryDataMulti = async (hs: number[]) => {
      setLoading(true);
      setError("");
      try {
        const merged: BetaSummary[] = [];
        for (const h of hs) {
          const response = await fetch(api(`factors/summary/?horizon=${h}`), {
            credentials: "include",
            headers: { "Content-Type": "application/json" },
          });
          if (!response.ok)
            throw new Error(`summary(h=${h}) ${response.status} ${response.statusText}`);
          const json = await response.json();
          const rows: BetaSummary[] = (json?.summary ?? []).map((r: BetaSummary) => ({
            ...r,
            horizon_days: r.horizon_days ?? h,
          }));
          merged.push(...rows);
        }
        setSummaryData(merged);
        setLastUpdated(new Date());
      } catch (err: any) {
        setSummaryData([]);
        setError(err?.message ?? "Failed to fetch summary data");
      } finally {
        setLoading(false);
      }
    };

    if (selectedTableHorizons.length === 0) {
      setSummaryData([]);
      return;
    }
    fetchSummaryDataMulti(selectedTableHorizons);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTableHorizons.join(",")]);

  const handleDialogOpenChange = (open: boolean) => setIsDialogOpen(open);

  const fetchTimeSeriesData = async (ticker: string) => {
    if (!ticker || horizon == null) return;
    setTimeSeriesLoading(true);
    setError("");

    const tryFetch = async (symbol: string) => {
      const url = api(`beta/timeseries/${seg(symbol)}/?horizon=${horizon}`);
      return fetch(url, {
        credentials: "include",
        headers: { "Content-Type": "application/json" },
      });
    };

    try {
      let res = await tryFetch(ticker);
      if (res.status === 404 && ticker.includes("/")) {
        const aliasDash = ticker.replace(/\//g, "-").trim();
        res = await tryFetch(aliasDash);
        if (res.status === 404) {
          const aliasNoSlash = ticker.replace(/\//g, "").trim();
          res = await tryFetch(aliasNoSlash);
        }
      }
      if (!res.ok) {
        const msg = `series ${res.status} ${res.statusText}`;
        setTimeSeriesData(null);
        throw new Error(msg);
      }
      const data = (await res.json()) as BetaTimeSeriesData;
      setTimeSeriesData(data);
    } catch (err: any) {
      setError((prev) => prev || err?.message || "Failed to fetch time series data");
    } finally {
      setTimeSeriesLoading(false);
    }
  };

  const handleTickerSelect = (tickerPossiblyWithZW: string) => {
    const clean = stripZeroWidth(tickerPossiblyWithZW);
    setSelectedTicker(clean);
    setIsDialogOpen(true);
    setTimeSeriesData(null);
    fetchTimeSeriesData(clean);
  };

  const eqFromShared = useMemo(() => {
    if (!sharedStats) return "N/A";
    const stored = (sharedStats as any).model_equation as string | undefined;
    return stored && stored.trim().length > 0 ? stored : buildEquationFromShared(sharedStats);
  }, [sharedStats]);

  const tableData = useMemo(() => makeTableSafeRows(summaryData), [summaryData]);

  // @ts-ignore
    // @ts-ignore
    return (
    <div className="space-y-6">


      {/* Header */}
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
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

        {runs.length > 0 && (
          <div className="w-full md:w-auto md:ml-6">
            <div className="w-full overflow-x-auto pb-1">
              <div className="inline-flex gap-2">
                {runs.map((run) => (
                  <button
                    key={run.id}
                    onClick={() => setSelectedRunId(run.id)}
                    className={[
                      "px-3 py-1 text-sm rounded-full border",
                      selectedRunId === run.id
                        ? "bg-primary text-primary-foreground"
                        : "bg-background",
                    ].join(" ")}
                    title={`${run.run_name ?? "Run"} • ${
                      run.horizon_days ?? "-"
                    }d • ${
                      run.created_at ? new Date(run.created_at).toLocaleString() : ""
                    }`}
                  >
                    {run.run_name ?? `Run #${run.id}`}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Two-column row: Horizon controls + Run hyperparameters */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card className="w-full">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Horizon controls</CardTitle>
            <CardDescription>
              The active horizon informs the global information cards, model equation, and time-series.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <div className="flex items-center gap-3">
              <div className="text-xs text-muted-foreground">Active horizon</div>
              <Select
                value={horizon != null ? String(horizon) : undefined}
                onValueChange={(v) => setHorizon(Number(v))}
              >
                <SelectTrigger className="w-[220px] h-9 font-medium shadow-sm">
                  <SelectValue placeholder="Select horizon" />
                </SelectTrigger>
                <SelectContent>
                  {availableHorizons.map((h) => (
                    <SelectItem key={h} value={String(h)}>
                      {h} days
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {availableHorizons.length > 0 && (
              <div className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
                <span>Available horizons:</span>
                {availableHorizons.map((h) => (
                  <Badge key={h} variant="secondary">
                    {h}d
                    {horizonCounts.get(h)
                      ? ` • ${horizonCounts.get(h)} run${
                          (horizonCounts.get(h) ?? 0) > 1 ? "s" : ""
                        }`
                      : ""}
                  </Badge>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {sharedStats && (
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Run hyperparameters</CardTitle>
              <CardDescription>Horizon {sharedStats.horizon_days ?? "?"}d</CardDescription>
            </CardHeader>
            <CardContent className="text-sm space-y-1">
              <div>Training window: {sharedStats.training_days ?? "N/A"} days</div>
              <div>Testing window: {sharedStats.testing_days ?? "N/A"} days</div>
              <div>
                ElasticNet α:{" "}
                {typeof sharedStats.enet_alpha === "number" ? sharedStats.enet_alpha.toFixed(6) : "N/A"}
              </div>
              <div>
                L1 ratio:{" "}
                {typeof sharedStats.enet_l1_ratio === "number" ? sharedStats.enet_l1_ratio.toFixed(3) : "N/A"}
              </div>
              {sharedStats.run_params && (
                <details className="mt-2">
                  <summary className="cursor-pointer">Parameters passed to the model</summary>
                  <pre className="mt-2 text-xs whitespace-pre-wrap break-words border rounded p-2">
{JSON.stringify(sharedStats.run_params, null, 2)}
                  </pre>
                </details>
              )}
            </CardContent>
          </Card>
        )}
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* Model Equation */}
      <Card className="md:col-span-2">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">Model Equation</CardTitle>
          {sharedStats?.horizon_days != null && (
            <CardDescription>Horizon {sharedStats.horizon_days}d</CardDescription>
          )}
        </CardHeader>
        <CardContent>
          <>
            <div
              className="font-mono text-sm whitespace-pre-wrap break-words max-h-40 overflow-auto rounded border p-2"
              title={eqFromShared}
            >
              {eqFromShared}
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              ElasticNet regression form used for the selected horizon
            </p>
            {eqFromShared !== "N/A" && (
              <Button variant="outline" size="sm" className="mt-2" onClick={() => navigator.clipboard.writeText(eqFromShared)}>
                Copy equation
              </Button>
            )}
          </>
        </CardContent>
      </Card>

      {/* KPI cards + 5th CTA card */}
      {sharedStats && (
        <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Global R² Score</CardTitle>
              <CardDescription>Horizon {sharedStats.horizon_days ?? "?"}d</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {typeof sharedStats.r2_global === "number" ? sharedStats.r2_global.toFixed(4) : "N/A"}
              </div>
              <p className="text-xs text-muted-foreground">Model fit across tickers</p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Y-Intercept</CardTitle>
              <CardDescription>Average across tickers</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {typeof sharedStats.y_intercept === "number" ? sharedStats.y_intercept.toFixed(3) : "N/A"}
              </div>
              <p className="text-xs text-muted-foreground">Baseline term</p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Top Positive Factor</CardTitle>
            </CardHeader>
            <CardContent>
              {(() => {
                const coefEntries = Object.entries(sharedStats ?? {}).filter(
                  (e): e is [string, number] => e[0].startsWith("coef_") && isFiniteNumber(e[1])
                );
                if (coefEntries.length === 0) return <div className="text-sm text-gray-500">N/A</div>;
                const top = [...coefEntries].sort((a, b) => b[1] - a[1])[0];
                const topVal = Number(top[1]);
                const isZeroish = Math.abs(topVal) < EPS;
                return (
                  <>
                    <div className="text-2xl font-bold">{isZeroish ? "N/A" : top[0].replace("coef_", "")}</div>
                    <p className="text-xs text-muted-foreground">Weight: {fmtWeight(topVal)}</p>
                  </>
                );
              })()}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Top Negative Factor</CardTitle>
            </CardHeader>
            <CardContent>
              {(() => {
                const coefEntries = Object.entries(sharedStats ?? {}).filter(
                  (e): e is [string, number] => e[0].startsWith("coef_") && isFiniteNumber(e[1])
                );
                if (coefEntries.length === 0) return <div className="text-sm text-gray-500">N/A</div>;
                const bottom = [...coefEntries].sort((a, b) => a[1] - b[1])[0];
                return (
                  <>
                    <div className="text-2xl font-bold">{bottom[0].replace("coef_", "")}</div>
                    <p className="text-xs text-muted-foreground">Weight: {fmtWeight(bottom[1])}</p>
                  </>
                );
              })()}
            </CardContent>
          </Card>

          <Card
            role="button"
            tabIndex={0}
            aria-pressed={showMore}
            onClick={() => setShowMore((v) => !v)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                setShowMore((v) => !v);
              }
            }}
            className={[
              "relative overflow-hidden cursor-pointer",
              "border-2 border-primary/50 bg-gradient-to-br from-primary/10 to-transparent",
              "hover:from-primary/20 hover:to-primary/5 transition-all",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary",
              "group",
            ].join(" ")}
            title={showMore ? "Hide detailed metrics and coefficients" : "Show detailed metrics and coefficients"}
          >
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-semibold flex items-center gap-2">
                {showMore ? "Hide detailed information" : "Show more information"}
              </CardTitle>
              <CardDescription>
                {showMore ? "Collapse extended metrics & factors" : "Expand extended metrics & factors"}
              </CardDescription>
            </CardHeader>
            <CardContent />
          </Card>
        </div>
      )}

      {showMore && sharedStats && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5 auto-rows-fr">
          {(() => {
            const exclude = new Set<string>([
              "r2_global",
              "volatility_coeff",
              "y_intercept",
              "horizon_days",
              "model_equation",
              "training_days",
              "testing_days",
              "enet_alpha",
              "enet_l1_ratio",
              "run_params",
              "id",
            ]);
            const rest = Object.entries(sharedStats)
              .filter(([k, v]) => (k.startsWith("avg_") || k.startsWith("coef_")) && !exclude.has(k))
              .filter(([, v]) => isNonZero(v))
              .sort(([a], [b]) => a.localeCompare(b));
            return rest.map(([k, v]) => (
              <Card key={k} className="w-full min-w-0">
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium truncate">{prettyKey(k)}</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">{fmtNum(v)}</div>
                  <p className="text-xs text-muted-foreground">
                    {k.startsWith("avg_") ? "Cross-universe average" : "Model coefficient"}
                  </p>
                </CardContent>
              </Card>
            ));
          })()}
        </div>
      )}

      {/* Summary Table — now renders the horizon filter in its own toolbar */}
      <BetaSummaryTable
        data={tableData}
        loading={loading}
        onTickerSelect={handleTickerSelect}
        horizons={availableHorizons}
        selectedHorizons={selectedTableHorizons}
        onSelectedHorizonsChange={setSelectedTableHorizons}
      />

      {/* Time Series Modal */}
      <Dialog open={isDialogOpen} onOpenChange={handleDialogOpenChange}>
        <DialogContent className="sm:max-w-[1200px] w-[95vw]">
          <DialogHeader>
            <DialogTitle>
              {selectedTicker ? `Time Series — ${selectedTicker}` : "Time Series"}
            </DialogTitle>
            <DialogDescription>
              Historical and predicted beta with confidence bands
              {horizon != null ? ` (horizon ${horizon}d)` : ""}.
            </DialogDescription>
          </DialogHeader>

          <div className="mt-2">
            {timeSeriesLoading ? (
              <div className="h-64 flex items-center justify-center text-muted-foreground">Loading…</div>
            ) : timeSeriesData ? (
              <BetaTimeSeriesChart data={timeSeriesData} loading={false} />
            ) : (
              <div className="h-64 flex flex-col items-center justify-center text-center text-muted-foreground">
                <div className="mb-2">No time series data available for this ticker.</div>
                <div className="text-xs">
                  If the symbol contains a slash (e.g., BRK/B), it may require an alias on the backend (e.g., BRK-B or BRKB).
                </div>
              </div>
            )}
          </div>

          <DialogFooter className="mt-4">
            <DialogClose asChild>
              <Button variant="outline">Close</Button>
            </DialogClose>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
