import { Badge } from "@/components/ui/badge"
import { getPercentileZone } from "@/types/analysis"

interface PercentileZoneBarProps {
  percentile: number
  label: string
  showNumeric?: boolean
}

export function PercentileZoneBar({ percentile, label, showNumeric = true }: PercentileZoneBarProps) {
  const zone = getPercentileZone(percentile)

  return (
    <div className="space-y-2">
      <div className="flex justify-between items-center">
        <span className="text-sm font-medium">{label}</span>
        <div className="flex items-center gap-2">
          {showNumeric && <span className="text-sm font-mono">{(percentile * 100).toFixed(0)}%</span>}
          <Badge className={`${zone.bgColor} ${zone.color} border-0`}>{zone.label}</Badge>
        </div>
      </div>

      {/* Zone bar visualization */}
      <div className="relative w-full h-6 bg-gray-200 rounded-full overflow-hidden">
        {/* Zone backgrounds */}
        <div className="absolute inset-0 flex">
          <div className="w-1/5 bg-blue-100"></div>
          <div className="w-1/5 bg-blue-50"></div>
          <div className="w-1/5 bg-gray-100"></div>
          <div className="w-1/5 bg-orange-50"></div>
          <div className="w-1/5 bg-red-100"></div>
        </div>

        {/* Zone labels */}
        <div className="absolute inset-0 flex text-xs">
          <div className="w-1/5 flex items-center justify-center text-blue-700">Cheap</div>
          <div className="w-1/5 flex items-center justify-center text-blue-600">Mod Cheap</div>
          <div className="w-1/5 flex items-center justify-center text-gray-600">Fair</div>
          <div className="w-1/5 flex items-center justify-center text-orange-600">Expensive</div>
          <div className="w-1/5 flex items-center justify-center text-red-600">V.Exp</div>
        </div>

        {/* Current position marker */}
        <div className="absolute top-0 bottom-0 w-1 bg-gray-800 shadow-lg" style={{ left: `${percentile * 100}%` }}>
          <div className="absolute -top-1 -left-1 w-3 h-3 bg-gray-800 rounded-full"></div>
        </div>
      </div>
    </div>
  )
}
