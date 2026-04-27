/**
 * TimelineTrack - 叙事时间轴主视图组件
 *
 * 创建时间: 2026-04-05
 * 创建者: GLM-5
 * 任务: Phase 2-B 叙事时间轴
 * 说明: 横向时间轴轨道，包含节点和连接线
 *
 * 修改时间: 2026-04-21
 * 任务: 重设计叙事时间轴主视觉
 * 修改内容:
 *   - 将单线点阵改为“阶段背景 + 节奏底图 + 上下分层节点”的叙事视图
 *   - 让密集节点通过多层车道避让，减少右侧拥挤和横向滚动依赖
 *   - 为每个节点补上短标签与引导线，真正占用下半区表达信息
 *
 * 修改时间: 2026-04-21
 * 任务: 优化时间轴密集节点的可读性
 * 修改内容:
 *   - 为主轨道增加横向滚动容器，让密集节点优先展开而不是硬挤
 *   - 放大画布宽度和首尾安全边距，减少节点与标签贴边感
 *   - 为滚动区域补充底部留白，让滚动条和时间轴内容更易区分
 *
 * 修改时间: 2026-04-21
 * 任务: 修复时间轴滚动后的背景与圆角表现
 * 修改内容:
 *   - 将阶段背景与张力底图并入可滚动画布，确保随时间轴宽度一起延展
 *   - 恢复滚动主图区的圆角裁切，避免出现生硬直角块面
 *   - 统一滚动画布的背景层，减少前景滚动与背景静止的割裂感
 *
 * 修改时间: 2026-04-21
 * 任务: 第一版节点贴合张力曲线
 * 修改内容:
 *   - 节点圆点按 progress 插值吸附到张力曲线，增强事件与节奏的对应关系
 *   - 保留标签分层避让，仅让锚点贴线，避免密集区瞬间失去可读性
 *   - 收紧图例与主图之间的外部间隙，同时在轨道内部补一点上下呼吸空间
 *
 * 修改时间: 2026-04-21
 * 任务: 第二版时间轴主轴视觉收敛
 * 修改内容:
 *   - 移除中部旧基线，让张力曲线直接承担时间轴主轴角色
 *   - 将张力曲线提升到画布中段，节点围绕曲线分布而不是落在下半区
 *   - 将内部留白转移为色块与上下标签卡之间的呼吸空间，减少无效空白
 *
 * 修改时间: 2026-04-22
 * 任务: 收紧时间轴底部空白
 * 修改内容:
 *   - 收紧主画布高度与阶段底边，减少下方无效空带
 *   - 让张力底图更贴近底部，同时缩小底部说明行与主图之间的间距
 *
 * 修改时间: 2026-04-22
 * 任务: 回收时间轴底部文字区空间
 * 修改内容:
 *   - 移除底部“开篇/叙事张力逐步累积/结尾”文字区，将高度回灌给主画布
 *   - 适当放宽下方标签卡的容纳高度，避免底部节点卡被裁切
 *
 * 修改时间: 2026-04-22
 * 任务: 收紧时间轴整体卡片高度
 * 修改内容:
 *   - 缩小顶部保留区与外层内边距，减少主图上方无效空白
 *   - 轻微压缩主画布高度，让整块时间轴卡片更紧凑
 *
 * 修改时间: 2026-04-23
 * 任务: 复杂度与耦合审查 P1
 * 修改内容:
 *   - 拆分布局计算与 SVG path 生成纯函数
 *   - TimelineTrack 只保留视图编排职责，并补纯函数测试
 */

import { motion } from "framer-motion";
import { useCallback, useMemo } from "react";

import type { TimelineCompositeNode, TimelineNode as TimelineNodeType } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";

import { TimelineNode } from "./TimelineNode";
import {
  calculateCanvasMinWidth,
  calculateNodeAnchorX,
  calculateNodeAnchorY,
  createTimelineLayoutNodes,
  getClampedLabelLeftPx,
  getLabelTopPx,
  GUIDE_LINE_OFFSET_X_PX,
  GUIDE_LINE_OFFSET_Y_PX,
  LABEL_HEIGHT_PX,
  NODE_RENDER_OFFSET_X_PX,
  NODE_RENDER_OFFSET_Y_PX,
  PHASE_BAND_BOTTOM_PX,
  PHASE_BAND_TOP_PX,
} from "./timelineTrackLayout";
import { getTimelineNodePresentation } from "./timelineNodePresentation";
import { buildTensionAreaPath, TRACK_HEIGHT_PX } from "./timelineTrackPaths";

type TimelineDisplayNode = TimelineNodeType | TimelineCompositeNode;

export interface TimelineTrackProps {
  nodes: TimelineDisplayNode[];
  phases?: { name: string; start: number; end: number; ratio: number }[];
  activePhase?: string;
  selectedNodeId?: string;
  onNodeClick?: (node: TimelineDisplayNode) => void;
  className?: string;
  tensionCurve?: number[];
  totalChunks?: number;
  showTension?: boolean;
}

const PHASE_SURFACE_CLASS_MAP: Record<string, string> = {
  引入期: "from-chart-1/12 to-chart-1/4",
  发展期: "from-chart-2/12 to-chart-2/4",
  高潮期: "from-chart-3/12 to-chart-3/4",
  收束期: "from-chart-4/12 to-chart-4/4",
};

export function TimelineTrack({
  nodes,
  phases,
  activePhase,
  selectedNodeId,
  onNodeClick,
  className,
  tensionCurve,
  totalChunks = 0,
  showTension = true,
}: TimelineTrackProps) {
  const highlightedRange = useMemo(() => {
    if (!activePhase || !phases) return null;
    const phase = phases.find((item) => item.name === activePhase);
    return phase ? ([phase.start, phase.end] as [number, number]) : null;
  }, [activePhase, phases]);

  const isNodeInHighlight = useCallback(
    (node: TimelineDisplayNode): boolean => {
      if (!highlightedRange) return false;
      return node.anchor_chunk_id >= highlightedRange[0] && node.anchor_chunk_id <= highlightedRange[1];
    },
    [highlightedRange]
  );

  const sortedNodes = useMemo(() => [...(nodes || [])].sort((a, b) => a.progress - b.progress), [nodes]);
  const canvasMinWidth = useMemo(() => calculateCanvasMinWidth(sortedNodes.length, totalChunks), [sortedNodes.length, totalChunks]);
  const layoutNodes = useMemo(() => createTimelineLayoutNodes(sortedNodes, canvasMinWidth), [canvasMinWidth, sortedNodes]);

  const tensionPath = useMemo(() => {
    if (!showTension || !tensionCurve || tensionCurve.length === 0) {
      return null;
    }
    return buildTensionAreaPath(tensionCurve, totalChunks, canvasMinWidth);
  }, [canvasMinWidth, showTension, tensionCurve, totalChunks]);

  const phaseLayouts = useMemo(() => {
    if (!phases || phases.length === 0) return [];

    let accumulatedRatio = 0;
    return phases.map((phase, index) => {
      const left = accumulatedRatio * canvasMinWidth;
      accumulatedRatio += phase.ratio;
      const rawRight = index === phases.length - 1 ? canvasMinWidth : accumulatedRatio * canvasMinWidth;
      return {
        ...phase,
        left,
        width: Math.max(rawRight - left, 0),
      };
    });
  }, [canvasMinWidth, phases]);

  return (
    <div className={cn("relative overflow-hidden rounded-[28px] border border-border/70 bg-background/80", className)}>
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(255,255,255,0.8),transparent_45%),linear-gradient(180deg,rgba(255,255,255,0.92),rgba(247,240,236,0.76))]" />

      <div className="relative pb-3 pt-2">
        <div className="flex flex-wrap items-center justify-between gap-3 px-5">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline" className="border-border/70 bg-background/85 text-text">
              {sortedNodes.length} 个可见节点
            </Badge>
            <Badge variant="outline" className="border-border/70 bg-background/85 text-text-muted">
              曲线表示叙事主轴
            </Badge>
            {showTension ? (
              <Badge variant="outline" className="border-border/70 bg-background/85 text-text-muted">
                底图表示节奏张力
              </Badge>
            ) : null}
          </div>
          <div className="text-xs text-text-muted">点击节点可在下方查看完整叙事细节</div>
        </div>

        <div className="overflow-x-auto overflow-y-hidden px-2 pb-2">
          <div className="w-max min-w-full">
            <div
              className="relative overflow-hidden rounded-[24px] border border-white/60 bg-[radial-gradient(circle_at_top_left,rgba(255,255,255,0.72),transparent_42%),linear-gradient(180deg,rgba(255,255,255,0.7),rgba(247,240,236,0.4))]"
              style={{ minWidth: `${canvasMinWidth}px` }}
            >
              {phaseLayouts.map((phase) => {
                const isActive = activePhase === phase.name;
                return (
                  <div
                    key={phase.name}
                    className={cn(
                      "absolute rounded-[24px] border border-white/70 bg-gradient-to-b",
                      PHASE_SURFACE_CLASS_MAP[phase.name] ?? "from-primary/12 to-primary/4",
                      isActive && "shadow-[0_0_0_2px_rgba(255,255,255,0.75)]"
                    )}
                    style={{
                      left: `${phase.left}px`,
                      width: `${phase.width}px`,
                      top: `${PHASE_BAND_TOP_PX}px`,
                      bottom: `${PHASE_BAND_BOTTOM_PX}px`,
                    }}
                  />
                );
              })}

              {tensionPath && (
                <svg
                  className="pointer-events-none absolute inset-0"
                  viewBox={`0 0 ${canvasMinWidth} ${TRACK_HEIGHT_PX}`}
                  preserveAspectRatio="none"
                >
                  <defs>
                    <linearGradient id="timeline-tension-fill" x1="0" x2="0" y1="0" y2="1">
                      <stop offset="0%" stopColor="rgba(191, 110, 52, 0.22)" />
                      <stop offset="100%" stopColor="rgba(191, 110, 52, 0.02)" />
                    </linearGradient>
                  </defs>
                  <path d={tensionPath.areaPath} fill="url(#timeline-tension-fill)" />
                  <path
                    d={tensionPath.linePath}
                    fill="none"
                    stroke="rgba(171, 98, 44, 0.7)"
                    strokeWidth="2.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              )}

              <div className="relative" style={{ height: `${TRACK_HEIGHT_PX}px`, minWidth: `${canvasMinWidth}px` }}>
                {layoutNodes.map((layoutNode, index) => {
                  const { node, lane, labelWidth } = layoutNode;
                  const anchorX = calculateNodeAnchorX(node.progress, canvasMinWidth);
                  const anchorY = calculateNodeAnchorY(node.progress, lane, {
                    showTension,
                    tensionCurve,
                    totalChunks,
                  });
                  const calibratedAnchorX = anchorX + NODE_RENDER_OFFSET_X_PX;
                  const calibratedAnchorY = anchorY + NODE_RENDER_OFFSET_Y_PX;
                  const guideLineX = calibratedAnchorX + GUIDE_LINE_OFFSET_X_PX;
                  const guideLineY = calibratedAnchorY + GUIDE_LINE_OFFSET_Y_PX;
                  const labelTop = getLabelTopPx(anchorY, lane);
                  const labelLeft = getClampedLabelLeftPx(anchorX, labelWidth, canvasMinWidth);
                  const labelAnchorY = lane < 0 ? labelTop + LABEL_HEIGHT_PX : labelTop;
                  const presentationSubtype = "node_subtype" in node ? node.node_subtype : (node.node_subtypes[0] ?? "plot");
                  const presentation = getTimelineNodePresentation(node.node_type, presentationSubtype);
                  const isSelected = selectedNodeId === node.node_id;
                  const isHighlighted = isNodeInHighlight(node);
                  const chunkLabel =
                    "start_chunk_id" in node && node.start_chunk_id !== node.end_chunk_id
                      ? `Chunk ${node.start_chunk_id}-${node.end_chunk_id}`
                      : `Chunk ${node.anchor_chunk_id}`;

                  return (
                    <div key={node.node_id}>
                      <motion.div
                        className={cn(
                          "absolute w-px bg-border/80",
                          isSelected && "bg-primary/70",
                          isHighlighted && !isSelected && "bg-chart-4/70"
                        )}
                        style={{
                          left: `${guideLineX}px`,
                          top: `${Math.min(guideLineY, labelAnchorY)}px`,
                          height: `${Math.max(Math.abs(labelAnchorY - guideLineY), 2)}px`,
                        }}
                        initial={{ scaleY: 0, opacity: 0.3 }}
                        animate={{ scaleY: 1, opacity: 1 }}
                        transition={{ duration: 0.25, delay: index * 0.03 }}
                      />

                      <motion.button
                        type="button"
                        className={cn(
                          "absolute z-[5] flex items-start gap-2 rounded-2xl border px-3 py-2 text-left shadow-sm backdrop-blur-sm transition-all",
                          "hover:-translate-y-0.5 hover:shadow-md",
                          isSelected
                            ? "border-primary/35 bg-primary/10 shadow-[0_12px_30px_rgba(161,90,43,0.16)]"
                            : "border-white/80 bg-background/88 hover:border-border/80",
                          isHighlighted && !isSelected && "border-chart-4/35 bg-chart-4/8"
                        )}
                        style={{
                          left: `${labelLeft}px`,
                          top: `${labelTop}px`,
                          width: `${labelWidth}px`,
                        }}
                        onClick={() => onNodeClick?.(node)}
                      >
                        <div
                          className={cn(
                            "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border",
                            presentation.dotClassName
                          )}
                        >
                          <presentation.icon className={cn("h-3.5 w-3.5", presentation.iconClassName)} />
                        </div>
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span className="text-[11px] font-semibold text-text">{presentation.label}</span>
                            <span className="text-[11px] text-text-muted">{chunkLabel}</span>
                          </div>
                          <p className="mt-1 line-clamp-2 text-xs leading-5 text-text">{node.summary}</p>
                          {"child_node_ids" in node && node.child_node_ids.length > 1 ? (
                            <p className="mt-1 text-[11px] text-text-muted">
                              聚合 {node.child_node_ids.length} 个原子节点
                            </p>
                          ) : null}
                        </div>
                      </motion.button>

                      <TimelineNode
                        node={node}
                        baselineY={calibratedAnchorY}
                        position={`${calibratedAnchorX}px`}
                        verticalOffset={0}
                        isSelected={isSelected}
                        isHighlighted={isHighlighted}
                        onClick={() => onNodeClick?.(node)}
                      />
                    </div>
                  );
                })}

                {layoutNodes.length === 0 ? (
                  <div className="flex h-full items-center justify-center text-sm text-text-muted">暂无时间轴节点</div>
                ) : null}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
