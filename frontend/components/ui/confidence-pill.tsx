import { Badge } from "@/components/ui/badge"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"

interface ConfidencePillProps {
  ci: [number, number]
  value?: number
  label?: string
}

export function ConfidencePill({ ci, value, label = "95% CI" }: ConfidencePillProps) {
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <Badge variant="outline" className="font-mono text-xs">
            {value !== undefined && `${value.toFixed(2)} `}({ci[0].toFixed(2)}–{ci[1].toFixed(2)})
          </Badge>
        </TooltipTrigger>
        <TooltipContent>
          <p>{label}</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}
