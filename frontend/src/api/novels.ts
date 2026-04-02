import { apiClient } from "./client";
import type { Novel, NovelUploadResponse, BatchDeleteRequest, BatchDeleteResponse } from "./types";

export async function getNovels(): Promise<Novel[]> {
  const { data } = await apiClient.get<Novel[]>("/api/novels/");
  return data;
}

export async function uploadNovel(file: File): Promise<NovelUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  const { data } = await apiClient.post<NovelUploadResponse>(
    "/api/novels/upload",
    formData,
    { headers: { "Content-Type": "multipart/form-data" } }
  );
  return data;
}

export async function deleteNovel(novelId: string): Promise<void> {
  await apiClient.delete(`/api/novels/${novelId}`);
}

export async function batchDeleteNovels(
  novelIds: string[]
): Promise<BatchDeleteResponse> {
  const { data } = await apiClient.post<BatchDeleteResponse>(
    "/api/novels/batch-delete",
    { novel_ids: novelIds } satisfies BatchDeleteRequest
  );
  return data;
}
