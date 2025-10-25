"use client";

import React, { useState, useEffect } from 'react';
import { useSearchParams } from 'next/navigation';
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { UniversalBetaDashboard } from '@/components/beta/UniversalBetaDashboard';
import { IntegratedWorkflow } from '@/components/beta/IntegratedWorkflow';
import { Upload, BarChart3, Database, Zap } from "lucide-react";

export default function CompleteBetaAnalysisPage() {
  const searchParams = useSearchParams();
  const [activeTab, setActiveTab] = useState('overview');
  const [clientResultsReady, setClientResultsReady] = useState<string | null>(null);

  // Get parameters from URL
  const tabParam = searchParams.get('tab');
  const fileIdParam = searchParams.get('fileId');

  useEffect(() => {
    // If tab parameter is provided, set it as active
    if (tabParam) {
      setActiveTab(tabParam);
    } else if (fileIdParam) {
      // If fileId is provided (coming from My Data analyze), go directly to upload tab
      setActiveTab('upload');
    }
  }, [tabParam, fileIdParam]);

  const handleResultsReady = (clientId: string) => {
    setClientResultsReady(clientId);
    setActiveTab('dashboard');
  };

  return (
    <div className="container mx-auto px-4 py-8">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold tracking-tight mb-2">
          Universal Beta Forecasting Platform
        </h1>
        <p className="text-muted-foreground">
          Complete solution for beta coefficient prediction - use pre-trained models or analyze your own data
        </p>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-6">
        <TabsList className="grid w-full grid-cols-4">
          <TabsTrigger value="overview" className="flex items-center gap-2">
            <Zap className="h-4 w-4" />
            Overview
          </TabsTrigger>
          <TabsTrigger value="upload" className="flex items-center gap-2">
            <Upload className="h-4 w-4" />
            Configure & Analyze
          </TabsTrigger>
          <TabsTrigger value="dashboard" className="flex items-center gap-2">
            <BarChart3 className="h-4 w-4" />
            Live Dashboard
          </TabsTrigger>
          <TabsTrigger value="data" className="flex items-center gap-2">
            <Database className="h-4 w-4" />
            Pre-trained Models
          </TabsTrigger>
        </TabsList>

        {/* Overview Tab */}
        <TabsContent value="overview" className="space-y-6">
          <div className="grid md:grid-cols-2 gap-6">
            {/* Custom Analysis Option */}
            <Card className="border-2 border-blue-200 bg-blue-50/50">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Upload className="h-5 w-5 text-blue-600" />
                  Custom Data Analysis
                </CardTitle>
                <CardDescription>
                  Upload your own stock data and run the universal beta model
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  <div className="space-y-2">
                    <h4 className="font-medium">Perfect for:</h4>
                    <ul className="text-sm space-y-1 text-gray-600">
                      <li>• Your proprietary stock data</li>
                      <li>• Custom time periods</li>
                      <li>• Specific stock universes</li>
                      <li>• Real-time analysis needs</li>
                    </ul>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="text-blue-700 border-blue-300">
                      2-5 min processing
                    </Badge>
                    <Badge variant="outline" className="text-green-700 border-green-300">
                      Full customization
                    </Badge>
                  </div>
                  <button
                    onClick={() => setActiveTab('upload')}
                    className="w-full bg-blue-600 text-white py-2 px-4 rounded-md hover:bg-blue-700 transition-colors"
                  >
                    Start Custom Analysis
                  </button>
                </div>
              </CardContent>
            </Card>

            {/* Pre-trained Models Option */}
            <Card className="border-2 border-green-200 bg-green-50/50">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <BarChart3 className="h-5 w-5 text-green-600" />
                  Pre-trained Models
                </CardTitle>
                <CardDescription>
                  Explore results from our universal model trained on 518 stocks
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  <div className="space-y-2">
                    <h4 className="font-medium">Features:</h4>
                    <ul className="text-sm space-y-1 text-gray-600">
                      <li>• 518-stock universe</li>
                      <li>• 60K+ predictions</li>
                      <li>• 4 horizons (1d, 5d, 10d, 20d)</li>
                      <li>• Institutional-grade accuracy</li>
                    </ul>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="text-green-700 border-green-300">
                      Instant access
                    </Badge>
                    <Badge variant="outline" className="text-purple-700 border-purple-300">
                      58.4% directional accuracy
                    </Badge>
                  </div>
                  <button
                    onClick={() => setActiveTab('dashboard')}
                    className="w-full bg-green-600 text-white py-2 px-4 rounded-md hover:bg-green-700 transition-colors"
                  >
                    View Live Dashboard
                  </button>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Feature Comparison */}
          <Card>
            <CardHeader>
              <CardTitle>Platform Capabilities</CardTitle>
              <CardDescription>
                Comprehensive beta forecasting with universal cross-sectional learning
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid md:grid-cols-3 gap-6">
                <div className="text-center">
                  <div className="bg-blue-100 w-12 h-12 rounded-full flex items-center justify-center mx-auto mb-3">
                    <Upload className="h-6 w-6 text-blue-600" />
                  </div>
                  <h3 className="font-semibold mb-2">Data Upload & Processing</h3>
                  <p className="text-sm text-gray-600">
                    Upload CSV files with Date, Ticker, Price columns. Automatic feature engineering and data validation.
                  </p>
                </div>
                <div className="text-center">
                  <div className="bg-purple-100 w-12 h-12 rounded-full flex items-center justify-center mx-auto mb-3">
                    <Zap className="h-6 w-6 text-purple-600" />
                  </div>
                  <h3 className="font-semibold mb-2">Universal Model Training</h3>
                  <p className="text-sm text-gray-600">
                    Cross-sectional learning with 23+ features including momentum, volatility, and technical indicators.
                  </p>
                </div>
                <div className="text-center">
                  <div className="bg-green-100 w-12 h-12 rounded-full flex items-center justify-center mx-auto mb-3">
                    <BarChart3 className="h-6 w-6 text-green-600" />
                  </div>
                  <h3 className="font-semibold mb-2">Interactive Dashboard</h3>
                  <p className="text-sm text-gray-600">
                    Trading opportunities, performance analytics, and time series analysis for informed decisions.
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Upload & Analyze Tab */}
        <TabsContent value="upload" className="space-y-6">
          <IntegratedWorkflow 
            onResultsReady={handleResultsReady} 
            fileId={fileIdParam ? parseInt(fileIdParam, 10) : undefined}
          />
        </TabsContent>

        {/* Dashboard Tab */}
        <TabsContent value="dashboard" className="space-y-6">
          {clientResultsReady && (
            <Card className="border-blue-200 bg-blue-50/50">
              <CardContent className="pt-6">
                <div className="flex items-center gap-3">
                  <Badge variant="default" className="bg-blue-600">
                    Custom Analysis
                  </Badge>
                  <span className="text-sm text-blue-700">
                    Showing results for client: {clientResultsReady}
                  </span>
                </div>
              </CardContent>
            </Card>
          )}
          <UniversalBetaDashboard />
        </TabsContent>

        {/* Pre-trained Models Tab */}
        <TabsContent value="data" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Pre-trained Universal Models</CardTitle>
              <CardDescription>
                Access our institutional-grade models trained on comprehensive market data
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-4">
                  <div className="p-4 border rounded-lg">
                    <h3 className="font-semibold text-lg">518</h3>
                    <p className="text-sm text-gray-600">Unique stocks in universe</p>
                  </div>
                  <div className="p-4 border rounded-lg">
                    <h3 className="font-semibold text-lg">60K+</h3>
                    <p className="text-sm text-gray-600">Out-of-sample predictions</p>
                  </div>
                  <div className="p-4 border rounded-lg">
                    <h3 className="font-semibold text-lg">58.4%</h3>
                    <p className="text-sm text-gray-600">Directional accuracy (10d)</p>
                  </div>
                  <div className="p-4 border rounded-lg">
                    <h3 className="font-semibold text-lg">23+</h3>
                    <p className="text-sm text-gray-600">Engineered features</p>
                  </div>
                </div>
                
                <div className="space-y-3">
                  <h4 className="font-medium">Model Features:</h4>
                  <div className="grid md:grid-cols-2 gap-4 text-sm">
                    <div>
                      <h5 className="font-medium text-blue-600 mb-2">Technical Indicators</h5>
                      <ul className="space-y-1 text-gray-600">
                        <li>• Autocorrelation (10d, 20d, 60d)</li>
                        <li>• Sign persistence patterns</li>
                        <li>• Moving average z-scores</li>
                        <li>• Multi-horizon volatility</li>
                      </ul>
                    </div>
                    <div>
                      <h5 className="font-medium text-green-600 mb-2">Cross-Sectional Features</h5>
                      <ul className="space-y-1 text-gray-600">
                        <li>• Relative return rankings</li>
                        <li>• Volatility percentiles</li>
                        <li>• Market dispersion indicators</li>
                        <li>• Momentum rankings</li>
                      </ul>
                    </div>
                  </div>
                </div>

                <button
                  onClick={() => setActiveTab('dashboard')}
                  className="w-full bg-green-600 text-white py-3 px-4 rounded-md hover:bg-green-700 transition-colors"
                >
                  Explore Pre-trained Models
                </button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}