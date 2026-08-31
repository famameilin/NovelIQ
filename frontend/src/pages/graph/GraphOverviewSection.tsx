import { motion } from "framer-motion";
import { Sigma, UsersRound } from "lucide-react";

import type { GraphAlgorithmMetrics, GraphData } from "@/api/types";
import { AnalysisDetails } from "@/components/common/AnalysisDetails";
import { AnalysisMetricStrip } from "@/components/common/AnalysisMetricStrip";

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
    return <p className="py-4 text-center text-sm text-text-muted">暂无关系中心度数据</p>;
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
        className="block"
      >
        <AnalysisMetricStrip
          items={[
            { label: "图谱实体", value: graphData.nodes.length, description: "人物、地点、组织与物品" },
            { label: "有效关系", value: activeRelationCount, description: "当前仍然成立的关系" },
            {
              label: "关系密度",
              value: graphDensity.toFixed(4),
              description: "有效关系占全部可能连接的比例",
            },
            {
              label: "关系变化",
              value: totalChangeCount,
              description:
                totalChangeCount > loadedChangeCount
                  ? `已加载 ${loadedChangeCount} / ${totalChangeCount} 条`
                  : "变化记录已全部加载",
            },
          ]}
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
        className="block"
      >
        <AnalysisDetails description="关系中心度、关系群组、群组区分度与非活跃关系均保留在此">
          <div className="grid grid-cols-2 gap-6">
            <section>
              <div className="mb-3 flex items-center gap-2">
                <Sigma className="h-4 w-4 text-chart-2" aria-hidden="true" />
                <h3 className="text-sm font-medium text-text">关系中心度前五</h3>
              </div>
              {graphMetrics && !graphMetrics.unavailable_reason ? (
                <PagerankList metrics={graphMetrics} />
              ) : (
                <p className="py-4 text-sm text-text-muted">当前快照暂时无法计算关系中心度</p>
              )}
            </section>

            <section>
              <div className="mb-3 flex items-center gap-2">
                <UsersRound className="h-4 w-4 text-chart-4" aria-hidden="true" />
                <h3 className="text-sm font-medium text-text">关系群组</h3>
              </div>
              {graphMetrics && !graphMetrics.unavailable_reason ? (
                <dl className="space-y-3 text-sm">
                  <div className="flex justify-between gap-4">
                    <dt className="text-text-muted">群组数量</dt>
                    <dd className="font-medium text-text">{communityCount}</dd>
                  </div>
                  <div className="flex justify-between gap-4">
                    <dt className="text-text-muted">群组区分度</dt>
                    <dd className="font-medium text-text">
                      {typeof modularity === "number" ? modularity.toFixed(4) : "—"}
                    </dd>
                  </div>
                  <div className="flex justify-between gap-4">
                    <dt className="text-text-muted">已经结束的关系</dt>
                    <dd className="font-medium text-text">{inactiveRelationCount}</dd>
                  </div>
                  <p className="pt-1 text-xs leading-5 text-text-muted">
                    关系群组只表示连接紧密程度，不直接等同于故事阵营
                  </p>
                </dl>
              ) : (
                <p className="py-4 text-sm text-text-muted">当前快照暂时无法识别关系群组</p>
              )}
            </section>
          </div>
        </AnalysisDetails>
      </motion.section>
    </div>
  );
}
