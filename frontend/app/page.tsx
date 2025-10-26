import { ArrowRight, BarChart3, TrendingUp, Shield, Zap } from "lucide-react"
import Link from "next/link"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

export default function HomePage() {
  return (
    // 1) Make the page a column flex layout that fills the dynamic viewport height
    <div className="min-h-dvh flex flex-col bg-gradient-to-br from-slate-50 to-blue-50">
      {/* 2) Put all main content in a flex-1 <main> so it takes remaining space */}
      <main className="flex-1">
        {/* Hero Section */}
        <section className="py-20 px-4">
          <div className="container mx-auto text-center max-w-4xl">
            <h1 className="text-5xl md:text-6xl font-bold text-gray-900 mb-6">
              Beta Forecasting with
              <span className="text-blue-500"> ARIMA Model</span>
            </h1>
            <p className="text-lg text-gray-600 mb-2 leading-relaxed">
              Our model captures how each stock’s short-term behavior shifts relative to its peers and market volatility,
              using advanced ElasticNet regression to forecast next-period β values across multiple horizons -s revealing
              the real-time balance between mean reversion and momentum.
            </p>
            <div className="grid md:grid-cols-3 gap-4 mb-8 text-center"></div>
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
                  <CardTitle>Market-Wide Learning</CardTitle>
                </CardHeader>
                <CardContent>
                  <CardDescription className="text-base">
                    Our Universal Model learns from patterns across the entire stock universe, not just individual stocks.
                    This approach provides stable and forward-looking beta forecasts.
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
                  <CardTitle>Performance Outcomes</CardTitle>
                </CardHeader>
                <CardContent>
                  <CardDescription className="text-base">
                    Our forecasts translate complex market signals into tangible performance insights. Identify which
                    stocks are likely to outperform or lag, anticipate beta shifts before they happen.
                  </CardDescription>
                </CardContent>
              </Card>
            </div>
          </div>
        </section>
      </main>

      {/* 3) Footer naturally sits at the bottom; mt-auto optional as a guard */}
      <footer className="mt-auto bg-gray-900 text-white py-12 px-4">
        <div className="container mx-auto max-w-6xl">
          <div className="border-t border-gray-800 text-center text-gray-400">
            <p>&copy; 2025 Capital Compass - Team Bobbers.</p>
          </div>
        </div>
      </footer>
    </div>
  )
}
