import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { RefreshCw, BookOpen, Upload, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { NovelCard, type NovelCardData } from "@/components/common/NovelCard";
import { UploadDialog, type UploadFileInfo } from "@/components/home/UploadDialog";

import { getNovels, uploadNovel, deleteNovel } from "@/api/novels";
import type { Novel } from "@/api/types";

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

// 生成随机主题色
function generateThemeColor(): string {
  const hue = Math.floor(Math.random() * 360);
  return `hsl(${hue}, 70%, 50%)`;
}

// 映射 Novel 到 NovelCardData
function mapNovelToCardData(novel: Novel): NovelCardData {
  return {
    id: novel.id,
    title: novel.title,
    author: undefined, // 后端未返回作者信息
    filename: novel.filename,
    fileSize: novel.file_size,
    status: "pending", // 后端未返回状态，默认 pending
    updatedAt: novel.upload_time,
    themeColor: generateThemeColor(), // 生成随机主题色增加辨识度
  };
}

/* ------------------------------------------------------------------ */
/*  Component                                                         */
/* ------------------------------------------------------------------ */

export function HomePage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false);
  const [uploadFiles, setUploadFiles] = useState<UploadFileInfo[]>([]);
  const [page, setPage] = useState(1);

  const { data: novelsData, isLoading, isError, refetch } = useQuery({
    queryKey: ["novels", page],
    queryFn: () => getNovels({ page, page_size: 10 }),
  });

  const novels = novelsData?.items ?? [];
  const total = novelsData?.total ?? 0;
  const totalPages = novelsData?.total_pages ?? 1;

  const uploadMutation = useMutation({
    mutationFn: async (files: UploadFileInfo[]) => {
      const results = [];
      for (const fileInfo of files) {
        if (fileInfo.status !== "pending") continue;
        try {
          const result = await uploadNovel(fileInfo.file);
          results.push({ success: true, result });
        } catch (error) {
          results.push({
            success: false,
            error: error instanceof Error ? error.message : "上传失败",
          });
        }
      }
      return results;
    },
    onSuccess: (results) => {
      const successCount = results.filter((r) => r.success).length;
      if (successCount > 0) {
        toast.success(`成功上传 ${successCount} 本小说`);
        queryClient.invalidateQueries({ queryKey: ["novels"] });
      }
      const failCount = results.length - successCount;
      if (failCount > 0) toast.error(`${failCount} 本小说上传失败`);
      if (failCount === 0) {
        setTimeout(() => {
          setUploadDialogOpen(false);
          setUploadFiles([]);
        }, 1000);
      }
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteNovel,
    onSuccess: () => {
      toast.success("小说已删除");
      queryClient.invalidateQueries({ queryKey: ["novels"] });
    },
  });

  const novelCards: NovelCardData[] = novels.map((n) => mapNovelToCardData(n));

  if (isError) {
    return (
      <div className="flex h-full w-full items-center justify-center">
        <div className="text-center">
          <h2 className="mb-4 text-2xl font-bold text-gray-900 dark:text-gray-100">加载失败</h2>
          <p className="mb-6 text-gray-600 dark:text-gray-400">无法加载小说列表，请稍后重试。</p>
          <Button onClick={() => refetch()} variant="outline">
            <RefreshCw className="mr-2 h-4 w-4" />
            重试
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full w-full overflow-hidden bg-gradient-to-br from-background via-background to-primary/5">
      {/* 左侧内容区 */}
      <aside className="relative flex w-96 shrink-0 flex-col border-r border-border/50 overflow-hidden">
        {/* 渐变背景 */}
        <div className="absolute inset-0 bg-gradient-to-br from-primary/10 via-surface to-chart-2/5" />
        <div className="absolute -right-20 -top-20 h-64 w-64 rounded-full bg-primary/10 blur-3xl" />
        <div className="absolute -bottom-10 left-10 h-48 w-48 rounded-full bg-chart-2/10 blur-2xl" />

        {/* 内容 */}
        <div className="relative z-10 flex flex-1 flex-col p-8">
          {/* Logo */}
          <div className="mb-8 flex items-center gap-3">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-lg shadow-primary/20">
              <BookOpen className="h-6 w-6" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100">小说分析</h1>
              <p className="text-xs text-gray-600 dark:text-gray-400">AI 驱动的网文分析</p>
            </div>
          </div>

          {/* 主标题 */}
          <div className="mb-8">
            <div className="mb-4 inline-flex items-center gap-2 rounded-full bg-primary/10 px-3 py-1.5 border border-primary/20">
              <Sparkles className="h-4 w-4 text-primary" />
              <span className="text-sm font-medium text-primary">探索叙事的奥秘</span>
            </div>
            <h2 className="text-3xl font-bold leading-tight text-gray-900 dark:text-gray-100">
              上传中文网络小说，
              <br />
              <span className="bg-gradient-to-r from-primary to-chart-2 bg-clip-text text-transparent">
                开启 AI 分析之旅
              </span>
            </h2>
            <p className="mt-3 text-sm text-text-secondary leading-relaxed">
              自动分析叙事结构、情感走向、人物关系和文化元素，帮助你更深入地理解作品。
            </p>
          </div>

          {/* 统计 */}
          <div className="mb-6 rounded-xl bg-surface/50 backdrop-blur-sm p-4 border border-border/50">
            <div className="flex items-center gap-2 text-sm text-text-muted mb-1">
              <BookOpen className="h-4 w-4" />
              <span>已上传小说</span>
            </div>
            <p className="text-4xl font-bold text-text">{isLoading ? "..." : total}</p>
          </div>

          {/* 上传按钮 */}
          <Button
            onClick={() => setUploadDialogOpen(true)}
            size="lg"
            className="w-full gap-2 shadow-lg shadow-primary/20"
          >
            <Upload className="h-5 w-5" />
            上传小说
          </Button>

          {/* 分页 */}
          {totalPages > 1 && (
            <div className="mt-auto pt-6">
              <div className="flex items-center justify-between">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page <= 1}
                  onClick={() => setPage(page - 1)}
                >
                  上一页
                </Button>
                <span className="text-sm text-text-muted">
                  {page} / {totalPages}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page >= totalPages}
                  onClick={() => setPage(page + 1)}
                >
                  下一页
                </Button>
              </div>
            </div>
          )}
        </div>
      </aside>

      {/* 右侧网格区 */}
      <div className="min-h-0 flex-1 overflow-auto p-8">
        {isLoading ? (
          <div className="grid gap-5 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
            {Array.from({ length: 10 }).map((_, i) => (
              <div key={i} className="aspect-[2/3] animate-pulse rounded-lg bg-surface-hover" />
            ))}
          </div>
        ) : novels.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center">
            <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-primary/10">
              <BookOpen className="h-8 w-8 text-primary" />
            </div>
            <h3 className="mb-1 text-lg font-semibold text-gray-900 dark:text-gray-100">书架是空的</h3>
            <p className="mb-6 text-sm text-gray-600 dark:text-gray-400">上传你的第一本小说开始分析</p>
            <Button onClick={() => setUploadDialogOpen(true)} className="gap-2">
              <Upload className="h-4 w-4" />
              上传小说
            </Button>
          </div>
        ) : (
          <div className="grid gap-5 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
            {novelCards.map((novel) => (
              <NovelCard
                key={novel.id}
                novel={novel}
                onView={(id) => navigate(`/novels/${id}`)}
                onDelete={(id) => deleteMutation.mutate(id)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Upload Dialog */}
      <UploadDialog
        open={uploadDialogOpen}
        onOpenChange={setUploadDialogOpen}
        files={uploadFiles}
        onFilesChange={setUploadFiles}
        onUpload={async () => {
          await uploadMutation.mutateAsync(uploadFiles);
        }}
      />
    </div>
  );
}

export default HomePage;
