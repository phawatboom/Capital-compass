/**
 * Mock API functions for Capital Compass
 * Simulates the Django REST API responses
 */

import type { Upload, AnalysisListItem, AnalysisDetail } from "@/types/analysis"
import { mockUploads, mockAnalyses, mockDetailedAnalyses, mockUploadAnalyses } from "./mockData"

// Simulate network delay
const delay = (ms = 500) => new Promise((resolve) => setTimeout(resolve, ms))

/**
 * Upload a CSV file to the server (mock)
 */
export async function createUpload(file: File): Promise<Upload> {
  await delay(1000)

  // Validate file
  if (!file.name.toLowerCase().endsWith(".csv")) {
    throw new Error("Please upload a CSV file (.csv)")
  }

  if (file.size > 20 * 1024 * 1024) {
    throw new Error("File size must be less than 20MB")
  }

  // Generate mock upload
  const uploadId = `upload-${Date.now()}`
  const upload: Upload = {
    upload_id: uploadId,
    original_filename: file.name,
    row_count: Math.floor(Math.random() * 10000) + 1000,
    status: "queued",
    created_at: new Date().toISOString(),
  }

  // Store mock upload
  mockUploads[uploadId] = upload

  return upload
}

/**
 * Trigger analysis of an uploaded file (mock)
 */
export async function analyzeUpload(uploadId: string): Promise<{
  upload_id: string
  tickers: string[]
  analysis_ids: string[]
  summary: { stocks: number; failed: number }
}> {
  await delay(1500)

  // Use existing analyses for demo
  const analysisIds = ["analysis-aapl", "analysis-msft", "analysis-googl"]
  const tickers = ["AAPL", "MSFT", "GOOGL"]

  // Update upload status
  if (mockUploads[uploadId]) {
    mockUploads[uploadId].status = "processing"
  }

  // Store mapping
  mockUploadAnalyses[uploadId] = analysisIds

  return {
    upload_id: uploadId,
    tickers,
    analysis_ids: analysisIds,
    summary: { stocks: tickers.length, failed: 0 },
  }
}

/**
 * Get list of analyses for an upload (mock)
 */
export async function listAnalyses(
  uploadId?: string,
  limit?: number,
  order?: string,
): Promise<{ items: AnalysisListItem[] }> {
  await delay(300)

  let items = [...mockAnalyses]

  // Filter by upload ID if provided
  if (uploadId && mockUploadAnalyses[uploadId]) {
    const analysisIds = mockUploadAnalyses[uploadId]
    items = items.filter((item) => analysisIds.includes(item.analysis_id))
  }

  // Apply ordering
  if (order === "-analysis_date") {
    items.sort((a, b) => b.analysis_date.localeCompare(a.analysis_date))
  }

  // Apply limit
  if (limit) {
    items = items.slice(0, limit)
  }

  return { items }
}

/**
 * Get detailed analysis for a specific stock (mock)
 */
export async function getAnalysis(analysisId: string): Promise<AnalysisDetail> {
  await delay(400)

  const analysis = mockDetailedAnalyses[analysisId]
  if (!analysis) {
    throw new Error("Analysis not found")
  }

  return analysis
}

/**
 * Get PDF report URL for a specific analysis (mock)
 */
export function getPdfReportUrl(analysisId: string): string {
  // Return a mock PDF URL - in real implementation this would be the actual API endpoint
  return `data:application/pdf;base64,mock-pdf-${analysisId}`
}

/**
 * Poll for upload status until complete (mock)
 */
export async function pollUploadStatus(uploadId: string, interval = 1000, maxAttempts = 10): Promise<Upload> {
  let attempts = 0

  const poll = async (): Promise<Upload> => {
    await delay(interval)

    const upload = mockUploads[uploadId]
    if (!upload) {
      throw new Error("Upload not found")
    }

    // Simulate processing completion
    if (attempts >= 2 && upload.status === "processing") {
      upload.status = "done"
      upload.completed_at = new Date().toISOString()
    } else if (upload.status === "queued" && attempts >= 1) {
      upload.status = "processing"
    }

    if (upload.status === "done") {
      return upload
    }

    if (upload.status === "failed") {
      throw new Error(upload.error_text || "Upload processing failed")
    }

    if (attempts >= maxAttempts) {
      throw new Error("Upload processing timed out")
    }

    attempts++
    return poll()
  }

  return poll()
}
