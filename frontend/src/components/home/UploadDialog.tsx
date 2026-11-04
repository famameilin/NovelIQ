import { useRef, useState } from "react";
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
import { Upload, Plus, ChevronRight } from "lucide-react";
import { cn } from "@/lib/cn";
import { formatFileSize } from "@/lib/utils";
import { appConfig } from "@/config";
import { UploadFileListItem } from "./UploadFileListItem";
import type { UploadFileInfo } from "./uploadTypes";

export type { UploadFileInfo } from "./uploadTypes";

export interface UploadDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  files: UploadFileInfo[];
  onFilesChange?: (files: UploadFileInfo[]) => void;
  onContinue?: () => void;
  maxFileSize?: number;
  acceptedTypes?: string[];
}

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

export function UploadDialog({
  open,
  onOpenChange,
  files,
  onFilesChange,
  onContinue,
  maxFileSize = appConfig.maxUploadSizeBytes,
  acceptedTypes = [".txt"],
}: UploadDialogProps) {
  const [dragActive, setDragActive] = useState(false);

  const inputRef = useRef<HTMLInputElement>(null);

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

  const pendingCount = files.filter((f) => f.status === "pending").length;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>上传小说</DialogTitle>
          <DialogDescription>
            上传中文网络小说，开始分析其叙事结构、情感走向和人物关系。
          </DialogDescription>
        </DialogHeader>

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

        {files.length > 0 && (
          <div className="space-y-2">
            <p className="text-sm font-medium text-text">
              待上传文件 ({files.length})
            </p>
            <AnimatePresence mode="popLayout">
              {files.map((file) => (
                <UploadFileListItem
                  key={file.id}
                  file={file}
                  onRemove={removeFile}
                />
              ))}
            </AnimatePresence>
          </div>
        )}

        <DialogFooter>
          {pendingCount > 0 && (
            <Button onClick={onContinue}>
              下一步：填写书籍信息
              <ChevronRight className="ml-1 h-4 w-4" />
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default UploadDialog;
