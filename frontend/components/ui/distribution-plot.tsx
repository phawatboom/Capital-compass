import { BarChart, Bar, XAxis, YAxis, ResponsiveContainer, ReferenceLine } from "recharts"

interface DistributionPlotProps {
  data: Array<{ zscore: number; count: number }>
  currentValue: number
  title: string
}

export function DistributionPlot({ data, currentValue, title }: DistributionPlotProps) {
  return (
    <div className="space-y-2">
      <h4 className="text-sm font-medium text-gray-700">{title}</h4>
      <div className="h-32 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 5, right: 5, left: 5, bottom: 5 }}>
            <XAxis dataKey="zscore" tick={{ fontSize: 10 }} tickFormatter={(value) => value.toFixed(1)} />
            <YAxis hide />
            <Bar dataKey="count" fill="#e5e7eb" stroke="#9ca3af" strokeWidth={0.5} />
            <ReferenceLine x={currentValue} stroke="#dc2626" strokeWidth={2} strokeDasharray="2 2" />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="flex items-center justify-center gap-2 text-xs text-gray-600">
        <div className="w-3 h-0.5 bg-red-600"></div>
        <span>Current: {currentValue.toFixed(2)}</span>
      </div>
    </div>
  )
}
