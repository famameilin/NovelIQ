import { useState, useRef, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Upload, FileText, X, CheckCircle2, AlertCircle, Plus } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { formatFileSize } from "@/lib/utils";

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

export interface UploadFile {
  file: File;
  id: string;
  progress: number;
  status: "pending" | "uploading" | "success" | "error";
  error?: string;
}

export interface UploadCardProps {
  onFilesSelected?: (files: File[]) => void;
  onUpload?: (files: UploadFile[]) => Promise<void>;
  maxFileSize?: number; // bytes, default 10MB
  acceptedTypes?: string[]; // default [".txt"]
  className?: string;
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
    return `文件大小超过 ${formatFileSize(maxSize)}`;
  }

  const extension = `.${file.name.split(".").pop()?.toLowerCase()}`;
  if (!acceptedTypes.includes(extension)) {
    return `不支持的文件格式，请上传 ${acceptedTypes.join(", ")} 文件`;
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
  file: UploadFile;
  onRemove: (id: string) => void;
}) {
  const isUploading = file.status === "uploading";
  const isSuccess = file.status === "success";
  const isError = file.status === "error";

  return (
    <motion.div
      layout
      initial={{ opacity: 0, x: -20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 20 }}
    >
      <Card
        className={cn(
          "flex items-center gap-3 p-3",
          isSuccess && "border-chart-positive/30 bg-chart-positive/5",
          isError && "border-chart-negative/30 bg-chart-negative/5"
        )}
      >
      {/* 文件图标 */}
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-surface-hover">
        {isSuccess ? (
          <CheckCircle2 className="h-5 w-5 text-chart-positive" />
        ) : isError ? (
          <AlertCircle className="h-5 w-5 text-chart-negative" />
        ) : (
          <FileText className="h-5 w-5 text-text-muted" />
        )}
      </div>

      {/* 文件信息 */}
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-text">
          {file.file.name}
        </p>
        <p className="text-xs text-text-muted">
          {formatFileSize(file.file.size)}
          {isError && file.error && (
            <span className="ml-2 text-chart-negative">{file.error}</span>
          )}
        </p>
      </div>

      {/* 进度条或删除按钮 */}
      <div className="flex w-24 shrink-0 items-center justify-end">
        {isUploading ? (
          <div className="w-full">
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-border">
              <div
                className="h-full rounded-full bg-primary transition-all duration-300"
                style={{ width: `${file.progress}%` }}
              />
            </div>
            <p className="mt-1 text-right text-xs text-text-muted">
              {file.progress}%
            </p>
          </div>
        ) : (
          <button
            onClick={() => onRemove(file.id)}
            className="flex h-8 w-8 items-center justify-center rounded-full text-text-muted transition-colors hover:bg-surface-hover hover:text-text"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>
      </Card>
    </motion.div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main Component                                                    */
/* ------------------------------------------------------------------ */

export function UploadCard({
  onFilesSelected,
  onUpload,
  maxFileSize = 10 * 1024 * 1024, // 10MB
  acceptedTypes = [".txt"],
  className,
}: UploadCardProps) {
  const [files, setFiles] = useState<UploadFile[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const processFiles = useCallback(
    (newFiles: FileList | null) => {
      if (!newFiles) return;

      const processedFiles: UploadFile[] = [];
      const errors: string[] = [];

      Array.from(newFiles).forEach((file) => {
        const error = validateFile(file, maxFileSize, acceptedTypes);
        if (error) {
          errors.push(`${file.name}: ${error}`);
          processedFiles.push({
            file,
            id: generateId(),
            progress: 0,
            status: "error",
            error,
          });
        } else {
          processedFiles.push({
            file,
            id: generateId(),
            progress: 0,
            status: "pending",
          });
        }
      });

      setFiles((prev) => [...prev, ...processedFiles]);
      onFilesSelected?.(processedFiles.map((f) => f.file));
    },
    [maxFileSize, acceptedTypes, onFilesSelected]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragging(false);
      processFiles(e.dataTransfer.files);
    },
    [processFiles]
  );

  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      processFiles(e.target.files);
      // Reset input value to allow selecting the same file again
      e.target.value = "";
    },
    [processFiles]
  );

  const handleRemoveFile = useCallback((id: string) => {
    setFiles((prev) => prev.filter((f) => f.id !== id));
  }, []);

  const handleUpload = useCallback(async () => {
    const pendingFiles = files.filter((f) => f.status === "pending");
    if (pendingFiles.length === 0) return;

    // Mark all pending files as uploading
    setFiles((prev) =
      prev.map((f) =
        f.status === "pending" ? { ...f, status: "uploading" } : f
      )
    );

    // Simulate progress updates
    const progressInterval = setInterval(() => {
      setFiles((prev) =
        prev.map((f) => {
          if (f.status === "uploading" && f.progress < 90) {
            return { ...f, progress: f.progress + Math.random() * 10 };
          }
          return f;
        })
      );
    }, 200);

    try {
      await onUpload?.(pendingFiles);

      // Mark as success
      clearInterval(progressInterval);
      setFiles((prev) =>
        prev.map((f) =>
          f.status === "uploading"
            ? { ...f, status: "success", progress: 100 }
            : f
        )
      );
    } catch (error) {
      // Mark as error
      clearInterval(progressInterval);
      setFiles((prev) =>
        prev.map((f) =>
          f.status === "uploading"
            ? { ...f, status: "error", error: "上传失败" }
            : f
        )
      );
    }
  }, [files, onUpload]);

  const handleClick = () => {
    inputRef.current?.click();
  };

  const pendingCount = files.filter((f) => f.status === "pending").length;

  return (
    <div className={cn("space-y-4", className)}>
      {/* 拖拽上传区域 */}
      <Card
        className={cn(
          "relative cursor-pointer overflow-hidden border-2 border-dashed transition-all duration-200",
          isDragging
            ? "border-primary bg-primary-subtle/50"
            : "border-border bg-surface hover:border-primary/50 hover:bg-surface-hover"
        )}
        onDragEnter={handleDragEnter}
        onDragLeave={handleDragLeave}
        onDragOver={handleDragOver}
        onDrop={handleDrop}
        onClick={handleClick}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".txt"
          multiple
          className="hidden"
          onChange={handleInputChange}
        />

        <div className="flex flex-col items-center justify-center px-8 py-12 text-center">
          <div
            className={cn(
              "mb-4 flex h-16 w-16 items-center justify-center rounded-full transition-colors",
              isDragging ? "bg-primary/20" : "bg-surface-hover"
            )}
          >
            <Upload
              className={cn(
                "h-8 w-8 transition-colors",
                isDragging ? "text-primary" : "text-text-muted"
              )}
            />
          </div>

          <p className="mb-2 text-lg font-medium text-text">
            {isDragging ? "松开以上传文件" : "拖拽文件到此处上传"}
          </p>

          <p className="mb-4 text-sm text-text-muted">
            支持 .txt 格式，单个文件最大 10MB
          </p>

          <Button
            variant="outline"
            size="sm"
            onClick={(e) => {
              e.stopPropagation();
              handleClick();
            }}
          >
            <Plus className="mr-2 h-4 w-4" />
            选择文件
          </Button>
        </div>
      </Card>

      {/* 文件列表 */}
      <AnimatePresence mode="popLayout">
        {files.length > 0 && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="space-y-2"
          >
            <div className="flex items-center justify-between">
              <h4 className="text-sm font-medium text-text">
                待上传文件 ({files.length})
              </h4>
              {pendingCount > 0 && (
                <Button
                  size="sm"
                  onClick={handleUpload}
                  disabled={
                    files.filter((f) => f.status === "uploading").length > 0
                  }
                >
                  开始上传
                </Button>
              )}
            </div>

            <div className="space-y-2">
              {files.map((file) => (
                <FileListItem
                  key={file.id}
                  file={file}
                  onRemove={handleRemoveFile}
                />
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export default UploadCard;
