/** 展示运行状态、取消入口和真实 Agent 的模型输出 */
import { AnalysisWorkbench } from "./AnalysisWorkbench";

export interface AnalysisProgressPanelProps {
  taskId: string;
  onCancel: () => void | Promise<void>;
  onResume: () => void | Promise<void>;
}

export function AnalysisProgressPanel({
  taskId,
  onCancel,
  onResume,
}: AnalysisProgressPanelProps) {
  return (
    <AnalysisWorkbench key={taskId} taskId={taskId} onCancel={onCancel} onResume={onResume} />
  );
}
