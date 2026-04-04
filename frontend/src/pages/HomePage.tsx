import { useEffect, useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { RefreshCw } from "lucide-react";
import { BookOpen } from "lucide-react";
import { Button } from "@/components/ui/button";
import { NovelCard, type NovelCardData } from "@/components/common/NovelCard";
import { UploadDialog, type UploadFileInfo } from "@/components/home/UploadDialog";
import { useHomeContext } from "@/components/layout/AppLayout";

import { getNovels, uploadNovel, deleteNovel } from "@/api/novels";
import type { Novel } from "@/api/types";
import { useNovelStore } from "@/store/novelStore";

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

function generateThemeColor(seed: string | undefined): string {
  if (!seed) return "hsl(0, 65%, 55%)";
  let hash = 0;
  for (let i = 0; i < seed.length; i++) {
    hash = seed.charCodeAt(i) + ((hash << 5) - hash);
    hash = hash & hash;
  }
  const hue = Math.abs(hash) % 360;
  return `hsl(${hue}, 65%, 55%)`;
}

function mapNovelToCardData(novel: Novel): NovelCardData {
  return {
    id: novel.novel_id,
    title: novel.title || novel.filename.replace(/\.txt$/, ""),
    author: novel.author || "未知作者",
    filename: novel.filename,
    fileSize: novel.file_size,
    updatedAt: novel.upload_time || new Date().toISOString(),
    themeColor: generateThemeColor(novel.novel_id),
  };
}

/* ------------------------------------------------------------------ */
/*  Component                                                         */
/* ------------------------------------------------------------------ */

export function HomePage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const homeContext = useHomeContext();
  const setNovelsCache = useNovelStore((s) => s.setNovelsCache);

  const page = homeContext?.page ?? 1;
  const uploadDialogOpen = homeContext?.uploadDialogOpen ?? false;
  const openUploadDialog = homeContext?.openUploadDialog;
  const closeUploadDialog = homeContext?.closeUploadDialog;
  const setTotal = homeContext?.setTotal;
  const setIsLoading = homeContext?.setIsLoading;
  const setTotalPages = homeContext?.setTotalPages;

  const [uploadFiles, setUploadFiles] = useState<UploadFileInfo[]>([]);

  const { data: novelsData, isLoading, isError, refetch } = useQuery({
    queryKey: ["novels", page],
    queryFn: () => getNovels({ page, page_size: 10 }),
  });

  const novels = useMemo(
    () => novelsData?.items ?? [],
    [novelsData?.items]
  );
  const total = novelsData?.total ?? 0;
  const totalPages = novelsData?.total_pages ?? 1;

  // 同步小说列表到 store 缓存（供 TopBar 面包屑等跨页面复用）
  useEffect(() => {
    if (novels.length > 0) {
      setNovelsCache(novels);
    }
  }, [novels, setNovelsCache]);

  useEffect(() => {
    if (setTotal) setTotal(total);
    if (setIsLoading) setIsLoading(isLoading);
    if (setTotalPages) setTotalPages(totalPages);
  }, [total, isLoading, totalPages, setTotal, setIsLoading, setTotalPages]);

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
          closeUploadDialog?.();
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
          <h2 className="mb-4 text-2xl font-bold text-text">加载失败</h2>
          <p className="mb-6 text-text-secondary">无法加载小说列表，请稍后重试。</p>
          <Button onClick={() => refetch()} variant="outline">
            <RefreshCw className="mr-2 h-4 w-4" />
            重试
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto p-8">
      {isLoading ? (
        <div className="grid gap-5 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
          {Array.from({ length: 10 }).map((_, i) => (
            <div key={i} className="aspect-[2/3] animate-pulse rounded-lg bg-surface-hover" />
          ))}
        </div>
      ) : novels.length === 0 ? (
        <div className="flex h-full items-center justify-center">
          <div className="text-center">
            <BookOpen className="mx-auto mb-4 h-12 w-12 text-text-muted/30" />
            <p className="text-lg text-text-secondary">还没有小说</p>
            <p className="mt-1 text-sm text-text-muted">点击左侧「上传小说」开始分析</p>
          </div>
        </div>
      ) : (
        <div className="grid gap-5 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
          {novelCards.map((novel, index) => (
            <NovelCard
              key={novel.id ?? `novel-${index}`}
              novel={novel}
              onView={(id) => navigate(`/novels/${id}`)}
              onDelete={(id) => deleteMutation.mutate(id)}
            />
          ))}
        </div>
      )}

      <UploadDialog
        open={uploadDialogOpen}
        onOpenChange={(open) => {
          if (open) openUploadDialog?.();
          else closeUploadDialog?.();
        }}
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
