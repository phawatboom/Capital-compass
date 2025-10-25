"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
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
} from "lucide-react";
import * as XLSX from "xlsx";
import RequireAuth from "../lib/requireAuth";
import { Button } from "@/components/ui/button";

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

  useEffect(() => {
    fetchUploads();
  }, [fetchUploads]);

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
      // Navigate to beta analysis platform with the file ID
      router.push(`/dashboard/beta-analysis-platform?fileId=${uploadId}`);
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
                              className="h-8 px-2"
                              onClick={() => handleAnalyze(u.id)}
                              title="Analyze with Beta Model"
                            >
                              Analyze
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
      </div>
    </RequireAuth>
  );
}