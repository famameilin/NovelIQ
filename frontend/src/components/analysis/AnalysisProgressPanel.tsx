/**
 * AnalysisProgressPanel - 仪表盘进度展示面板
 *
 * 任务运行中时在仪表盘展示进度，替代骨架屏
 *
 * 使用 flex-1 填满父元素高度，移除固定高度
 *
 * 配合 NovelDetailPage 的 flex-1 flex-col min-h-0 父容器使用 flex-1
 */
import { Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ProgressDetail } from "./ProgressDetail";
import { StreamOutput } from "./StreamOutput";

export interface AnalysisProgressPanelProps {
  taskId: string;
  onCancel: () => void;
}

export function AnalysisProgressPanel({
  taskId,
  onCancel,
}: AnalysisProgressPanelProps) {
  return (
    <Card className="flex min-h-0 flex-1 flex-col overflow-hidden p-6">
      <div className="mb-4 flex shrink-0 items-center justify-between">
        <h2 className="text-lg font-semibold text-text">分析进行中</h2>
        <Button variant="destructive" size="sm" onClick={onCancel}>
          <Square className="mr-2 h-4 w-4" />
          停止分析
        </Button>
      </div>

      <ProgressDetail className="mb-4 shrink-0" />

      <div className="min-h-0 flex-1 overflow-hidden">
        <StreamOutput taskId={taskId} className="h-full" />
      </div>
    </Card>
  );
}
