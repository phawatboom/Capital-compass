import { Badge } from "@/components/ui/badge"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"

interface PercentileBadgesProps {
  market: number
  cluster: number
}

export function PercentileBadges({ market, cluster }: PercentileBadgesProps) {
  return (
    <div className="flex gap-2">
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <Badge variant="secondary">Market: {(market * 100).toFixed(0)}%</Badge>
          </TooltipTrigger>
          <TooltipContent>
            <p>Market Percentile - ranks better than {(market * 100).toFixed(0)}% of all stocks</p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>

      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <Badge variant="outline">Cluster: {(cluster * 100).toFixed(0)}%</Badge>
          </TooltipTrigger>
          <TooltipContent>
            <p>Cluster Percentile - ranks better than {(cluster * 100).toFixed(0)}% of cluster peers</p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    </div>
  )
}
