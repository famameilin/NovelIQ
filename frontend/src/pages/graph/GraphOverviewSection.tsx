import { motion } from "framer-motion";
import { Activity, AlertTriangle, History, Link2, Network, Sparkles, Users } from "lucide-react";

import type { GraphEdge, GraphPageSummary } from "@/api/types";
import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import { MetricCard } from "@/components/common/MetricCard";
import { Badge } from "@/components/ui/badge";

interface GraphOverviewSectionProps {
  graphSummary: GraphPageSummary | null;
  activeRelationCount: number;
  inactiveRelationCount: number;
  loadedEventCount: number;
  totalEventCount: number;
  weakRelations: Array<GraphEdge & { from: string; to: string }>;
  pageSectionVariants: {
    hidden: { opacity: number; y: number };
    visible: { opacity: number; y: number };
  };
}

// 2026-04-23，任务：复杂度与耦合审查 P1
// 把图谱页顶部指标卡与关系摘要区块拆出，减少 GraphPage 的渲染噪声
export function GraphOverviewSection({
  graphSummary,
  activeRelationCount,
  inactiveRelationCount,
  loadedEventCount,
  totalEventCount,
  weakRelations,
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
          value={graphSummary?.node_count ?? 0}
          format="raw"
          decimals={0}
          icon={<Network className="h-5 w-5" />}
          description="当前识别到的人物、组织与群体"
          accent="primary"
        />
        <MetricCard
          label="关系连线"
          value={graphSummary?.edge_count ?? 0}
          format="raw"
          decimals={0}
          icon={<Link2 className="h-5 w-5" />}
          description="当前关系网络中的主要连接"
          accent="chart-2"
        />
        <MetricCard
          label="网络密度"
          value={graphSummary?.density ?? 0}
          format="raw"
          decimals={4}
          icon={<Activity className="h-5 w-5" />}
          description="关系是否集中在少数核心角色身上"
          accent="chart-4"
        />
        <MetricCard
          label="关系变化"
          value={totalEventCount}
          format="raw"
          decimals={0}
          icon={<History className="h-5 w-5" />}
          description={
            totalEventCount > loadedEventCount ? `已加载 ${loadedEventCount} / ${totalEventCount} 条变化记录` : "已记录的关系变化"
          }
          accent="chart-5"
        />
      </motion.section>

      <motion.section
        variants={pageSectionVariants}
        initial="hidden"
        animate="visible"
        transition={{ duration: 0.28, delay: 0.1 }}
        className="grid gap-4 xl:grid-cols-3"
      >
        <DashboardCardShell
          title="核心网络"
          icon={<Users className="h-4 w-4" />}
          accent="primary"
          showOrb
          bodyClassName="gap-4"
        >
          <p className="text-sm text-text-muted">这一组角色处在当前关系网络的中心位置，适合作为阅读入口。</p>
          <div className="space-y-4 rounded-2xl border border-border/60 bg-surface/70 p-4">
            <div className="flex flex-wrap gap-2">
              {graphSummary?.core_characters.map((name) => (
                <Badge key={name} variant="secondary" className="px-3 py-1 text-sm">
                  {name}
                </Badge>
              ))}
            </div>
            <div className="rounded-xl border border-border/70 bg-surface-hover/40 p-4 text-sm text-text-muted">
              当前活跃关系 {activeRelationCount} 条
              {inactiveRelationCount > 0 ? `，另有 ${inactiveRelationCount} 条关系处于非活跃状态。` : "。"}
            </div>
          </div>
        </DashboardCardShell>

        <DashboardCardShell
          title="关键关系"
          icon={<Sparkles className="h-4 w-4" />}
          accent="chart-2"
          bodyClassName="gap-3"
        >
          <p className="text-sm text-text-muted">这里展示当前最重要、最能代表人物网络主干的关系。</p>
          <div className="space-y-3 rounded-2xl border border-border/60 bg-surface/70 p-4">
            {graphSummary?.key_relations.length ? (
              graphSummary.key_relations.map((relation) => (
                <div
                  key={`${relation.from}-${relation.to}-${relation.type ?? "unknown"}`}
                  className="rounded-xl border border-border/70 bg-surface-hover/40 p-4"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium text-text">
                        {relation.from} · {relation.to}
                      </p>
                      <p className="mt-1 text-xs text-text-muted">{relation.type ?? "未标注关系类型"}</p>
                    </div>
                    <Badge variant="outline">出现 {relation.support_count} 次</Badge>
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-xl border border-dashed border-border p-4 text-sm text-text-muted">
                暂无关键关系摘要。
              </div>
            )}
          </div>
        </DashboardCardShell>

        <DashboardCardShell
          title="边缘关系"
          icon={<AlertTriangle className="h-4 w-4 text-chart-negative" />}
          accent="chart-5"
          bodyClassName="gap-3"
        >
          <p className="text-sm text-text-muted">这些关系连接较弱或变化较少，更像是支线关系的补充信息。</p>
          <div className="space-y-3 rounded-2xl border border-border/60 bg-surface/70 p-4">
            {weakRelations.length ? (
              weakRelations.map((relation) => (
                <div
                  key={`${relation.source}-${relation.target}-${relation.relation_type ?? "unknown"}`}
                  className="rounded-xl border border-border/70 bg-surface-hover/40 p-4"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium text-text">
                        {relation.from} · {relation.to}
                      </p>
                      <p className="mt-1 text-xs text-text-muted">{relation.relation_type ?? "未标注关系"}</p>
                    </div>
                    <div className="text-right text-xs text-text-muted">
                      <div>连接强度 {relation.weight ?? 1}</div>
                      <div>变化 {relation.change_count ?? 0} 次</div>
                    </div>
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-xl border border-dashed border-border p-4 text-sm text-text-muted">
                当前没有明显的边缘关系。
              </div>
            )}
          </div>
        </DashboardCardShell>
      </motion.section>
    </div>
  );
}
