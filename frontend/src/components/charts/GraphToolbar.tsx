import { Crosshair, Filter, Layers, Maximize, Search, Users, ZoomIn, ZoomOut } from "lucide-react";

import type { GraphNode } from "@/api/types";
import type { GraphScope } from "@/components/charts/forceGraph/graphFocusModel";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/cn";
import { formatAnalysisLabel } from "@/lib/analysisLabels";
import { formatEntityTypeLabel } from "@/lib/graphLabels";

/* ------------------------------------------------------------------ */
/*  类型定义                                                           */
/* ------------------------------------------------------------------ */

export interface GraphEntityTypeOption {
  type: string;
  count: number;
}

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
  graphScope: GraphScope;
  onGraphScopeChange: (scope: GraphScope) => void;
  /** 聚焦模式下总览范围不可调 */
  scopeDisabled?: boolean;
  entityTypeOptions: GraphEntityTypeOption[];
  selectedEntityTypes: Set<string>;
  onEntityTypeChange: (types: Set<string>) => void;
  searchMatches: GraphNode[];
  onSelectSearchMatch: (node: GraphNode) => void;
  className?: string;
}

const SCOPE_LABELS: Record<GraphScope, string> = {
  core: "核心圈层",
  extended: "扩展圈层",
  all: "全部实体",
};

const SCOPE_ITEMS: Array<{ scope: GraphScope; description: string }> = [
  { scope: "core", description: "关系最强的 30 个实体" },
  { scope: "extended", description: "关系最强的 100 个实体" },
  { scope: "all", description: "当前类型下的全部实体" },
];

/* ------------------------------------------------------------------ */
/*  组件主体                                                           */
/* ------------------------------------------------------------------ */

/**
 * 图谱工具栏组件
 *
 * 提供显示范围、实体类型、缩放、居中、关系类型过滤和节点搜索定位
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
  graphScope,
  onGraphScopeChange,
  scopeDisabled = false,
  entityTypeOptions,
  selectedEntityTypes,
  onEntityTypeChange,
  searchMatches,
  onSelectSearchMatch,
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

  const handleEntityTypeToggle = (type: string) => {
    const next = new Set(selectedEntityTypes);
    if (next.has(type)) {
      next.delete(type);
    } else {
      next.add(type);
    }
    onEntityTypeChange(next);
  };

  const isPartialSelected = selectedRelationTypes.size > 0 && selectedRelationTypes.size < relationTypes.length;
  const entityTypeLabel =
    selectedEntityTypes.size === 0
      ? "全部类型"
      : selectedEntityTypes.size === 1
        ? formatEntityTypeLabel(Array.from(selectedEntityTypes)[0])
        : `${selectedEntityTypes.size} 类实体`;

  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-1 rounded-lg border border-border/60 bg-surface/80 px-2 py-1.5 backdrop-blur-sm",
        className
      )}
    >
      {/* 显示范围 */}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="sm" className="h-8 gap-1.5 px-2" disabled={scopeDisabled}>
            <Layers className="h-4 w-4" />
            <span className="text-xs">
              {scopeDisabled ? "聚焦中" : SCOPE_LABELS[graphScope]}
            </span>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-52">
          <DropdownMenuLabel>显示范围</DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuRadioGroup
            value={graphScope}
            onValueChange={(value) => onGraphScopeChange(value as GraphScope)}
          >
            {SCOPE_ITEMS.map((item) => (
              <DropdownMenuRadioItem key={item.scope} value={item.scope}>
                <span className="flex flex-col">
                  <span>{SCOPE_LABELS[item.scope]}</span>
                  <span className="text-xs text-text-muted">{item.description}</span>
                </span>
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
        </DropdownMenuContent>
      </DropdownMenu>

      {/* 实体类型 */}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="sm" className="h-8 gap-1.5 px-2">
            <Users className="h-4 w-4" />
            <span className="text-xs">{entityTypeLabel}</span>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-52">
          <DropdownMenuLabel className="flex items-center justify-between">
            <span>实体类型</span>
            <button
              type="button"
              onClick={() => onEntityTypeChange(new Set())}
              className="text-xs text-text-muted hover:text-text"
            >
              全部类型
            </button>
          </DropdownMenuLabel>
          <DropdownMenuSeparator />
          {entityTypeOptions.length === 0 ? (
            <div className="px-2 py-1.5 text-sm text-text-muted">暂无实体类型</div>
          ) : (
            entityTypeOptions.map((option) => (
              <DropdownMenuCheckboxItem
                key={option.type}
                checked={selectedEntityTypes.has(option.type)}
                onCheckedChange={() => handleEntityTypeToggle(option.type)}
                onSelect={(event) => event.preventDefault()}
              >
                <span className="flex w-full items-center justify-between gap-3">
                  <span>{formatEntityTypeLabel(option.type)}</span>
                  <span className="text-xs text-text-muted">{option.count}</span>
                </span>
              </DropdownMenuCheckboxItem>
            ))
          )}
        </DropdownMenuContent>
      </DropdownMenu>

      <div className="mx-1 h-4 w-px bg-border" />

      {/* 缩放按钮组 */}
      <Tooltip>
        <TooltipTrigger asChild>
          <Button variant="ghost" size="sm" className="h-8 w-8 p-0" onClick={onZoomIn} aria-label="放大关系图">
            <ZoomIn className="h-4 w-4" />
          </Button>
        </TooltipTrigger>
        <TooltipContent>放大</TooltipContent>
      </Tooltip>

      <Tooltip>
        <TooltipTrigger asChild>
          <Button variant="ghost" size="sm" className="h-8 w-8 p-0" onClick={onZoomOut} aria-label="缩小关系图">
            <ZoomOut className="h-4 w-4" />
          </Button>
        </TooltipTrigger>
        <TooltipContent>缩小</TooltipContent>
      </Tooltip>

      <Tooltip>
        <TooltipTrigger asChild>
          <Button variant="ghost" size="sm" className="h-8 w-8 p-0" onClick={onFitToScreen} aria-label="适应关系图范围">
            <Maximize className="h-4 w-4" />
          </Button>
        </TooltipTrigger>
        <TooltipContent>适应屏幕</TooltipContent>
      </Tooltip>

      <div className="mx-1 h-4 w-px bg-border" />

      {/* 居中按钮 */}
      <Tooltip>
        <TooltipTrigger asChild>
          <Button variant="ghost" size="sm" className="h-8 w-8 p-0" onClick={onCenter} aria-label="居中关系图">
            <Crosshair className="h-4 w-4" />
          </Button>
        </TooltipTrigger>
        <TooltipContent>居中</TooltipContent>
      </Tooltip>

      <div className="mx-1 h-4 w-px bg-border" />

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
                <span>{formatAnalysisLabel(type, "relation")}</span>
              </DropdownMenuCheckboxItem>
            ))
          )}
        </DropdownMenuContent>
      </DropdownMenu>

      <div className="mx-1 h-4 w-px bg-border" />

      {/* 节点搜索与定位 */}
      <div className="relative flex items-center">
        <Search className="pointer-events-none absolute left-2 h-3.5 w-3.5 text-text-muted" />
        <Input
          type="text"
          placeholder="搜索节点..."
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          className="h-8 w-40 pl-7 pr-2 text-xs"
        />
        {searchQuery && searchMatches.length > 0 ? (
          <div className="absolute left-0 top-9 z-30 w-56 overflow-hidden rounded-lg border border-border bg-surface shadow-lg">
            {searchMatches.map((node) => (
              <button
                key={node.entity_id}
                type="button"
                onClick={() => onSelectSearchMatch(node)}
                className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-xs transition-colors hover:bg-surface-hover"
              >
                <span className="truncate text-text">{node.name}</span>
                <span className="shrink-0 text-text-muted">{formatEntityTypeLabel(node.entity_type)}</span>
              </button>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}
