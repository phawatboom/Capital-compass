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
import { AlertCircle } from "lucide-react";
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

// ADD: just below other ui imports
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

/** API base URL - adjust based on your backend configuration */
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/** Build absolute URLs robustly and safely encode path segments */
const api = (path: string) => new URL(path, API_BASE).toString();
const seg = (s: string) => encodeURIComponent(String(s).trim());

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

type RunSummary = {
  id: number;
  run_name?: string;
  horizon_days?: number;
  created_at?: string;
};

/** Accept numbers or numeric-looking strings from the API */
type NumericLike = number | `${number}`;

/** Shared stats shape: known scalars plus "coef_*" entries */
type SharedStats = {
  r2_global?: number;
  volatility_coeff?: number;
  y_intercept?: number;

  // add these
  model_equation?: string;
  training_days?: number;
  testing_days?: number;
  enet_alpha?: number;
  enet_l1_ratio?: number;

  
  // Coefficients (from your DB screenshots)
  coef_train_b?: NumericLike | null;
  coef_lag_train_b?: NumericLike | null;
  coef_ar1_corr_10d?: NumericLike | null;
  coef_ar1_corr_20d?: NumericLike | null;
  coef_ar1_corr_60d?: NumericLike | null;
  coef_sign_persist_20d?: NumericLike | null;
  coef_sign_persist_60d?: NumericLike | null;
  coef_ret_1d?: NumericLike | null;
  coef_ret_5d?: NumericLike | null;
  coef_ret_20d?: NumericLike | null;
  coef_vol_63d?: NumericLike | null;
  coef_vol_126d?: NumericLike | null;
  coef_vol_252d?: NumericLike | null;
  coef_vol_756d?: NumericLike | null;
  coef_Z_ma_20d?: NumericLike | null;
  coef_cs_rank_ret_1d?: NumericLike | null;
  coef_cs_rank_ret_5d?: NumericLike | null;
  coef_cs_rank_ret_20d?: NumericLike | null;
  coef_cs_rank_z_ma_20d?: NumericLike | null;
  coef_cs_rank_vol_63d?: NumericLike | null;
  coef_cs_rank_vol_126d?: NumericLike | null;
  coef_cs_rank_vol_252d?: NumericLike | null;
  coef_cs_rank_vol_756d?: NumericLike | null;

  // Averages (from your DB screenshots)
  avg_train_b?: NumericLike | null;
  avg_lag_train_b?: NumericLike | null;
  avg_ar1_corr_10d?: NumericLike | null;
  avg_ar1_corr_20d?: NumericLike | null;
  avg_ar1_corr_60d?: NumericLike | null;
  avg_sign_persist_20d?: NumericLike | null;
  avg_sign_persist_60d?: NumericLike | null;
  avg_ret_1d?: NumericLike | null;
  avg_ret_5d?: NumericLike | null;
  avg_ret_20d?: NumericLike | null;
  avg_vol_63d?: NumericLike | null;
  avg_vol_126d?: NumericLike | null;
  avg_vol_252d?: NumericLike | null;
  avg_vol_756d?: NumericLike | null;
  avg_Z_ma_20d?: NumericLike | null;
  avg_cs_rank_ret_1d?: NumericLike | null;
  avg_cs_rank_ret_5d?: NumericLike | null;
  avg_cs_rank_ret_20d?: NumericLike | null;
  avg_cs_rank_z_ma_20d?: NumericLike | null;
  avg_cs_rank_vol_63d?: NumericLike | null;
  avg_cs_rank_vol_126d?: NumericLike | null;
  avg_cs_rank_vol_252d?: NumericLike | null;
  avg_cs_rank_vol_756d?: NumericLike | null;

  /** Future-proof fallbacks */
  [key: `coef_${string}`]: NumericLike | null | undefined;
  [key: `avg_${string}`]: NumericLike | null | undefined;
};


type Entry = [string, unknown];

const isFiniteNumber = (v: unknown): v is number =>
  typeof v === "number" && Number.isFinite(v);

// Guard for coef_* entries with numeric values
function isCoefEntryNumber(e: Entry): e is [string, number] {
  return e[0].startsWith("coef_") && isFiniteNumber(e[1]);
}

// Optional: a safe formatter for tiny numbers
function fmtNum(v: unknown) {
  const n = Number(v);
  if (!Number.isFinite(n)) return "N/A";
  const a = Math.abs(n);
  if (a > 0 && a < 1e-4) return n.toExponential(2);
  return n.toFixed(4);
}
// Pretty-print keys like "avg_cs_rank_vol_126d" → "Average cs rank vol 126d"
const prettyKey = (k: string) =>
  k
    .replace(/^avg_/, "Average ")
    .replace(/^coef_/, "Coefficient ")
    .replace(/_/g, " ");

const EPS = 1e-12;
const isNonZero = (v: unknown) =>
  Number.isFinite(Number(v)) && Math.abs(Number(v as number)) > EPS;

/** Type guard to narrow unknown → number */
// const isFiniteNumber = (v: unknown): v is number =>
//   typeof v === "number" && Number.isFinite(v);

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
  const [horizon, setHorizon] = useState(5);

  // Analysis run selection state
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);


  // Modal state
  const [isDialogOpen, setIsDialogOpen] = useState(false);

  useEffect(() => {
  fetch(api("/api/factors/shared/"))
    .then(res => res.json())
    .then(setSharedStats)
    .catch(() => {});
  }, []);

  // Load available analysis runs once
    useEffect(() => {
      (async () => {
        try {
          const data = await fetchRuns();
          setRuns(data || []);
          if (data?.length) setSelectedRunId(data[0].id);
        } catch {}
      })();
    }, []);

  useEffect(() => {
    // need both: shared stats id and a non-empty summary table
    const sharedId = (sharedStats as any)?.id as number | undefined;
    if (!sharedId || summaryData.length === 0) return;

    (async () => {
      const oos = await fetchOOS(sharedId);
      const byTicker = new Map(oos.map(r => [r.ticker, r.r2_oos]));
      setSummaryData(prev =>
        prev.map(row => ({
          ...row,
          r2_oos: byTicker.get(row.ticker) ?? null,
        })),
      );
    })();
    // depend on length to avoid loops when only values change
  }, [sharedStats, summaryData.length]);

  async function fetchRuns() {
    const res = await fetch(api("/api/analysis-runs/"), { credentials: "include" });
    if (!res.ok) return [];
    return await res.json();
  }


  useEffect(() => {
    if (!selectedRunId || !summaryData?.length) return;

    (async () => {
      try {
        const res = await fetch(api(`/api/analysis-runs/${selectedRunId}/performance/`), { credentials: "include" });
        if (!res.ok) return;
        const payload = await res.json();
        const rows = Array.isArray(payload?.results) ? payload.results : [];
        const r2ByTicker = new Map(rows.map((r: any) => [r.ticker, r.r2_oos]));
        setSummaryData(prev =>
          Array.isArray(prev)
            ? prev.map(row => ({ ...row, r2_oos: r2ByTicker.get(row.ticker) ?? row.r2_oos ?? null }))
            : prev
        );
      } catch {}
    })();
  }, [selectedRunId, summaryData?.length]);


  // useEffect(() => {
  // fetch(api(`/api/factor-stats/latest/summary?horizon=${horizon}`))
  //   .then((res) => res.json())
  //   .then(setSharedStats)
  //   .catch(() => {});
  //   }, [horizon]);

  // add this helper near other API helpers
  async function fetchOOS(sharedId: number) {
    const res = await fetch(api(`/api/factor-stats/${sharedId}/oos/?min_n=10&order=-r2_oos`), {
      credentials: "include",
      headers: { "Content-Type": "application/json" },
    });
    if (!res.ok) return [];
    return (await res.json()) as Array<{ ticker: string; r2_oos: number | null }>;
  }

  /** Summary fetch */
  const fetchSummaryData = async () => {
    setLoading(true);
    setError("");

    try {
      const response = await fetch(api("/api/factors/summary/"), {
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

  /** Time series fetch with safe encoding and gentle fallbacks for slashy tickers */
  const fetchTimeSeriesData = async (ticker: string) => {
    if (!ticker) return;
    setTimeSeriesLoading(true);
    setError("");

    const tryFetch = async (symbol: string) => {
      const url = api(`/api/beta/timeseries/${seg(symbol)}/`);
      return fetch(url, {
        credentials: "include",
        headers: { "Content-Type": "application/json" },
      });
    };

    try {
      // Primary attempt with raw ticker (encoded)
      let res = await tryFetch(ticker);

      // If not found and ticker contains slash, try common aliases
      if (res.status === 404 && ticker.includes("/")) {
        // 1) Replace slash with hyphen (e.g., BRK/B UN -> BRK-B UN)
        const aliasDash = ticker.replace(/\//g, "-").trim();
        res = await tryFetch(aliasDash);

        // 2) If still not found, drop the slash entirely (e.g., BRK/B UN -> BRKB UN)
        if (res.status === 404) {
          const aliasNoSlash = ticker.replace(/\//g, "").trim();
          res = await tryFetch(aliasNoSlash);
        }
      }

      if (!res.ok) {
        // At this point, we surface a clear error for the modal
        const msg = `Failed to fetch time series data: ${res.status} ${res.statusText}`;
        setTimeSeriesData(null);
        throw new Error(msg);
      }

      const data = (await res.json()) as BetaTimeSeriesData;
      setTimeSeriesData(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch time series data");
      console.error("Error fetching time series data:", err);
    } finally {
      setTimeSeriesLoading(false);
    }
  };

  /** Handle ticker click: open modal and fetch its series */
  const handleTickerSelect = (ticker: string) => {
    setSelectedTicker(ticker);
    setIsDialogOpen(true);
    setTimeSeriesData(null); // reset previous chart data while loading
    fetchTimeSeriesData(ticker);
  };

  // Load summary data on component mount
  useEffect(() => {
    fetchSummaryData();
  }, []);

  // Close dialog handler
  const handleDialogOpenChange = (open: boolean) => {
    setIsDialogOpen(open);
    if (!open) {
      // Optional: keep selection for context, or clear here.
      // setSelectedTicker("");
      // setTimeSeriesData(null);
    }
  };

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
            <p className="text-sm text-gray-500 mt-1">Last updated: {lastUpdated.toLocaleString()}</p>
          )}
        </div>
          {sharedStats && (
          <Button variant="outline" size="sm" onClick={() => setShowMore((s) => !s)}>
            {showMore ? "Show less" : "Show more"}
          </Button>
)}
      </div>

      {/* Analysis files / runs selector */}
      {runs.length > 0 && (
        <div className="w-full overflow-x-auto pb-2">
          <div className="inline-flex gap-2">
            {runs.map(run => (
              <button
                key={run.id}
                onClick={() => setSelectedRunId(run.id)}
                className={[
                  "px-3 py-1 text-sm rounded-full border",
                  selectedRunId === run.id ? "bg-primary text-primary-foreground" : "bg-background"
                ].join(" ")}
                title={`${run.run_name ?? "Run"} • ${run.horizon_days ?? "-"}d • ${run.created_at ? new Date(run.created_at).toLocaleString() : ""}`}
              >
                {run.run_name ?? `Run #${run.id}`}
              </button>
            ))}
          </div>
        </div>
      )}


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
              <div className="text-2xl font-bold">{sharedStats.r2_global?.toFixed(4) ?? "N/A"}</div>
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

      {/* Model Equation
      <Card>
        <CardHeader className="pb-1">
          <CardTitle className="text-sm font-medium">Model Equation</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-xl font-bold">{sharedStats.model_equation ?? "N/A"}</div>
          <p className="text-xs text-muted-foreground">Model Equation</p>
        </CardContent>
      </Card> */}

      
      {/* Collapsible metrics */}
      {showMore && sharedStats && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5 auto-rows-fr">
          {(() => {
            // find top positive / negative coefficient keys to exclude
            const coefPairs = Object.entries(sharedStats).filter(
              ([k, v]) => k.startsWith("coef_") && isNonZero(v)
            ) as [string, number][];
          

            const topPos = coefPairs.length
              ? [...coefPairs].sort((a, b) => b[1] - a[1])[0][0] // key only
              : null;

            const topNeg = coefPairs.length
              ? [...coefPairs].sort((a, b) => a[1] - b[1])[0][0]
              : null;

            const exclude = new Set<string>([
              "r2_global",
              "volatility_coeff",
              "y_intercept",
              topPos ?? "",
              topNeg ?? "",
            ]);

            // collect the rest: all avg_* and coef_* remaining
            const rest = Object.entries(sharedStats)
              .filter(([k, v]) => (k.startsWith("avg_") || k.startsWith("coef_")) && !exclude.has(k))
                .filter(([, v]) => isNonZero(v))   // hide zeros
              .sort(([a], [b]) => a.localeCompare(b)); // simple stable order

            return rest.map(([k, v]) => (
              <Card key={k} className="w-full min-w-0">
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium truncate">{prettyKey(k)}</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold break-words">{fmtNum(v)}</div>
                  <p className="text-xs text-muted-foreground">
                    {k.startsWith("avg_") ? "Cross-universe average" : "Model coefficient"}
                  </p>
                </CardContent>
              </Card>
            ));
          })()}
        </div>
      )}


      {/* Summary Table (clicking a ticker opens the dialog) */}
      <BetaSummaryTable data={summaryData} loading={loading} onTickerSelect={handleTickerSelect} />

      {/* Time Series Modal */}
      <Dialog open={isDialogOpen} onOpenChange={handleDialogOpenChange}>
        <DialogContent className="sm:max-w-[1200px] w-[95vw]">
          <DialogHeader>
            <DialogTitle>
              {selectedTicker ? `Time Series — ${selectedTicker}` : "Time Series"}
            </DialogTitle>
            <DialogDescription>
              Historical and predicted beta with confidence bands.
            </DialogDescription>
          </DialogHeader>

          <div className="mt-2">
            {timeSeriesLoading ? (
              <div className="h-64 flex items-center justify-center text-muted-foreground">
                Loading…
              </div>
            ) : timeSeriesData ? (
              <BetaTimeSeriesChart data={timeSeriesData} loading={false} />
            ) : (
              <div className="h-64 flex flex-col items-center justify-center text-center text-muted-foreground">
                <div className="mb-2">No time series data available for this ticker.</div>
                <div className="text-xs">
                  If the symbol contains a slash (e.g., BRK/B), it may require an alias on the
                  backend (e.g., BRK-B or BRKB).
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

