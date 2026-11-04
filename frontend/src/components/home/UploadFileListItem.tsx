import { motion } from "framer-motion";
import { CheckCircle2, AlertCircle, FileText, X } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/cn";
import { formatFileSize } from "@/lib/utils";
import type { UploadFileInfo } from "./uploadTypes";

export function UploadFileListItem({
  file,
  onRemove,
}: {
  file: UploadFileInfo;
  onRemove?: (id: string) => void;
}) {
  const isUploading = file.status === "uploading";
  const isSuccess = file.status === "success";
  const isError = file.status === "error";

  return (
    <motion.div
      layout
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 10 }}
    >
      <Card
        className={cn(
          "flex items-center gap-3 p-3",
          isSuccess && "border-chart-positive/30 bg-chart-positive/5",
          isError && "border-chart-negative/30 bg-chart-negative/5",
          !isSuccess && !isError && "border-border bg-surface"
        )}
      >
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-surface-hover">
          {isSuccess ? (
            <CheckCircle2 className="h-5 w-5 text-chart-positive" />
          ) : isError ? (
            <AlertCircle className="h-5 w-5 text-chart-negative" />
          ) : (
            <FileText className="h-5 w-5 text-text-muted" />
          )}
        </div>

        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-text">{file.file.name}</p>
          <p className="text-xs text-text-muted">
            {formatFileSize(file.file.size)}
            {isError && file.error && (
              <span className="ml-2 text-chart-negative"> · {file.error}</span>
            )}
          </p>

          {isUploading && (
            <div className="mt-2">
              <Progress value={file.progress} className="h-1.5" />
            </div>
          )}
        </div>

        {!isUploading && !isSuccess && onRemove && (
          <button
            onClick={() => onRemove(file.id)}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-text-muted transition-colors hover:bg-surface-hover hover:text-text"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </Card>
    </motion.div>
  );
}
