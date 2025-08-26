"use client"

import { useState, useEffect } from "react"
import Link from "next/link"
import { FileText, Search } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Input } from "@/components/ui/input"
import { listAnalyses } from "@/lib/mockApi"
import { type AnalysisListItem, getSignalFromScore, getSignalLabel, getSignalColor } from "@/types/analysis"

export default function ReportsIndexPage() {
  const [analyses, setAnalyses] = useState<AnalysisListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [searchTerm, setSearchTerm] = useState("")

  useEffect(() => {
    const fetchAnalyses = async () => {
      try {
        setLoading(true)
        const response = await listAnalyses(undefined, 100, "-analysis_date")
        setAnalyses(response.items)
        setError(null)
      } catch (err) {
        setError("Failed to load reports. Please try again.")
      } finally {
        setLoading(false)
      }
    }

    fetchAnalyses()
  }, [])

  // Group analyses by date
  const analysesByDate = analyses.reduce((groups: Record<string, AnalysisListItem[]>, analysis) => {
    const date = new Date(analysis.analysis_date || "").toISOString().split("T")[0]
    if (!groups[date]) {
      groups[date] = []
    }
    groups[date].push(analysis)
    return groups
  }, {})

  const filteredDates = Object.keys(analysesByDate)
    .filter((date) => {
      return analysesByDate[date].some((analysis) => analysis.ticker.toLowerCase().includes(searchTerm.toLowerCase()))
    })
    .sort((a, b) => b.localeCompare(a)) // Sort dates in descending order

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
          <p className="text-gray-600">Loading reports...</p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="min-h-screen bg-gray-50 p-8">
        <Card className="max-w-2xl mx-auto">
          <CardHeader>
            <CardTitle className="text-red-600">Error Loading Reports</CardTitle>
          </CardHeader>
          <CardContent>
            <p>{error}</p>
            <Button className="mt-4" onClick={() => window.location.reload()}>
              Try Again
            </Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="container mx-auto px-4 py-8 max-w-4xl">
        <div className="flex items-center justify-between mb-8">
          <h1 className="text-3xl font-bold text-gray-900">Available Reports</h1>
          <Link href="/upload">
            <Button>Upload New Data</Button>
          </Link>
        </div>

        {/* Search */}
        <div className="mb-6">
          <div className="relative">
            <Search className="absolute left-3 top-3 h-4 w-4 text-gray-400" />
            <Input
              placeholder="Search by ticker..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="pl-10"
            />
          </div>
        </div>

        {filteredDates.length === 0 ? (
          <Card>
            <CardContent className="py-8 text-center">
              <p className="text-gray-500">No reports found matching your search.</p>
            </CardContent>
          </Card>
        ) : (
          filteredDates.map((date) => {
            const dateAnalyses = analysesByDate[date].filter((analysis) =>
              analysis.ticker.toLowerCase().includes(searchTerm.toLowerCase()),
            )

            if (dateAnalyses.length === 0) return null

            return (
              <Card key={date} className="mb-6">
                <CardHeader>
                  <CardTitle>
                    Reports from{" "}
                    {new Date(date).toLocaleDateString("en-US", {
                      year: "numeric",
                      month: "long",
                      day: "numeric",
                    })}
                  </CardTitle>
                  <CardDescription>Click on a report to view its detailed one-page summary.</CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="overflow-x-auto">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Stock</TableHead>
                          <TableHead>Score (95% CI)</TableHead>
                          <TableHead>Signal</TableHead>
                          <TableHead>Action</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {dateAnalyses.map((analysis) => {
                          const signal = getSignalFromScore(analysis.score)
                          const signalLabel = getSignalLabel(signal)

                          return (
                            <TableRow key={analysis.analysis_id} className="hover:bg-gray-50">
                              <TableCell>
                                <div className="font-medium">{analysis.ticker}</div>
                              </TableCell>
                              <TableCell>
                                <div className="font-mono">
                                  {analysis.score.toFixed(2)}
                                  <span className="text-gray-500 text-xs">
                                    {` (${analysis.ci95_lower.toFixed(2)}–${analysis.ci95_upper.toFixed(2)})`}
                                  </span>
                                </div>
                              </TableCell>
                              <TableCell>
                                <Badge className={getSignalColor(signal)}>{signalLabel}</Badge>
                              </TableCell>
                              <TableCell>
                                <Link href={`/reports/${analysis.analysis_id}`}>
                                  <Button variant="outline" size="sm">
                                    <FileText className="h-4 w-4 mr-1" />
                                    View Report
                                  </Button>
                                </Link>
                              </TableCell>
                            </TableRow>
                          )
                        })}
                      </TableBody>
                    </Table>
                  </div>
                </CardContent>
              </Card>
            )
          })
        )}
      </div>
    </div>
  )
}
