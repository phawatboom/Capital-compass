'use client';

import React, { useState, useEffect } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, LineChart, Line, PieChart, Pie, Cell } from 'recharts';
import { TrendingUp, TrendingDown, Activity, BarChart3, Target, Calendar } from 'lucide-react';

interface AnalysisResult {
  id: string;
  filename: string;
  created_at: string;
  status: string;
  stats?: {
    total_predictions: number;
    mse: number;
    mae: number;
    rmse: number;
    r_squared: number;
    accuracy_score?: number;
  };
  model_type?: string;
  parameters?: any;
}

interface BetaRealized {
  stock_symbol: string;
  beta_realized: number;
  forecast_date: string;
  mse: number;
  mae: number;
}

interface ForecastData {
  stock_symbol: string;
  forecast_value: number;
  actual_value?: number;
  forecast_date: string;
  accuracy: number;
}

interface LiveDashboardProps {
  refreshTrigger?: number;
}

const LiveDashboard: React.FC<LiveDashboardProps> = ({ refreshTrigger = 0 }) => {
  const [analysisResults, setAnalysisResults] = useState<AnalysisResult[]>([]);
  const [betaData, setBetaData] = useState<BetaRealized[]>([]);
  const [forecastData, setForecastData] = useState<ForecastData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchDashboardData = async () => {
    try {
      setLoading(true);
      setError(null);

      // Fetch dashboard summary from our new endpoint
      try {
        const dashboardResponse = await fetch('/api/dashboard-summary/', {
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('token')}`,
            'Content-Type': 'application/json',
          },
        });

        if (dashboardResponse.ok) {
          const dashboardData = await dashboardResponse.json();
          console.log('Dashboard summary:', dashboardData);
          
          // Create analysis results from dashboard data
          if (dashboardData.recent_activity && dashboardData.recent_activity.length > 0) {
            const recentAnalyses = dashboardData.recent_activity.map((run: any) => ({
              id: run.id.toString(),
              filename: run.run_name || 'Analysis Run',
              created_at: run.created_at,
              status: run.status,
              stats: {
                total_predictions: dashboardData.total_predictions || 0,
                mse: run.mae || 0,
                mae: run.mae || 0,
                rmse: run.rmse || 0,
                r_squared: run.r2_global || 0,
                accuracy_score: run.directional_accuracy || 0
              },
              model_type: run.model_type || 'Pooled ElasticNet'
            }));
            setAnalysisResults(recentAnalyses);
          }
        }
      } catch (err) {
        console.log('Dashboard summary endpoint not available, trying analysis runs...');
      }

      // Fetch analysis runs from our new endpoint
      try {
        const analysisResponse = await fetch('/api/analysis-runs/', {
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('token')}`,
            'Content-Type': 'application/json',
          },
        });

        if (analysisResponse.ok) {
          const analysisData = await analysisResponse.json();
          console.log('Analysis runs:', analysisData);
          
          if (analysisData.results && analysisData.results.length > 0) {
            const formattedResults = analysisData.results.map((run: any) => ({
              id: run.id.toString(),
              filename: run.run_name || 'Analysis Run',
              created_at: run.created_at,
              status: run.status,
              stats: {
                total_predictions: run.sample_size || 0,
                mse: run.mae || 0,
                mae: run.mae || 0,
                rmse: run.rmse || 0,
                r_squared: run.r2_global || 0,
                accuracy_score: run.directional_accuracy || 0
              },
              model_type: run.model_type || 'Pooled ElasticNet'
            }));
            setAnalysisResults(formattedResults);
          }
        }
      } catch (err) {
        console.log('Analysis runs endpoint not available, using mock data');
        // Keep existing mock data as fallback
        setAnalysisResults([
          {
            id: '1',
            filename: 'market_data_2024.csv',
            created_at: new Date().toISOString(),
            status: 'completed',
            stats: {
              total_predictions: 25,
              mse: 0.0034,
              mae: 0.0421,
              rmse: 0.0583,
              r_squared: 0.847,
              accuracy_score: 0.92
            },
            model_type: 'Universal Beta Model'
          }
        ]);
      }

      // For beta data, try to get stock performance metrics
      try {
        const latestRunResponse = await fetch('/api/analysis-runs/?limit=1', {
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('token')}`,
            'Content-Type': 'application/json',
          },
        });

        if (latestRunResponse.ok) {
          const latestRunData = await latestRunResponse.json();
          if (latestRunData.results && latestRunData.results.length > 0) {
            const latestRun = latestRunData.results[0];
            
            // Fetch performance metrics for this run
            const metricsResponse = await fetch(`/api/analysis-runs/${latestRun.id}/performance/`, {
              headers: {
                'Authorization': `Bearer ${localStorage.getItem('token')}`,
                'Content-Type': 'application/json',
              },
            });

            if (metricsResponse.ok) {
              const metricsData = await metricsResponse.json();
              const formattedBetaData = metricsData.slice(0, 10).map((metric: any) => ({
                stock_symbol: metric.ticker,
                beta_realized: Math.random() * 2, // Mock beta for now
                forecast_date: new Date().toISOString().split('T')[0],
                mse: metric.mae_oos || 0,
                mae: metric.mae_oos || 0
              }));
              setBetaData(formattedBetaData);
            }
          }
        }
      } catch (err) {
        console.log('Beta data endpoint not available, using mock data');
        setBetaData([
          { stock_symbol: 'AAPL', beta_realized: 1.24, forecast_date: '2024-12-01', mse: 0.003, mae: 0.042 },
          { stock_symbol: 'MSFT', beta_realized: 0.98, forecast_date: '2024-12-01', mse: 0.002, mae: 0.038 },
          { stock_symbol: 'GOOGL', beta_realized: 1.15, forecast_date: '2024-12-01', mse: 0.004, mae: 0.045 }
        ]);
      }

      // Mock forecast data for now
      setForecastData([
        { stock_symbol: 'AAPL', forecast_value: 1.24, actual_value: 1.22, forecast_date: '2024-12-01', accuracy: 98.4 },
        { stock_symbol: 'MSFT', forecast_value: 0.98, actual_value: 1.01, forecast_date: '2024-12-01', accuracy: 97.0 },
        { stock_symbol: 'GOOGL', forecast_value: 1.15, actual_value: 1.18, forecast_date: '2024-12-01', accuracy: 97.4 }
      ]);

    } catch (err) {
      console.error('Error fetching dashboard data:', err);
      setError('Failed to load dashboard data');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDashboardData();
  }, [refreshTrigger]);

  // Auto-refresh every 30 seconds
  useEffect(() => {
    const interval = setInterval(fetchDashboardData, 30000);
    return () => clearInterval(interval);
  }, []);

  const getLatestAnalysis = () => {
    return analysisResults
      .filter(result => result.status === 'completed')
      .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())[0];
  };

  const calculateOverallMetrics = () => {
    const completedAnalyses = analysisResults.filter(r => r.status === 'completed' && r.stats);
    
    if (completedAnalyses.length === 0) return null;

    const avgMSE = completedAnalyses.reduce((sum, r) => sum + (r.stats?.mse || 0), 0) / completedAnalyses.length;
    const avgMAE = completedAnalyses.reduce((sum, r) => sum + (r.stats?.mae || 0), 0) / completedAnalyses.length;
    const avgRSquared = completedAnalyses.reduce((sum, r) => sum + (r.stats?.r_squared || 0), 0) / completedAnalyses.length;

    return {
      totalAnalyses: analysisResults.length,
      completedAnalyses: completedAnalyses.length,
      avgMSE: avgMSE.toFixed(4),
      avgMAE: avgMAE.toFixed(4),
      avgRSquared: avgRSquared.toFixed(4),
      successRate: ((completedAnalyses.length / analysisResults.length) * 100).toFixed(1)
    };
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed': return 'bg-green-100 text-green-800';
      case 'processing': return 'bg-blue-100 text-blue-800';
      case 'failed': return 'bg-red-100 text-red-800';
      default: return 'bg-gray-100 text-gray-800';
    }
  };

  const formatChartData = () => {
    return betaData.map(item => ({
      stock: item.stock_symbol,
      beta: parseFloat(item.beta_realized.toFixed(4)),
      mse: parseFloat(item.mse.toFixed(6)),
      mae: parseFloat(item.mae.toFixed(6))
    }));
  };

  const formatForecastAccuracy = () => {
    return forecastData.map(item => ({
      stock: item.stock_symbol,
      accuracy: parseFloat(item.accuracy.toFixed(2)),
      forecast: parseFloat(item.forecast_value.toFixed(4)),
      actual: item.actual_value ? parseFloat(item.actual_value.toFixed(4)) : null
    }));
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
        <span className="ml-2 text-gray-600">Loading dashboard...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-center py-8">
        <p className="text-red-600 mb-4">{error}</p>
        <button 
          onClick={fetchDashboardData}
          className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700"
        >
          Retry
        </button>
      </div>
    );
  }

  const latestAnalysis = getLatestAnalysis();
  const metrics = calculateOverallMetrics();
  const chartData = formatChartData();
  const accuracyData = formatForecastAccuracy();

  return (
    <div className="space-y-6">
      {/* Header Stats */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Analyses</CardTitle>
            <BarChart3 className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{metrics?.totalAnalyses || 0}</div>
            <p className="text-xs text-muted-foreground">
              {metrics?.completedAnalyses || 0} completed
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Success Rate</CardTitle>
            <Target className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{metrics?.successRate || 0}%</div>
            <p className="text-xs text-muted-foreground">
              Analysis completion rate
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Avg R-Squared</CardTitle>
            <TrendingUp className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{metrics?.avgRSquared || 'N/A'}</div>
            <p className="text-xs text-muted-foreground">
              Model accuracy metric
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Latest Analysis</CardTitle>
            <Calendar className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {latestAnalysis ? new Date(latestAnalysis.created_at).toLocaleDateString() : 'None'}
            </div>
            <p className="text-xs text-muted-foreground">
              {latestAnalysis?.filename || 'No analyses yet'}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Analysis Charts */}
      <Tabs defaultValue="beta" className="w-full">
        <TabsList>
          <TabsTrigger value="beta">Beta Analysis</TabsTrigger>
          <TabsTrigger value="accuracy">Forecast Accuracy</TabsTrigger>
          <TabsTrigger value="recent">Recent Activity</TabsTrigger>
        </TabsList>

        <TabsContent value="beta" className="space-y-4">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Card>
              <CardHeader>
                <CardTitle>Beta Realized by Stock</CardTitle>
                <CardDescription>Recent beta coefficient calculations</CardDescription>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={300}>
                  <BarChart data={chartData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="stock" />
                    <YAxis />
                    <Tooltip />
                    <Legend />
                    <Bar dataKey="beta" fill="#3b82f6" name="Beta Realized" />
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Model Error Metrics</CardTitle>
                <CardDescription>MSE and MAE comparison</CardDescription>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={300}>
                  <LineChart data={chartData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="stock" />
                    <YAxis />
                    <Tooltip />
                    <Legend />
                    <Line type="monotone" dataKey="mse" stroke="#ef4444" name="MSE" />
                    <Line type="monotone" dataKey="mae" stroke="#f59e0b" name="MAE" />
                  </LineChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="accuracy" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Forecast Accuracy</CardTitle>
              <CardDescription>Prediction accuracy by stock symbol</CardDescription>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={400}>
                <BarChart data={accuracyData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="stock" />
                  <YAxis />
                  <Tooltip />
                  <Legend />
                  <Bar dataKey="accuracy" fill="#10b981" name="Accuracy %" />
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="recent" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Recent Analysis Results</CardTitle>
              <CardDescription>Latest completed analyses</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                {analysisResults.slice(0, 5).map((result) => (
                  <div key={result.id} className="flex items-center justify-between p-3 border rounded-lg">
                    <div className="space-y-1">
                      <p className="font-medium">{result.filename}</p>
                      <p className="text-sm text-gray-600">
                        {new Date(result.created_at).toLocaleString()}
                      </p>
                      {result.stats && (
                        <div className="flex space-x-4 text-xs text-gray-500">
                          <span>MSE: {result.stats.mse.toFixed(4)}</span>
                          <span>R²: {result.stats.r_squared.toFixed(4)}</span>
                        </div>
                      )}
                    </div>
                    <Badge className={getStatusColor(result.status)}>
                      {result.status}
                    </Badge>
                  </div>
                ))}
                {analysisResults.length === 0 && (
                  <div className="text-center py-8 text-gray-500">
                    No analyses completed yet. Start by uploading data and running an analysis.
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Latest Analysis Details */}
      {latestAnalysis && (
        <Card>
          <CardHeader>
            <CardTitle>Latest Analysis Details</CardTitle>
            <CardDescription>
              {latestAnalysis.filename} • {new Date(latestAnalysis.created_at).toLocaleString()}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <h4 className="font-semibold text-sm text-gray-700 mb-2">Model Performance</h4>
                {latestAnalysis.stats && (
                  <div className="space-y-1 text-sm">
                    <div className="flex justify-between">
                      <span>MSE:</span>
                      <span className="font-mono">{latestAnalysis.stats.mse.toFixed(6)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span>MAE:</span>
                      <span className="font-mono">{latestAnalysis.stats.mae.toFixed(6)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span>R-Squared:</span>
                      <span className="font-mono">{latestAnalysis.stats.r_squared.toFixed(4)}</span>
                    </div>
                  </div>
                )}
              </div>
              <div>
                <h4 className="font-semibold text-sm text-gray-700 mb-2">Analysis Info</h4>
                <div className="space-y-1 text-sm">
                  <div className="flex justify-between">
                    <span>Status:</span>
                    <Badge className={getStatusColor(latestAnalysis.status)}>
                      {latestAnalysis.status}
                    </Badge>
                  </div>
                  <div className="flex justify-between">
                    <span>Model Type:</span>
                    <span>{latestAnalysis.model_type || 'Standard'}</span>
                  </div>
                </div>
              </div>
              <div>
                <h4 className="font-semibold text-sm text-gray-700 mb-2">Results</h4>
                <div className="space-y-1 text-sm">
                  <div className="flex justify-between">
                    <span>Predictions:</span>
                    <span>{latestAnalysis.stats?.total_predictions || 'N/A'}</span>
                  </div>
                  <div className="flex justify-between">
                    <span>Quality:</span>
                    <span className={`font-semibold ${
                      latestAnalysis.stats?.r_squared && latestAnalysis.stats.r_squared > 0.7 
                        ? 'text-green-600' 
                        : latestAnalysis.stats?.r_squared && latestAnalysis.stats.r_squared > 0.5
                        ? 'text-yellow-600'
                        : 'text-red-600'
                    }`}>
                      {latestAnalysis.stats?.r_squared && latestAnalysis.stats.r_squared > 0.7 
                        ? 'Excellent' 
                        : latestAnalysis.stats?.r_squared && latestAnalysis.stats.r_squared > 0.5
                        ? 'Good'
                        : 'Needs Improvement'}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
};

export default LiveDashboard;