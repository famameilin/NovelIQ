"上传流程共享的普通类型定义"

export interface UploadFileInfo {
  file: File;
  id: string;
  status: "pending" | "uploading" | "success" | "error";
  progress: number;
  error?: string;
}

export interface NovelMetadata {
  title: string;
  author: string;
  coverFile: File | null;
  coverPreviewUrl: string | null;
}
