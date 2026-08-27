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

// GET /api/novels/:novelId - 详情页与面包屑使用的小说详情
export const novelDetailHandler = http.get(`${BASE}/api/novels/:novelId`, async ({ params }) => {
  await delay(150);
  const novel = novelDb.get(params.novelId as string);
  if (!novel) {
    return HttpResponse.json({ detail: `小说不存在: ${params.novelId}` }, { status: 404 });
  }
  return HttpResponse.json(novel);
});

// GET /api/novels/:novelId/cover - 首页卡片使用的稳定 mock 封面
export const novelCoverHandler = http.get(`${BASE}/api/novels/:novelId/cover`, async ({ params }) => {
  await delay(100);
  const novel = novelDb.get(params.novelId as string);
  if (!novel) {
    return HttpResponse.json({ detail: `小说不存在: ${params.novelId}` }, { status: 404 });
  }

  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 480 720">
    <defs>
      <linearGradient id="cover" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stop-color="#0f766e"/>
        <stop offset="100%" stop-color="#164e63"/>
      </linearGradient>
    </defs>
    <rect width="480" height="720" fill="url(#cover)"/>
    <rect x="28" y="28" width="424" height="664" rx="16" fill="none" stroke="#ccfbf1" stroke-opacity=".55" stroke-width="3"/>
    <text x="240" y="360" fill="#f0fdfa" font-size="34" font-family="sans-serif" text-anchor="middle">${novel.title}</text>
  </svg>`;

  return new HttpResponse(svg, {
    headers: { "Content-Type": "image/svg+xml; charset=utf-8" },
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
