/**
 * MSW Handler — 小说上传、列表、删除
 */
import { http, HttpResponse, delay } from "msw";
import { novelDb, novelList, createNovel } from "../data";

const BASE = import.meta.env.VITE_API_BASE_URL || "";

// GET /api/novels/ — 分页列表
export const novelListHandler = http.get(`${BASE}/api/novels/`, async ({ request }) => {
  await delay(300);
  const url = new URL(request.url);
  const page = Number(url.searchParams.get("page")) || 1;
  const pageSize = Number(url.searchParams.get("page_size")) || 12;

  const start = (page - 1) * pageSize;
  const items = novelList.slice(start, start + pageSize);

  return HttpResponse.json({
    items,
    total: novelList.length,
    page,
    page_size: pageSize,
    total_pages: Math.ceil(novelList.length / pageSize),
  });
});

// POST /api/novels/upload — 上传文件
export const novelUploadHandler = http.post(`${BASE}/api/novels/upload`, async ({ request }) => {
  await delay(800);

  const formData = await request.formData();
  const file = formData.get("file") as File | null;

  if (!file) {
    return HttpResponse.json({ detail: "未提供文件" }, { status: 400 });
  }

  const title = file.name.replace(/\.txt$/i, "");
  const novel = createNovel({
    title,
    filename: file.name,
    file_size: file.size,
    upload_time: new Date().toISOString(),
  });

  novelDb.set(novel.novel_id, novel);
  novelList.unshift(novel);

  return HttpResponse.json({
    novel_id: novel.novel_id,
    title: novel.title,
    message: "上传成功",
  });
});

// 删除 /api/novels/:novelId
export const novelDeleteHandler = http.delete(`${BASE}/api/novels/:novelId`, async ({ params }) => {
  await delay(200);
  const { novelId } = params;

  const idx = novelList.findIndex((n) => n.novel_id === novelId);
  if (idx !== -1) {
    novelList.splice(idx, 1);
    novelDb.delete(novelId as string);
  }

  return new HttpResponse(null, { status: 204 });
});

// POST /api/novels/batch-delete（批量删除）
export const novelBatchDeleteHandler = http.post(`${BASE}/api/novels/batch-delete`, async ({ request }) => {
  await delay(300);
  const body = await request.json() as { novel_ids: string[] };
  const deleted: string[] = [];
  const failed: string[] = [];

  for (const id of body.novel_ids) {
    const idx = novelList.findIndex((n) => n.novel_id === id);
    if (idx !== -1) {
      novelList.splice(idx, 1);
      novelDb.delete(id);
      deleted.push(id);
    } else {
      failed.push(id);
    }
  }

  return HttpResponse.json({ deleted, failed });
});
