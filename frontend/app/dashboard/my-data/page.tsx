"use client";

import { useState, useEffect } from "react";
import { FileText, Calendar, BarChart3, AlertCircle, Plus, TrendingUp, Activity, PieChart } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import LiveDashboard from "./_components/LiveDashboard";
import api from "@/app/lib/api";
import { useRouter, useSearchParams } from "next/navigation";
import RequireAuth from "@/app/lib/requireAuth";

interface CSVFile {
  id: number;
  filename: string;
  upload_date: string;
  file_size: number;
  rows: number;
  columns: number;
  status: "pending" | "processed" | "error";
}

interface AnalysisResult {
  id: number;
  csv_file: number;
  filename: string;
  created_at: string;
  status: "running" | "completed" | "failed";
  results?: any;
}

function MyDataContent() {
  const [csvFiles, setCsvFiles] = useState<CSVFile[]>([]);
  const [analysisResults, setAnalysisResults] = useState<AnalysisResult[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hasCompletedAnalysis, setHasCompletedAnalysis] = useState(false);
  const router = useRouter();
  const searchParams = useSearchParams();
  
  // Determine default tab based on analysis completion status
  const getDefaultTab = () => {
    const urlTab = searchParams.get("tab");
    if (urlTab) return urlTab;
    
    // Check if user has completed any analysis
    const completedAnalysis = analysisResults.some(result => result.status === "completed");
    return completedAnalysis ? "dashboard" : "datasets";
  };

  const [activeTab, setActiveTab] = useState(getDefaultTab());

  useEffect(() => {
    fetchData();
  }, []);

  useEffect(() => {
    // Update tab when URL params change
    const urlTab = searchParams.get("tab");
    if (urlTab) {
      setActiveTab(urlTab);
    }
  }, [searchParams]);

  useEffect(() => {
    // Check if user has completed analysis to set default view
    const completedAnalysis = analysisResults.some(result => result.status === "completed");
    setHasCompletedAnalysis(completedAnalysis);
    
    // If user just completed analysis and no specific tab is set, go to dashboard
    if (completedAnalysis && !searchParams.get("tab")) {
      setActiveTab("dashboard");
    }
  }, [analysisResults, searchParams]);

  const fetchData = async () => {
    try {
      setIsLoading(true);
      // Use the existing CSV uploads endpoint
      const csvResponse = await api.get("/csv-uploads/");
      setCsvFiles(csvResponse.data || []);
      
      // Mock analysis results for now - you can replace this with actual API call
      const mockAnalysisResults: AnalysisResult[] = csvFiles.map((file, index) => ({
        id: index + 1,
        csv_file: file.id,
        filename: file.filename,
        created_at: file.upload_date,
        status: Math.random() > 0.7 ? "completed" : Math.random() > 0.5 ? "running" : "failed" as any,
        results: Math.random() > 0.5 ? { accuracy: 95.2, beta: 1.24 } : undefined
      }));
      setAnalysisResults(mockAnalysisResults);
      
    } catch (err) {
      console.error("Error fetching data:", err);
      setError("Failed to load data. Please try again.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleAnalyze = (fileId: number) => {
    console.log('Navigating to beta analysis platform with fileId:', fileId);
    router.push(`/dashboard/beta-analysis-platform?fileId=${fileId}`);
  };

  const handleTabChange = (value: string) => {
    setActiveTab(value);
    // Update URL without page reload
    const newUrl = new URL(window.location.href);
    newUrl.searchParams.set("tab", value);
    window.history.pushState({}, "", newUrl.toString());
  };

  const formatFileSize = (bytes: number) => {
    if (bytes === 0) return "0 Bytes";
    const k = 1024;
    const sizes = ["Bytes", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
  };

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="h-8 bg-gray-200 rounded animate-pulse" />
        <div className="grid gap-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-32 bg-gray-200 rounded animate-pulse" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">My Data</h1>
          <p className="text-muted-foreground mt-2">
            Manage your uploaded datasets, view analysis results, and monitor performance
          </p>
        </div>
        <Button onClick={() => router.push('/upload')} className="gap-2">
          <Plus className="h-4 w-4" />
          Upload New Data
        </Button>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <Tabs value={activeTab} onValueChange={handleTabChange} className="space-y-6">
        <TabsList className="grid w-full grid-cols-4">
          <TabsTrigger value="dashboard" className="gap-2">
            <Activity className="h-4 w-4" />
            Live Dashboard
            {hasCompletedAnalysis && (
              <Badge variant="secondary" className="ml-1 px-1 py-0 text-xs">
                Active
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="datasets" className="gap-2">
            <FileText className="h-4 w-4" />
            Datasets
          </TabsTrigger>
          <TabsTrigger value="analysis" className="gap-2">
            <BarChart3 className="h-4 w-4" />
            Analysis Results
          </TabsTrigger>
          <TabsTrigger value="insights" className="gap-2">
            <PieChart className="h-4 w-4" />
            Insights
          </TabsTrigger>
        </TabsList>

        <TabsContent value="dashboard" className="space-y-6">
          <LiveDashboard refreshTrigger={refreshTrigger} />
        </TabsContent>

        <TabsContent value="datasets" className="space-y-4">
          {csvFiles.length === 0 ? (
            <Card>
              <CardContent className="pt-6">
                <div className="text-center py-12">
                  <FileText className="h-12 w-12 text-muted-foreground mx-auto mb-4" />
                  <h3 className="text-lg font-semibold mb-2">No datasets uploaded</h3>
                  <p className="text-muted-foreground mb-4">
                    Upload your first CSV file to get started with data analysis
                  </p>
                  <Button onClick={() => router.push('/upload')}>
                    Upload CSV File
                  </Button>
                </div>
              </CardContent>
            </Card>
          ) : (
            <div className="grid gap-4">
              {csvFiles.map((file) => (
                <Card key={file.id} className="transition-all hover:shadow-md">
                  <CardHeader className="pb-3">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <FileText className="h-5 w-5 text-blue-600" />
                        <div>
                          <CardTitle className="text-lg">{file.filename}</CardTitle>
                          <CardDescription className="flex items-center gap-4 mt-1">
                            <span className="flex items-center gap-1">
                              <Calendar className="h-3 w-3" />
                              {formatDate(file.upload_date)}
                            </span>
                            <span>{formatFileSize(file.file_size)}</span>
                          </CardDescription>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <Badge
                          variant={
                            file.status === "processed"
                              ? "default"
                              : file.status === "error"
                              ? "destructive"
                              : "secondary"
                          }
                        >
                          {file.status}
                        </Badge>
                        <Button 
                          onClick={() => handleAnalyze(file.id)}
                          className="gap-2"
                          size="sm"
                        >
                          <TrendingUp className="h-4 w-4" />
                          Analyze
                        </Button>
                      </div>
                    </div>
                  </CardHeader>
                  <CardContent>
                    <div className="flex items-center gap-6 text-sm text-muted-foreground">
                      <span className="flex items-center gap-1">
                        <BarChart3 className="h-3 w-3" />
                        {file.rows?.toLocaleString() || 0} rows
                      </span>
                      <span>{file.columns || 0} columns</span>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>

        <TabsContent value="analysis" className="space-y-4">
          {analysisResults.length === 0 ? (
            <Card>
              <CardContent className="pt-6">
                <div className="text-center py-12">
                  <BarChart3 className="h-12 w-12 text-muted-foreground mx-auto mb-4" />
                  <h3 className="text-lg font-semibold mb-2">No analysis results</h3>
                  <p className="text-muted-foreground mb-4">
                    Run analysis on your datasets to see results here
                  </p>
                </div>
              </CardContent>
            </Card>
          ) : (
            <div className="grid gap-4">
              {analysisResults.map((result) => (
                <Card key={result.id} className="transition-all hover:shadow-md">
                  <CardHeader className="pb-3">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <BarChart3 className="h-5 w-5 text-green-600" />
                        <div>
                          <CardTitle className="text-lg">{result.filename}</CardTitle>
                          <CardDescription className="flex items-center gap-4 mt-1">
                            <span className="flex items-center gap-1">
                              <Calendar className="h-3 w-3" />
                              {formatDate(result.created_at)}
                            </span>
                          </CardDescription>
                        </div>
                      </div>
                      <Badge
                        variant={
                          result.status === "completed"
                            ? "default"
                            : result.status === "failed"
                            ? "destructive"
                            : "secondary"
                        }
                      >
                        {result.status}
                      </Badge>
                    </div>
                  </CardHeader>
                  {result.status === "completed" && result.results && (
                    <CardContent>
                      <div className="text-sm text-muted-foreground">
                        Analysis completed successfully - view in Live Dashboard
                      </div>
                    </CardContent>
                  )}
                </Card>
              ))}
            </div>
          )}
        </TabsContent>

        <TabsContent value="insights" className="space-y-4">
          <Card>
            <CardContent className="pt-6">
              <div className="text-center py-12">
                <PieChart className="h-12 w-12 text-muted-foreground mx-auto mb-4" />
                <h3 className="text-lg font-semibold mb-2">Advanced Insights</h3>
                <p className="text-muted-foreground mb-4">
                  Coming soon - Advanced portfolio insights and recommendations
                </p>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}

export default function MyDataPage() {
  return (
    <RequireAuth>
      <MyDataContent />
    </RequireAuth>
  );
}