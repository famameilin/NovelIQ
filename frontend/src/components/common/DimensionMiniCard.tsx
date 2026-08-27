import { useRef } from "react";
import { motion, useInView } from "framer-motion";
import { Link } from "react-router-dom";
import {
  DashboardCardShell,
  getMetricAccentHoverTextClass,
  type MetricAccent,
} from "@/components/common/DashboardCardShell";
import {
  formatNullableNumber,
  formatSampleInsufficient,
} from "@/lib/metricFormat";
import { cn } from "@/lib/cn";

/* ------------------------------------------------------------------ */
/*  类型定义                                                           */
/* ------------------------------------------------------------------ */

export type DimensionType = "narrative" | "emotion" | "character" | "style" | "topic";

export interface DimensionData {
  middle_collapse_index?: number | null;
  lexical_pos_neg_ratio?: number | null;
  lexical_positive_density?: number | null;
  lexical_negative_density?: number | null;
  network_density?: number | null;
  string_token_diversity?: number | null;
  dialogue_ratio?: number | null;
  topic_count?: number | null;
  top_topics?: Array<{ words: string[]; weight: number }>;
}

export interface DimensionMiniCardProps {
  dimension: DimensionType;
  data: DimensionData;
  novelId: string;
  linkTo?: string;
  className?: string;
}

/* ------------------------------------------------------------------ */
/*  维度配置                                                           */
/* ------------------------------------------------------------------ */

const DIMENSION_CONFIG: Record<
  DimensionType,
  {
    label: string;
    accent: MetricAccent;
  }
> = {
  narrative: {
    label: "叙事结构",
    accent: "primary",
  },
  emotion: {
    label: "情绪指标",
    accent: "chart-2",
  },
  character: {
    label: "人物网络",
    accent: "chart-2",
  },
  style: {
    label: "语言风格",
    accent: "chart-4",
  },
  topic: {
    label: "主题内容",
    accent: "chart-2",
  },
};

/* ------------------------------------------------------------------ */
/*  叙事维度可视化（半圆仪表）                                         */
/* ------------------------------------------------------------------ */

function NarrativeVisualization({
  value,
  gradientId,
  accent = "chart-1",
}: {
  value: number | null | undefined;
  gradientId: string;
  accent?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true, margin: "-30px" });

  if (value === undefined || value === null) {
    return <EmptyState />;
  }

  const angle = (value / 1) * 180;
  const isWarning = value < 0.85;

  return (
    <div ref={ref} className="flex h-full w-full items-center justify-center">
      <svg viewBox="0 0 100 56" className="h-full w-full">
        <defs>
          <linearGradient id={gradientId} x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor={`hsl(var(--${accent}))`} stopOpacity="0.3" />
            <stop offset="100%" stopColor={`hsl(var(--${accent}))`} stopOpacity="0.8" />
          </linearGradient>
        </defs>

        <path
          d="M 10 50 A 40 40 0 0 1 90 50"
          fill="none"
          stroke="hsl(var(--border))"
          strokeWidth="5"
          strokeLinecap="round"
        />

        <motion.path
          d="M 10 50 A 40 40 0 0 1 90 50"
          fill="none"
          stroke={`url(#${gradientId})`}
          strokeWidth="5"
          strokeLinecap="round"
          initial={{ pathLength: 0 }}
          animate={{ pathLength: isInView ? 1 : 0 }}
          transition={{ duration: 0.8, ease: "easeOut" }}
        />

        <motion.line
          x1="50"
          y1="50"
          x2="50"
          y2="18"
          stroke={isWarning ? "hsl(var(--chart-negative))" : `hsl(var(--${accent}))`}
          strokeWidth="1.8"
          strokeLinecap="round"
          initial={{ rotate: -90 }}
          animate={{ rotate: isInView ? angle - 90 : -90 }}
          transition={{ duration: 0.8, ease: "easeOut" }}
          style={{ transformOrigin: "50px 50px" }}
        />

        <circle cx="50" cy="50" r="2.5" fill={isWarning ? "hsl(var(--chart-negative))" : `hsl(var(--${accent}))`} />

        <text
          x="50"
          y="45"
          textAnchor="middle"
          className="fill-text text-[10px] font-semibold"
        >
          {value.toFixed(2)}
        </text>
      </svg>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  情绪维度可视化（正负条形图）                                       */
/* ------------------------------------------------------------------ */

function EmotionVisualization({
  positiveDensity,
  negativeDensity,
}: {
  positiveDensity: number | null | undefined;
  negativeDensity: number | null | undefined;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true, margin: "-30px" });

  if (positiveDensity == null || negativeDensity == null) {
    return <EmptyState />;
  }

  const maxDensity = Math.max(positiveDensity, negativeDensity, 0.0001);
  const barHeight = 36;
  const barWidth = 16;

  return (
    <div ref={ref} className="flex h-full w-full items-center justify-center gap-2">
      <svg viewBox="0 0 50 48" className="h-full w-full">
        <text x="25" y="6" textAnchor="middle" className="fill-text-muted text-[8px]">
          正/负
        </text>

        <motion.rect
          x="8"
          y={44 - barHeight}
          width={barWidth}
          height={barHeight}
          fill="hsl(var(--chart-positive))"
          rx="2"
          initial={{ scaleY: 0 }}
          animate={{ scaleY: isInView ? Math.min(positiveDensity / maxDensity, 1) : 0 }}
          transition={{ duration: 0.5, ease: "easeOut" }}
          style={{ transformOrigin: `${8 + barWidth / 2}px 44px` }}
        />

        <motion.rect
          x={26}
          y={44 - barHeight}
          width={barWidth}
          height={barHeight}
          fill="hsl(var(--chart-negative))"
          rx="2"
          initial={{ scaleY: 0 }}
          animate={{ scaleY: isInView ? Math.min(negativeDensity / maxDensity, 1) : 0 }}
          transition={{ duration: 0.5, ease: "easeOut", delay: 0.1 }}
          style={{ transformOrigin: `${26 + barWidth / 2}px 44px` }}

        />
      </svg>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  角色维度可视化（迷你关系图）                                       */
/* ------------------------------------------------------------------ */

function CharacterVisualization({ density }: { density: number | null | undefined }) {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true, margin: "-30px" });

  if (density === undefined || density === null) {
    return <EmptyState />;
  }

  const nodeCount = Math.max(3, Math.min(7, Math.round(density * 20)));
  const nodes = Array.from({ length: nodeCount }, (_, i) => {
    const angle = (i / nodeCount) * Math.PI * 2 - Math.PI / 2;
    const radius = 18;
    return {
      x: 28 + Math.cos(angle) * radius,
      y: 28 + Math.sin(angle) * radius,
    };
  });

  return (
    <div ref={ref} className="flex h-full w-full items-center justify-center">
      <svg viewBox="0 0 56 56" className="h-full w-full">
        {nodes.map((node, i) =>
          nodes.slice(i + 1).map((target, j) => (
            <motion.line
              key={`line-${i}-${j}`}
              x1={node.x}
              y1={node.y}
              x2={target.x}
              y2={target.y}
              stroke="hsl(var(--chart-3) / 0.35)"
              strokeWidth="1"
              initial={{ opacity: 0 }}
              animate={{ opacity: isInView ? 1 : 0 }}
              transition={{ duration: 0.5, delay: (i + j) * 0.05 }}
            />
          ))
        )}

        {nodes.map((node, i) => (
          <motion.circle
            key={`node-${i}`}
            cx={node.x}
            cy={node.y}
            r="3.5"
            fill="hsl(var(--chart-3))"
            initial={{ scale: 0 }}
            animate={{ scale: isInView ? 1 : 0 }}
            transition={{ duration: 0.5, delay: i * 0.05 }}
          />
        ))}
      </svg>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  风格维度可视化（横向条形图）                                       */
/* ------------------------------------------------------------------ */

function StyleVisualization({
  stringTokenDiversity,
  dialogueRatio,
}: {
  stringTokenDiversity: number | null | undefined;
  dialogueRatio: number | null | undefined;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true, margin: "-30px" });

  if (stringTokenDiversity == null || dialogueRatio == null) {
    return <EmptyState />;
  }

  return (
    <div ref={ref} className="flex h-full w-full flex-col justify-center gap-2 px-1">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="w-6 text-[8px] text-text-muted">词汇</span>
          <div className="h-2 flex-1 overflow-hidden rounded-full bg-border">
            <motion.div
              className="h-full rounded-full bg-chart-4"
              initial={{ scaleX: 0 }}
              animate={{ scaleX: isInView ? Math.min(stringTokenDiversity, 1) : 0 }}
              transition={{ duration: 0.6, ease: "easeOut" }}
              style={{ transformOrigin: "left" }}
            />
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-6 text-[8px] text-text-muted">对话</span>
          <div className="h-2 flex-1 overflow-hidden rounded-full bg-border">
            <motion.div
              className="h-full rounded-full bg-chart-4/70"
              initial={{ scaleX: 0 }}
              animate={{ scaleX: isInView ? Math.min(dialogueRatio, 1) : 0 }}
              transition={{ duration: 0.6, ease: "easeOut", delay: 0.15 }}
              style={{ transformOrigin: "left" }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  主题维度可视化（主题标签）                                         */
/* ------------------------------------------------------------------ */

function TopicVisualization({
  topicCount,
  topTopics,
}: {
  topicCount: number | null | undefined;
  topTopics: Array<{ words: string[]; weight: number }> | undefined;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true, margin: "-30px" });

  if (!topicCount || !topTopics || topTopics.length === 0) {
    return <EmptyState />;
  }

  const validTopics = topTopics.filter((t) => t.words && t.words.length > 0);
  if (validTopics.length === 0) {
    return <EmptyState />;
  }

  return (
    <div ref={ref} className="flex h-full w-full flex-col items-center justify-center gap-1.5">
      <span className="text-[8px] text-text-muted">热门主题</span>
      <div className="flex flex-wrap items-center justify-center gap-1">
        {validTopics.slice(0, 3).map((topic, i) => (
          <motion.span
            key={i}
            className={cn(
              "inline-block rounded px-1.5 py-0.5 text-[9px] font-medium",
              "bg-chart-5/15 text-chart-5 border border-chart-5/20"
            )}
            style={{
              opacity: 0.7 + topic.weight * 0.3,
            }}
            initial={{ opacity: 0, scale: 0.8 }}
            animate={{ opacity: isInView ? 0.7 + topic.weight * 0.3 : 0, scale: isInView ? 1 : 0.8 }}
            transition={{ duration: 0.35, delay: i * 0.08 }}
          >
            {topic.words[0]}
          </motion.span>
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  空状态                                                             */
/* ------------------------------------------------------------------ */

function EmptyState() {
  return (
    <div className="flex h-full w-full items-center justify-center">
      <span className="text-[10px] text-text-muted">{formatSampleInsufficient()}</span>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  主组件                                                             */
/* ------------------------------------------------------------------ */

/**
 * 2026-04-21，任务：仪表盘组件视觉重构
 * 修改原因：让五维速览卡片直接复用共享卡片壳，和 MetricCard 保持统一的外观反馈
 */
export function DimensionMiniCard({
  dimension,
  data,
  novelId,
  linkTo,
  className,
}: DimensionMiniCardProps) {
  const config = DIMENSION_CONFIG[dimension];
  const gradientId = `narrative-gradient-${novelId}`;

  const renderVisualization = () => {
    switch (dimension) {
      case "narrative":
        return (
          <NarrativeVisualization
            value={data.middle_collapse_index}
            gradientId={gradientId}
            accent={config.accent}
          />
        );
      case "emotion":
        return (
          <EmotionVisualization
            positiveDensity={data.lexical_positive_density}
            negativeDensity={data.lexical_negative_density}
          />
        );
      case "character":
        return <CharacterVisualization density={data.network_density} />;
      case "style":
        return (
          <StyleVisualization
            stringTokenDiversity={data.string_token_diversity}
            dialogueRatio={data.dialogue_ratio}
          />
        );
      case "topic":
        return (
          <TopicVisualization
            topicCount={data.topic_count}
            topTopics={data.top_topics}
          />
        );
    }
  };

  const renderValue = () => {
    switch (dimension) {
      case "narrative":
        return formatNullableNumber(data.middle_collapse_index);
      case "emotion":
        return null;
      case "character":
        return formatNullableNumber(data.network_density);
      case "style":
        return data.string_token_diversity != null
          ? `${(data.string_token_diversity * 100).toFixed(0)}%`
          : formatSampleInsufficient();
      case "topic":
        return data.topic_count != null ? data.topic_count.toString() : formatSampleInsufficient();
    }
  };

  const renderValueLabel = () => {
    switch (dimension) {
      case "narrative":
        return "中段塌陷";
      case "emotion":
        return "正向密度 / 负向密度";
      case "character":
        return "关系集中度（度中心化）";
      case "style":
        return "词频广度";
      case "topic":
        return "主题数量";
    }
  };

  const renderLinkText = () => {
    switch (dimension) {
      case "narrative":
        return "→ 时间轴";
      case "emotion":
        return "→ 曲线页";
      case "character":
        return "→ 关系图谱";
      case "topic":
        return "→ 主题分布";
      default:
        return null;
    }
  };

  const content = (
    <DashboardCardShell
      title={config.label}
      accent={config.accent}
      className={cn("h-full", className)}
      contentClassName="gap-2.5 p-3.5"
      bodyClassName="gap-2.5"
      titleClassName="text-xs font-medium uppercase tracking-wide text-text-muted"
      footer={
        linkTo ? (
          <Link
            to={linkTo}
            className={cn(
              "inline-flex items-center gap-0.5 text-xs text-text-muted transition-colors",
              getMetricAccentHoverTextClass(config.accent)
            )}
          >
            {renderLinkText()}
          </Link>
        ) : undefined
      }
    >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            {dimension === "emotion" ? (
              <div className="space-y-1.5 pt-1">
                <div className="flex items-center justify-between gap-2 text-[10px] text-text-muted">
                  <span>正向密度</span>
                  <span className="font-medium tabular-nums text-text">
                    {formatNullableNumber(data.lexical_positive_density, 4)}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-2 text-[10px] text-text-muted">
                  <span>负向密度</span>
                  <span className="font-medium tabular-nums text-text">
                    {formatNullableNumber(data.lexical_negative_density, 4)}
                  </span>
                </div>
              </div>
            ) : (
              <>
                <p className="text-2xl font-bold tabular-nums text-text">{renderValue()}</p>
                <div className="mt-0.5 flex flex-wrap items-center gap-1.5">
                  <p className="text-[10px] text-text-muted">{renderValueLabel()}</p>
                </div>
              </>
            )}
          </div>
          <div className="flex h-12 w-[72px] flex-shrink-0 items-center justify-center">
            {renderVisualization()}
          </div>
        </div>
    </DashboardCardShell>
  );

  return content;
}
