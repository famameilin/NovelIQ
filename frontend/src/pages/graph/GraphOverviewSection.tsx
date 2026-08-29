import { motion } from "framer-motion";
import { Activity, History, Link2, Network, Sigma } from "lucide-react";

import type { GraphAlgorithmMetrics, GraphData } from "@/api/types";
import { MetricCard } from "@/components/common/MetricCard";

interface GraphOverviewSectionProps {
  graphData: GraphData;
  activeRelationCount: number;
  inactiveRelationCount: number;
  graphDensity: number;
  loadedChangeCount: number;
  totalChangeCount: number;
  graphMetrics: GraphAlgorithmMetrics | null;
  pageSectionVariants: {
    hidden: { opacity: number; y: number };
    visible: { opacity: number; y: number };
  };
}

/** PageRank Top-N 列表（图结构信号，不解释为人物重要性结论） */
function PagerankList({ metrics }: { metrics: GraphAlgorithmMetrics }) {
  const topEntries = Object.entries(metrics.pagerank)
    .sort((left, right) => right[1] - left[1])
    .slice(0, 5);
  const maxScore = topEntries.length > 0 ? topEntries[0][1] : 0;

  if (topEntries.length === 0) {
    return <p className="py-4 text-center text-sm text-text-muted">暂无 PageRank 数据</p>;
  }

  return (
    <ul className="space-y-2">
      {topEntries.map(([name, score]) => (
        <li key={name} className="flex items-center gap-3">
          <span className="w-24 shrink-0 truncate text-sm text-text">{name}</span>
          <div className="h-2 min-w-0 flex-1 overflow-hidden rounded-full bg-surface-hover">
            <div
              className="h-full rounded-full bg-chart-2"
              style={{ width: `${maxScore > 0 ? (score / maxScore) * 100 : 0}%` }}
            />
          </div>
          <span className="w-20 shrink-0 text-right text-xs text-text-muted">{score.toFixed(4)}</span>
        </li>
      ))}
    </ul>
  );
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
  graphMetrics,
  pageSectionVariants,
}: GraphOverviewSectionProps) {
  const communityIds = graphMetrics?.communities?.community_ids as Record<string, number> | undefined;
  const communityCount = communityIds ? new Set(Object.values(communityIds)).size : 0;
  const modularity = graphMetrics?.communities?.modularity;

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
          label="关系集中度"
          value={graphDensity}
          format="raw"
          decimals={4}
          icon={<Activity className="h-5 w-5" />}
          description="度中心化口径：关系是否集中在少数核心角色身上"
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
        当前章节边界为第 {graphData.chapter_order} 章（第 {graphData.first_chapter_id} 至 {graphData.last_chapter_id} 章）。
        {inactiveRelationCount > 0 ? `另有 ${inactiveRelationCount} 条非活跃关系。` : ""}
      </motion.p>

      <motion.section
        variants={pageSectionVariants}
        initial="hidden"
        animate="visible"
        transition={{ duration: 0.28, delay: 0.15 }}
        className="grid gap-4 lg:grid-cols-2"
      >
        <div className="rounded-2xl border border-border/60 bg-surface/70 p-4">
          <div className="mb-3 flex items-center gap-2">
            <Sigma className="h-4 w-4 text-chart-2" />
            <h3 className="text-sm font-medium text-text">PageRank Top-5（图结构信号）</h3>
          </div>
          {graphMetrics && !graphMetrics.unavailable_reason ? (
            <PagerankList metrics={graphMetrics} />
          ) : (
            <p className="py-4 text-center text-sm text-text-muted">
              {graphMetrics?.unavailable_reason ?? "图结构指标暂不可用"}
            </p>
          )}
        </div>

        <div className="rounded-2xl border border-border/60 bg-surface/70 p-4">
          <h3 className="mb-3 text-sm font-medium text-text">结构社区（Louvain）</h3>
          {graphMetrics && !graphMetrics.unavailable_reason ? (
            <dl className="space-y-2 text-sm">
              <div className="flex justify-between">
                <dt className="text-text-muted">社区数量</dt>
                <dd className="font-medium text-text">{communityCount}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-text-muted">模块度</dt>
                <dd className="font-medium text-text">
                  {typeof modularity === "number" ? modularity.toFixed(4) : "—"}
                </dd>
              </div>
              <p className="pt-2 text-xs leading-5 text-text-muted">
                结构社区仅表示关系网络的连接紧密程度，不直接等同于故事阵营。
              </p>
            </dl>
          ) : (
            <p className="py-4 text-center text-sm text-text-muted">
              {graphMetrics?.unavailable_reason ?? "社区发现暂不可用"}
            </p>
          )}
        </div>
      </motion.section>
    </div>
  );
}
