import { useState, useRef, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { FileText, Upload, CheckCircle2, AlertCircle, X, Plus } from "lucide-react";
import { cn } from "@/lib/cn";
import { formatFileSize } from "@/lib/utils";
import { appConfig } from "@/config";

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

export interface UploadFileInfo {
  file: File;
  id: string;
  status: "pending" | "uploading" | "success" | "error";
  progress: number;
  error?: string;
}

export interface UploadDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  files: UploadFileInfo[];
  onFilesChange?: (files: UploadFileInfo[]) => void;
  onUpload?: (signal: AbortSignal) => Promise<void>;
  maxFileSize?: number;
  acceptedTypes?: string[];
}

/* ------------------------------------------------------------------ */
/*  Utils                                                             */
/* ------------------------------------------------------------------ */

function generateId(): string {
  return Math.random().toString(36).substring(2, 9);
}

function validateFile(
  file: File,
  maxSize: number,
  acceptedTypes: string[]
): string | null {
  if (file.size > maxSize) {
    return `文件大小超过限制`;
  }

  const extension = `.${file.name.split(".").pop()?.toLowerCase()}`;
  if (!acceptedTypes.includes(extension)) {
    return `不支持的文件格式`;
  }

  return null;
}

/* ------------------------------------------------------------------ */
/*  Components                                                        */
/* ------------------------------------------------------------------ */

function FileListItem({
  file,
  onRemove,
}: {
  file: UploadFileInfo;
  onRemove: (id: string) => void;
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
      {/* 图标 */}
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-surface-hover">
        {isSuccess ? (
          <CheckCircle2 className="h-5 w-5 text-chart-positive" />
        ) : isError ? (
          <AlertCircle className="h-5 w-5 text-chart-negative" />
        ) : (
          <FileText className="h-5 w-5 text-text-muted" />
        )}
      </div>

      {/* 信息 */}
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-text">{file.file.name}</p>
        <p className="text-xs text-text-muted">
          {formatFileSize(file.file.size)}
          {isError && file.error && (
            <span className="ml-2 text-chart-negative"> · {file.error}</span>
          )}
        </p>

        {/* 进度条 */}
        {isUploading && (
          <div className="mt-2">
            <Progress value={file.progress} className="h-1.5" />
          </div>
        )}
      </div>

      {/* 删除按钮 */}
      {!isUploading && !isSuccess && (
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

/* ------------------------------------------------------------------ */
/*  Main Component                                                    */
/* ------------------------------------------------------------------ */

export function UploadDialog({
  open,
  onOpenChange,
  files,
  onFilesChange,
  onUpload,
  maxFileSize = appConfig.maxUploadSizeBytes,
  acceptedTypes = [".txt"],
}: UploadDialogProps) {
  const [isUploading, setIsUploading] = useState(false);
  const [dragActive, setDragActive] = useState(false);

  const inputRef = useRef<HTMLInputElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      addFiles(e.dataTransfer.files);
    }
  };

  const addFiles = (newFiles: FileList) => {
    const newFileInfos: UploadFileInfo[] = [];

    Array.from(newFiles).forEach((file) => {
      const error = validateFile(file, maxFileSize, acceptedTypes);
      newFileInfos.push({
        file,
        id: generateId(),
        status: error ? "error" : "pending",
        progress: 0,
        error: error || undefined,
      });
    });

    onFilesChange?.([...files, ...newFileInfos]);
  };

  const removeFile = (id: string) => {
    onFilesChange?.(files.filter((f) => f.id !== id));
  };

  const handleUpload = async () => {
    if (files.length === 0) return;

    const controller = new AbortController();
    abortControllerRef.current = controller;
    setIsUploading(true);

    // Update all pending files to uploading
    const uploadingFiles = files.map((f) =>
      f.status === "pending" ? { ...f, status: "uploading" as const } : f
    );
    onFilesChange?.(uploadingFiles);

    try {
      await onUpload?.(controller.signal);

      // Mark as success
      onFilesChange?.(
        uploadingFiles.map((f) =>
          f.status === "uploading"
            ? { ...f, status: "success" as const, progress: 100 }
            : f
        )
      );
    } catch {
      if (controller.signal.aborted) {
        onFilesChange?.(
          uploadingFiles.map((f) =>
            f.status === "uploading"
              ? { ...f, status: "pending" as const, progress: 0 }
              : f
          )
        );
      } else {
        onFilesChange?.(
          uploadingFiles.map((f) =>
            f.status === "uploading"
              ? {
                  ...f,
                  status: "error" as const,
                  error: "上传失败，请重试",
                }
              : f
          )
        );
      }
    } finally {
      abortControllerRef.current = null;
      setIsUploading(false);
    }
  };

  const handleCancel = useCallback(() => {
    abortControllerRef.current?.abort();
  }, []);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>上传小说</DialogTitle>
          <DialogDescription>
            上传中文网络小说，开始分析其叙事结构、情感走向和人物关系。
          </DialogDescription>
        </DialogHeader>

        {/* 拖拽上传区域 */}
        <div
          className={cn(
            "relative rounded-xl border-2 border-dashed p-6 transition-all duration-200",
            dragActive
              ? "border-primary bg-primary-subtle/30"
              : "border-border bg-surface hover:border-primary/30 hover:bg-surface-hover"
          )}
          onDragEnter={handleDrag}
          onDragLeave={handleDrag}
          onDragOver={handleDrag}
          onDrop={handleDrop}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".txt"
            multiple
            className="hidden"
            onChange={(e) => {
              if (e.target.files) addFiles(e.target.files);
              e.target.value = "";
            }}
          />

          <div className="text-center">
            <motion.div
              initial={{ scale: 1 }}
              animate={{ scale: dragActive ? 1.1 : 1 }}
              transition={{ duration: 0.2 }}
              className={cn(
                "mx-auto mb-3 flex h-16 w-16 items-center justify-center rounded-2xl transition-colors",
                dragActive ? "bg-primary/20" : "bg-surface-hover"
              )}
            >
              <Upload
                className={cn(
                  "h-8 w-8 transition-colors",
                  dragActive ? "text-primary" : "text-text-muted"
                )}
              />
            </motion.div>

            <p className="text-sm font-medium text-text">
              {dragActive ? "松开以上传文件" : "拖拽文件到此处"}
            </p>
            <p className="mt-1 text-xs text-text-muted">
              支持 .txt 格式，单个文件最大 {formatFileSize(maxFileSize)}
            </p>

            <Button
              variant="outline"
              size="sm"
              className="mt-3"
              onClick={() => inputRef.current?.click()}
            >
              <Plus className="mr-2 h-4 w-4" />
              选择文件
            </Button>
          </div>
        </div>

        {/* 文件列表 */}
        {files.length > 0 && (
          <div className="space-y-2">
            <p className="text-sm font-medium text-text">
              待上传文件 ({files.length})
            </p>
            <AnimatePresence mode="popLayout">
              {files.map((file) => (
                <FileListItem
                  key={file.id}
                  file={file}
                  onRemove={removeFile}
                />
              ))}
            </AnimatePresence>
          </div>
        )}

        <DialogFooter>
          {isUploading ? (
            <Button variant="destructive" size="sm" onClick={handleCancel}>
              <X className="mr-2 h-4 w-4" />
              取消上传
            </Button>
          ) : files.filter((f) => f.status === "pending").length > 0 ? (
            <Button onClick={handleUpload}>
              <Upload className="mr-2 h-4 w-4" />
              开始上传
            </Button>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default UploadDialog;
