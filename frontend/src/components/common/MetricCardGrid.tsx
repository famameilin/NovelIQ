import { motion } from "framer-motion";
import { Settings, Heart, Users, Palette, BookOpen } from "lucide-react";
import { MetricCard } from "@/components/common/MetricCard";
import { cn } from "@/lib/cn";
import type { MetricAccent } from "@/components/common/MetricCard";
import type {
  NarrativeStructureMetrics,
  EmotionStatsMetrics,
  CharacterStatsMetrics,
  StyleStatsMetrics,
  CultureStatsMetrics,
} from "@/api/types";

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

interface MetricDefinition {
  label: string;
  value: number;
  format: "number" | "percent" | "score";
  decimals: number;
  icon: React.ReactNode;
  accent: MetricAccent;
  description: string;
}

export interface MetricCardGridProps {
  narrative: NarrativeStructureMetrics;
  emotion: EmotionStatsMetrics;
  character: CharacterStatsMetrics;
  style: StyleStatsMetrics;
  culture: CultureStatsMetrics;
  className?: string;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

function buildMetrics(props: MetricCardGridProps): MetricDefinition[] {
  return [
    {
      label: "叙事结构",
      value: props.narrative.cliffhanger_rate,
      format: "percent",
      decimals: 1,
      icon: <Settings className="h-5 w-5" />,
      accent: "chart-1",
      description: "悬念保持率：章节以悬念结尾的比例，越高说明读者驱动越强",
    },
    {
      label: "情感统计",
      value: props.emotion.pivot_moment_density,
      format: "number",
      decimals: 3,
      icon: <Heart className="h-5 w-5" />,
      accent: "chart-2",
      description: "转折时刻密度：情感转折点在全文中的分布密度",
    },
    {
      label: "人物网络",
      value: props.character.network_density,
      format: "number",
      decimals: 3,
      icon: <Users className="h-5 w-5" />,
      accent: "chart-3",
      description: "网络密度：角色关系图谱的连接紧密程度",
    },
    {
      label: "风格指标",
      value: props.style.vocab_breadth,
      format: "number",
      decimals: 3,
      icon: <Palette className="h-5 w-5" />,
      accent: "chart-4",
      description: "词汇广度：词汇多样性的量化指标",
    },
    {
      label: "文化元素",
      value: props.culture.idiom_density,
      format: "number",
      decimals: 4,
      icon: <BookOpen className="h-5 w-5" />,
      accent: "chart-5",
      description: "成语密度：文本中成语使用的频率",
    },
  ];
}

/* ------------------------------------------------------------------ */
/*  Animation variants                                                 */
/* ------------------------------------------------------------------ */

const containerVariants = {
  hidden: {},
  show: {
    transition: {
      staggerChildren: 0.05,
    },
  },
};

const itemVariants = {
  hidden: { opacity: 0, y: 12 },
  show: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.4, ease: [0.16, 1, 0.3, 1] },
  },
};

/* ------------------------------------------------------------------ */
/*  Component                                                         */
/* ------------------------------------------------------------------ */

export function MetricCardGrid(props: MetricCardGridProps) {
  const metrics = buildMetrics(props);

  return (
    <motion.div
      className={cn(
        "grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-5",
        props.className,
      )}
      variants={containerVariants}
      initial="hidden"
      animate="show"
    >
      {metrics.map((m) => (
        <motion.div key={m.label} variants={itemVariants}>
          <MetricCard
            label={m.label}
            value={m.value}
            format={m.format}
            decimals={m.decimals}
            icon={m.icon}
            accent={m.accent}
            description={m.description}
            showBar
          />
        </motion.div>
      ))}
    </motion.div>
  );
}
