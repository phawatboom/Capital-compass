"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  Download,
  Search,
  Trash2,
  Upload as UploadIcon,
  X,
  SortAsc,
  SortDesc,
  Link as LinkIcon,
  Info,
  ShieldAlert,
  Filter as FilterIcon,
  FileText,
  BarChart3,
  TrendingUp,
  TrendingDown,
  Activity,
  Target,
  Calendar,
} from "lucide-react";
import * as XLSX from "xlsx";
import RequireAuth from "@/app/lib/requireAuth";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import LiveDashboard from "./_components/LiveDashboard";

type UploadRecord = {
  id: number;
  filename: string;
  uploaded_at: string; // ISO
};

type FileMeta = {
  id: number;
  filename: string; // basename from backend
  uploaded_at: string; // ISO
  file_size: number;
};

type AnalysisResult = {
  id: number;
  run_name: string;
  model_type: string;
  horizon_days: number;
  status: string;
  created_at: string;
  completed_at?: string;
  mae?: number;
  rmse?: number;
  directional_accuracy?: number;
  sample_size?: number;
  r2_global?: number;
};

type SortKey = "name" | "uploaded_at";
type SortDir = "asc" | "desc";
type ConfirmState =
  | { mode: "single"; id: number; name: string }
  | { mode: "bulk" }
  | null;

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000/api";

function basename(p: string): string {
  const parts = (p ?? "").split(/[\\/]/);
  return parts[parts.length - 1] || p || "";
}
function ext(p: string): string {
  const b = basename(p);
  const i = b.lastIndexOf(".");
  return i >= 0 ? b.slice(i + 1).toLowerCase() : "";
}
function formatBytes(n: number): string {
  if (!Number.isFinite(n) || n < 0) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let idx = 0;
  let val = n;
  while (val >= 1024 && idx < units.length - 1) {
    val /= 1024;
    idx++;
  }
  return `${val.toFixed(val < 10 && idx > 0 ? 1 : 0)} ${units[idx]}`;
}
function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso || "—";
    return d.toLocaleString();
  } catch {
    return iso || "—";
  }
}
function isoDay(iso: string): string {
  const i = iso.indexOf("T");
  return i > 0 ? iso.slice(0, i) : iso.slice(0, 10);
}
function getCsrfToken(): string | null {
  if (typeof document === "undefined") return null;
  const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : null;
}

export default function UploadsPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  
  // Tab state
  const [activeTab, setActiveTab] = useState(searchParams?.get("tab") || "datasets");
  
  // Analysis Results State
  const [analysisResults, setAnalysisResults] = useState<AnalysisResult[]>([]);
  const [selectedAnalysis, setSelectedAnalysis] = useState<number | null>(null);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  
  const [results, setResults] = useState([]); // State for storing analysis results
  // Data
  const [uploads, setUploads] = useState<UploadRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  // Filters/sort/pagination
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<"" | "csv" | "xlsx">("");
  const [dayFilter, setDayFilter] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("uploaded_at");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  // Selection
  const [selected, setSelected] = useState<Set<number>>(new Set());

  // Upload form
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Delete confirmation modal
  const [confirm, setConfirm] = useState<ConfirmState>(null);

  // Info modal
  const [infoOpen, setInfoOpen] = useState(false);
  const [infoLoading, setInfoLoading] = useState(false);
  const [infoData, setInfoData] = useState<FileMeta | null>(null);
  const [previewRows, setPreviewRows] = useState<string[][] | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

  // "Arm to delete" state: hide delete by default; reveal for 5s after arming
  const [armed, setArmed] = useState<Set<number>>(new Set());
  const armTimers = useRef<Map<number, number>>(new Map());
  const disarmAll = useCallback(() => {
    armTimers.current.forEach((t) => window.clearTimeout(t));
    armTimers.current.clear();
    setArmed(new Set());
  }, []);
  useEffect(() => () => disarmAll(), [disarmAll]);

  const fetchUploads = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch(`${API_BASE}/csv-uploads/`, {
        credentials: "include",
      });
      if (!r.ok) throw new Error(`Failed to load uploads (${r.status})`);
      const data: UploadRecord[] = await r.json();
      setUploads(data ?? []);
    } catch (e: any) {
      setError(e?.message || "Failed to load uploads");
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchAnalysisResults = useCallback(async () => {
    try {
      setAnalysisLoading(true);
      const resp = await fetch(`${API_BASE}/analysis-runs/`, {
        credentials: "include",
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      setAnalysisResults(data.results || []);
    } catch (err: any) {
      console.error("fetchAnalysisResults error:", err);
    } finally {
      setAnalysisLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchUploads();
    fetchAnalysisResults();
  }, [fetchUploads, fetchAnalysisResults]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return uploads.filter((u) => {
      const name = basename(u.filename);
      const matchesQuery = !q || name.toLowerCase().includes(q);
      const e = ext(u.filename);
      const matchesType = !typeFilter || e === typeFilter;
      const matchesDay = !dayFilter || isoDay(u.uploaded_at) === dayFilter;
      return matchesQuery && matchesType && matchesDay;
    });
  }, [uploads, query, typeFilter, dayFilter]);

  const sorted = useMemo(() => {
    const arr = [...filtered];
    arr.sort((a, b) => {
      if (sortKey === "uploaded_at") {
        const ta = new Date(a.uploaded_at).getTime();
        const tb = new Date(b.uploaded_at).getTime();
        return sortDir === "asc" ? ta - tb : tb - ta;
      }
      // name
      const av = basename(a.filename).toLowerCase();
      const bv = basename(b.filename).toLowerCase();
      return sortDir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
    });
    return arr;
  }, [filtered, sortKey, sortDir]);

  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const currentPage = Math.min(page, totalPages);
  const pageData = useMemo(() => {
    const startIdx = (currentPage - 1) * pageSize;
    return sorted.slice(startIdx, startIdx + pageSize);
  }, [sorted, currentPage, pageSize]);

  const toggleSort = (key: SortKey) => {
    setPage(1);
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(key === "uploaded_at" ? "desc" : "asc");
    }
  };

  const clearFilters = () => {
    setQuery("");
    setTypeFilter("");
    setDayFilter(null);
    setSortKey("uploaded_at");
    setSortDir("desc");
    setPage(1);
  };

  const removeFilterChip = (kind: "query" | "type" | "day") => {
    setPage(1);
    if (kind === "query") setQuery("");
    if (kind === "type") setTypeFilter("");
    if (kind === "day") setDayFilter(null);
  };

  const handleAnalyze = (uploadId: number) => {
    // Navigate to configuration page with the file ID
    router.push(`/config?fileId=${uploadId}`);
  };
  const handleSelectAllOnPage = (checked: boolean) => {
    const next = new Set(selected);
    pageData.forEach((u) => {
      if (checked) next.add(u.id);
      else next.delete(u.id);
    });
    setSelected(next);
  };

  const handleSelectOne = (id: number, checked: boolean) => {
    const next = new Set(selected);
    if (checked) next.add(id);
    else next.delete(id);
    setSelected(next);
  };

  const handleDownload = (id: number) => {
    window.location.href = `${API_BASE}/csv-uploads/${id}/download/`;
  };

  const handleCopyLink = async (id: number) => {
    const url = `${API_BASE}/csv-uploads/${id}/download/`;
    try {
      await navigator.clipboard.writeText(url);
      setMessage("Download link copied");
      setTimeout(() => setMessage(null), 1500);
    } catch {
      setError("Failed to copy link");
      setTimeout(() => setError(null), 2000);
    }
  };

  async function ensureCsrf(): Promise<string> {
    await fetch(`${API_BASE}/auth/csrf/`, { credentials: "include" });
    const token = getCsrfToken();
    if (!token) throw new Error("Missing CSRF token");
    return token;
  }

  const deleteOne = useCallback(async (id: number) => {
    const token = await ensureCsrf();
    const r = await fetch(`${API_BASE}/csv-uploads/${id}/`, {
      method: "DELETE",
      credentials: "include",
      headers: { "X-CSRFToken": token },
    });
    if (!r.ok && r.status !== 204) {
      const txt = await r.text().catch(() => "");
      throw new Error(`Delete failed (${r.status}) ${txt}`);
    }
  }, []);

  const openConfirmSingle = (id: number, name: string) =>
    setConfirm({ mode: "single", id, name });

  const openConfirmBulk = () => {
    if (selected.size === 0) return;
    setConfirm({ mode: "bulk" });
  };

  const confirmDelete = async () => {
    if (!confirm) return;
    setBusy(true);
    setError(null);
    try {
      if (confirm.mode === "single") {
        await deleteOne(confirm.id);
        setSelected((prev) => {
          const n = new Set(prev);
          n.delete(confirm.id);
          return n;
        });
      } else {
        const ids = Array.from(selected);
        for (const id of ids) {
          await deleteOne(id);
        }
        setSelected(new Set());
      }
      disarmAll();
      await fetchUploads();
      setConfirm(null);
    } catch (e: any) {
      setError(e?.message || "Delete failed");
    } finally {
      setBusy(false);
    }
  };

  const cancelConfirm = () => setConfirm(null);
  //
  // const handleUpload = async (e: React.FormEvent) => {
  //   e.preventDefault();
  //   if (!file) return;
  //   setUploading(true);
  //   setMessage(null);
  //   setError(null);
  //   try {
  //     const token = await ensureCsrf();
  //     const fd = new FormData();
  //     fd.append("file", file);
  //     const r = await fetch(`${API_BASE}/upload-csv/`, {
  //       method: "POST",
  //       body: fd,
  //       credentials: "include",
  //       headers: { "X-CSRFToken": token },
  //     });
  //     if (!r.ok) {
  //       const data = await r.json().catch(() => ({}));
  //       throw new Error(data?.error || `Upload failed (${r.status})`);
  //     }
  //     setFile(null);
  //     setMessage("Uploaded successfully");
  //     await fetchUploads();
  //   } catch (e: any) {
  //     setError(e?.message || "Upload failed");
  //   } finally {
  //     setUploading(false);
  //     setTimeout(() => {
  //       setMessage(null);
  //       setError(null);
  //     }, 2500);
  //   }
  // };

  // Data preview loader (first sheet/CSV 10x10)
  const loadPreview = useCallback(async (id: number) => {
    setPreviewRows(null);
    setPreviewError(null);
    try {
      const r = await fetch(`${API_BASE}/csv-uploads/${id}/download/`, {
        credentials: "include",
      });
      if (!r.ok) throw new Error(`Failed to fetch file (${r.status})`);
      const buf = await r.arrayBuffer();
      const wb = XLSX.read(new Uint8Array(buf), { type: "array" });
      const firstSheetName = wb.SheetNames[0];
      if (!firstSheetName) {
        setPreviewRows([]);
        return;
      }
      const sheet = wb.Sheets[firstSheetName];
      const rows: any[][] = XLSX.utils.sheet_to_json(sheet, { header: 1 });
      const top = rows.slice(0, 10).map((row) =>
        row.slice(0, 10).map((v) => (v == null ? "" : String(v)))
      );
      setPreviewRows(top);
    } catch (e: any) {
      setPreviewError(e?.message || "Preview failed");
    }
  }, []);

  const openInfo = async (id: number) => {
    setInfoOpen(true);
    setInfoLoading(true);
    setInfoData(null);
    setPreviewRows(null);
    setPreviewError(null);
    try {
      const r = await fetch(`${API_BASE}/csv-uploads/${id}/meta/`, {
        credentials: "include",
      });
      if (!r.ok) throw new Error(`Failed to load file info (${r.status})`);
      const meta: FileMeta = await r.json();
      setInfoData(meta);
      // Load preview after meta
      await loadPreview(id);
    } catch (e: any) {
      setPreviewError(e?.message || "Failed to load info");
    } finally {
      setInfoLoading(false);
    }
  };

  // Arm delete handling
  const toggleArm = (id: number) => {
    setArmed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
        const t = armTimers.current.get(id);
        if (t) window.clearTimeout(t);
        armTimers.current.delete(id);
      } else {
        next.add(id);
        const t = window.setTimeout(() => {
          setArmed((p) => {
            const n = new Set(p);
            n.delete(id);
            return n;
          });
          armTimers.current.delete(id);
        }, 5000);
        armTimers.current.set(id, t);
      }
      return next;
    });
  };

  const getStatusBadgeVariant = (status: string) => {
    switch (status) {
      case 'completed':
        return 'default';
      case 'running':
        return 'secondary';
      case 'error':
        return 'destructive';
      default:
        return 'outline';
    }
  };

  // Render
  return (
    <RequireAuth>
      <div className="mx-auto w-full max-w-screen-xl px-3 sm:px-4 py-6">
        {/* Header */}
        <div className="mb-6">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-bold text-gray-900">My Data</h1>
              <p className="text-gray-600 text-sm mt-1">
                View and manage your uploaded data files
              </p>
            </div>
            <Link href="/upload">
              <Button className="inline-flex items-center gap-2">
                <UploadIcon className="w-4 h-4" />
                Upload New Data
              </Button>
            </Link>
          </div>
        </div>

        {/*<div className="mb-6">*/}
        {/*  <form onSubmit={handleUpload} className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3">*/}
        {/*    <input*/}
        {/*      type="file"*/}
        {/*      className="border rounded px-3 py-2 w-full sm:w-auto"*/}
        {/*      onChange={(e) => setFile(e.target.files?.[0] ?? null)}*/}
        {/*      accept=".csv,.xlsx"*/}
        {/*    />*/}
        {/*    <Button type="submit" disabled={!file || uploading} className="inline-flex items-center gap-2">*/}
        {/*      <UploadIcon className="w-4 h-4" />*/}
        {/*      {uploading ? "Uploading..." : "Upload"}*/}
        {/*    </Button>*/}
        {/*  </form>*/}
        {/*</div>*/}

        {(message || error) && (
          <div
            className={`mb-4 text-sm rounded px-3 py-2 ${
              message ? "bg-green-50 text-green-700 border border-green-200" : "bg-red-50 text-red-700 border border-red-200"
            }`}
          >
            {message || error}
          </div>
        )}

        {/* Tabs */}
        <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-6">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="datasets" className="flex items-center gap-2">
              <FileText className="h-4 w-4" />
              Datasets
            </TabsTrigger>
            <TabsTrigger value="analysis" className="flex items-center gap-2">
              <BarChart3 className="h-4 w-4" />
              Analysis Results
            </TabsTrigger>
          </TabsList>

          {/* Datasets Tab */}
          <TabsContent value="datasets" className="space-y-6">

        {/* Filters bar */}
        <div className="bg-white border rounded-lg p-4 shadow-sm mb-3 w-full">
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex-1 min-w-[220px]">
              <label className="text-xs text-gray-500">Search</label>
              <div className="relative">
                <input
                  className="w-full border rounded px-3 py-2 pr-9"
                  placeholder="Filter by name..."
                  value={query}
                  onChange={(e) => {
                    setQuery(e.target.value);
                    setPage(1);
                  }}
                />
                <Search className="absolute right-2 top-2.5 h-4 w-4 text-gray-400" />
              </div>
            </div>
            <div>
              <label className="text-xs text-gray-500">Type</label>
              <select
                className="border rounded px-3 py-2"
                value={typeFilter}
                onChange={(e) => {
                  setTypeFilter(e.target.value as any);
                  setPage(1);
                }}
              >
                <option value="">All</option>
                <option value="csv">CSV</option>
                <option value="xlsx">XLSX</option>
              </select>
            </div>
            <div className="ml-auto">
              <Button type="button" variant="outline" onClick={clearFilters} className="h-9">
                Clear filters
              </Button>
            </div>
          </div>

          {/* Active filter chips */}
          <div className="mt-3 flex flex-wrap gap-2">
            {query && (
              <span className="inline-flex items-center gap-2 text-xs bg-gray-100 text-gray-700 px-2 py-1 rounded">
                Query: {query}
                <button onClick={() => removeFilterChip("query")} className="hover:text-gray-900">
                  <X className="w-3 h-3" />
                </button>
              </span>
            )}
            {typeFilter && (
              <span className="inline-flex items-center gap-2 text-xs bg-gray-100 text-gray-700 px-2 py-1 rounded">
                Type: {typeFilter.toUpperCase()}
                <button onClick={() => removeFilterChip("type")} className="hover:text-gray-900">
                  <X className="w-3 h-3" />
                </button>
              </span>
            )}
            {dayFilter && (
              <span className="inline-flex items-center gap-2 text-xs bg-gray-100 text-gray-700 px-2 py-1 rounded">
                Date: {dayFilter}
                <button onClick={() => removeFilterChip("day")} className="hover:text-gray-900">
                  <X className="w-3 h-3" />
                </button>
              </span>
            )}
          </div>
        </div>

        {/* Table */}
        <div className="bg-white border rounded-lg shadow-sm overflow-hidden w-full">
          {/* Render analysis results here */}
          {results.length > 0 && (
            <div className="mt-8 bg-white border rounded-lg shadow-sm p-4">
              <h3 className="text-lg font-semibold mb-4">Analysis Results</h3>
              <div className="overflow-x-auto">
                <table className="w-full table-auto">
                  <thead>
                    <tr>
                      {Object.keys(results[0]).map((col) => (
                        <th key={col} className="px-3 py-2 text-left border-b">{col}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {results.map((row, i) => (
                      <tr key={i}>
                        {Object.values(row).map((val, j) => (
                          <td key={j} className="px-3 py-2 border-b">{String(val)}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
          <div className="overflow-x-auto w-full">
            <table className="w-full table-auto min-w-[720px] sm:min-w-full">
              <thead className="bg-gray-50">
                <tr className="text-left text-xs font-semibold text-gray-500">
                  <th className="px-3 py-2 w-10">
                    <input
                      type="checkbox"
                      onChange={(e) => handleSelectAllOnPage(e.target.checked)}
                      checked={pageData.length > 0 && pageData.every((u) => selected.has(u.id))}
                      aria-label="Select all on page"
                    />
                  </th>
                  <th className="px-3 py-2 cursor-pointer select-none" onClick={() => toggleSort("name")}>
                    <div className="inline-flex items-center gap-2">
                      Name
                      {sortKey === "name" &&
                        (sortDir === "asc" ? (
                          <SortAsc className="w-3.5 h-3.5 text-gray-400" />
                        ) : (
                          <SortDesc className="w-3.5 h-3.5 text-gray-400" />
                        ))}
                    </div>
                  </th>
                  <th className="px-3 py-2">Type</th>
                  <th className="px-3 py-2 cursor-pointer select-none" onClick={() => toggleSort("uploaded_at")}>
                    <div className="inline-flex items-center gap-2">
                      Uploaded
                      {sortKey === "uploaded_at" &&
                        (sortDir === "asc" ? (
                          <SortAsc className="w-3.5 h-3.5 text-gray-400" />
                        ) : (
                          <SortDesc className="w-3.5 h-3.5 text-gray-400" />
                        ))}
                    </div>
                  </th>
                  <th className="px-3 py-2 w-48 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr>
                    <td colSpan={5} className="px-3 py-8 text-center text-sm text-gray-500">
                      Loading...
                    </td>
                  </tr>
                ) : pageData.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-3 py-8 text-center text-sm text-gray-500">
                      No uploads found
                    </td>
                  </tr>
                ) : (
                  pageData.map((u) => {
                    const name = basename(u.filename);
                    const e = ext(u.filename);
                    const armedNow = armed.has(u.id);
                    return (
                      <tr key={u.id} className="border-t text-sm">
                        <td className="px-3 py-2 align-top">
                          <input
                            type="checkbox"
                            checked={selected.has(u.id)}
                            onChange={(ev) => handleSelectOne(u.id, ev.target.checked)}
                            aria-label={`Select ${name}`}
                          />
                        </td>
                        <td className="px-3 py-2 align-top">
                          <div className="flex items-center gap-2">
                            <span className="font-medium text-gray-900 truncate">{name}</span>
                            <button
                              title="Filter by this name"
                              className="p-1 rounded-full hover:bg-gray-100 text-gray-500"
                              onClick={(e2) => {
                                e2.stopPropagation();
                                setQuery(name);
                                setPage(1);
                              }}
                            >
                              <FilterIcon className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        </td>
                        <td className="px-3 py-2 align-top">
                          <span className="inline-block text-xs px-2 py-0.5 rounded bg-gray-100 text-gray-700">
                            {e ? e.toUpperCase() : "—"}
                          </span>
                        </td>
                        <td className="px-3 py-2 align-top">
                          <button
                            className="text-left text-gray-700 hover:underline"
                            title="Filter by day"
                            onClick={() => {
                              setDayFilter(isoDay(u.uploaded_at));
                              setPage(1);
                            }}
                          >
                            {formatDate(u.uploaded_at)}
                          </button>
                        </td>
                        <td className="px-3 py-2 align-top">
                          <div className="flex items-center justify-end gap-2">
                            <Button
                              type="button"
                              variant="outline"
                              className="h-8 px-2"
                              onClick={() => openInfo(u.id)}
                              title="Info"
                            >
                              <Info className="w-4 h-4" />
                            </Button>
                            <Button
                              type="button"
                              variant="outline"
                              className="h-8 px-2"
                              onClick={() => handleDownload(u.id)}
                              title="Download"
                            >
                              <Download className="w-4 h-4" />
                            </Button>
                            <Button
                              type="button"
                              variant="outline"
                              className="h-8 px-3"
                              onClick={() => handleAnalyze(u.id)}
                              title="Configure and Run Universal Beta Analysis"
                            >
                              Configure & Analyze
                            </Button>
                            <Button
                              type="button"
                              variant="outline"
                              className="h-8 px-2"
                              onClick={() => handleCopyLink(u.id)}
                              title="Copy link"
                            >
                              <LinkIcon className="w-4 h-4" />
                            </Button>

                            <button
                              className={`h-8 w-8 inline-flex items-center justify-center rounded-full border ${
                                armedNow
                                  ? "border-amber-300 bg-amber-50 text-amber-700"
                                  : "border-gray-200 bg-white text-gray-500"
                              }`}
                              onClick={() => toggleArm(u.id)}
                              title={armedNow ? "Disarm delete" : "Arm delete"}
                            >
                              <ShieldAlert className="w-4 h-4" />
                            </button>

                            <div className="h-8">
                                <Button
                                  type="button"
                                  variant="destructive"
                                  className={`h-8 px-2 transition-opacity duration-200 ${
                                    armedNow ? "opacity-100" : "opacity-0 pointer-events-none"
                                  }`}
                                  onClick={() => openConfirmSingle(u.id, name)}
                                  title="Delete"
                                >
                                  <Trash2 className="w-4 h-4" />
                                </Button>
                            </div>
                          </div>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>

          {/* Footer: bulk actions + pagination */}
          <div className="p-3 flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={selected.size === 0}
                onClick={openConfirmBulk}
                className="h-9"
              >
                <Trash2 className="w-4 h-4 mr-1" />
                Delete selected ({selected.size})
              </Button>
            </div>

            <div className="ml-auto flex items-center gap-3">
              <span className="text-xs text-gray-500">
                Page {currentPage} of {totalPages}
              </span>
              <select
                className="border rounded px-2 py-1 text-sm"
                value={pageSize}
                onChange={(e) => {
                  setPageSize(parseInt(e.target.value, 10));
                  setPage(1);
                }}
              >
                {[10, 20, 50].map((n) => (
                  <option key={n} value={n}>
                    {n} / page
                  </option>
                ))}
              </select>
              <div className="flex items-center gap-1">
                <Button
                  type="button"
                  variant="outline"
                  className="h-8"
                  disabled={currentPage <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                >
                  Prev
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  className="h-8"
                  disabled={currentPage >= totalPages}
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                >
                  Next
                </Button>
              </div>
            </div>
          </div>
        </div>

        {/* Confirm delete modal */}
        {confirm && (
          <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
            <div className="bg-white rounded-lg shadow-lg w-full max-w-md p-5">
              <div className="flex items-start gap-3">
                <ShieldAlert className="w-5 h-5 text-amber-600 mt-0.5" />
                <div className="flex-1">
                  <h3 className="text-base font-semibold mb-1">Confirm deletion</h3>
                  <p className="text-sm text-gray-600">
                    {confirm.mode === "single"
                      ? `This will permanently delete "${confirm.name}".`
                      : "This will permanently delete all selected files."}
                  </p>
                </div>
              </div>
              <div className="mt-5 flex justify-end gap-2">
                <Button type="button" variant="outline" onClick={cancelConfirm} disabled={busy}>
                  Cancel
                </Button>
                <Button type="button" variant="destructive" onClick={confirmDelete} disabled={busy}>
                  {busy ? "Deleting..." : "Delete"}
                </Button>
              </div>
            </div>
          </div>
        )}

        {/* Info modal */}
        {infoOpen && (
          <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
            <div className="bg-white rounded-lg shadow-lg w-full max-w-3xl">
              <div className="flex items-center justify-between px-4 py-3 border-b">
                <h3 className="text-base font-semibold">File info</h3>
                <button
                  className="p-2 rounded hover:bg-gray-100"
                  onClick={() => {
                    setInfoOpen(false);
                    setInfoData(null);
                    setPreviewRows(null);
                    setPreviewError(null);
                  }}
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
              <div className="p-4">
                {infoLoading && <div className="text-sm text-gray-500">Loading...</div>}
                {!infoLoading && infoData && (
                  <div className="space-y-2 text-sm">
                    <div>
                      <span className="text-gray-500">Name:</span> {basename(infoData.filename)}
                    </div>
                    <div>
                      <span className="text-gray-500">Type:</span>{" "}
                      {ext(infoData.filename).toUpperCase() || "—"}
                    </div>
                    <div>
                      <span className="text-gray-500">Size:</span> {formatBytes(infoData.file_size)}
                    </div>
                    <div>
                      <span className="text-gray-500">Uploaded:</span> {formatDate(infoData.uploaded_at)}
                    </div>

                    {/* Preview section */}
                    <div className="mt-3">
                      <div className="font-medium mb-2">Preview (first 10×10)</div>
                      {previewError && (
                        <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded px-2 py-1 inline-block">
                          {previewError}
                        </div>
                      )}
                      {!previewError && !previewRows && (
                        <div className="text-sm text-gray-500">Generating preview...</div>
                      )}
                      {!previewError && previewRows && previewRows.length > 0 && (
                        <div className="max-h-[360px] overflow-auto border rounded">
                          <table className="w-full text-xs">
                            <tbody>
                              {previewRows.map((row, i) => (
                                <tr key={i} className="border-b last:border-b-0">
                                  {row.map((cell, j) => (
                                    <td key={j} className="px-2 py-1 border-r last:border-r-0 whitespace-pre">
                                      {cell}
                                    </td>
                                  ))}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                      {!previewError && previewRows && previewRows.length === 0 && (
                        <div className="text-sm text-gray-500">No preview available.</div>
                      )}
                    </div>
                  </div>
                )}
              </div>
              <div className="px-4 py-3 border-t flex justify-end">
                <Button onClick={() => setInfoOpen(false)}>Close</Button>
              </div>
            </div>
          </div>
        )}

          </TabsContent>

          {/* Analysis Results Tab */}
          <TabsContent value="analysis" className="space-y-6">
            {analysisLoading ? (
              <div className="flex h-64 items-center justify-center">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
              </div>
            ) : analysisResults.length === 0 ? (
              <div className="space-y-6">
                {/* Empty state with call to action */}
                <Card>
                  <CardContent className="flex flex-col items-center justify-center py-12">
                    <BarChart3 className="h-12 w-12 text-gray-400 mb-4" />
                    <h3 className="text-lg font-medium text-gray-900 mb-2">No Analysis Results</h3>
                    <p className="text-gray-600 text-center mb-4">
                      Run an analysis on your datasets to see comprehensive results here.
                    </p>
                    <p className="text-sm text-gray-500 mb-4 text-center">
                      Go to the Datasets tab and click "Analyze" on any uploaded file
                    </p>
                    <Button onClick={() => setActiveTab("datasets")} className="mb-6">
                      Go to Datasets
                    </Button>
                  </CardContent>
                </Card>

                {/* Rich Demo Preview - Shows what results will look like */}
                <div className="border-t pt-6">
                  <div className="mb-6">
                    <h3 className="text-xl font-semibold text-gray-900 mb-2">Preview: Your Analysis Results Will Look Like This</h3>
                    <p className="text-gray-600">This demonstrates the comprehensive insights you'll get from our Universal Beta Forecasting Platform</p>
                  </div>

                  {/* Core Performance Metrics - Actual Model Output */}
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4 mb-6">
                    <Card className="opacity-75 border-dashed border-2">
                      <CardHeader className="pb-2">
                        <CardTitle className="text-sm font-medium text-muted-foreground">Mean Absolute Error</CardTitle>
                      </CardHeader>
                      <CardContent>
                        <div className="text-2xl font-bold text-muted-foreground">0.0342</div>
                        <p className="text-xs text-muted-foreground">Prediction accuracy</p>
                      </CardContent>
                    </Card>

                    <Card className="opacity-75 border-dashed border-2">
                      <CardHeader className="pb-2">
                        <CardTitle className="text-sm font-medium text-muted-foreground">RMSE</CardTitle>
                      </CardHeader>
                      <CardContent>
                        <div className="text-2xl font-bold text-muted-foreground">0.0487</div>
                        <p className="text-xs text-muted-foreground">Root mean square error</p>
                      </CardContent>
                    </Card>

                    <Card className="opacity-75 border-dashed border-2">
                      <CardHeader className="pb-2">
                        <CardTitle className="text-sm font-medium text-muted-foreground">R² Score</CardTitle>
                      </CardHeader>
                      <CardContent>
                        <div className="text-2xl font-bold text-muted-foreground">0.7834</div>
                        <p className="text-xs text-muted-foreground">Model fit quality</p>
                      </CardContent>
                    </Card>

                    <Card className="opacity-75 border-dashed border-2">
                      <CardHeader className="pb-2">
                        <CardTitle className="text-sm font-medium text-muted-foreground">Directional Accuracy</CardTitle>
                      </CardHeader>
                      <CardContent>
                        <div className="text-2xl font-bold text-muted-foreground">67.8%</div>
                        <p className="text-xs text-muted-foreground">Direction prediction</p>
                      </CardContent>
                    </Card>

                    <Card className="opacity-75 border-dashed border-2">
                      <CardHeader className="pb-2">
                        <CardTitle className="text-sm font-medium text-muted-foreground">Sample Size</CardTitle>
                      </CardHeader>
                      <CardContent>
                        <div className="text-2xl font-bold text-muted-foreground">15,420</div>
                        <p className="text-xs text-muted-foreground">Data points analyzed</p>
                      </CardContent>
                    </Card>
                  </div>

                  {/* Performance by Stock - Actual Output */}
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
                    <Card className="opacity-75 border-dashed border-2">
                      <CardHeader>
                        <CardTitle className="text-muted-foreground">Performance Metrics by Stock</CardTitle>
                        <CardDescription className="text-muted-foreground">Individual stock prediction accuracy</CardDescription>
                      </CardHeader>
                      <CardContent>
                        <div className="h-64 flex items-center justify-center">
                          <div className="text-center text-muted-foreground">
                            <BarChart3 className="h-12 w-12 mx-auto mb-2" />
                            <p className="font-medium">Interactive Performance Charts</p>
                            <p className="text-sm">MAE, RMSE, R² by stock symbol</p>
                          </div>
                        </div>
                      </CardContent>
                    </Card>

                    <Card className="opacity-75 border-dashed border-2">
                      <CardHeader>
                        <CardTitle className="text-muted-foreground">Beta Predictions Over Time</CardTitle>
                        <CardDescription className="text-muted-foreground">Forecasted vs realized beta coefficients</CardDescription>
                      </CardHeader>
                      <CardContent>
                        <div className="h-64 flex items-center justify-center">
                          <div className="text-center text-muted-foreground">
                            <Activity className="h-12 w-12 mx-auto mb-2" />
                            <p className="font-medium">Time Series Chart</p>
                            <p className="text-sm">Forecast vs actual beta values</p>
                          </div>
                        </div>
                      </CardContent>
                    </Card>
                  </div>

                  {/* Top Performers Table - Based on Actual Model Output */}
                  <Card className="opacity-75 border-dashed border-2 mb-6">
                    <CardHeader>
                      <CardTitle className="text-muted-foreground">Top Performing Predictions</CardTitle>
                      <CardDescription className="text-muted-foreground">Stocks with highest prediction accuracy</CardDescription>
                    </CardHeader>
                    <CardContent>
                      <div className="space-y-2">
                        {[
                          { stock: 'AAPL', mae: 0.0234, rmse: 0.0312, r2: 0.8456, dir_acc: 0.723 },
                          { stock: 'MSFT', mae: 0.0267, rmse: 0.0334, r2: 0.8123, dir_acc: 0.698 },
                          { stock: 'GOOGL', mae: 0.0298, rmse: 0.0389, r2: 0.7834, dir_acc: 0.687 },
                          { stock: 'NVDA', mae: 0.0356, rmse: 0.0445, r2: 0.7234, dir_acc: 0.645 },
                          { stock: 'TSLA', mae: 0.0423, rmse: 0.0567, r2: 0.6789, dir_acc: 0.623 }
                        ].map((stock) => (
                          <div key={stock.stock} className="flex items-center justify-between p-3 border rounded-lg opacity-75">
                            <div className="font-medium text-muted-foreground">{stock.stock}</div>
                            <div className="grid grid-cols-4 gap-4 text-sm text-muted-foreground">
                              <div>MAE: {stock.mae.toFixed(4)}</div>
                              <div>RMSE: {stock.rmse.toFixed(4)}</div>
                              <div>R²: {stock.r2.toFixed(4)}</div>
                              <div>Dir Acc: {(stock.dir_acc * 100).toFixed(1)}%</div>
                            </div>
                          </div>
                        ))}
                      </div>
                    </CardContent>
                  </Card>

                  {/* Model Configuration - Based on Actual Parameters */}
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
                    <Card className="opacity-75 border-dashed border-2">
                      <CardHeader>
                        <CardTitle className="text-muted-foreground">Analysis Configuration</CardTitle>
                        <CardDescription className="text-muted-foreground">Model parameters and settings used</CardDescription>
                      </CardHeader>
                      <CardContent className="space-y-4">
                        <div className="grid grid-cols-2 gap-4 text-sm">
                          <div className="flex justify-between">
                            <span className="text-muted-foreground">Model Type:</span>
                            <Badge variant="outline" className="opacity-75">ElasticNet Pooled</Badge>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-muted-foreground">Horizon Days:</span>
                            <span className="text-muted-foreground font-medium">10</span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-muted-foreground">Training Window:</span>
                            <span className="text-muted-foreground font-medium">252 days</span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-muted-foreground">Testing Window:</span>
                            <span className="text-muted-foreground font-medium">256 days</span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-muted-foreground">Cross Validation:</span>
                            <span className="text-muted-foreground font-medium">5-fold</span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-muted-foreground">Status:</span>
                            <Badge variant="default" className="opacity-75">Completed</Badge>
                          </div>
                        </div>
                        
                        <div className="mt-4 pt-4 border-t">
                          <h4 className="font-medium text-muted-foreground mb-2">Key Features Analyzed:</h4>
                          <div className="flex flex-wrap gap-2">
                            {['Market Return', 'Size Factor', 'Value Factor', 'Momentum', 'Volatility', 'Industry Dummy'].map((feature) => (
                              <Badge key={feature} variant="outline" className="opacity-75 text-muted-foreground">
                                {feature}
                              </Badge>
                            ))}
                          </div>
                        </div>
                      </CardContent>
                    </Card>

                    <Card className="opacity-75 border-dashed border-2">
                      <CardHeader>
                        <CardTitle className="text-muted-foreground">Run Information</CardTitle>
                        <CardDescription className="text-muted-foreground">Execution details and timing</CardDescription>
                      </CardHeader>
                      <CardContent className="space-y-4">
                        <div className="space-y-2">
                          <div className="flex justify-between">
                            <span className="text-muted-foreground">Status:</span>
                            <Badge variant="default" className="opacity-75 bg-green-100 text-green-800">Completed</Badge>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-muted-foreground">Runtime:</span>
                            <span className="text-muted-foreground font-medium">2m 34s</span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-muted-foreground">Memory Used:</span>
                            <span className="text-muted-foreground font-medium">1.2 GB</span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-muted-foreground">Started:</span>
                            <span className="text-muted-foreground">Oct 26, 2025 2:30 PM</span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-muted-foreground">Completed:</span>
                            <span className="text-muted-foreground">Oct 26, 2025 2:33 PM</span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-muted-foreground">Data Source:</span>
                            <span className="text-muted-foreground font-medium">stock_data.csv</span>
                          </div>
                        </div>
                      </CardContent>
                    </Card>
                  </div>

                  {/* Prediction Output Sample - Actual Model Structure */}
                  <Card className="opacity-75 border-dashed border-2 mb-6">
                    <CardHeader>
                      <CardTitle className="text-muted-foreground">Sample Predictions</CardTitle>
                      <CardDescription className="text-muted-foreground">Beta coefficient predictions for selected stocks</CardDescription>
                    </CardHeader>
                    <CardContent>
                      <div className="space-y-2">
                        <div className="grid grid-cols-4 gap-4 text-xs font-semibold text-muted-foreground border-b pb-2">
                          <div>Stock</div>
                          <div>Predicted Beta</div>
                          <div>Confidence</div>
                          <div>Date</div>
                        </div>
                        {[
                          { stock: 'AAPL', beta: 1.234, confidence: 'High', date: '2025-11-05' },
                          { stock: 'MSFT', beta: 0.987, confidence: 'High', date: '2025-11-05' },
                          { stock: 'GOOGL', beta: 1.156, confidence: 'Medium', date: '2025-11-05' },
                          { stock: 'NVDA', beta: 1.543, confidence: 'Medium', date: '2025-11-05' },
                          { stock: 'TSLA', beta: 1.876, confidence: 'Low', date: '2025-11-05' }
                        ].map((pred) => (
                          <div key={pred.stock} className="grid grid-cols-4 gap-4 text-sm text-muted-foreground py-1">
                            <div className="font-medium">{pred.stock}</div>
                            <div>{pred.beta.toFixed(3)}</div>
                            <div>
                              <Badge 
                                variant={pred.confidence === 'High' ? 'default' : pred.confidence === 'Medium' ? 'secondary' : 'outline'} 
                                className="opacity-75"
                              >
                                {pred.confidence}
                              </Badge>
                            </div>
                            <div>{pred.date}</div>
                          </div>
                        ))}
                      </div>
                    </CardContent>
                  </Card>

                  <div className="mt-6 p-4 bg-blue-50 rounded-lg border border-blue-200">
                    <div className="flex items-start space-x-3">
                      <div className="flex-shrink-0">
                        <BarChart3 className="h-5 w-5 text-blue-600 mt-0.5" />
                      </div>
                      <div className="flex-1">
                        <h4 className="text-sm font-medium text-blue-900">Ready to Get Started?</h4>
                        <p className="text-sm text-blue-700 mt-1">
                          Upload your financial data and run your first analysis to see all these comprehensive insights and more.
                          Our Universal Beta Forecasting Platform provides institutional-grade analytics for portfolio optimization.
                        </p>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <div className="space-y-6">
                {/* Analysis Selection */}
                <Card>
                  <CardHeader>
                    <CardTitle>Analysis Results</CardTitle>
                    <CardDescription>
                      Select an analysis run to view detailed results
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <Select
                      value={selectedAnalysis?.toString() || ""}
                      onValueChange={(value) => setSelectedAnalysis(value ? parseInt(value) : null)}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Select an analysis run..." />
                      </SelectTrigger>
                      <SelectContent>
                        {analysisResults.map((result) => (
                          <SelectItem key={result.id} value={result.id.toString()}>
                            <div className="flex items-center justify-between w-full">
                              <span>{result.run_name}</span>
                              <Badge variant={getStatusBadgeVariant(result.status)}>
                                {result.status}
                              </Badge>
                            </div>
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </CardContent>
                </Card>

                {/* Selected Analysis Dashboard */}
                {selectedAnalysis && (
                  <AnalysisDashboard
                    analysis={analysisResults.find(r => r.id === selectedAnalysis)!}
                  />
                )}

                {/* Live Dashboard */}
                <Card>
                  <CardHeader>
                    <CardTitle>Live Dashboard</CardTitle>
                    <CardDescription>
                      Real-time overview of your analysis performance
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <LiveDashboard refreshTrigger={0} />
                  </CardContent>
                </Card>
              </div>
            )}
          </TabsContent>
        </Tabs>
      </div>
    </RequireAuth>
  );
}

// Analysis Dashboard Component
const AnalysisDashboard = ({ analysis }: { analysis: AnalysisResult }) => {
  const performanceData = [
    { name: 'MAE', value: analysis.mae || 0, color: '#ef4444' },
    { name: 'RMSE', value: analysis.rmse || 0, color: '#f97316' },
    { name: 'R²', value: analysis.r2_global || 0, color: '#22c55e' },
    { name: 'Dir. Acc.', value: analysis.directional_accuracy || 0, color: '#3b82f6' },
  ];

  // Quality indicators based on performance metrics
  const getQualityIndicator = (metric: string, value: number) => {
    switch (metric) {
      case 'r2':
        return value > 0.1 ? 'High' : value > 0.05 ? 'Medium' : 'Low';
      case 'directional_accuracy':
        return value > 0.55 ? 'Good' : value > 0.5 ? 'Fair' : 'Poor';
      case 'sample_size':
        return value > 1000 ? 'Sufficient' : 'Limited';
      default:
        return 'N/A';
    }
  };

  const modelSignificance = getQualityIndicator('r2', analysis.r2_global || 0);
  const predictionAccuracy = getQualityIndicator('directional_accuracy', analysis.directional_accuracy || 0);
  const sampleAdequacy = getQualityIndicator('sample_size', analysis.sample_size || 0);

  return (
    <div className="grid gap-6">
      {/* Enhanced Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Mean Absolute Error</CardTitle>
            <TrendingDown className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{(analysis.mae || 0).toFixed(4)}</div>
            <p className="text-xs text-muted-foreground">Lower is better</p>
            <div className="flex items-center mt-1">
              <div className={`w-2 h-2 rounded-full mr-2 ${
                (analysis.mae || 0) < 0.05 ? 'bg-green-500' : 
                (analysis.mae || 0) < 0.1 ? 'bg-yellow-500' : 'bg-red-500'
              }`}></div>
              <span className="text-xs text-muted-foreground">
                {(analysis.mae || 0) < 0.05 ? 'Excellent' : 
                 (analysis.mae || 0) < 0.1 ? 'Good' : 'Needs Improvement'}
              </span>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">R² Score</CardTitle>
            <Target className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{((analysis.r2_global || 0) * 100).toFixed(1)}%</div>
            <p className="text-xs text-muted-foreground">Model fit quality</p>
            <div className="flex items-center mt-1">
              <Badge variant={modelSignificance === 'High' ? 'default' : modelSignificance === 'Medium' ? 'secondary' : 'outline'}>
                {modelSignificance}
              </Badge>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Directional Accuracy</CardTitle>
            <Activity className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{((analysis.directional_accuracy || 0) * 100).toFixed(1)}%</div>
            <p className="text-xs text-muted-foreground">Prediction direction</p>
            <div className="flex items-center mt-1">
              <Badge variant={predictionAccuracy === 'Good' ? 'default' : predictionAccuracy === 'Fair' ? 'secondary' : 'outline'}>
                {predictionAccuracy}
              </Badge>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Sample Size</CardTitle>
            <BarChart3 className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{(analysis.sample_size || 0).toLocaleString()}</div>
            <p className="text-xs text-muted-foreground">Data points analyzed</p>
            <div className="flex items-center mt-1">
              <Badge variant={sampleAdequacy === 'Sufficient' ? 'default' : 'outline'}>
                {sampleAdequacy}
              </Badge>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Enhanced Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>Performance Metrics</CardTitle>
            <CardDescription>Universal Beta Model accuracy indicators</CardDescription>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={performanceData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" />
                <YAxis />
                <Tooltip 
                  formatter={(value: any, name: any) => [
                    name === 'R²' || name === 'Dir. Acc.' 
                      ? `${(value * 100).toFixed(1)}%` 
                      : value.toFixed(4), 
                    name
                  ]}
                />
                <Bar dataKey="value" fill="#3b82f6" />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Model Insights & Quality Assessment</CardTitle>
            <CardDescription>Advanced analytics and model interpretation</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-3">
              <div className="flex justify-between items-center">
                <span className="text-sm text-muted-foreground">Model Type:</span>
                <Badge variant="outline">Universal Beta ElasticNet</Badge>
              </div>
              <div className="flex justify-between">
                <span className="text-sm text-muted-foreground">Horizon Days:</span>
                <span className="text-sm font-medium">{analysis.horizon_days}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-sm text-muted-foreground">Status:</span>
                <Badge variant={analysis.status === 'completed' ? 'default' : 'secondary'}>
                  {analysis.status}
                </Badge>
              </div>
              
              <div className="border-t pt-3 mt-4">
                <h4 className="font-medium text-sm mb-2">Quality Indicators</h4>
                <div className="space-y-2">
                  <div className="flex justify-between items-center">
                    <span className="text-xs text-muted-foreground">Model Significance:</span>
                    <Badge variant={modelSignificance === 'High' ? 'default' : modelSignificance === 'Medium' ? 'secondary' : 'outline'}>
                      {modelSignificance}
                    </Badge>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-xs text-muted-foreground">Prediction Accuracy:</span>
                    <Badge variant={predictionAccuracy === 'Good' ? 'default' : predictionAccuracy === 'Fair' ? 'secondary' : 'outline'}>
                      {predictionAccuracy}
                    </Badge>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-xs text-muted-foreground">Sample Adequacy:</span>
                    <Badge variant={sampleAdequacy === 'Sufficient' ? 'default' : 'outline'}>
                      {sampleAdequacy}
                    </Badge>
                  </div>
                </div>
              </div>

              <div className="border-t pt-3 mt-4">
                <h4 className="font-medium text-sm mb-2">Performance Summary</h4>
                <div className="bg-muted rounded-lg p-3">
                  <p className="text-xs text-muted-foreground mb-1">Model Performance:</p>
                  <p className="text-sm font-medium">
                    R² = {((analysis.r2_global || 0) * 100).toFixed(1)}%, 
                    MAE = {(analysis.mae || 0).toFixed(4)}, 
                    Dir. Accuracy = {((analysis.directional_accuracy || 0) * 100).toFixed(1)}%
                  </p>
                  <p className="text-xs text-muted-foreground mt-2">
                    {analysis.sample_size?.toLocaleString() || 0} observations analyzed across {analysis.horizon_days} day horizon
                  </p>
                </div>
              </div>

              <div className="border-t pt-3 mt-4">
                <h4 className="font-medium text-sm mb-2">Timing</h4>
                <div className="space-y-1">
                  <div className="flex justify-between">
                    <span className="text-xs text-muted-foreground">Created:</span>
                    <span className="text-xs">{formatDate(analysis.created_at)}</span>
                  </div>
                  {analysis.completed_at && (
                    <div className="flex justify-between">
                      <span className="text-xs text-muted-foreground">Completed:</span>
                      <span className="text-xs">{formatDate(analysis.completed_at)}</span>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Additional Insights Section */}
      <div className="grid grid-cols-1 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>Universal Beta Model Explanation</CardTitle>
            <CardDescription>Understanding your analysis results</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
                <h4 className="font-medium text-blue-900 mb-2">What This Analysis Shows</h4>
                <p className="text-sm text-blue-800">
                  This Universal Beta Forecasting model predicts future beta coefficients (market sensitivity) 
                  for individual stocks using cross-sectional features and advanced machine learning techniques.
                </p>
              </div>
              
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <h4 className="font-medium mb-2">Key Metrics Explained</h4>
                  <ul className="text-sm space-y-1 text-muted-foreground">
                    <li><strong>R² Score:</strong> How well the model explains beta variations (higher = better)</li>
                    <li><strong>MAE:</strong> Average prediction error magnitude (lower = better)</li>
                    <li><strong>Directional Accuracy:</strong> % of time model predicts correct direction</li>
                    <li><strong>Sample Size:</strong> Number of stock-date observations used</li>
                  </ul>
                </div>
                <div>
                  <h4 className="font-medium mb-2">Investment Applications</h4>
                  <ul className="text-sm space-y-1 text-muted-foreground">
                    <li>• Portfolio risk management and hedging strategies</li>
                    <li>• Factor model optimization for asset allocation</li>
                    <li>• Market-neutral strategy development</li>
                    <li>• Dynamic beta forecasting for risk models</li>
                  </ul>
                </div>
              </div>

              <div className="bg-amber-50 border border-amber-200 rounded-lg p-4">
                <h4 className="font-medium text-amber-900 mb-2">Interpretation Guidelines</h4>
                <div className="text-sm text-amber-800 space-y-1">
                  <p>• <strong>High R² (&gt;10%):</strong> Strong predictive power for beta forecasting</p>
                  <p>• <strong>Good Dir. Accuracy (&gt;55%):</strong> Reliable for directional beta changes</p>
                  <p>• <strong>Low MAE (&lt;0.05):</strong> Precise magnitude predictions</p>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
};