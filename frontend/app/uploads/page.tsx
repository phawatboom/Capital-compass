"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
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
} from "lucide-react";
import api from "../lib/api";
import RequireAuth from "../lib/requireAuth";
import { Button } from "@/components/ui/button";

type UploadRecord = {
  id: number;
  filename: string;
  uploaded_at: string; // ISO
};

type FileMeta = {
  id: number;
  filename: string;
  uploaded_at: string;
  size: number;
  type: string;
  rows?: number;
  sheets?: { name: string; rows: number; cols: number }[];
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
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export default function UploadsPage() {
  const [uploads, setUploads] = useState<UploadRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  // Filters/sort/pagination
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<"" | "csv" | "xlsx">("");
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

  const fetchUploads = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await api.get<UploadRecord[]>("/csv-uploads/");
      setUploads(data);
    } catch {
      setError("Failed to load uploads.");
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
      const name = basename(u.filename).toLowerCase();
      const t = ext(u.filename);
      const matchesName = !q || name.includes(q);
      const matchesType = !typeFilter || t === typeFilter;
      return matchesName && matchesType;
    });
  }, [uploads, query, typeFilter]);

  const sorted = useMemo(() => {
    const arr = [...filtered];
    arr.sort((a, b) => {
      if (sortKey === "name") {
        const an = basename(a.filename).toLowerCase();
        const bn = basename(b.filename).toLowerCase();
        return sortDir === "asc" ? an.localeCompare(bn) : bn.localeCompare(an);
      } else {
        const ad = +new Date(a.uploaded_at);
        const bd = +new Date(b.uploaded_at);
        return sortDir === "asc" ? ad - bd : bd - ad;
      }
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
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  };

  const clearFilters = () => {
    setQuery("");
    setTypeFilter("");
    setSortKey("uploaded_at");
    setSortDir("desc");
    setPage(1);
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
      setMessage("Download link copied to clipboard.");
      setTimeout(() => setMessage(null), 2500);
    } catch {
      setError("Failed to copy link.");
      setTimeout(() => setError(null), 2500);
    }
  };

  const deleteOne = useCallback(async (id: number) => {
    await api.get("/auth/csrf/");
    await api.delete(`/csv-uploads/${id}/`);
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
        setUploads((prev) => prev.filter((u) => u.id !== confirm.id));
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
        setUploads((prev) => prev.filter((u) => !selected.has(u.id)));
        setSelected(new Set());
      }
      setMessage("Delete completed.");
      setTimeout(() => setMessage(null), 2000);
    } catch {
      setError("Failed to delete file(s).");
    } finally {
      setBusy(false);
      setConfirm(null);
    }
  };

  const cancelConfirm = () => setConfirm(null);

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setUploading(true);
    setMessage(null);
    setError(null);
    try {
      await api.get("/auth/csrf/");
      const fd = new FormData();
      fd.append("file", file);
      await api.post("/upload-csv/", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setFile(null);
      setMessage("File uploaded successfully.");
      await fetchUploads();
    } catch (err: any) {
      setError(
        err?.response?.data?.error ||
          "Upload failed. Please verify the file format."
      );
    } finally {
      setUploading(false);
      setTimeout(() => setMessage(null), 2500);
    }
  };

  const openInfo = async (id: number) => {
    setInfoOpen(true);
    setInfoLoading(true);
    setInfoData(null);
    try {
      const { data } = await api.get<FileMeta>(`/csv-uploads/${id}/meta/`);
      setInfoData(data);
    } catch {
      setInfoData(null);
    } finally {
      setInfoLoading(false);
    }
  };

  return (
    <RequireAuth>
      <div className="container mx-auto px-4 py-8 max-w-6xl">
        <div className="flex items-center justify-between gap-4 mb-6">
          <h1 className="text-2xl font-semibold">My Uploads</h1>
          <form onSubmit={handleUpload} className="flex items-center gap-3">
            <input
              type="file"
              className="block text-sm"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              accept=".csv,.xlsx"
            />
            <Button type="submit" disabled={!file || uploading}>
              <UploadIcon className="h-4 w-4 mr-2" />
              {uploading ? "Uploading..." : "Upload"}
            </Button>
          </form>
        </div>

        {(message || error) && (
          <div
            className={`mb-4 rounded px-4 py-3 text-sm ${
              message
                ? "bg-green-50 text-green-800 border border-green-200"
                : "bg-red-50 text-red-800 border border-red-200"
            }`}
          >
            {message || error}
          </div>
        )}

        <div className="bg-white border rounded-lg p-4 shadow-sm mb-4">
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex-1 min-w-[220px]">
              <label className="text-xs text-gray-600">Search name</label>
              <div className="flex items-center border rounded px-2 py-1">
                <Search className="h-4 w-4 text-gray-500 mr-2" />
                <input
                  value={query}
                  onChange={(e) => {
                    setQuery(e.target.value);
                    setPage(1);
                  }}
                  placeholder="e.g. prices"
                  className="w-full outline-none text-sm"
                />
              </div>
            </div>
            <div>
              <label className="text-xs text-gray-600">File type</label>
              <select
                value={typeFilter}
                onChange={(e) => {
                  setTypeFilter(e.target.value as any);
                  setPage(1);
                }}
                className="border rounded px-2 py-1 text-sm"
              >
                <option value="">All</option>
                <option value="csv">CSV</option>
                <option value="xlsx">XLSX</option>
              </select>
            </div>
            <div className="ml-auto flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => toggleSort("name")}
                className="text-sm"
              >
                Name {sortKey === "name" ? (sortDir === "asc" ? <SortAsc className="ml-1 h-4 w-4" /> : <SortDesc className="ml-1 h-4 w-4" />) : null}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => toggleSort("uploaded_at")}
                className="text-sm"
              >
                Uploaded {sortKey === "uploaded_at" ? (sortDir === "asc" ? <SortAsc className="ml-1 h-4 w-4" /> : <SortDesc className="ml-1 h-4 w-4" />) : null}
              </Button>
              <Button variant="ghost" onClick={clearFilters} className="text-sm">
                <X className="h-4 w-4 mr-1" />
                Clear
              </Button>
            </div>
          </div>
        </div>

        <div className="flex items-center justify-between mb-2">
          <div className="text-sm text-gray-600">
            {loading ? "Loading..." : `${sorted.length} file(s)`}
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="destructive"
              disabled={selected.size === 0}
              onClick={openConfirmBulk}
              className="text-sm"
            >
              <Trash2 className="h-4 w-4 mr-2" />
              Delete selected
            </Button>
            <select
              value={pageSize}
              onChange={(e) => {
                setPageSize(parseInt(e.target.value, 10));
                setPage(1);
              }}
              className="border rounded px-2 py-1 text-sm"
            >
              {[10, 20, 50].map((n) => (
                <option key={n} value={n}>
                  {n} / page
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="overflow-x-auto bg-white border rounded-lg shadow-sm">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50">
              <tr className="text-left">
                <th className="px-3 py-2 w-10">
                  <input
                    type="checkbox"
                    checked={
                      pageData.length > 0 &&
                      pageData.every((u) => selected.has(u.id))
                    }
                    onChange={(e) =>
                      handleSelectAllOnPage(e.currentTarget.checked)
                    }
                  />
                </th>
                <th className="px-3 py-2">Name</th>
                <th className="px-3 py-2">Type</th>
                <th className="px-3 py-2">Uploaded</th>
                <th className="px-3 py-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {pageData.map((u) => {
                const name = basename(u.filename);
                const t = ext(u.filename);
                return (
                  <tr key={u.id} className="border-t">
                    <td className="px-3 py-2 align-middle">
                      <input
                        type="checkbox"
                        checked={selected.has(u.id)}
                        onChange={(e) =>
                          handleSelectOne(u.id, e.currentTarget.checked)
                        }
                      />
                    </td>
                    <td className="px-3 py-2 align-middle">{name}</td>
                    <td className="px-3 py-2 align-middle uppercase">{t || "—"}</td>
                    <td className="px-3 py-2 align-middle">
                      {formatDate(u.uploaded_at)}
                    </td>
                    <td className="px-3 py-2 align-middle">
                      <div className="flex justify-end gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => handleDownload(u.id)}
                          title="Download"
                        >
                          <Download className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => handleCopyLink(u.id)}
                          title="Copy download link"
                        >
                          <LinkIcon className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => openInfo(u.id)}
                          title="File info"
                        >
                          <Info className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="destructive"
                          size="sm"
                          onClick={() => openConfirmSingle(u.id, name)}
                          title="Delete"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </td>
                  </tr>
                );
              })}
              {!loading && pageData.length === 0 && (
                <tr>
                  <td className="px-3 py-8 text-center text-gray-500" colSpan={5}>
                    No files match your filters.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="flex items-center justify-between mt-4">
          <div className="text-sm text-gray-600">
            Page {currentPage} of {totalPages}
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={currentPage <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
            >
              Prev
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={currentPage >= totalPages}
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            >
              Next
            </Button>
          </div>
        </div>
      </div>

      {/* Delete Confirm Modal */}
      {confirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/40" />
          <div className="relative bg-white rounded-lg shadow-lg w-full max-w-md p-6">
            <h2 className="text-lg font-semibold mb-2">Confirm deletion</h2>
            <p className="text-sm text-gray-600 mb-4">
              {confirm.mode === "single"
                ? `Delete “${confirm.name}”? This action cannot be undone.`
                : `Delete ${selected.size} selected file(s)? This action cannot be undone.`}
            </p>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={cancelConfirm} disabled={busy}>
                Cancel
              </Button>
              <Button variant="destructive" onClick={confirmDelete} disabled={busy}>
                {busy ? "Deleting..." : "Delete"}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Info Modal */}
      {infoOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/40" onClick={() => setInfoOpen(false)} />
          <div className="relative bg-white rounded-lg shadow-lg w-full max-w-lg p-6">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-lg font-semibold">File info</h2>
              <button onClick={() => setInfoOpen(false)}>
                <X className="h-5 w-5" />
              </button>
            </div>
            {infoLoading && <div className="text-sm text-gray-600">Loading...</div>}
            {!infoLoading && !infoData && (
              <div className="text-sm text-red-600">Failed to load file info.</div>
            )}
            {!infoLoading && infoData && (
              <div className="space-y-2 text-sm">
                <div><span className="text-gray-500">Name:</span> {basename(infoData.filename)}</div>
                <div><span className="text-gray-500">Type:</span> {infoData.type?.toUpperCase() || "—"}</div>
                <div><span className="text-gray-500">Size:</span> {formatBytes(infoData.size)}</div>
                <div><span className="text-gray-500">Uploaded:</span> {formatDate(infoData.uploaded_at)}</div>
                {"rows" in infoData && (
                  <div><span className="text-gray-500">Rows:</span> {infoData.rows}</div>
                )}
                {infoData.sheets && infoData.sheets.length > 0 && (
                  <div className="mt-3">
                    <div className="text-gray-500 mb-1">Sheets:</div>
                    <ul className="list-disc pl-5 space-y-1">
                      {infoData.sheets.map((s) => (
                        <li key={s.name}>
                          <span className="font-medium">{s.name}</span> — {s.rows} rows, {s.cols} cols
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
            <div className="mt-4 flex justify-end">
              <Button variant="outline" onClick={() => setInfoOpen(false)}>
                Close
              </Button>
            </div>
          </div>
        </div>
      )}
    </RequireAuth>
  );
}