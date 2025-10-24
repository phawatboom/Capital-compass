"use client";

import React, { useState, useCallback } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Progress } from "@/components/ui/progress";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Upload, Play, CheckCircle, AlertCircle, RefreshCw, BarChart3 } from "lucide-react";
import { useDropzone } from 'react-dropzone';

interface ClientStatus {
  status: string;
  stage?: string;
  progress?: number;
  filename?: string;
  n_rows?: number;
  n_cols?: number;
  results?: any;
  error?: string;
  completion_time?: string;
}

interface IntegratedWorkflowProps {
  onResultsReady?: (clientId: string) => void;
}

export function IntegratedWorkflow({ onResultsReady }: IntegratedWorkflowProps) {
  const [uploadState, setUploadState] = useState<'idle' | 'uploading' | 'uploaded' | 'processing' | 'completed' | 'error'>('idle');
  const [clientId, setClientId] = useState<string>('');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [horizonDays, setHorizonDays] = useState<string>('10');
  
  // Enhanced model configuration for fund managers
  const [modelConfig, setModelConfig] = useState({
    riskTolerance: 'medium', // low, medium, high
    sectorFilter: 'all', // all, technology, financials, healthcare, etc.
    minimumConfidence: '0.6', // 0.5-0.9
    lookbackPeriod: '60', // 30, 60, 90, 120 days
    volatilityAdjustment: 'true', // true/false
    crossSectionalRanking: 'true' // true/false
  });
  
  const [clientStatus, setClientStatus] = useState<ClientStatus | null>(null);
  const [error, setError] = useState<string>('');
  const [uploadProgress, setUploadProgress] = useState<number>(0);
  const [statusInterval, setStatusInterval] = useState<NodeJS.Timeout | null>(null);

  const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

  const onDrop = useCallback((acceptedFiles: File[]) => {
    if (acceptedFiles.length > 0) {
      const file = acceptedFiles[0];
      if (file && file.name && file.name.endsWith('.csv')) {
        setSelectedFile(file);
        setError('');
      } else {
        setError('Please upload a CSV file only');
      }
    }
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'text/csv': ['.csv'],
      'application/vnd.ms-excel': ['.csv']
    },
    multiple: false
  });

  const uploadFile = async () => {
    if (!selectedFile) return;

    setUploadState('uploading');
    setError('');
    setUploadProgress(0);

    const formData = new FormData();
    formData.append('file', selectedFile);
    formData.append('client_id', clientId || `client_${Date.now()}`);

    try {
      const response = await fetch(`${API_BASE}/api/integrated/upload/`, {
        method: 'POST',
        body: formData,
        credentials: 'include',
      });

      const result = await response.json();

      if (result.status === 'success') {
        setClientId(result.data.client_id);
        setUploadState('uploaded');
        setClientStatus({
          status: 'uploaded',
          filename: result.data.filename,
          n_rows: result.data.n_rows,
          n_cols: result.data.n_cols
        });
      } else {
        throw new Error(result.message || 'Upload failed');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed');
      setUploadState('error');
    }
  };

  const runModel = async () => {
    if (!clientId) return;

    setUploadState('processing');
    setError('');

    try {
      const response = await fetch(`${API_BASE}/api/integrated/run-model/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify({
          client_id: clientId,
          horizon_days: parseInt(horizonDays),
          // Enhanced model configuration
          risk_tolerance: modelConfig.riskTolerance,
          sector_filter: modelConfig.sectorFilter,
          minimum_confidence: parseFloat(modelConfig.minimumConfidence),
          lookback_period: parseInt(modelConfig.lookbackPeriod),
          volatility_adjustment: modelConfig.volatilityAdjustment === 'true',
          cross_sectional_ranking: modelConfig.crossSectionalRanking === 'true'
        }),
      });

      const result = await response.json();

      if (result.status === 'success') {
        // Start polling for status
        const interval = setInterval(checkStatus, 2000);
        setStatusInterval(interval);
      } else {
        throw new Error(result.message || 'Failed to start model');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start model');
      setUploadState('error');
    }
  };

  const checkStatus = async () => {
    if (!clientId) return;

    try {
      const response = await fetch(`${API_BASE}/api/integrated/status/${clientId}/`, {
        credentials: 'include',
      });

      const result = await response.json();

      if (result.status === 'success') {
        setClientStatus(result.data);

        if (result.data.status === 'completed' || result.data.status === 'completed_with_warnings') {
          setUploadState('completed');
          if (statusInterval) {
            clearInterval(statusInterval);
            setStatusInterval(null);
          }
          if (onResultsReady) {
            onResultsReady(clientId);
          }
        } else if (result.data.status === 'failed') {
          setUploadState('error');
          setError(result.data.error || 'Model processing failed');
          if (statusInterval) {
            clearInterval(statusInterval);
            setStatusInterval(null);
          }
        }
      }
    } catch (err) {
      console.error('Status check failed:', err);
    }
  };

  const resetWorkflow = () => {
    setUploadState('idle');
    setClientId('');
    setSelectedFile(null);
    setClientStatus(null);
    setError('');
    setUploadProgress(0);
    if (statusInterval) {
      clearInterval(statusInterval);
      setStatusInterval(null);
    }
  };

  const getStatusIcon = () => {
    switch (uploadState) {
      case 'uploaded': return <CheckCircle className="h-5 w-5 text-green-600" />;
      case 'processing': return <RefreshCw className="h-5 w-5 text-blue-600 animate-spin" />;
      case 'completed': return <CheckCircle className="h-5 w-5 text-green-600" />;
      case 'error': return <AlertCircle className="h-5 w-5 text-red-600" />;
      default: return <Upload className="h-5 w-5 text-gray-600" />;
    }
  };

  const getStatusBadge = () => {
    const variants = {
      'idle': 'secondary',
      'uploading': 'default',
      'uploaded': 'default',
      'processing': 'default',
      'completed': 'default',
      'error': 'destructive'
    } as const;

    const labels = {
      'idle': 'Ready',
      'uploading': 'Uploading',
      'uploaded': 'Ready to Process',
      'processing': 'Processing',
      'completed': 'Completed',
      'error': 'Error'
    };

    return (
      <Badge variant={variants[uploadState]}>
        {getStatusIcon()}
        <span className="ml-2">{labels[uploadState]}</span>
      </Badge>
    );
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex justify-between items-start">
        <div>
          <h2 className="text-2xl font-bold">Custom Beta Model Analysis</h2>
          <p className="text-muted-foreground">
            Upload your data, run the universal model, and view personalized results
          </p>
        </div>
        <div className="flex items-center gap-3">
          {getStatusBadge()}
          {uploadState !== 'idle' && (
            <Button variant="outline" onClick={resetWorkflow}>
              Start New Analysis
            </Button>
          )}
        </div>
      </div>

      {/* Error Alert */}
      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* Step 1: File Upload */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <span className={`w-6 h-6 rounded-full flex items-center justify-center text-sm ${
              uploadState === 'idle' ? 'bg-blue-600 text-white' : 
              uploadState === 'uploading' || uploadState === 'uploaded' ? 'bg-green-600 text-white' : 
              'bg-gray-400 text-white'
            }`}>1</span>
            Upload Your Data
          </CardTitle>
          <CardDescription>
            Upload a CSV file with columns: Date, Ticker, Price (or Close/Adj_Close)
          </CardDescription>
        </CardHeader>
        <CardContent>
          {uploadState === 'idle' || uploadState === 'error' ? (
            <div className="space-y-4">
              <div
                {...getRootProps()}
                className={`border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition-colors ${
                  isDragActive ? 'border-blue-400 bg-blue-50' : 'border-gray-300 hover:border-gray-400'
                }`}
              >
                <input {...getInputProps()} />
                <Upload className="mx-auto h-12 w-12 text-gray-400 mb-4" />
                {selectedFile ? (
                  <div>
                    <p className="text-sm font-medium">{selectedFile.name}</p>
                    <p className="text-xs text-gray-500">{(selectedFile.size / 1024 / 1024).toFixed(2)} MB</p>
                  </div>
                ) : (
                  <div>
                    <p className="text-sm text-gray-600">
                      {isDragActive ? 'Drop the CSV file here' : 'Drag & drop a CSV file here, or click to select'}
                    </p>
                    <p className="text-xs text-gray-500 mt-1">
                      Expected format: Date, Ticker, Price columns
                    </p>
                  </div>
                )}
              </div>
              
              {selectedFile && (
                <Button onClick={uploadFile} disabled={uploadState === 'uploading'} className="w-full">
                  {uploadState === 'uploading' ? (
                    <>
                      <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
                      Uploading...
                    </>
                  ) : (
                    <>
                      <Upload className="mr-2 h-4 w-4" />
                      Upload File
                    </>
                  )}
                </Button>
              )}
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex items-center justify-between p-3 bg-green-50 rounded-lg">
                <div className="flex items-center gap-3">
                  <CheckCircle className="h-5 w-5 text-green-600" />
                  <div>
                    <p className="font-medium">{clientStatus?.filename}</p>
                    <p className="text-sm text-gray-600">
                      {clientStatus?.n_rows?.toLocaleString()} rows, {clientStatus?.n_cols} columns
                    </p>
                  </div>
                </div>
                <Badge variant="outline" className="text-green-700 border-green-300">
                  Uploaded
                </Badge>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Step 2: Model Configuration */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <span className={`w-6 h-6 rounded-full flex items-center justify-center text-sm ${
              uploadState === 'uploaded' || uploadState === 'processing' || uploadState === 'completed' ? 'bg-blue-600 text-white' : 'bg-gray-400 text-white'
            }`}>2</span>
            Configure Model
          </CardTitle>
          <CardDescription>
            Select prediction horizon for your beta forecasting model
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-6">
            {/* Primary Configuration */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <Label htmlFor="horizon">Prediction Horizon</Label>
                <Select value={horizonDays} onValueChange={setHorizonDays}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select horizon" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="1">1 Day (Short-term)</SelectItem>
                    <SelectItem value="5">5 Days (Weekly)</SelectItem>
                    <SelectItem value="10">10 Days (Bi-weekly)</SelectItem>
                    <SelectItem value="20">20 Days (Monthly)</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label>Client ID</Label>
                <Input 
                  value={clientId} 
                  readOnly 
                  className="bg-gray-50"
                  placeholder="Auto-generated after upload"
                />
              </div>
            </div>

            {/* Advanced Fund Manager Configuration */}
            <div className="border-t pt-4">
              <h4 className="font-medium mb-4 text-sm text-gray-700">Advanced Configuration for Fund Managers</h4>
              
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                <div>
                  <Label htmlFor="riskTolerance">Risk Tolerance</Label>
                  <Select 
                    value={modelConfig.riskTolerance} 
                    onValueChange={(value) => setModelConfig(prev => ({...prev, riskTolerance: value}))}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Select risk level" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="low">Conservative (Low Risk)</SelectItem>
                      <SelectItem value="medium">Balanced (Medium Risk)</SelectItem>
                      <SelectItem value="high">Aggressive (High Risk)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div>
                  <Label htmlFor="minimumConfidence">Minimum Confidence</Label>
                  <Select 
                    value={modelConfig.minimumConfidence} 
                    onValueChange={(value) => setModelConfig(prev => ({...prev, minimumConfidence: value}))}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Select confidence" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="0.5">50% (Include more signals)</SelectItem>
                      <SelectItem value="0.6">60% (Balanced)</SelectItem>
                      <SelectItem value="0.7">70% (High quality)</SelectItem>
                      <SelectItem value="0.8">80% (Very selective)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div>
                  <Label htmlFor="lookbackPeriod">Lookback Period</Label>
                  <Select 
                    value={modelConfig.lookbackPeriod} 
                    onValueChange={(value) => setModelConfig(prev => ({...prev, lookbackPeriod: value}))}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Select period" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="30">30 Days (Short-term)</SelectItem>
                      <SelectItem value="60">60 Days (Standard)</SelectItem>
                      <SelectItem value="90">90 Days (Medium-term)</SelectItem>
                      <SelectItem value="120">120 Days (Long-term)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
                <div>
                  <Label htmlFor="sectorFilter">Sector Filter</Label>
                  <Select 
                    value={modelConfig.sectorFilter} 
                    onValueChange={(value) => setModelConfig(prev => ({...prev, sectorFilter: value}))}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Select sector" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All Sectors</SelectItem>
                      <SelectItem value="technology">Technology</SelectItem>
                      <SelectItem value="financials">Financials</SelectItem>
                      <SelectItem value="healthcare">Healthcare</SelectItem>
                      <SelectItem value="consumer">Consumer Discretionary</SelectItem>
                      <SelectItem value="industrials">Industrials</SelectItem>
                      <SelectItem value="energy">Energy</SelectItem>
                      <SelectItem value="utilities">Utilities</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-3">
                  <div className="flex items-center space-x-2">
                    <input
                      type="checkbox"
                      id="volatilityAdjustment"
                      checked={modelConfig.volatilityAdjustment === 'true'}
                      onChange={(e) => setModelConfig(prev => ({...prev, volatilityAdjustment: e.target.checked ? 'true' : 'false'}))}
                      className="rounded border-gray-300"
                    />
                    <Label htmlFor="volatilityAdjustment" className="text-sm">
                      Volatility Adjustment
                    </Label>
                  </div>
                  <div className="flex items-center space-x-2">
                    <input
                      type="checkbox"
                      id="crossSectionalRanking"
                      checked={modelConfig.crossSectionalRanking === 'true'}
                      onChange={(e) => setModelConfig(prev => ({...prev, crossSectionalRanking: e.target.checked ? 'true' : 'false'}))}
                      className="rounded border-gray-300"
                    />
                    <Label htmlFor="crossSectionalRanking" className="text-sm">
                      Cross-Sectional Ranking
                    </Label>
                  </div>
                </div>
              </div>

              {/* Configuration Summary */}
              <div className="mt-4 p-3 bg-gray-50 rounded-lg">
                <h5 className="text-sm font-medium mb-2">Configuration Summary</h5>
                <div className="text-xs text-gray-600 space-y-1">
                  <p>• Horizon: {horizonDays} days | Risk: {modelConfig.riskTolerance} | Confidence: {modelConfig.minimumConfidence}</p>
                  <p>• Lookback: {modelConfig.lookbackPeriod} days | Sector: {modelConfig.sectorFilter}</p>
                  <p>• Volatility Adj: {modelConfig.volatilityAdjustment} | Cross-Sectional: {modelConfig.crossSectionalRanking}</p>
                </div>
              </div>
            </div>
            
            <Button 
              onClick={runModel} 
              disabled={uploadState !== 'uploaded'}
              className="w-full"
            >
              {uploadState === 'processing' ? (
                <>
                  <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
                  Processing Model...
                </>
              ) : (
                <>
                  <Play className="mr-2 h-4 w-4" />
                  Run Universal Beta Model
                </>
              )}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Step 3: Processing Status */}
      {(uploadState === 'processing' || uploadState === 'completed') && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <span className={`w-6 h-6 rounded-full flex items-center justify-center text-sm ${
                uploadState === 'completed' ? 'bg-green-600 text-white' : 'bg-blue-600 text-white'
              }`}>3</span>
              Model Processing
            </CardTitle>
            <CardDescription>
              Universal beta model analysis in progress
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {clientStatus && (
                <>
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium">
                      {clientStatus.stage || 'Processing'}
                    </span>
                    <span className="text-sm text-gray-500">
                      {clientStatus.progress || 0}%
                    </span>
                  </div>
                  <Progress value={clientStatus.progress || 0} className="w-full" />
                  
                  {uploadState === 'completed' && clientStatus.results && (
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4">
                      <div className="text-center p-3 bg-blue-50 rounded-lg">
                        <p className="text-2xl font-bold text-blue-600">
                          {clientStatus.results.total_stocks || 0}
                        </p>
                        <p className="text-sm text-gray-600">Stocks Analyzed</p>
                      </div>
                      <div className="text-center p-3 bg-green-50 rounded-lg">
                        <p className="text-2xl font-bold text-green-600">
                          {horizonDays}d
                        </p>
                        <p className="text-sm text-gray-600">Horizon</p>
                      </div>
                      <div className="text-center p-3 bg-purple-50 rounded-lg">
                        <p className="text-2xl font-bold text-purple-600">
                          {clientStatus.results.model_performance?.test_r2?.toFixed(4) || 'N/A'}
                        </p>
                        <p className="text-sm text-gray-600">R² Score</p>
                      </div>
                      <div className="text-center p-3 bg-orange-50 rounded-lg">
                        <p className="text-2xl font-bold text-orange-600">
                          {clientStatus.results.model_performance?.test_dir_acc ? 
                            (clientStatus.results.model_performance.test_dir_acc * 100).toFixed(1) + '%' : 'N/A'}
                        </p>
                        <p className="text-sm text-gray-600">Directional Accuracy</p>
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Step 4: View Results */}
      {uploadState === 'completed' && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <CheckCircle className="h-6 w-6 text-green-600" />
              Results Ready
            </CardTitle>
            <CardDescription>
              Your custom beta analysis is complete and ready to view
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <Alert>
                <BarChart3 className="h-4 w-4" />
                <AlertDescription>
                  Analysis completed successfully! Your results are now available in the dashboard.
                  The universal model has been trained on your data and predictions are ready.
                </AlertDescription>
              </Alert>
              
              <div className="flex gap-3">
                <Button 
                  onClick={() => onResultsReady && onResultsReady(clientId)}
                  className="flex-1"
                >
                  <BarChart3 className="mr-2 h-4 w-4" />
                  View Results Dashboard
                </Button>
                <Button variant="outline" onClick={resetWorkflow}>
                  Run New Analysis
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}