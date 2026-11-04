import { useRef } from "react";
import { AnimatePresence } from "framer-motion";
import { ArrowLeft, ImagePlus, Upload, X } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { appConfig } from "@/config";
import { UploadFileListItem } from "./UploadFileListItem";
import type { NovelMetadata, UploadFileInfo } from "./uploadTypes";

export interface NovelInfoDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  files: UploadFileInfo[];
  metadata: Record<string, NovelMetadata>;
  isUploading: boolean;
  onMetadataChange: (fileId: string, patch: Partial<NovelMetadata>) => void;
  onCoverSelect: (fileId: string, cover: File) => void;
  onCoverRemove: (fileId: string) => void;
  onBack: () => void;
  onUpload: () => void;
  onCancelUpload: () => void;
}

function CoverPicker({
  previewUrl,
  onSelect,
  onRemove,
}: {
  previewUrl: string | null;
  onSelect: (file: File) => void;
  onRemove: () => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);

  return (
    <div className="relative shrink-0">
      <input
        ref={inputRef}
        type="file"
        accept={appConfig.acceptedCoverTypes.join(",")}
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onSelect(file);
          e.target.value = "";
        }}
      />
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        className="flex h-24 w-16 items-center justify-center overflow-hidden rounded-lg border border-dashed border-border bg-surface-hover text-text-muted transition-colors hover:border-primary/40 hover:text-text"
      >
        {previewUrl ? (
          <img src={previewUrl} alt="封面预览" className="h-full w-full object-cover" />
        ) : (
          <span className="flex flex-col items-center gap-1 text-[10px]">
            <ImagePlus className="h-5 w-5" />
            选择封面
          </span>
        )}
      </button>
      {previewUrl && (
        <button
          type="button"
          onClick={onRemove}
          className="absolute -right-1.5 -top-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-surface text-text-muted shadow-sm transition-colors hover:text-text"
        >
          <X className="h-3 w-3" />
        </button>
      )}
    </div>
  );
}

export function NovelInfoDialog({
  open,
  onOpenChange,
  files,
  metadata,
  isUploading,
  onMetadataChange,
  onCoverSelect,
  onCoverRemove,
  onBack,
  onUpload,
  onCancelUpload,
}: NovelInfoDialogProps) {
  const editableFiles = files.filter((f) => f.status === "pending" || f.status === "error");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>填写书籍信息</DialogTitle>
          <DialogDescription>
            书名、作者与封面都可以不填，书名留空时使用文件名。
          </DialogDescription>
        </DialogHeader>

        {isUploading ? (
          <div className="space-y-2">
            <p className="text-sm font-medium text-text">正在上传</p>
            <AnimatePresence mode="popLayout">
              {files.map((file) => (
                <UploadFileListItem key={file.id} file={file} />
              ))}
            </AnimatePresence>
          </div>
        ) : (
          <div className="max-h-[50vh] space-y-3 overflow-y-auto pr-1">
            {editableFiles.map((file) => {
              const draft = metadata[file.id];
              return (
                <div key={file.id} className="rounded-xl border border-border p-3">
                  <p className="mb-2 truncate text-xs text-text-muted">{file.file.name}</p>
                  <div className="flex gap-3">
                    <CoverPicker
                      previewUrl={draft?.coverPreviewUrl ?? null}
                      onSelect={(cover) => onCoverSelect(file.id, cover)}
                      onRemove={() => onCoverRemove(file.id)}
                    />
                    <div className="flex min-w-0 flex-1 flex-col gap-2">
                      <Input
                        value={draft?.title ?? ""}
                        onChange={(e) => onMetadataChange(file.id, { title: e.target.value })}
                        placeholder="书名"
                        className="h-9"
                      />
                      <Input
                        value={draft?.author ?? ""}
                        onChange={(e) => onMetadataChange(file.id, { author: e.target.value })}
                        placeholder="作者（可选）"
                        className="h-9"
                      />
                    </div>
                  </div>
                  {file.status === "error" && file.error && (
                    <p className="mt-2 text-xs text-chart-negative">{file.error}</p>
                  )}
                </div>
              );
            })}
          </div>
        )}

        <DialogFooter>
          {isUploading ? (
            <Button variant="destructive" size="sm" onClick={onCancelUpload}>
              <X className="mr-2 h-4 w-4" />
              取消上传
            </Button>
          ) : (
            <>
              <Button variant="outline" size="sm" onClick={onBack}>
                <ArrowLeft className="mr-2 h-4 w-4" />
                返回
              </Button>
              <Button onClick={onUpload} disabled={editableFiles.length === 0}>
                <Upload className="mr-2 h-4 w-4" />
                开始上传
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default NovelInfoDialog;
