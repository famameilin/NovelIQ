import { useRef } from "react";
import { motion, useInView } from "framer-motion";
import { Link } from "react-router-dom";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/cn";

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

export type DimensionType = "narrative" | "emotion" | "character" | "style" | "topic";

export interface DimensionData {
  middle_collapse_index?: number;
  pos_neg_ratio?: number;
  positive_ratio?: number;
  negative_ratio?: number;
  network_density?: number;
  vocab_breadth?: number;
  dialogue_ratio?: number;
  topic_count?: number;
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
/*  Dimension Config                                                  */
/* ------------------------------------------------------------------ */

const DIMENSION_CONFIG: Record<
  DimensionType,
  {
    label: string;
    accent: string;
    gradientEnd: string;
    hoverBorder: string;
  }
> = {
  narrative: {
    label: "叙事结构",
    accent: "chart-1",
    gradientEnd: "to-chart-1/15",
    hoverBorder: "hover:border-chart-1/30",
  },
  emotion: {
    label: "情感基调",
    accent: "chart-2",
    gradientEnd: "to-chart-2/15",
    hoverBorder: "hover:border-chart-2/30",
  },
  character: {
    label: "人物网络",
    accent: "chart-3",
    gradientEnd: "to-chart-3/15",
    hoverBorder: "hover:border-chart-3/30",
  },
  style: {
    label: "语言风格",
    accent: "chart-4",
    gradientEnd: "to-chart-4/15",
    hoverBorder: "hover:border-chart-4/30",
  },
  topic: {
    label: "主题内容",
    accent: "chart-5",
    gradientEnd: "to-chart-5/15",
    hoverBorder: "hover:border-chart-5/30",
  },
};

/* ------------------------------------------------------------------ */
/*  Narrative Visualization (Semi-circular Gauge)                     */
/* ------------------------------------------------------------------ */

function NarrativeVisualization({
  value,
  gradientId,
}: {
  value: number | undefined;
  gradientId: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true, margin: "-30px" });

  if (value === undefined || value === null) {
    return <EmptyState />;
  }

  const angle = (value / 1) * 180;
  const isWarning = value < 0.85;

  return (
    <div ref={ref} className="h-16 w-24">
      <svg viewBox="0 0 100 60" className="h-full w-full">
        <defs>
          <linearGradient id={gradientId} x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="hsl(var(--chart-1))" stopOpacity="0.3" />
            <stop offset="100%" stopColor="hsl(var(--chart-1))" stopOpacity="0.8" />
          </linearGradient>
        </defs>
        
        <path
          d="M 10 55 A 40 40 0 0 1 90 55"
          fill="none"
          stroke="hsl(var(--border))"
          strokeWidth="6"
          strokeLinecap="round"
        />
        
        <motion.path
          d="M 10 55 A 40 40 0 0 1 90 55"
          fill="none"
          stroke={`url(#${gradientId})`}
          strokeWidth="6"
          strokeLinecap="round"
          initial={{ pathLength: 0 }}
          animate={{ pathLength: isInView ? 1 : 0 }}
          transition={{ duration: 0.8, ease: "easeOut" }}
        />
        
        <motion.line
          x1="50"
          y1="55"
          x2="50"
          y2="20"
          stroke={isWarning ? "hsl(var(--chart-negative))" : "hsl(var(--chart-1))"}
          strokeWidth="2"
          strokeLinecap="round"
          initial={{ rotate: -90 }}
          animate={{ rotate: isInView ? angle - 90 : -90 }}
          transition={{ duration: 0.8, ease: "easeOut" }}
          style={{ transformOrigin: "50px 55px" }}
        />
        
        <circle cx="50" cy="55" r="3" fill={isWarning ? "hsl(var(--chart-negative))" : "hsl(var(--chart-1))"} />
        
        <text
          x="50"
          y="50"
          textAnchor="middle"
          className="fill-text text-[10px] font-bold"
        >
          {value.toFixed(2)}
        </text>
      </svg>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Emotion Visualization (Positive/Negative Bar Chart)               */
/* ------------------------------------------------------------------ */

function EmotionVisualization({
  positiveRatio,
  negativeRatio,
}: {
  positiveRatio: number | undefined;
  negativeRatio: number | undefined;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true, margin: "-30px" });

  if (positiveRatio === undefined || negativeRatio === undefined) {
    return <EmptyState />;
  }

  const maxHeight = 40;

  return (
    <div ref={ref} className="h-12 w-20">
      <svg viewBox="0 0 80 50" className="h-full w-full">
        <motion.rect
          x="15"
          y={50 - maxHeight}
          width="20"
          height={maxHeight}
          fill="hsl(var(--chart-positive))"
          rx="2"
          initial={{ scaleY: 0 }}
          animate={{ scaleY: isInView ? positiveRatio : 0 }}
          transition={{ duration: 0.5, ease: "easeOut" }}
          style={{ transformOrigin: "25px 50px" }}
        />
        
        <motion.rect
          x="45"
          y={50 - maxHeight}
          width="20"
          height={maxHeight}
          fill="hsl(var(--chart-negative))"
          rx="2"
          initial={{ scaleY: 0 }}
          animate={{ scaleY: isInView ? negativeRatio : 0 }}
          transition={{ duration: 0.5, ease: "easeOut", delay: 0.1 }}
          style={{ transformOrigin: "55px 50px" }}
        />
        
        <text x="25" y="48" textAnchor="middle" className="fill-text-muted text-[8px]">
          正
        </text>
        <text x="55" y="48" textAnchor="middle" className="fill-text-muted text-[8px]">
          负
        </text>
      </svg>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Character Visualization (Mini Network Graph)                      */
/* ------------------------------------------------------------------ */

function CharacterVisualization({ density }: { density: number | undefined }) {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true, margin: "-30px" });

  if (density === undefined || density === null) {
    return <EmptyState />;
  }

  const nodeCount = Math.max(3, Math.min(7, Math.round(density * 20)));
  const nodes = Array.from({ length: nodeCount }, (_, i) => {
    const angle = (i / nodeCount) * Math.PI * 2 - Math.PI / 2;
    const radius = 16;
    return {
      x: 24 + Math.cos(angle) * radius,
      y: 24 + Math.sin(angle) * radius,
    };
  });

  return (
    <div ref={ref} className="h-12 w-12">
      <svg viewBox="0 0 48 48" className="h-full w-full">
        {nodes.map((node, i) =>
          nodes.slice(i + 1).map((target, j) => (
            <motion.line
              key={`line-${i}-${j}`}
              x1={node.x}
              y1={node.y}
              x2={target.x}
              y2={target.y}
              stroke="hsl(var(--chart-3) / 0.3)"
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
            r="3"
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
/*  Style Visualization (Horizontal Bar Chart)                        */
/* ------------------------------------------------------------------ */

function StyleVisualization({
  vocabBreadth,
  dialogueRatio,
}: {
  vocabBreadth: number | undefined;
  dialogueRatio: number | undefined;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true, margin: "-30px" });

  if (vocabBreadth === undefined || dialogueRatio === undefined) {
    return <EmptyState />;
  }

  return (
    <div ref={ref} className="flex h-16 w-20 flex-col justify-center gap-1.5">
      <div className="space-y-0.5">
        <div className="h-1.5 overflow-hidden rounded-full bg-border">
          <motion.div
            className="h-full rounded-full bg-chart-4"
            initial={{ scaleX: 0 }}
            animate={{ scaleX: isInView ? Math.min(vocabBreadth, 1) : 0 }}
            transition={{ duration: 0.5, ease: "easeOut" }}
            style={{ transformOrigin: "left" }}
          />
        </div>
        <div className="h-1.5 overflow-hidden rounded-full bg-border">
          <motion.div
            className="h-full rounded-full bg-chart-4/70"
            initial={{ scaleX: 0 }}
            animate={{ scaleX: isInView ? Math.min(dialogueRatio, 1) : 0 }}
            transition={{ duration: 0.5, ease: "easeOut", delay: 0.1 }}
            style={{ transformOrigin: "left" }}
          />
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Topic Visualization (Topic Tags)                                  */
/* ------------------------------------------------------------------ */

function TopicVisualization({
  topicCount,
  topTopics,
}: {
  topicCount: number | undefined;
  topTopics: Array<{ words: string[]; weight: number }> | undefined;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true, margin: "-30px" });

  if (!topicCount || !topTopics || topTopics.length === 0) {
    return <EmptyState />;
  }

  return (
    <div ref={ref} className="flex h-16 w-20 flex-wrap items-center justify-center gap-1">
      {topTopics.slice(0, 3).map((topic, i) => (
        <motion.span
          key={i}
          className={cn(
            "inline-block rounded px-1.5 py-0.5 text-[9px]",
            "bg-chart-5/20 text-chart-5"
          )}
          style={{
            opacity: 0.7 + topic.weight * 0.3,
          }}
          initial={{ opacity: 0, scale: 0.8 }}
          animate={{ opacity: isInView ? 0.7 + topic.weight * 0.3 : 0, scale: isInView ? 1 : 0.8 }}
          transition={{ duration: 0.3, delay: i * 0.1 }}
        >
          {topic.words[0]}
        </motion.span>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Empty State                                                       */
/* ------------------------------------------------------------------ */

function EmptyState() {
  return (
    <div className="flex h-16 w-full items-center justify-center">
      <span className="text-xs text-text-muted">暂无数据</span>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main Component                                                    */
/* ------------------------------------------------------------------ */

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
          />
        );
      case "emotion":
        return (
          <EmotionVisualization
            positiveRatio={data.positive_ratio}
            negativeRatio={data.negative_ratio}
          />
        );
      case "character":
        return <CharacterVisualization density={data.network_density} />;
      case "style":
        return (
          <StyleVisualization
            vocabBreadth={data.vocab_breadth}
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
        return data.middle_collapse_index?.toFixed(2) ?? "—";
      case "emotion":
        return data.pos_neg_ratio?.toFixed(2) ?? "—";
      case "character":
        return data.network_density?.toFixed(2) ?? "—";
      case "style":
        return data.vocab_breadth !== undefined
          ? `${(data.vocab_breadth * 100).toFixed(0)}%`
          : "—";
      case "topic":
        return data.topic_count?.toString() ?? "—";
    }
  };

  const renderValueLabel = () => {
    switch (dimension) {
      case "narrative":
        return "中段塌陷";
      case "emotion":
        return "正负词比";
      case "character":
        return "网络密度";
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
    <Card
      variant="elevated"
      className={cn(
        "relative rounded-xl p-4 transition-all duration-300",
        "bg-gradient-to-br from-surface via-surface",
        config.gradientEnd,
        config.hoverBorder,
        "hover:-translate-y-1 hover:shadow-lg",
        className
      )}
    >
      <div className="space-y-3">
        <p className="text-xs font-medium uppercase tracking-wide text-text-muted">
          {config.label}
        </p>

        <div className="flex items-start justify-between">
          <div>
            <p className="text-2xl font-bold tabular-nums text-text">
              {renderValue()}
            </p>
            <p className="mt-0.5 text-[10px] text-text-muted">{renderValueLabel()}</p>
          </div>
          <div className="flex-shrink-0">{renderVisualization()}</div>
        </div>

        {linkTo && (
          <Link
            to={linkTo}
            className="inline-block text-xs text-text-muted transition-colors hover:text-primary"
          >
            {renderLinkText()}
          </Link>
        )}
      </div>
    </Card>
  );

  return content;
}
