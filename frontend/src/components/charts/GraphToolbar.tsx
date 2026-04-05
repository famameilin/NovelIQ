import { Crosshair, Filter, Maximize, Search, ZoomIn, ZoomOut } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/cn";

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

export interface GraphToolbarProps {
  onZoomIn: () => void;
  onZoomOut: () => void;
  onFitToScreen: () => void;
  onCenter: () => void;
  relationTypes: string[];
  selectedRelationTypes: Set<string>;
  onRelationTypeChange: (types: Set<string>) => void;
  searchQuery: string;
  onSearchChange: (query: string) => void;
  className?: string;
}

/* ------------------------------------------------------------------ */
/*  Component                                                         */
/* ------------------------------------------------------------------ */

/**
 * 图谱工具栏组件
 *
 * 创建时间: 2026-04-05
 * 创建者: GLM-5
 * 任务: 创建 GraphToolbar 组件
 * 说明: 提供图谱的缩放、居中、关系类型过滤和节点搜索功能
 */
export function GraphToolbar({
  onZoomIn,
  onZoomOut,
  onFitToScreen,
  onCenter,
  relationTypes,
  selectedRelationTypes,
  onRelationTypeChange,
  searchQuery,
  onSearchChange,
  className,
}: GraphToolbarProps) {
  const handleRelationTypeToggle = (type: string) => {
    const newTypes = new Set(selectedRelationTypes);
    if (newTypes.has(type)) {
      newTypes.delete(type);
    } else {
      newTypes.add(type);
    }
    onRelationTypeChange(newTypes);
  };

  const handleSelectAll = () => {
    onRelationTypeChange(new Set(relationTypes));
  };

  const handleClearAll = () => {
    onRelationTypeChange(new Set());
  };

  const isPartialSelected = selectedRelationTypes.size > 0 && selectedRelationTypes.size < relationTypes.length;

  return (
    <div
      className={cn(
        "flex items-center gap-1 rounded-lg border border-border/60 bg-surface/80 px-2 py-1.5 backdrop-blur-sm",
        className
      )}
    >
      {/* 缩放按钮组 */}
      <Tooltip>
        <TooltipTrigger asChild>
          <Button variant="ghost" size="sm" className="h-8 w-8 p-0" onClick={onZoomIn}>
            <ZoomIn className="h-4 w-4" />
          </Button>
        </TooltipTrigger>
        <TooltipContent>放大</TooltipContent>
      </Tooltip>

      <Tooltip>
        <TooltipTrigger asChild>
          <Button variant="ghost" size="sm" className="h-8 w-8 p-0" onClick={onZoomOut}>
            <ZoomOut className="h-4 w-4" />
          </Button>
        </TooltipTrigger>
        <TooltipContent>缩小</TooltipContent>
      </Tooltip>

      <Tooltip>
        <TooltipTrigger asChild>
          <Button variant="ghost" size="sm" className="h-8 w-8 p-0" onClick={onFitToScreen}>
            <Maximize className="h-4 w-4" />
          </Button>
        </TooltipTrigger>
        <TooltipContent>适应屏幕</TooltipContent>
      </Tooltip>

      <div className="h-4 w-px bg-border mx-1" />

      {/* 居中按钮 */}
      <Tooltip>
        <TooltipTrigger asChild>
          <Button variant="ghost" size="sm" className="h-8 w-8 p-0" onClick={onCenter}>
            <Crosshair className="h-4 w-4" />
          </Button>
        </TooltipTrigger>
        <TooltipContent>居中</TooltipContent>
      </Tooltip>

      <div className="h-4 w-px bg-border mx-1" />

      {/* 关系类型过滤 */}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="sm" className="h-8 gap-1.5 px-2">
            <Filter className="h-4 w-4" />
            <span className="text-xs">关系类型</span>
            {isPartialSelected && (
              <span className="flex h-4 w-4 items-center justify-center rounded-full bg-primary-subtle text-[10px] font-medium text-primary">
                {selectedRelationTypes.size}
              </span>
            )}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-48">
          <DropdownMenuLabel className="flex items-center justify-between">
            <span>关系类型</span>
            <div className="flex gap-1">
              <button
                type="button"
                onClick={handleSelectAll}
                className="text-xs text-primary hover:underline"
              >
                全选
              </button>
              <span className="text-text-muted">|</span>
              <button
                type="button"
                onClick={handleClearAll}
                className="text-xs text-text-muted hover:text-text"
              >
                清空
              </button>
            </div>
          </DropdownMenuLabel>
          <DropdownMenuSeparator />
          {relationTypes.length === 0 ? (
            <div className="px-2 py-1.5 text-sm text-text-muted">暂无关系类型</div>
          ) : (
            relationTypes.map((type) => (
              <DropdownMenuCheckboxItem
                key={type}
                checked={selectedRelationTypes.has(type)}
                onCheckedChange={() => handleRelationTypeToggle(type)}
                onSelect={(e) => e.preventDefault()}
              >
                {type}
              </DropdownMenuCheckboxItem>
            ))
          )}
        </DropdownMenuContent>
      </DropdownMenu>

      <div className="h-4 w-px bg-border mx-1" />

      {/* 节点搜索 */}
      <div className="relative flex items-center">
        <Search className="absolute left-2 h-3.5 w-3.5 text-text-muted pointer-events-none" />
        <Input
          type="text"
          placeholder="搜索节点..."
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          className="h-8 w-40 pl-7 pr-2 text-xs"
        />
      </div>
    </div>
  );
}
