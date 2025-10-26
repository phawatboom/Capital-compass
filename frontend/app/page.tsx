import { ArrowRight, Upload, BarChart3, TrendingUp, Shield, Zap } from "lucide-react"
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
            Beta Forecasting with
            <span className="text-blue-500"> ARIMA Model</span>
          </h1>
          <p className="text-lg text-gray-600 mb-2 leading-relaxed">
            Our model captures how each stock’s short-term behavior shifts relative to its peers and market volatility, using advanced ElasticNet regression to forecast next-period β values across multiple horizons -s revealing the real-time balance between mean reversion and momentum.
          </p>
          <div className="grid md:grid-cols-3 gap-4 mb-8 text-center">
            {/* <div className="bg-white p-4 rounded-lg shadow-sm">
              <p className="text-2xl font-bold text-blue-500">58.4%</p>
              <p className="text-sm text-gray-600">Directional Accuracy</p>
            </div> */}
            {/* <div className="bg-white p-4 rounded-lg shadow-sm">
              <p className="text-2xl font-bold text-green-500">544</p>
              <p className="text-sm text-gray-600">Stock Universe</p>
            </div> */}
            {/* <div className="bg-white p-4 rounded-lg shadow-sm">
              <p className="text-2xl font-bold text-purple-500">60K+</p>
              <p className="text-sm text-gray-600">Predictions Generated</p>
            </div> */}
          </div>
          <div className="flex flex-col sm:flex-row gap-4 justify-center">
            <Link href="/beta">
              <Button size="lg" className="text-lg px-8 py-3">
                View Results
                <ArrowRight className="ml-2 h-5 w-5" />
              </Button>
            </Link>
            <Link href="/upload">
              <Button variant="outline" size="lg" className="text-lg px-8 py-3 bg-transparent">
                Upload Data
              </Button>
            </Link>
          </div>
        </div>
      </section>

      {/* Value Propositions */}
      <section className="py-16 px-4 bg-white">
        <div className="container mx-auto max-w-6xl">
          <h2 className="text-3xl font-bold text-center mb-12">Why Universal Beta Forecasting?</h2>
          <div className="grid md:grid-cols-3 gap-8">
            <Card className="border-0 shadow-lg">
              <CardHeader>
                <Zap className="h-12 w-12 text-blue-600 mb-4" />
                <CardTitle>Cross-Sectional Learning</CardTitle>
              </CardHeader>
              <CardContent>
                <CardDescription className="text-base">
                  Our Universal Model learns from patterns across the entire stock universe, not just individual stocks. 
                  This cross-sectional approach provides more robust predictions by leveraging market-wide information.
                </CardDescription>
              </CardContent>
            </Card>

            <Card className="border-0 shadow-lg">
              <CardHeader>
                <TrendingUp className="h-12 w-12 text-green-600 mb-4" />
                <CardTitle>Pooled Intelligence</CardTitle>
              </CardHeader>
              <CardContent>
                <CardDescription className="text-base">
                  Combines information from 544 stocks with 23 engineered features including momentum, volatility, 
                  technical indicators, and cross-sectional rankings to deliver superior forecasting accuracy.
                </CardDescription>
              </CardContent>
            </Card>

            <Card className="border-0 shadow-lg">
              <CardHeader>
                <Shield className="h-12 w-12 text-purple-600 mb-4" />
                <CardTitle>Automated Confidence</CardTitle>
              </CardHeader>
              <CardContent>
                <CardDescription className="text-base">
                  Built-in confidence assessment and trading signal generation. Get high-confidence opportunities 
                  automatically identified with directional predictions and risk metrics for informed decision-making.
                </CardDescription>
              </CardContent>
            </Card>
          </div>
        </div>
      </section>

      {/* Key Metrics */}
      <section id="features" className="py-16 px-4 bg-slate-50">
        <div className="container mx-auto max-w-6xl">
          <h2 className="text-3xl font-bold text-center mb-12">Universal Model Features</h2>
          <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-6">
            <div className="bg-white p-6 rounded-lg shadow-md">
              <h3 className="font-semibold text-lg mb-2">Pooled Learning</h3>
              <p className="text-gray-600">
                Leverages patterns from entire stock universe with elastic net regularization for robust predictions
              </p>
            </div>
            <div className="bg-white p-6 rounded-lg shadow-md">
              <h3 className="font-semibold text-lg mb-2">Multi-Horizon</h3>
              <p className="text-gray-600">Forecasts for 1, 5, 10, and 20-day horizons with consistent performance</p>
            </div>
            <div className="bg-white p-6 rounded-lg shadow-md">
              <h3 className="font-semibold text-lg mb-2">Feature Engineering</h3>
              <p className="text-gray-600">23 features including momentum, volatility, technical indicators, and cross-sectional rankings</p>
            </div>
            <div className="bg-white p-6 rounded-lg shadow-md">
              <h3 className="font-semibold text-lg mb-2">Trading Signals</h3>
              <p className="text-gray-600">Automated confidence assessment and high-conviction trading opportunity identification</p>
            </div>
          </div>
        </div>
      </section>

      {/* How It Works */}
      <section id="how-it-works" className="py-16 px-4 bg-white">
        <div className="container mx-auto max-w-4xl">
          <h2 className="text-3xl font-bold text-center mb-12">How Universal Forecasting Works</h2>
          <div className="space-y-8">
            <div className="flex items-start space-x-4">
              <div className="bg-blue-500 text-white rounded-full w-8 h-8 flex items-center justify-center font-bold">
                1
              </div>
              <div>
                <h3 className="font-semibold text-lg mb-2">Cross-Sectional Data Processing</h3>
                <p className="text-gray-600">
                  Our system processes data from 544 stocks simultaneously, computing historical betas, momentum indicators, 
                  volatility measures, and cross-sectional rankings to capture market-wide patterns.
                </p>
              </div>
            </div>
            <div className="flex items-start space-x-4">
              <div className="bg-blue-500 text-white rounded-full w-8 h-8 flex items-center justify-center font-bold">
                2
              </div>
              <div>
                <h3 className="font-semibold text-lg mb-2">Universal Model Training</h3>
                <p className="text-gray-600">
                  The Universal Pooled Model learns from the entire stock universe using elastic net regularization, 
                  combining historical beta coefficients with technical and fundamental features for robust predictions.
                </p>
              </div>
            </div>
            <div className="flex items-start space-x-4">
              <div className="bg-blue-500 text-white rounded-full w-8 h-8 flex items-center justify-center font-bold">
                3
              </div>
              <div>
                <h3 className="font-semibold text-lg mb-2">Trading Dashboard & Signals</h3>
                <p className="text-gray-600">
                  Access high-confidence trading opportunities, automated signal generation, and comprehensive performance 
                  metrics through our interactive dashboard designed for fund managers.
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* CTA Section
      <section className="py-16 px-4 bg-blue-500 text-white">
        <div className="container mx-auto text-center max-w-3xl">
          <h2 className="text-3xl font-bold mb-6">Ready for Next-Generation Beta Forecasting?</h2>
          <p className="text-xl mb-8 opacity-90">
            Experience the power of universal cross-sectional learning with our advanced pooled model. 
            Join institutional investors leveraging market-wide intelligence for superior trading decisions.
          </p>
          <Link href="/beta">
            <Button size="lg" variant="secondary" className="text-lg px-8 py-3">
              Explore Universal Dashboard
              <ArrowRight className="ml-2 h-5 w-5" />
            </Button>
          </Link>
        </div>
      </section> */}

      {/* Footer */}
      <footer className="bg-gray-900 text-white py-12 px-4">
        <div className="container mx-auto max-w-6xl">
          {/* <div className="grid md:grid-cols-4 gap-8">
            <div>
              <div className="flex items-center space-x-2 mb-4">
                <BarChart3 className="h-6 w-6" />
                <span className="text-xl font-bold">Universal Beta Platform</span>
              </div>
              <p className="text-gray-400">Cross-sectional learning for institutional-grade beta coefficient forecasting.</p>
            </div>
            <div>
              <h3 className="font-semibold mb-4">Platform</h3>
              <ul className="space-y-2 text-gray-400">
                <li>
                  <Link href="/beta" className="hover:text-white">
                    Universal Dashboard
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
          </div> */}
          <div className="border-t border-gray-800 text-center text-gray-400">
            <p>&copy; 2025 Capital Compass - Team Bobbers.</p>
          </div>
        </div>
      </footer>
    </div>
  )
}
