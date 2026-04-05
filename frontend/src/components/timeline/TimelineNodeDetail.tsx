/**
 * TimelineNodeDetail - 节点详情展开组件
 *
 * 创建时间: 2026-04-05
 * 创建者: GLM-5
 * 任务: Phase 2-B 叙事时间轴
 * 说明: 点击节点后展开的详情面板，显示事件描述、角色、关系变化等
 */

import { motion, AnimatePresence } from "framer-motion";
import { useNavigate } from "react-router-dom";
import {
  X,
  Zap,
  HelpCircle,
  User,
  UserMinus,
  Link2,
  Users,
  ArrowRight,
} from "lucide-react";
import { cn } from "@/lib/cn";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { TimelineNode as TimelineNodeType } from "@/api/types";

/* ------------------------------------------------------------------ */
/*  Constants                                                         */
/* ------------------------------------------------------------------ */

const NODE_TYPE_CONFIG: Record<
  string,
  { icon: typeof Zap; colorClass: string; label: string }
> = {
  plot: { icon: Zap, colorClass: "text-primary", label: "情节节点" },
  character_entry: {
    icon: User,
    colorClass: "text-chart-positive",
    label: "角色登场",
  },
  character_exit: {
    icon: UserMinus,
    colorClass: "text-chart-negative",
    label: "角色退场",
  },
  relation_change: {
    icon: Link2,
    colorClass: "text-chart-2",
    label: "关系变化",
  },
};

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

export interface TimelineNodeDetailProps {
  node: TimelineNodeType | null;
  novelId: string;
  onClose?: () => void;
  className?: string;
}

/* ------------------------------------------------------------------ */
/*  Component                                                         */
/* ------------------------------------------------------------------ */

export function TimelineNodeDetail({
  node,
  novelId,
  onClose,
  className,
}: TimelineNodeDetailProps) {
  const navigate = useNavigate();

  if (!node) {
    return null;
  }

  const config = NODE_TYPE_CONFIG[node.node_type] || NODE_TYPE_CONFIG.plot;
  const Icon = config.icon;

  const handleCharacterClick = (characterName: string) => {
    navigate(`/novels/${novelId}/characters?highlight=${encodeURIComponent(characterName)}`);
  };

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, height: 0 }}
        animate={{ opacity: 1, height: "auto" }}
        exit={{ opacity: 0, height: 0 }}
        transition={{ duration: 0.3, ease: "easeOut" }}
        className={cn("overflow-hidden", className)}
      >
        <Card variant="elevated" className="rounded-xl">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Icon className={cn("h-5 w-5", config.colorClass)} />
                <CardTitle className="text-base font-semibold text-text">
                  {config.label}
                </CardTitle>
              </div>
              {onClose && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={onClose}
                  className="h-8 w-8 p-0"
                >
                  <X className="h-4 w-4" />
                </Button>
              )}
            </div>
          </CardHeader>

          <CardContent className="space-y-4">
            <div>
              <p className="text-sm text-text">{node.event}</p>
              <div className="mt-2 flex items-center gap-4 text-xs text-text-muted">
                <span>第 {node.chunk_id} 块</span>
                <span>进度: {Math.round(node.progress * 100)}%</span>
                <span>重要性: {node.importance_score.toFixed(1)}</span>
              </div>
            </div>

            {(node.characters?.length ?? 0) > 0 && (
              <div>
                <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-text-muted">
                  <Users className="h-3.5 w-3.5" />
                  <span>涉及角色</span>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {node.characters.map((char) => (
                    <Badge
                      key={char}
                      variant="secondary"
                      className="cursor-pointer hover:bg-primary/20"
                      onClick={() => handleCharacterClick(char)}
                    >
                      {char}
                    </Badge>
                  ))}
                </div>
              </div>
            )}

            {(node.is_pivot || node.is_cliffhanger) && (
              <div className="flex gap-2">
                {node.is_pivot && (
                  <Badge variant="outline" className="gap-1 border-chart-negative text-chart-negative">
                    <Zap className="h-3 w-3" />
                    转折点
                  </Badge>
                )}
                {node.is_cliffhanger && (
                  <Badge variant="outline" className="gap-1 border-chart-3 text-chart-3">
                    <HelpCircle className="h-3 w-3" />
                    悬念点
                  </Badge>
                )}
              </div>
            )}

            {node.character_entries && node.character_entries.length > 0 && (
              <div>
                <div className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-chart-positive">
                  <User className="h-3.5 w-3.5" />
                  <span>角色登场</span>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {node.character_entries.map((char) => (
                    <Badge
                      key={char}
                      variant="secondary"
                      className="cursor-pointer bg-chart-positive/10 text-chart-positive hover:bg-chart-positive/20"
                      onClick={() => handleCharacterClick(char)}
                    >
                      {char}
                    </Badge>
                  ))}
                </div>
              </div>
            )}

            {node.character_exits && node.character_exits.length > 0 && (
              <div>
                <div className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-chart-negative">
                  <UserMinus className="h-3.5 w-3.5" />
                  <span>角色退场</span>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {node.character_exits.map((char) => (
                    <Badge
                      key={char}
                      variant="secondary"
                      className="cursor-pointer bg-chart-negative/10 text-chart-negative hover:bg-chart-negative/20"
                      onClick={() => handleCharacterClick(char)}
                    >
                      {char}
                    </Badge>
                  ))}
                </div>
              </div>
            )}

            {node.relation_changes && node.relation_changes.length > 0 && (
              <div>
                <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-chart-2">
                  <Link2 className="h-3.5 w-3.5" />
                  <span>关系变化</span>
                </div>
                <div className="space-y-2">
                  {node.relation_changes.map((rc, i) => (
                    <div
                      key={i}
                      className="flex items-center gap-2 rounded-md bg-surface-hover p-2 text-xs"
                    >
                      <span className="font-medium">{rc.from_char}</span>
                      <ArrowRight className="h-3 w-3 text-text-muted" />
                      <span className="font-medium">{rc.to_char}</span>
                      <Badge variant="outline" className="text-[10px]">
                        {rc.relation_type}
                      </Badge>
                      <Badge variant="secondary" className="text-[10px]">
                        {rc.change_type}
                      </Badge>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </motion.div>
    </AnimatePresence>
  );
}
