import { motion, AnimatePresence } from "framer-motion";
import { X, User, Users } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";
import type { GraphNode } from "@/api/types";

/* ------------------------------------------------------------------ */
/*  类型定义                                                           */
/* ------------------------------------------------------------------ */

export interface RelatedNodeInfo {
  node: GraphNode;
  relationType: string;
  relationRevision: number;
}

export interface NodeDetailPanelProps {
  node: GraphNode | null;
  relatedNodes: RelatedNodeInfo[];
  isOpen: boolean;
  onClose: () => void;
  className?: string;
}

/* ------------------------------------------------------------------ */
/*  动画变体                                                           */
/* ------------------------------------------------------------------ */

const slideInVariants = {
  hidden: { x: "100%", opacity: 0 },
  visible: {
    x: 0,
    opacity: 1,
    transition: { duration: 0.3, ease: "easeOut" as const },
  },
  exit: {
    x: "100%",
    opacity: 0,
    transition: { duration: 0.2 },
  },
};

const overlayVariants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { duration: 0.2 } },
  exit: { opacity: 0, transition: { duration: 0.2 } },
};

/* ------------------------------------------------------------------ */
/*  关系类型颜色映射                                                   */
/*  与 ForceGraph.getRelationColorsFromCSS() 保持一致                  */
/* ------------------------------------------------------------------ */

const relationTypeColors: Record<string, string> = {
  家族: "bg-chart-neutral/20 text-chart-neutral",
  师徒: "bg-chart-neutral/20 text-chart-neutral",
  主从: "bg-chart-neutral/20 text-chart-neutral",
  敌对: "bg-chart-negative/20 text-chart-negative",
  盟友: "bg-chart-positive/20 text-chart-positive",
  友情: "bg-chart-positive/20 text-chart-positive",
  爱慕: "bg-chart-positive/20 text-chart-positive",
  利益: "bg-chart-neutral/20 text-chart-neutral",
  领导: "bg-chart-neutral/20 text-chart-neutral",
  同一人物: "bg-chart-neutral/20 text-chart-neutral",
  隶属: "bg-chart-neutral/20 text-chart-neutral",
  位于: "bg-chart-neutral/20 text-chart-neutral",
};

function getRelationTypeColor(relationType: string): string {
  return relationTypeColors[relationType] || "bg-primary-subtle text-primary";
}

/* ------------------------------------------------------------------ */
/*  实体类型显示名称                                                   */
/* ------------------------------------------------------------------ */

const entityTypeDisplayNames: Record<string, string> = {
  character: "角色",
  location: "地点",
  item: "物品",
  organization: "组织",
  object: "物品",
};

function getEntityTypeDisplayName(entityType: string): string {
  return entityTypeDisplayNames[entityType] || entityType;
}

/* ------------------------------------------------------------------ */
/*  子组件                                                             */
/* ------------------------------------------------------------------ */

interface InfoRowProps {
  label: string;
  value: string | React.ReactNode;
}

function InfoRow({ label, value }: InfoRowProps) {
  return (
    <div className="flex items-center justify-between py-2">
      <span className="text-sm text-text-muted">{label}</span>
      <span className="text-sm font-medium text-text">{value}</span>
    </div>
  );
}

interface RelatedNodeItemProps {
  relatedNode: RelatedNodeInfo;
  onClick?: () => void;
}

function RelatedNodeItem({ relatedNode, onClick }: RelatedNodeItemProps) {
  const { node, relationType, relationRevision } = relatedNode;

  return (
    <motion.button
      whileHover={{ backgroundColor: "rgba(var(--surface-hover-rgb), 1)" }}
      className="w-full rounded-lg p-3 text-left transition-colors"
      onClick={onClick}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-text">{node.name}</span>
          <Badge
            className={cn(
              "text-[10px] px-1.5 py-0",
              getRelationTypeColor(relationType)
            )}
          >
            {relationType}
          </Badge>
        </div>
        <span className="text-xs text-text-muted">版本 {relationRevision}</span>
      </div>
    </motion.button>
  );
}

/* ------------------------------------------------------------------ */
/*  主组件                                                             */
/* ------------------------------------------------------------------ */

/**
 * 节点详情面板 - 展示选中节点的详细信息和关联节点
 *
 * 用于知识图谱页面展示选中节点的详细信息，包含右侧滑出动画
 */
export function NodeDetailPanel({
  node,
  relatedNodes,
  isOpen,
  onClose,
  className,
}: NodeDetailPanelProps) {
  const primaryRole =
    typeof node?.state.primary_role_function === "string" ? node.state.primary_role_function : null;
  const stateStatus = typeof node?.state.status === "string" ? node.state.status : null;

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* 背景遮罩 */}
          <motion.div
            variants={overlayVariants}
            initial="hidden"
            animate="visible"
            exit="exit"
            className="fixed inset-0 z-40 bg-black/30 backdrop-blur-sm"
            onClick={onClose}
          />

          {/* 面板主体 */}
          <motion.div
            variants={slideInVariants}
            initial="hidden"
            animate="visible"
            exit="exit"
            className={cn(
              "fixed right-0 top-0 z-50 h-full w-80 overflow-y-auto border-l border-border bg-surface shadow-xl",
              className
            )}
          >
            {/* 关闭按钮 */}
            <div className="sticky top-0 z-10 flex items-center justify-end border-b border-border bg-surface p-4">
              <button
                onClick={onClose}
                className="flex h-8 w-8 items-center justify-center rounded-full text-text-muted transition-colors hover:bg-surface-hover hover:text-text"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {node ? (
              <div className="p-4">
                {/* 节点基本信息 */}
                <Card className="border-0 shadow-none">
                  <CardHeader className="p-0 pb-4">
                    <div className="flex items-center gap-3">
                      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
                        <User className="h-6 w-6 text-primary" />
                      </div>
                      <div>
                        <CardTitle className="text-lg text-text">
                          {node.name}
                        </CardTitle>
                        <Badge variant="outline" className="mt-1 text-xs">
                          {getEntityTypeDisplayName(node.entity_type)}
                        </Badge>
                      </div>
                    </div>
                  </CardHeader>

                  <CardContent className="p-0">
                    <div className="divide-y divide-border">
                      <InfoRow
                        label="类型"
                        value={getEntityTypeDisplayName(node.entity_type)}
                      />
                      {Array.isArray(node.tags) && node.tags.length > 0 && (
                        <div className="flex items-center justify-between gap-3 py-2">
                          <span className="text-sm text-text-muted">标签</span>
                          <span className="flex flex-wrap justify-end gap-1">
                            {node.tags.map((tag) => (
                              <Badge key={tag} variant="outline" className="text-[10px]">
                                {tag}
                              </Badge>
                            ))}
                          </span>
                        </div>
                      )}
                      {Array.isArray(node.aliases) && node.aliases.length > 0 && (
                        <InfoRow label="别名" value={node.aliases.join(" / ")} />
                      )}
                      {node.first_seen_chapter != null && node.last_seen_chapter != null && (
                        <InfoRow
                          label="出场"
                          value={`第 ${node.first_seen_chapter} 章 - 第 ${node.last_seen_chapter} 章`}
                        />
                      )}
                      <InfoRow label="状态版本" value={`第 ${node.state_revision} 版`} />
                      {primaryRole && (
                        <InfoRow
                          label="叙事职责"
                          value={primaryRole}
                        />
                      )}
                      {stateStatus && (
                        <InfoRow
                          label="当前状态"
                          value={stateStatus}
                        />
                      )}
                    </div>
                  </CardContent>
                </Card>

                {/* 关联节点 */}
                {relatedNodes.length > 0 && (
                  <div className="mt-6">
                    <div className="mb-3 flex items-center gap-2">
                      <Users className="h-4 w-4 text-text-muted" />
                      <h3 className="text-sm font-semibold text-text">
                        {node.entity_type === "character"
                          ? "关联角色"
                          : `关联${getEntityTypeDisplayName(node.entity_type) || "实体"}`}
                      </h3>
                      <span className="text-xs text-text-muted">
                        ({relatedNodes.length})
                      </span>
                    </div>

                    <div className="space-y-1 rounded-lg border border-border">
                      {relatedNodes.map((relatedNode) => (
                        <RelatedNodeItem
                          key={relatedNode.node.entity_id}
                          relatedNode={relatedNode}
                        />
                      ))}
                    </div>
                  </div>
                )}

                {/* 无关联节点提示 */}
                {relatedNodes.length === 0 && (
                  <div className="mt-6 flex flex-col items-center justify-center py-8 text-center">
                    <Users className="mb-2 h-8 w-8 text-text-muted/50" />
                    <p className="text-sm text-text-muted">暂无关联角色</p>
                  </div>
                )}
              </div>
            ) : (
              <div className="flex h-64 items-center justify-center">
                <p className="text-sm text-text-muted">未选中任何节点</p>
              </div>
            )}
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

export default NodeDetailPanel;
