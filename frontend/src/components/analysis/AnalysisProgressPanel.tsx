/** 展示运行状态、取消入口和真实 Agent 的模型输出 */
import { Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
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


      <div className="min-h-0 flex-1 overflow-hidden">
        <StreamOutput taskId={taskId} className="h-full" />
      </div>
    </Card>
  );
}
