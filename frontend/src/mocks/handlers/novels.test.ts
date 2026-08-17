import { beforeEach, describe, expect, it } from "vitest";

import type { Novel } from "@/api/types";
import { novelCoverHandler, novelDetailHandler } from "./novels";
import { novelDb } from "../data";

const KNOWN_NOVEL: Novel = {
  novel_id: "novel-handler-1",
  title: "测试之神",
  filename: "测试之神.txt",
  author: "某作者",
  upload_time: "2026-08-17T00:00:00.000Z",
  file_size: 12345,
};

function runHandler(
  handler: typeof novelDetailHandler,
  url: string,
): Promise<{ response: Response }> {
  return handler.run({ request: new Request(url) });
}

// MSW 相对路径解析到 jsdom 的 origin，请求 URL 必须与之一致才能命中
const ORIGIN = window.location.origin;

function novelUrl(novelId: string): string {
  return `${ORIGIN}/api/novels/${novelId}`;
}

function coverUrl(novelId: string): string {
  return `${ORIGIN}/api/novels/${novelId}/cover`;
}

describe("novelDetailHandler / novelCoverHandler", () => {
  beforeEach(() => {
    novelDb.clear();
    novelDb.set(KNOWN_NOVEL.novel_id, KNOWN_NOVEL);
  });

  it("详情接口命中已知小说时返回小说 JSON", async () => {
    const { response } = await runHandler(
      novelDetailHandler,
      novelUrl("novel-handler-1"),
    );

    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body.novel_id).toBe("novel-handler-1");
    expect(body.title).toBe("测试之神");
  });

  it("详情接口对未知小说返回 404", async () => {
    const { response } = await runHandler(
      novelDetailHandler,
      novelUrl("novel-missing"),
    );

    expect(response.status).toBe(404);
    const body = await response.json();
    expect(body.detail).toContain("novel-missing");
  });

  it("封面接口返回含小说标题的 SVG 与正确 Content-Type", async () => {
    const { response } = await runHandler(
      novelCoverHandler,
      coverUrl("novel-handler-1"),
    );

    expect(response.status).toBe(200);
    expect(response.headers.get("Content-Type")).toContain("image/svg+xml");
    const svg = await response.text();
    expect(svg).toContain("<svg");
    expect(svg).toContain("测试之神");
  });

  it("封面接口对未知小说返回 404", async () => {
    const { response } = await runHandler(
      novelCoverHandler,
      coverUrl("novel-missing"),
    );

    expect(response.status).toBe(404);
    const body = await response.json();
    expect(body.detail).toContain("novel-missing");
  });
});