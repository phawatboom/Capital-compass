import { Badge } from "@/components/ui/badge"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"

interface ClusterBadgeProps {
  id: string
  label?: string
  size?: number
}

export function ClusterBadge({ id, label, size }: ClusterBadgeProps) {
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <Badge variant="outline" className="bg-purple-50 text-purple-700 border-purple-200">
            {label || id}
          </Badge>
        </TooltipTrigger>
        <TooltipContent>
          <p>
            Cluster {id}
            {size && ` (${size} stocks)`}
          </p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}
