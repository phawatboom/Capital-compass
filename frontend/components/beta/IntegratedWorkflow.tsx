"use client";

import React, { useState, useCallback, useEffect } from 'react';
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
import api from '@/app/lib/api';

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
  fileId?: number; // Optional file ID for pre-uploaded files
}

export function IntegratedWorkflow({ onResultsReady, fileId }: IntegratedWorkflowProps) {
  const [uploadState, setUploadState] = useState<'idle' | 'uploading' | 'uploaded' | 'processing' | 'completed' | 'error'>('idle');
  const [clientId, setClientId] = useState<string>('');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [horizonDays, setHorizonDays] = useState<string>('10');
  const [preUploadedFileInfo, setPreUploadedFileInfo] = useState<any>(null);
  
  // Enhanced model configuration for fund managers
  const [modelConfig, setModelConfig] = useState({
    riskTolerance: 'medium', // low, medium, high
    sectorFilter: 'all', // all, technology, financials, healthcare, etc.
    minimumConfidence: '0.6', // 0.5-0.9
    lookbackPeriod: '60', // 30, 60, 90, 120 days
    volatilityAdjustment: 'true', // true/false
    crossSectionalRanking: 'true', // true/false
    // Advanced model parameters
    trainingDays: '252', // 1 year default
    testingDays: '63', // 3 months default  
    alpha: '0.01', // L1/L2 regularization strength
    l1Ratio: '0.5', // ElasticNet mixing parameter (0=Ridge, 1=Lasso)
    multiPeriod: 'false' // Run predictions for all periods (1d, 5d, 10d, 20d)
  });
  
  const [clientStatus, setClientStatus] = useState<ClientStatus | null>(null);
  const [error, setError] = useState<string>('');
  const [uploadProgress, setUploadProgress] = useState<number>(0);
  const [statusInterval, setStatusInterval] = useState<NodeJS.Timeout | null>(null);

  // Handle pre-uploaded file
  useEffect(() => {
    if (fileId) {
      console.log('Loading pre-uploaded file with ID:', fileId);
      loadPreUploadedFile();
    }
  }, [fileId]);

  const loadPreUploadedFile = async () => {
    if (!fileId) return;

    try {
      setUploadState('uploading');
      setError('');
      console.log('Fetching file meta for fileId:', fileId);
      
      // Fetch file information from the backend using the meta endpoint
      const response = await api.get(`/csv-uploads/${fileId}/meta/`);
      const fileInfo = response.data;
      
      console.log('Received file info:', fileInfo);
      
      setPreUploadedFileInfo(fileInfo);
      setClientId(`file_${fileId}_${Date.now()}`);
      setUploadState('uploaded');
      setClientStatus({
        status: 'uploaded',
        filename: fileInfo.filename,
        // Try multiple possible field names for row/column counts
        n_rows: fileInfo.n_rows || fileInfo.rows || fileInfo.row_count || 0,
        n_cols: fileInfo.n_cols || fileInfo.columns || fileInfo.column_count || 0
      });
      
      console.log('Pre-uploaded file loaded successfully');
    } catch (err) {
      console.error('Error loading pre-uploaded file:', err);
      setError(`Failed to load pre-uploaded file information: ${err instanceof Error ? err.message : 'Unknown error'}`);
      setUploadState('error');
    }
  };

  // File upload state

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
      const response = await api.post('/integrated/upload/', formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      });

      const result = response.data;

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
      // Use different endpoint based on whether we have a pre-uploaded file or uploaded via the workflow
      const endpoint = fileId ? '/integrated/run-model-with-file/' : '/integrated/run-model/';
      const payload: any = {
        client_id: clientId,
        horizon_days: parseInt(horizonDays),
        // Enhanced model configuration
        risk_tolerance: modelConfig.riskTolerance,
        sector_filter: modelConfig.sectorFilter,
        minimum_confidence: parseFloat(modelConfig.minimumConfidence),
        lookback_period: parseInt(modelConfig.lookbackPeriod),
        volatility_adjustment: modelConfig.volatilityAdjustment === 'true',
        cross_sectional_ranking: modelConfig.crossSectionalRanking === 'true',
        // Advanced model parameters
        training_days: parseInt(modelConfig.trainingDays),
        testing_days: parseInt(modelConfig.testingDays),
        alpha: parseFloat(modelConfig.alpha),
        l1_ratio: parseFloat(modelConfig.l1Ratio),
        multi_period: modelConfig.multiPeriod === 'true'
      };

      // Add file ID if using pre-uploaded file
      if (fileId) {
        payload.file_id = fileId;
      }

      const response = await api.post(endpoint, payload);

      const result = response.data;

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
      const response = await api.get(`/integrated/status/${clientId}/`);
      const result = response.data;

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
    if (fileId) {
      // If coming from a pre-uploaded file, navigate back to My Data
      window.location.href = '/uploads';
    } else {
      // Regular reset for normal workflow
      setUploadState('idle');
      setClientId('');
      setSelectedFile(null);
      setClientStatus(null);
      setError('');
      setUploadProgress(0);
      setPreUploadedFileInfo(null);
      if (statusInterval) {
        clearInterval(statusInterval);
        setStatusInterval(null);
      }
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
          <h2 className="text-2xl font-bold">
            {fileId ? 'Configure Beta Model Analysis' : 'Custom Beta Model Analysis'}
          </h2>
          <p className="text-muted-foreground">
            {fileId 
              ? 'Configure and run the universal model on your selected dataset'
              : 'Upload your data, run the universal model, and view personalized results'
            }
          </p>
        </div>
        <div className="flex items-center gap-3">
          {getStatusBadge()}
          {uploadState !== 'idle' && (
            <Button variant="outline" onClick={resetWorkflow}>
              {fileId ? 'Back to My Data' : 'Start New Analysis'}
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
              fileId || uploadState === 'uploaded' || uploadState === 'processing' || uploadState === 'completed' ? 'bg-green-600 text-white' : 
              uploadState === 'uploading' ? 'bg-blue-600 text-white' : 
              'bg-gray-400 text-white'
            }`}>1</span>
            {fileId ? 'Selected Data File' : 'Upload Your Data'}
          </CardTitle>
          <CardDescription>
            {fileId 
              ? 'File selected from My Data - ready for analysis'
              : 'Upload a CSV file with columns: Date, Ticker, Price (or Close/Adj_Close)'
            }
          </CardDescription>
        </CardHeader>
        <CardContent>
          {fileId && preUploadedFileInfo ? (
            // Show pre-uploaded file information
            <div className="space-y-3">
              <div className="flex items-center justify-between p-4 bg-blue-50 rounded-lg border-2 border-blue-200">
                <div className="flex items-center gap-3">
                  <CheckCircle className="h-5 w-5 text-blue-600" />
                  <div>
                    <p className="font-medium text-blue-900">Using Pre-uploaded File</p>
                    <p className="text-sm text-blue-700">{preUploadedFileInfo.filename}</p>
                    <p className="text-xs text-blue-600">
                      {(preUploadedFileInfo.rows || preUploadedFileInfo.row_count || 0).toLocaleString()} rows, 
                      {' '}{preUploadedFileInfo.columns || preUploadedFileInfo.column_count || 0} columns
                    </p>
                  </div>
                </div>
                <Badge variant="outline" className="text-blue-700 border-blue-300">
                  Ready for Analysis
                </Badge>
              </div>
              <div className="text-sm text-gray-600 p-3 bg-gray-50 rounded-lg">
                <p className="font-medium mb-1">File already uploaded from My Data</p>
                <p>Proceed to configure the model parameters and run the analysis.</p>
              </div>
            </div>
          ) : uploadState === 'idle' || uploadState === 'error' || uploadState === 'uploading' ? (
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
            // Show uploaded file status for regular upload workflow
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
                  <p className="text-xs text-gray-500 mt-1">Note: server-side sector filtering is only applied if the uploaded dataset includes a 'sector' column and the backend is configured to use it.</p>
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

              {/* Advanced Model Training Parameters */}
              <div className="border-t pt-4 mt-4">
                <h5 className="font-medium mb-4 text-sm text-gray-700">Advanced Model Training Parameters</h5>
                
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  <div>
                    <Label htmlFor="trainingDays">Training Period (Days)</Label>
                    <Select 
                      value={modelConfig.trainingDays} 
                      onValueChange={(value) => setModelConfig(prev => ({...prev, trainingDays: value}))}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Select training period" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="126">6 Months (126 days)</SelectItem>
                        <SelectItem value="252">1 Year (252 days)</SelectItem>
                        <SelectItem value="504">2 Years (504 days)</SelectItem>
                        <SelectItem value="756">3 Years (756 days)</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <div>
                    <Label htmlFor="testingDays">Testing Period (Days)</Label>
                    <Select 
                      value={modelConfig.testingDays} 
                      onValueChange={(value) => setModelConfig(prev => ({...prev, testingDays: value}))}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Select testing period" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="21">1 Month (21 days)</SelectItem>
                        <SelectItem value="42">2 Months (42 days)</SelectItem>
                        <SelectItem value="63">3 Months (63 days)</SelectItem>
                        <SelectItem value="126">6 Months (126 days)</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <div>
                    <Label htmlFor="alpha">Regularization Strength (Alpha)</Label>
                    <Select 
                      value={modelConfig.alpha} 
                      onValueChange={(value) => setModelConfig(prev => ({...prev, alpha: value}))}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Select alpha" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="0.001">0.001 (Weak regularization)</SelectItem>
                        <SelectItem value="0.01">0.01 (Standard)</SelectItem>
                        <SelectItem value="0.1">0.1 (Strong regularization)</SelectItem>
                        <SelectItem value="1.0">1.0 (Very strong)</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <div>
                    <Label htmlFor="l1Ratio">L1 Ratio (ElasticNet Mix)</Label>
                    <Select 
                      value={modelConfig.l1Ratio} 
                      onValueChange={(value) => setModelConfig(prev => ({...prev, l1Ratio: value}))}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Select L1 ratio" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="0.0">0.0 (Ridge - L2 only)</SelectItem>
                        <SelectItem value="0.25">0.25 (Mostly Ridge)</SelectItem>
                        <SelectItem value="0.5">0.5 (Balanced ElasticNet)</SelectItem>
                        <SelectItem value="0.75">0.75 (Mostly Lasso)</SelectItem>
                        <SelectItem value="1.0">1.0 (Lasso - L1 only)</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="md:col-span-2 lg:col-span-1">
                    <div className="flex items-center space-x-2">
                      <input
                        type="checkbox"
                        id="multiPeriod"
                        checked={modelConfig.multiPeriod === 'true'}
                        onChange={(e) => setModelConfig(prev => ({...prev, multiPeriod: e.target.checked ? 'true' : 'false'}))}
                        className="rounded border-gray-300"
                      />
                      <Label htmlFor="multiPeriod" className="text-sm">
                        Multi-Period Analysis (1d, 5d, 10d, 20d)
                      </Label>
                    </div>
                    <p className="text-xs text-gray-500 mt-1">
                      Run predictions for all time horizons
                    </p>
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
                  <p>• Training: {modelConfig.trainingDays}d | Testing: {modelConfig.testingDays}d | Alpha: {modelConfig.alpha} | L1: {modelConfig.l1Ratio}</p>
                  <p>• Multi-Period: {modelConfig.multiPeriod}</p>
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