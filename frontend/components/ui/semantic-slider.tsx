"use client"

import * as React from "react"
import * as SliderPrimitive from "@radix-ui/react-slider"
import { cn } from "@/lib/utils"

interface SemanticSliderProps extends React.ComponentPropsWithoutRef<typeof SliderPrimitive.Root> {
  semanticType?: "percentile" | "zscore" | "volatility" | "correlation" | "score" | "default"
  leftLabel?: string
  rightLabel?: string
  showLabels?: boolean
}

const getSemanticStyles = (type: string) => {
  switch (type) {
    case "percentile":
      return {
        track: "bg-gradient-to-r from-green-200 via-yellow-200 to-red-200",
        range: "bg-gradient-to-r from-green-500 via-yellow-500 to-red-500",
        thumb: "border-gray-600 bg-white shadow-md",
      }
    case "zscore":
      return {
        track: "bg-gradient-to-r from-blue-200 via-gray-200 to-red-200",
        range: "bg-gradient-to-r from-blue-500 via-gray-500 to-red-500",
        thumb: "border-gray-600 bg-white shadow-md",
      }
    case "volatility":
      return {
        track: "bg-gradient-to-r from-green-200 to-red-200",
        range: "bg-gradient-to-r from-green-500 to-red-500",
        thumb: "border-gray-600 bg-white shadow-md",
      }
    case "correlation":
      return {
        track: "bg-gradient-to-r from-red-200 via-gray-200 to-green-200",
        range: "bg-gradient-to-r from-red-500 via-gray-500 to-green-500",
        thumb: "border-gray-600 bg-white shadow-md",
      }
    case "score":
      return {
        track: "bg-gradient-to-r from-red-200 via-yellow-200 to-green-200",
        range: "bg-gradient-to-r from-red-500 via-yellow-500 to-green-500",
        thumb: "border-gray-600 bg-white shadow-md",
      }
    default:
      return {
        track: "bg-gray-200",
        range: "bg-blue-500",
        thumb: "border-blue-500 bg-white shadow-sm",
      }
  }
}

const SemanticSlider = React.forwardRef<React.ElementRef<typeof SliderPrimitive.Root>, SemanticSliderProps>(
  ({ className, semanticType = "default", leftLabel, rightLabel, showLabels = true, ...props }, ref) => {
    const styles = getSemanticStyles(semanticType)

    return (
      <div className="space-y-2">
        <SliderPrimitive.Root
          ref={ref}
          className={cn("relative flex w-full touch-none select-none items-center", className)}
          {...props}
        >
          <SliderPrimitive.Track className={cn("relative h-3 w-full grow overflow-hidden rounded-full", styles.track)}>
            <SliderPrimitive.Range className={cn("absolute h-full", styles.range)} />
          </SliderPrimitive.Track>
          <SliderPrimitive.Thumb
            className={cn(
              "block h-5 w-5 rounded-full border-2 ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50",
              styles.thumb,
            )}
          />
        </SliderPrimitive.Root>
        {showLabels && (leftLabel || rightLabel) && (
          <div className="flex justify-between text-xs text-gray-500 font-medium">
            <span>{leftLabel}</span>
            <span>{rightLabel}</span>
          </div>
        )}
      </div>
    )
  },
)
SemanticSlider.displayName = "SemanticSlider"

export { SemanticSlider }
