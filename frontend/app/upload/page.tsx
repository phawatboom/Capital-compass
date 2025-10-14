"use client";

import type React from "react";
import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import api from "@/app/lib/api";
import { Upload, FileSpreadsheet, AlertCircle, CheckCircle, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Progress } from "@/components/ui/progress";
import ModelSelectionCard from "@/components/ModelSelectionCard";
import type { ModelType } from "@/types/analysis";
import {format} from "node:url";

/**
 * Configure your API base:
 * - Create .env.local with: NEXT_PUBLIC_API_BASE=http://127.0.0.1:8000
 * - In production, point this to your deployed backend.
 */
const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

export default function UploadPage() {
  const [file, setFile] = useState<File | null>(null);
  const [selectedModel, setSelectedModel] = useState<ModelType>("beta-forecasting");
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const router = useRouter();

  const handleFileSelect = useCallback((event: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = event.target.files?.[0];
    if (selectedFile) {
      const validTypes = ["text/csv", "application/vnd.ms-excel"];
      if (
        !validTypes.includes(selectedFile.type) &&
        !selectedFile.name.toLowerCase().endsWith(".csv") &&
        !selectedFile.name.toLowerCase().endsWith(".xlsx")
      ) {
        setError("Please upload a CSV or Excel file (.csv, .xlsx)");
        setFile(null);
        return;
      }
      if (selectedFile.size > 200 * 1024 * 1024) {
        setError("File size must be less than 200MB");
        setFile(null);
        return;
      }
      setError(null);
      setFile(selectedFile);
    }
  }, []);

  const handleDrop = useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      const droppedFile = event.dataTransfer.files?.[0];
      if (!droppedFile) return;
      const synthetic = { target: { files: [droppedFile] } } as unknown as React.ChangeEvent<HTMLInputElement>;
      handleFileSelect(synthetic);
    },
    [handleFileSelect]
  );

  const handleDragOver = useCallback((event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
  }, []);

  const handleUpload = async () => {
    if (!file) return;
    setUploading(true);
    setUploadProgress(0);
    setError(null);
    setSuccessMsg(null);

    const formData = new FormData();
    formData.append("file", file);
    formData.append("model_type", selectedModel);

    try {
      const res = await api.post(
        `/upload-csv/`,
        formData,
        {
          headers: { "Content-Type": "multipart/form-data" },
          onUploadProgress: (evt) => {
            if (!evt.total) return;
            const pct = Math.round((evt.loaded / evt.total) * 80); // 0–80% = network upload
            setUploadProgress(pct);
          },
        }
      );

      // Simulate processing completion to 100%
      setUploadProgress(100);

      // Backend returns { message, upload: { id, filename, uploaded_at } }
      const msg = res.data?.message ?? "CSV Uploaded Successfully";
      const uploadId = res.data?.upload?.id;

      setSuccessMsg(`${msg} - Model: ${selectedModel === 'mean-reversion' ? 'Mean-Reversion (MR-PROD)' : 'β-Forecasting'}`);

      // Redirect after a short pause. Use /uploads since it already exists in your app.
      setTimeout(() => {
        router.push("/uploads");
        // or, if you later build a run page:
        // router.push(`/runs/${uploadId}`);
      }, 600);
    } catch (e: any) {
      setUploading(false);
      setUploadProgress(0);
      const apiErr =
        e?.response?.data?.error ||
        (typeof e?.response?.data === "string" ? e.response.data : null) ||
        e?.message ||
        "Upload failed. Please try again.";
      setError(apiErr);
    }
  };

  const formatFileSize = (bytes: number) => {
      if (bytes === 0) return "0 B";
      if (bytes < 1024) return `${bytes} B`;
      if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
      if (bytes < 1024 ** 3) return `${(bytes / (1024 ** 2)).toFixed(2)} MB`;
      return `${(bytes / (1024 ** 3)).toFixed(2)} GB`;
    };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50">
      <div className="container mx-auto px-4 py-8 max-w-4xl">
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-gray-900 mb-2">Upload Your Data</h1>
          <p className="text-gray-600">
            Upload your CSV file containing stock price data for analysis
          </p>
        </div>

        <div className="space-y-8">
          {/* Model Selection */}
          <ModelSelectionCard 
            selectedModel={selectedModel} 
            onModelChange={setSelectedModel} 
          />
          
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
                      <p className="text-sm text-gray-500">
                        {(formatFileSize(file.size))}
                      </p>
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

                {/* Make the input clickable over the whole drop zone */}
                <input
                  type="file"
                  accept=".csv,.xlsx"
                  onChange={handleFileSelect}
                  className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                  disabled={uploading}
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

              {uploading && (
                <div className="mt-4 space-y-2">
                  <div className="flex items-center justify-between text-sm">
                    <span>Uploading and processing...</span>
                    <span>{uploadProgress}%</span>
                  </div>
                  <Progress value={uploadProgress} />
                </div>
              )}

              <Button onClick={handleUpload} disabled={!file || uploading} className="w-full mt-4" size="lg">
                {uploading ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Processing...
                  </>
                ) : (
                  "Upload Data"
                )}
              </Button>
            </CardContent>
          </Card>

          {/* Requirements Section */}
          <Card>
            <CardHeader>
              <CardTitle>File Requirements</CardTitle>
              <CardDescription>Ensure your data meets these requirements for optimal analysis</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-start space-x-3">
                <FileSpreadsheet className="h-5 w-5 text-blue-600 mt-0.5" />
                <div>
                  <h3 className="font-medium">File Format</h3>
                  <p className="text-sm text-gray-600">CSV only (.csv) with UTF-8 encoding</p>
                </div>
              </div>

              <div className="flex items-start space-x-3">
                <CheckCircle className="h-5 w-5 text-green-600 mt-0.5" />
                <div>
                  <h3 className="font-medium">Required Headers</h3>
                  <p className="text-sm text-gray-600">
                    <span className="font-medium">Note:</span> Your current backend expects a wide CSV with a
                    header row of stock names (after skipping the first 3 lines), not the long format shown
                    below. We can add long‑format support later if you want.
                  </p>
                </div>
              </div>

              <div className="flex items-start space-x-3">
                <CheckCircle className="h-5 w-5 text-green-600 mt-0.5" />
                <div>
                  <h3 className="font-medium">Data Requirements</h3>
                  <p className="text-sm text-gray-600">
                    No empty rows; dates parseable by backend (e.g., <code>%d-%b-%Y</code> like 30-Jul-2010).
                  </p>
                </div>
              </div>

              <div className="flex items-start space-x-3">
                <CheckCircle className="h-5 w-5 text-green-600 mt-0.5" />
                <div>
                  <h3 className="font-medium">File Size</h3>
                  <p className="text-sm text-gray-600">Maximum 20MB per file</p>
                </div>
              </div>

              <div className="bg-blue-50 p-4 rounded-lg mt-6">
                <h3 className="font-medium text-blue-900 mb-2">Sample (long format)</h3>
                <div className="text-xs font-mono bg-white p-2 rounded border">
                  <div>date,ticker,adj_close</div>
                  <div>2025-08-01,AAPL,150.25</div>
                  <div>2025-08-02,AAPL,151.10</div>
                  <div>2025-08-01,MSFT,375.80</div>
                  <div>2025-08-02,MSFT,378.20</div>
                  <div>...</div>
                </div>
                <p className="text-xs text-gray-600 mt-2">
                  Your current backend expects a wide format (multiple stock columns). We can support both.
                </p>
              </div>
            </CardContent>
          </Card>
          </div>
        </div>
      </div>
    </div>
  );
}