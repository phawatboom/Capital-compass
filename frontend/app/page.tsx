import { ArrowRight, Upload, BarChart3, TrendingUp, Shield } from "lucide-react"
import Link from "next/link"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

export default function HomePage() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50">
      {/* Hero Section */}
      <section className="py-20 px-4">
        <div className="container mx-auto text-center max-w-4xl">
          <h1 className="text-5xl md:text-6xl font-bold text-gray-900 mb-6">
            Predict Stock Beta Coefficients with
            <span className="text-blue-600"> Advanced ARIMA Forecasting</span>
          </h1>
          <p className="text-xl text-gray-600 mb-8 leading-relaxed">
            Unlock the future of market sensitivity analysis with our cutting-edge beta coefficient prediction platform. 
            Combine ARIMA time series modeling with OLS regression to forecast how stocks will respond to market movements.
          </p>
          <p className="text-lg text-blue-600 mb-8">
            Get precise beta forecasts with confidence intervals and statistical significance testing.
          </p>
          <div className="flex flex-col sm:flex-row gap-4 justify-center">
            <Link href="/beta">
              <Button size="lg" className="text-lg px-8 py-3">
                View Beta Dashboard
                <ArrowRight className="ml-2 h-5 w-5" />
              </Button>
            </Link>
            <Link href="/upload">
              <Button variant="outline" size="lg" className="text-lg px-8 py-3 bg-transparent">
                Upload Stock Data
              </Button>
            </Link>
          </div>
        </div>
      </section>

      {/* Value Propositions */}
      <section className="py-16 px-4 bg-white">
        <div className="container mx-auto max-w-6xl">
          <h2 className="text-3xl font-bold text-center mb-12">Why Beta Coefficient Forecasting?</h2>
          <div className="grid md:grid-cols-3 gap-8">
            <Card className="border-0 shadow-lg">
              <CardHeader>
                <TrendingUp className="h-12 w-12 text-blue-600 mb-4" />
                <CardTitle>Predictive Market Sensitivity</CardTitle>
              </CardHeader>
              <CardContent>
                <CardDescription className="text-base">
                  Anticipate how stocks will respond to market movements before they happen. Our ARIMA-based models 
                  forecast beta coefficients to help you understand future market sensitivity and correlation patterns.
                </CardDescription>
              </CardContent>
            </Card>

            <Card className="border-0 shadow-lg">
              <CardHeader>
                <Upload className="h-12 w-12 text-green-600 mb-4" />
                <CardTitle>Advanced Time Series Modeling</CardTitle>
              </CardHeader>
              <CardContent>
                <CardDescription className="text-base">
                  Leverages cutting-edge ARIMA forecasting combined with ordinary least squares regression. 
                  Upload your price data and get sophisticated predictions with statistical confidence intervals.
                </CardDescription>
              </CardContent>
            </Card>

            <Card className="border-0 shadow-lg">
              <CardHeader>
                <Shield className="h-12 w-12 text-purple-600 mb-4" />
                <CardTitle>Statistical Validation</CardTitle>
              </CardHeader>
              <CardContent>
                <CardDescription className="text-base">
                  Every beta prediction comes with R-squared values, p-values, and significance testing. 
                  Understand model confidence and make data-driven portfolio decisions with statistical rigor.
                </CardDescription>
              </CardContent>
            </Card>
          </div>
        </div>
      </section>

      {/* Key Metrics */}
      <section id="features" className="py-16 px-4 bg-slate-50">
        <div className="container mx-auto max-w-6xl">
          <h2 className="text-3xl font-bold text-center mb-12">Beta Forecasting Features</h2>
          <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-6">
            <div className="bg-white p-6 rounded-lg shadow-md">
              <h3 className="font-semibold text-lg mb-2">ARIMA Forecasting</h3>
              <p className="text-gray-600">
                Advanced autoregressive integrated moving average models predict future beta coefficients with precision
              </p>
            </div>
            <div className="bg-white p-6 rounded-lg shadow-md">
              <h3 className="font-semibold text-lg mb-2">OLS Regression</h3>
              <p className="text-gray-600">Ordinary least squares validation provides R² statistics and significance testing</p>
            </div>
            <div className="bg-white p-6 rounded-lg shadow-md">
              <h3 className="font-semibold text-lg mb-2">Time Series Analysis</h3>
              <p className="text-gray-600">Rolling window analysis with 20-day prediction horizons and confidence bands</p>
            </div>
            <div className="bg-white p-6 rounded-lg shadow-md">
              <h3 className="font-semibold text-lg mb-2">Market Sensitivity</h3>
              <p className="text-gray-600">Predict how individual stocks will correlate with market movements over time</p>
            </div>
          </div>
        </div>
      </section>

      {/* How It Works */}
      <section id="how-it-works" className="py-16 px-4 bg-white">
        <div className="container mx-auto max-w-4xl">
          <h2 className="text-3xl font-bold text-center mb-12">How Beta Forecasting Works</h2>
          <div className="space-y-8">
            <div className="flex items-start space-x-4">
              <div className="bg-blue-600 text-white rounded-full w-8 h-8 flex items-center justify-center font-bold">
                1
              </div>
              <div>
                <h3 className="font-semibold text-lg mb-2">Upload Historical Price Data</h3>
                <p className="text-gray-600">
                  Upload CSV files with stock price history including dates, tickers, and adjusted closing prices. 
                  Our system automatically processes the data for time series analysis.
                </p>
              </div>
            </div>
            <div className="flex items-start space-x-4">
              <div className="bg-blue-600 text-white rounded-full w-8 h-8 flex items-center justify-center font-bold">
                2
              </div>
              <div>
                <h3 className="font-semibold text-lg mb-2">ARIMA Model Forecasting</h3>
                <p className="text-gray-600">
                  Our advanced ARIMA models analyze historical beta patterns and generate forward-looking predictions. 
                  Combined with OLS regression for validation and statistical significance testing.
                </p>
              </div>
            </div>
            <div className="flex items-start space-x-4">
              <div className="bg-blue-600 text-white rounded-full w-8 h-8 flex items-center justify-center font-bold">
                3
              </div>
              <div>
                <h3 className="font-semibold text-lg mb-2">Interactive Beta Dashboard</h3>
                <p className="text-gray-600">
                  Access real-time beta coefficient forecasts with confidence intervals, prediction accuracy metrics, 
                  and time series visualizations to guide your investment decisions.
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="py-16 px-4 bg-blue-600 text-white">
        <div className="container mx-auto text-center max-w-3xl">
          <h2 className="text-3xl font-bold mb-6">Ready to Predict Market Sensitivity?</h2>
          <p className="text-xl mb-8 opacity-90">
            Join quantitative analysts who are leveraging advanced beta forecasting for superior portfolio management.
          </p>
          <Link href="/beta">
            <Button size="lg" variant="secondary" className="text-lg px-8 py-3">
              Explore Beta Dashboard
              <ArrowRight className="ml-2 h-5 w-5" />
            </Button>
          </Link>
        </div>
      </section>

      {/* Footer */}
      <footer className="bg-gray-900 text-white py-12 px-4">
        <div className="container mx-auto max-w-6xl">
          <div className="grid md:grid-cols-4 gap-8">
            <div>
              <div className="flex items-center space-x-2 mb-4">
                <BarChart3 className="h-6 w-6" />
                <span className="text-xl font-bold">Beta Forecasting Platform</span>
              </div>
              <p className="text-gray-400">Advanced ARIMA modeling for beta coefficient prediction and portfolio optimization.</p>
            </div>
            <div>
              <h3 className="font-semibold mb-4">Platform</h3>
              <ul className="space-y-2 text-gray-400">
                <li>
                  <Link href="/beta" className="hover:text-white">
                    Beta Dashboard
                  </Link>
                </li>
                <li>
                  <Link href="/upload" className="hover:text-white">
                    Upload Data
                  </Link>
                </li>
                <li>
                  <Link href="#features" className="hover:text-white">
                    Features
                  </Link>
                </li>
              </ul>
            </div>
            <div>
              <h3 className="font-semibold mb-4">Company</h3>
              <ul className="space-y-2 text-gray-400">
                <li>
                  <Link href="/about" className="hover:text-white">
                    About
                  </Link>
                </li>
                <li>
                  <Link href="/contact" className="hover:text-white">
                    Contact
                  </Link>
                </li>
                <li>
                  <Link href="/pricing" className="hover:text-white">
                    Pricing
                  </Link>
                </li>
              </ul>
            </div>
            <div>
              <h3 className="font-semibold mb-4">Resources</h3>
              <ul className="space-y-2 text-gray-400">
                <li>
                  <Link href="/stocks" className="hover:text-white">
                    Stock Analysis
                  </Link>
                </li>
                <li>
                  <Link href="/dashboard" className="hover:text-white">
                    Analytics Dashboard
                  </Link>
                </li>
                <li>
                  <Link href="#how-it-works" className="hover:text-white">
                    How It Works
                  </Link>
                </li>
              </ul>
            </div>
          </div>
          <div className="border-t border-gray-800 mt-8 pt-8 text-center text-gray-400">
            <p>&copy; 2025 Beta Forecasting Platform. Developed by Team Bobbers.</p>
          </div>
        </div>
      </footer>
    </div>
  )
}
