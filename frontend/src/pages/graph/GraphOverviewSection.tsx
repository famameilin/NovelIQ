import { motion } from "framer-motion";
import { Activity, History, Link2, Network } from "lucide-react";

import type { GraphData } from "@/api/types";
import { MetricCard } from "@/components/common/MetricCard";

interface GraphOverviewSectionProps {
  graphData: GraphData;
  activeRelationCount: number;
  inactiveRelationCount: number;
  graphDensity: number;
  loadedChangeCount: number;
  totalChangeCount: number;
  pageSectionVariants: {
    hidden: { opacity: number; y: number };
    visible: { opacity: number; y: number };
  };
}

// 2026-04-23，任务：复杂度与耦合审查 P1
// 把图谱页顶部指标卡与关系摘要区块拆出，减少 GraphPage 的渲染噪声
export function GraphOverviewSection({
  graphData,
  activeRelationCount,
  inactiveRelationCount,
  graphDensity,
  loadedChangeCount,
  totalChangeCount,
  pageSectionVariants,
}: GraphOverviewSectionProps) {
  return (
    <div className="space-y-4">
      <motion.section
        variants={pageSectionVariants}
        initial="hidden"
        animate="visible"
        transition={{ duration: 0.28, delay: 0.05 }}
        className="grid gap-4 md:grid-cols-2 xl:grid-cols-4"
      >
        <MetricCard
          label="图谱实体"
          value={graphData.nodes.length}
          format="raw"
          decimals={0}
          icon={<Network className="h-5 w-5" />}
          description="当前识别到的人物、组织与群体"
          accent="primary"
        />
        <MetricCard
          label="关系连线"
          value={activeRelationCount}
          format="raw"
          decimals={0}
          icon={<Link2 className="h-5 w-5" />}
          description="当前关系网络中的主要连接"
          accent="chart-2"
        />
        <MetricCard
          label="网络密度"
          value={graphDensity}
          format="raw"
          decimals={4}
          icon={<Activity className="h-5 w-5" />}
          description="关系是否集中在少数核心角色身上"
          accent="chart-4"
        />
        <MetricCard
          label="图谱变化"
          value={totalChangeCount}
          format="raw"
          decimals={0}
          icon={<History className="h-5 w-5" />}
          description={
            totalChangeCount > loadedChangeCount
              ? `已加载 ${loadedChangeCount} / ${totalChangeCount} 条变化记录`
              : "已加载全部图谱变化"
          }
          accent="chart-5"
        />
      </motion.section>

      <motion.p
        variants={pageSectionVariants}
        initial="hidden"
        animate="visible"
        transition={{ duration: 0.28, delay: 0.1 }}
        className="text-sm leading-6 text-text-muted"
      >
        当前快照固定在第 {graphData.chapter_order} 章（第 {graphData.first_chapter_id} 至 {graphData.last_chapter_id} 章），
        图版本为 {graphData.graph_version_id}。{inactiveRelationCount > 0 ? `另有 ${inactiveRelationCount} 条非活跃关系。` : ""}
      </motion.p>
    </div>
  );
}
