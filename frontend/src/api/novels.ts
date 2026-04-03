import { apiClient } from "./client";
import type {
  Novel,
  NovelUploadResponse,
  BatchDeleteRequest,
  BatchDeleteResponse,
  PaginatedResponse,
} from "./types";

export interface GetNovelsParams {
  page?: number;
  page_size?: number;
}

export async function getNovels(
  params: GetNovelsParams = {}
): Promise<PaginatedResponse<Novel>> {
  const { page = 1, page_size = 12 } = params;
  const { data } = await apiClient.get<PaginatedResponse<Novel>>("/api/novels/", {
    params: { page, page_size },
  });
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
