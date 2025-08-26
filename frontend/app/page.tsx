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
            Smarter Investment Decisions with
            <span className="text-blue-600"> AI-Powered Analytics</span>
          </h1>
          <p className="text-xl text-gray-600 mb-8 leading-relaxed">
            Transform your stock analysis workflow with advanced metrics like Z-scores, serial correlation, and
            volatility clustering. Make confident buy/sell decisions backed by transparent, explainable insights.
          </p>
          <p className="text-lg text-blue-600 mb-8">
            Every score shows uncertainty range so you know how confident the model is.
          </p>
          <div className="flex flex-col sm:flex-row gap-4 justify-center">
            <Link href="/upload">
              <Button size="lg" className="text-lg px-8 py-3">
                Upload Your Data
                <ArrowRight className="ml-2 h-5 w-5" />
              </Button>
            </Link>
            <Link href="/demo">
              <Button variant="outline" size="lg" className="text-lg px-8 py-3 bg-transparent">
                View Demo Report
              </Button>
            </Link>
          </div>
        </div>
      </section>

      {/* Value Propositions */}
      <section className="py-16 px-4 bg-white">
        <div className="container mx-auto max-w-6xl">
          <h2 className="text-3xl font-bold text-center mb-12">Why Capital Compass?</h2>
          <div className="grid md:grid-cols-3 gap-8">
            <Card className="border-0 shadow-lg">
              <CardHeader>
                <TrendingUp className="h-12 w-12 text-blue-600 mb-4" />
                <CardTitle>Smarter Decision-Making</CardTitle>
              </CardHeader>
              <CardContent>
                <CardDescription className="text-base">
                  Unlock hidden insights and patterns in stock behavior with advanced analytics. Access characteristics
                  previously unavailable to fill in the missing pieces of market dynamics.
                </CardDescription>
              </CardContent>
            </Card>

            <Card className="border-0 shadow-lg">
              <CardHeader>
                <Upload className="h-12 w-12 text-green-600 mb-4" />
                <CardTitle>Intuitive & Easy to Use</CardTitle>
              </CardHeader>
              <CardContent>
                <CardDescription className="text-base">
                  One-click file upload, instant analysis. Integrate seamlessly into your workflow with zero training
                  required. Get the reports you need in seconds, not hours.
                </CardDescription>
              </CardContent>
            </Card>

            <Card className="border-0 shadow-lg">
              <CardHeader>
                <Shield className="h-12 w-12 text-purple-600 mb-4" />
                <CardTitle>Transparent & Traceable</CardTitle>
              </CardHeader>
              <CardContent>
                <CardDescription className="text-base">
                  Every metric traces back to well-recognized financial indicators. Understand exactly what the data
                  tells you and use insights with confidence.
                </CardDescription>
              </CardContent>
            </Card>
          </div>
        </div>
      </section>

      {/* Key Metrics */}
      <section id="features" className="py-16 px-4 bg-slate-50">
        <div className="container mx-auto max-w-6xl">
          <h2 className="text-3xl font-bold text-center mb-12">Core Analytics</h2>
          <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-6">
            <div className="bg-white p-6 rounded-lg shadow-md">
              <h3 className="font-semibold text-lg mb-2">Z-Score Analysis</h3>
              <p className="text-gray-600">
                Identify overbought/oversold conditions with statistical significance and 95% confidence intervals
              </p>
            </div>
            <div className="bg-white p-6 rounded-lg shadow-md">
              <h3 className="font-semibold text-lg mb-2">Serial Correlation</h3>
              <p className="text-gray-600">Detect mean reversion patterns with focus on 30–60 day windows</p>
            </div>
            <div className="bg-white p-6 rounded-lg shadow-md">
              <h3 className="font-semibold text-lg mb-2">Volatility Clustering</h3>
              <p className="text-gray-600">Group stocks by risk characteristics with short-term risk window (20d)</p>
            </div>
            <div className="bg-white p-6 rounded-lg shadow-md">
              <h3 className="font-semibold text-lg mb-2">Reversion Signals</h3>
              <p className="text-gray-600">Numeric score (0–1) with CI range and clear buy/sell/hold recommendations</p>
            </div>
          </div>
        </div>
      </section>

      {/* How It Works */}
      <section id="how-it-works" className="py-16 px-4 bg-white">
        <div className="container mx-auto max-w-4xl">
          <h2 className="text-3xl font-bold text-center mb-12">How It Works</h2>
          <div className="space-y-8">
            <div className="flex items-start space-x-4">
              <div className="bg-blue-600 text-white rounded-full w-8 h-8 flex items-center justify-center font-bold">
                1
              </div>
              <div>
                <h3 className="font-semibold text-lg mb-2">Upload Your Data</h3>
                <p className="text-gray-600">
                  Upload CSV files with your stock price data (headers: date, ticker, adj_close/ret). Our system
                  automatically detects the format and structure.
                </p>
              </div>
            </div>
            <div className="flex items-start space-x-4">
              <div className="bg-blue-600 text-white rounded-full w-8 h-8 flex items-center justify-center font-bold">
                2
              </div>
              <div>
                <h3 className="font-semibold text-lg mb-2">AI Analysis</h3>
                <p className="text-gray-600">
                  Our models calculate Z-scores, correlations, volatility metrics, and cluster memberships for each
                  stock, with confidence intervals for all metrics.
                </p>
              </div>
            </div>
            <div className="flex items-start space-x-4">
              <div className="bg-blue-600 text-white rounded-full w-8 h-8 flex items-center justify-center font-bold">
                3
              </div>
              <div>
                <h3 className="font-semibold text-lg mb-2">Get Actionable Reports</h3>
                <p className="text-gray-600">
                  Receive detailed reports with buy/sell/hold recommendations, one page per stock, with clear rationale
                  and confidence intervals.
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="py-16 px-4 bg-blue-600 text-white">
        <div className="container mx-auto text-center max-w-3xl">
          <h2 className="text-3xl font-bold mb-6">Ready to Transform Your Investment Process?</h2>
          <p className="text-xl mb-8 opacity-90">
            Join fund managers who are already making smarter decisions with Capital Compass.
          </p>
          <Link href="/upload">
            <Button size="lg" variant="secondary" className="text-lg px-8 py-3">
              Start Your Analysis
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
                <span className="text-xl font-bold">Capital Compass</span>
              </div>
              <p className="text-gray-400">AI-powered investment analytics for smarter decision-making.</p>
            </div>
            <div>
              <h3 className="font-semibold mb-4">Product</h3>
              <ul className="space-y-2 text-gray-400">
                <li>
                  <Link href="/upload" className="hover:text-white">
                    Upload Data
                  </Link>
                </li>
                <li>
                  <Link href="/demo" className="hover:text-white">
                    Demo
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
              <h3 className="font-semibold mb-4">Support</h3>
              <ul className="space-y-2 text-gray-400">
                <li>
                  <Link href="/docs" className="hover:text-white">
                    Documentation
                  </Link>
                </li>
                <li>
                  <Link href="/help" className="hover:text-white">
                    Help Center
                  </Link>
                </li>
                <li>
                  <Link href="/api" className="hover:text-white">
                    API
                  </Link>
                </li>
              </ul>
            </div>
          </div>
          <div className="border-t border-gray-800 mt-8 pt-8 text-center text-gray-400">
            <p>&copy; 2025 Capital Compass. All rights reserved.</p>
          </div>
        </div>
      </footer>
    </div>
  )
}
