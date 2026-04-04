import { RefreshCw, ZoomIn, ZoomOut, Maximize2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/cn";

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

export interface CurveToolbarProps {
  className?: string;
  onZoomIn?: () => void;
  onZoomOut?: () => void;
  onReset?: () => void;
  onFullscreen?: () => void;
  disabled?: boolean;
}

/* ------------------------------------------------------------------ */
/*  Component                                                         */
/* ------------------------------------------------------------------ */

export function CurveToolbar({
  className,
  onZoomIn,
  onZoomOut,
  onReset,
  onFullscreen,
  disabled = false,
}: CurveToolbarProps) {
  return (
    <div
      className={cn(
        "flex items-center gap-1 rounded-lg border border-border/60 bg-surface/80 px-2 py-1.5 backdrop-blur-sm",
        className
      )}
    >
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="ghost"
            size="sm"
            className="h-8 w-8 p-0"
            onClick={onZoomIn}
            disabled={disabled}
          >
            <ZoomIn className="h-4 w-4" />
          </Button>
        </TooltipTrigger>
        <TooltipContent>放大</TooltipContent>
      </Tooltip>

      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="ghost"
            size="sm"
            className="h-8 w-8 p-0"
            onClick={onZoomOut}
            disabled={disabled}
          >
            <ZoomOut className="h-4 w-4" />
          </Button>
        </TooltipTrigger>
        <TooltipContent>缩小</TooltipContent>
      </Tooltip>

      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="ghost"
            size="sm"
            className="h-8 w-8 p-0"
            onClick={onReset}
            disabled={disabled}
          >
            <RefreshCw className="h-4 w-4" />
          </Button>
        </TooltipTrigger>
        <TooltipContent>重置缩放</TooltipContent>
      </Tooltip>

      <div className="h-4 w-px bg-border mx-1" />

      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="ghost"
            size="sm"
            className="h-8 w-8 p-0"
            onClick={onFullscreen}
            disabled={disabled}
          >
            <Maximize2 className="h-4 w-4" />
          </Button>
        </TooltipTrigger>
        <TooltipContent>全屏</TooltipContent>
      </Tooltip>
    </div>
  );
}