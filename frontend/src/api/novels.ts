import axios from "axios";
import { apiClient } from "./client";
import type {
  Novel,
  NovelUploadResponse,
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

export async function getNovel(novelId: string): Promise<Novel | null> {
  try {
    const { data } = await apiClient.get<Novel>(`/api/novels/${novelId}`);
    return data;
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 404) {
      return null;
    }
    throw error;
  }
}

export interface UploadNovelOptions {
  signal?: AbortSignal;
  title?: string;
  author?: string;
  cover?: File | null;
}

export async function uploadNovel(
  file: File,
  options: UploadNovelOptions = {}
): Promise<NovelUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  if (options.title) formData.append("title", options.title);
  if (options.author) formData.append("author", options.author);
  if (options.cover) formData.append("cover", options.cover);
  const { data } = await apiClient.post<NovelUploadResponse>(
    "/api/novels/upload",
    formData,
    {
      headers: { "Content-Type": "multipart/form-data" },
      signal: options.signal,
    }
  );
  return data;
}

export async function deleteNovel(novelId: string): Promise<void> {
  await apiClient.delete(`/api/novels/${novelId}`);
}
