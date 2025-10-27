"use client";

import type React from "react";
import { useState, useCallback, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import api from "@/app/lib/api";
import type { AxiosProgressEvent } from "axios";
import {
  Upload,
  FileSpreadsheet,
  AlertCircle,
  CheckCircle,
  Loader2,
  XCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Progress } from "@/components/ui/progress";

type Phase = "idle" | "uploading" | "processing" | "done" | "error";

export default function UploadPage() {
  const [file, setFile] = useState<File | null>(null);

  // phase & messaging
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // upload metrics
  const [uploadPct, setUploadPct] = useState(0);
  const [bytesUploaded, setBytesUploaded] = useState(0);
  const [speedMbps, setSpeedMbps] = useState<number | null>(null);
  const [etaSec, setEtaSec] = useState<number | null>(null);
  const [uploadDone, setUploadDone] = useState(false);

  // server processing (real, from /uploads/:id/status/)
  const [statusUrl, setStatusUrl] = useState<string | null>(null);
  const [procPct, setProcPct] = useState(0);
  const [procStage, setProcStage] = useState("Queued…");

  const router = useRouter();
  const abortRef = useRef<AbortController | null>(null);

  const handleFileSelect = useCallback((event: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = event.target.files?.[0];
    if (!selectedFile) return;

    const validByExt =
      selectedFile.name.toLowerCase().endsWith(".xlsx") ||
      selectedFile.name.toLowerCase().endsWith(".csv");
    const validByMime =
      ["text/csv", "application/vnd.ms-excel"].includes(selectedFile.type) ||
      selectedFile.type ===
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

    if (!validByExt && !validByMime) {
      setError("Please upload a CSV or Excel file (.csv, .xlsx)");
      setFile(null);
      return;
    }
    if (selectedFile.size > 200 * 1024 * 1024) {
      setError("File size must be less than 200MB");
      setFile(null);
      return;
    }

    // reset state
    setError(null);
    setSuccessMsg(null);
    setPhase("idle");
    setFile(selectedFile);
    setUploadPct(0);
    setBytesUploaded(0);
    setSpeedMbps(null);
    setEtaSec(null);
    setUploadDone(false);

    // processing state
    setStatusUrl(null);
    setProcPct(0);
    setProcStage("Queued…");
  }, []);

  const handleDrop = useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      const droppedFile = event.dataTransfer.files?.[0];
      if (!droppedFile) return;
      const synthetic = {
        target: { files: [droppedFile] },
      } as unknown as React.ChangeEvent<HTMLInputElement>;
      handleFileSelect(synthetic);
    },
    [handleFileSelect]
  );

  const handleDragOver = useCallback((event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
  }, []);

  // Poll backend status while processing
  useEffect(() => {
    if (phase !== "processing" || !statusUrl) return;
    let cancelled = false;
    const interval = setInterval(async () => {
      try {
        const res = await api.get(statusUrl, { withCredentials: true });
        if (cancelled) return;

        const s = res.data || {};
        if (typeof s.progress === "number") setProcPct(s.progress);
        if (typeof s.stage === "string") setProcStage(s.stage);

        if (s.status === "completed") {
          setProcPct(100);
          setProcStage("Completed");
          setPhase("done");
          setSuccessMsg("File processed successfully.");
          clearInterval(interval);
        } else if (s.status === "failed") {
          setError(s.error || "Server processing failed.");
          setPhase("error");
          clearInterval(interval);
        }
      } catch (err: any) {
        // transient polling errors shouldn't nuke the UI; keep polling
      }
    }, 1200);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [phase, statusUrl]);

  const handleUpload = async () => {
    if (!file) return;

    setPhase("uploading");
    setUploadPct(0);
    setBytesUploaded(0);
    setSpeedMbps(null);
    setEtaSec(null);
    setUploadDone(false);
    setError(null);
    setSuccessMsg(null);

    const controller = new AbortController();
    abortRef.current = controller;

    const formData = new FormData();
    formData.append("file", file);

    // for speed/eta sampling
    let lastTime = performance.now();
    let lastLoaded = 0;

    try {
      const res = await api.post(`/upload-csv/`, formData, {
        headers: { "Content-Type": "multipart/form-data" },
        withCredentials: true,
        signal: controller.signal as unknown as AbortSignal,
        onUploadProgress: (evt: AxiosProgressEvent) => {
          const ratio =
            typeof evt.progress === "number"
              ? evt.progress
              : evt.total
              ? (evt.loaded ?? 0) / evt.total
              : null;

          if (ratio !== null) {
            const pct = Math.min(100, Math.max(0, Math.round(ratio * 100)));
            setUploadPct(pct);
            setBytesUploaded(evt.loaded ?? 0);

            const now = performance.now();
            const dt = Math.max(1, now - lastTime);
            const dBytes = Math.max(0, (evt.loaded ?? 0) - lastLoaded);
            const bytesPerSec = (dBytes / dt) * 1000;
            const mbps = (bytesPerSec * 8) / (1024 * 1024);
            const totalBytes = evt.total ?? file.size;
            const bytesRemaining = totalBytes - (evt.loaded ?? 0);
            const eta = bytesPerSec > 0 ? Math.round(bytesRemaining / bytesPerSec) : null;

            setSpeedMbps(Number.isFinite(mbps) ? mbps : null);
            setEtaSec(eta && Number.isFinite(eta) ? eta : null);

            lastTime = now;
            lastLoaded = evt.loaded ?? lastLoaded;

            if (pct >= 100) setUploadDone(true);
          }
        },
        maxBodyLength: Infinity,
        maxContentLength: Infinity,
      });

      // The server immediately returns { upload_id, status_url }
      const status_url: string | undefined = res.data?.status_url;
      if (!status_url) {
        // Fallback: treat as done if backend didn’t give us a URL
        setProcPct(100);
        setProcStage("Completed");
        setPhase("done");
        setSuccessMsg(res.data?.message ?? "File uploaded successfully.");
        return;
      }

      // Switch to processing and start polling
      setStatusUrl(status_url);
      setPhase("processing");
      setProcStage("Queued…");
      setProcPct((p) => (p > 1 ? p : 1));
    } catch (e: any) {
      if (controller.signal.aborted) {
        setError("Upload canceled.");
      } else {
        const apiErr =
          e?.response?.data?.error ||
          (typeof e?.response?.data === "string" ? e.response.data : null) ||
          e?.message ||
          "Upload failed. Please try again.";
        setError(apiErr);
      }
      setPhase("error");
      setUploadPct(0);
      setProcPct(0);
    } finally {
      abortRef.current = null;
    }
  };

  const cancelUpload = () => {
    if (phase === "uploading") {
      abortRef.current?.abort();
    }
  };

  const formatFileSize = (bytes: number) => {
    if (bytes === 0) return "0 B";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
    if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(2)} MB`;
    return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
  };

  const fmtEta = (s: number | null) => {
    if (!s || s < 0) return "—";
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    const r = s % 60;
    return `${m}m ${r}s`;
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50">
      <div className="container mx-auto px-4 py-8 max-w-4xl">
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-gray-900 mb-2">Upload Your Data</h1>
          <p className="text-gray-600">
            Upload your CSV/Excel file for Universal Beta Forecasting analysis.
          </p>
          <div className="mt-4 p-4 bg-blue-50 rounded-lg border border-blue-200">
            <div className="flex items-center gap-2 mb-2">
              <FileSpreadsheet className="h-4 w-4 text-blue-600" />
              <span className="text-sm font-medium text-blue-800">
                Universal Beta Forecasting Model
              </span>
            </div>
            <p className="text-sm text-blue-700">
              We show separate progress for the network upload and server processing.
              When the upload hits 100%, the file is on the server; processing continues until completed.
            </p>
          </div>
        </div>

        <div className="space-y-8">
          <div className="grid lg:grid-cols-2 gap-8">
            {/* Upload Section */}
            <Card>
              <CardHeader>
                <CardTitle>File Upload</CardTitle>
                <CardDescription>Drag and drop your file or click to browse</CardDescription>
              </CardHeader>
              <CardContent>
                <div
                  className={`relative border-2 border-dashed rounded-lg p-8 text-center transition-colors ${
                    file ? "border-green-300 bg-green-50" : "border-gray-300 hover:border-gray-400"
                  }`}
                  onDrop={handleDrop}
                  onDragOver={handleDragOver}
                >
                  {file ? (
                    <div className="space-y-4">
                      <CheckCircle className="h-12 w-12 text-green-600 mx-auto" />
                      <div>
                        <p className="font-medium text-gray-900">{file.name}</p>
                        <p className="text-sm text-gray-500">{formatFileSize(file.size)}</p>
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-4">
                      <Upload className="h-12 w-12 text-gray-400 mx-auto" />
                      <div>
                        <p className="text-lg font-medium text-gray-900">Drop your file here</p>
                        <p className="text-gray-500">or click to browse</p>
                      </div>
                    </div>
                  )}

                  {/* Click-through input */}
                  <input
                    type="file"
                    accept=".csv,.xlsx"
                    onChange={handleFileSelect}
                    className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                    disabled={phase === "uploading" || phase === "processing"}
                  />
                </div>

                {error && (
                  <Alert className="mt-4" variant="destructive">
                    <AlertCircle className="h-4 w-4" />
                    <AlertDescription>{error}</AlertDescription>
                  </Alert>
                )}

                {successMsg && (
                  <Alert className="mt-4">
                    <CheckCircle className="h-4 w-4" />
                    <AlertDescription>{successMsg}</AlertDescription>
                  </Alert>
                )}

                {(phase === "uploading" || phase === "processing") && (
                  <div className="mt-4 space-y-4">
                    {/* Upload progress (real) */}
                    <div>
                      <div className="flex items-center justify-between text-sm mb-1">
                        <span className="flex items-center gap-2">
                          Uploading to server
                          {uploadDone && (
                            <span className="text-xs px-2 py-0.5 rounded-full bg-green-100 text-green-700 border border-green-200">
                              Upload complete
                            </span>
                          )}
                        </span>
                        <span>{uploadPct}%</span>
                      </div>
                      <Progress value={uploadPct} />
                      <div className="mt-1 text-xs text-gray-500">
                        {bytesUploaded > 0 && file
                          ? `${formatFileSize(bytesUploaded)} of ${formatFileSize(file.size)}`
                          : null}
                        {speedMbps ? ` • ${speedMbps!.toFixed(1)} Mb/s • ETA ${fmtEta(etaSec)}` : ""}
                      </div>
                    </div>

                    {/* Processing progress (server-driven) */}
                    {statusUrl && (
                      <div>
                        <div className="flex items-center justify-between text-sm mb-1">
                          <span>Server processing</span>
                          <span>{procPct}%</span>
                        </div>
                        <Progress value={procPct} />
                        <div className="mt-1 text-xs text-gray-600">{procStage}</div>
                        <div className="mt-1 text-[11px] text-gray-400">
                          This step includes validating the sheet, parsing rows, and writing to the database.
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* Actions */}
                <div className="flex gap-2 mt-4">
                  {phase !== "done" ? (
                    <>
                      <Button
                        onClick={handleUpload}
                        disabled={!file || phase === "uploading" || phase === "processing"}
                        className="flex-1"
                        size="lg"
                      >
                        {phase === "uploading" || phase === "processing" ? (
                          <>
                            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                            {phase === "uploading" ? "Uploading…" : "Processing…"}
                          </>
                        ) : (
                          "Upload Data"
                        )}
                      </Button>

                      {(phase === "uploading") && (
                        <Button
                          type="button"
                          variant="outline"
                          onClick={cancelUpload}
                          className="shrink-0"
                        >
                          <XCircle className="mr-2 h-4 w-4" />
                          Cancel
                        </Button>
                      )}
                    </>
                  ) : (
                    <Button
                      onClick={() => router.push("/data")}
                      className="flex-1"
                      size="lg"
                    >
                      Go to My Data
                    </Button>
                  )}
                </div>
              </CardContent>
            </Card>

            {/* Requirements (trimmed) */}
            <Card>
              <CardHeader>
                <CardTitle>File Requirements</CardTitle>
                <CardDescription>
                  Ensure your file follows these requirements for successful analysis.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex items-start space-x-3">
                  <FileSpreadsheet className="h-5 w-5 text-blue-600 mt-0.5" />
                  <div>
                    <h3 className="font-medium">Format</h3>
                    <p className="text-sm text-gray-600">
                      <strong>Excel (.xlsx)</strong> or <strong>CSV</strong>. If Excel, use a sheet named{" "}
                      <code>Returns</code>.
                    </p>
                  </div>
                </div>
                <div className="flex items-start space-x-3">
                  <CheckCircle className="h-5 w-5 text-green-600 mt-0.5" />
                  <div>
                    <h3 className="font-medium">Size</h3>
                    <p className="text-sm text-gray-600">Max 200 MB</p>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
}
