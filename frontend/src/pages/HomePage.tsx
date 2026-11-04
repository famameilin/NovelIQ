import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { RefreshCw, BookOpen, Search, ArrowUpDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { NovelCard, type NovelCardData } from "@/components/common/NovelCard";
import { UploadDialog, type UploadFileInfo } from "@/components/home/UploadDialog";
import { NovelInfoDialog } from "@/components/home/NovelInfoDialog";
import type { NovelMetadata } from "@/components/home/uploadTypes";
import { useHomeContext } from "@/components/layout/AppLayout";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { getNovels, uploadNovel, deleteNovel, getNovel } from "@/api/novels";
import type { Novel } from "@/api/types";
import { useNovelStore } from "@/store/novelStore";
import { appConfig } from "@/config";

type SortKey = "title" | "updatedAt" | "wordCount";
type SortOrder = "asc" | "desc";

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
    wordCount: novel.word_count,
    updatedAt: novel.upload_time || new Date().toISOString(),
    themeColor: generateThemeColor(novel.novel_id),
  };
}

const SORT_OPTIONS: { value: SortKey; label: string }[] = [
  { value: "updatedAt", label: "最近上传" },
  { value: "title", label: "书名" },
  { value: "wordCount", label: "字数" },
];

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
  const [metadata, setMetadata] = useState<Record<string, NovelMetadata>>({});
  const [infoDialogOpen, setInfoDialogOpen] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("updatedAt");
  const [sortOrder, setSortOrder] = useState<SortOrder>("desc");

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

  const releasePreviews = (drafts: Record<string, NovelMetadata>) => {
    Object.values(drafts).forEach((draft) => {
      if (draft.coverPreviewUrl) URL.revokeObjectURL(draft.coverPreviewUrl);
    });
  };

  const openInfoStep = () => {
    const pending = uploadFiles.filter((fileInfo) => fileInfo.status === "pending");
    if (pending.length === 0) return;
    const drafts: Record<string, NovelMetadata> = {};
    for (const fileInfo of pending) {
      drafts[fileInfo.id] = {
        title: fileInfo.file.name.replace(/\.txt$/i, ""),
        author: "",
        coverFile: null,
        coverPreviewUrl: null,
      };
    }
    setMetadata(drafts);
    setInfoDialogOpen(true);
  };

  const backToFileStep = () => {
    releasePreviews(metadata);
    setMetadata({});
    setInfoDialogOpen(false);
  };

  const closeUploadFlow = () => {
    releasePreviews(metadata);
    setMetadata({});
    setInfoDialogOpen(false);
    closeUploadDialog?.();
    setUploadFiles([]);
  };

  const updateMetadata = (fileId: string, patch: Partial<NovelMetadata>) => {
    setMetadata((prev) => {
      const current = prev[fileId] ?? { title: "", author: "", coverFile: null, coverPreviewUrl: null };
      return { ...prev, [fileId]: { ...current, ...patch } };
    });
  };

  const selectCover = (fileId: string, cover: File) => {
    const extension = `.${cover.name.split(".").pop()?.toLowerCase()}`;
    if (!(appConfig.acceptedCoverTypes as readonly string[]).includes(extension)) {
      toast.error("封面只支持 jpg、png、webp");
      return;
    }
    if (cover.size > appConfig.maxCoverSizeBytes) {
      toast.error("封面不能超过 2 MB");
      return;
    }
    setMetadata((prev) => {
      const current = prev[fileId];
      if (current?.coverPreviewUrl) URL.revokeObjectURL(current.coverPreviewUrl);
      return {
        ...prev,
        [fileId]: {
          title: current?.title ?? "",
          author: current?.author ?? "",
          coverFile: cover,
          coverPreviewUrl: URL.createObjectURL(cover),
        },
      };
    });
  };

  const removeCover = (fileId: string) => {
    setMetadata((prev) => {
      const current = prev[fileId];
      if (current?.coverPreviewUrl) URL.revokeObjectURL(current.coverPreviewUrl);
      return {
        ...prev,
        [fileId]: {
          title: current?.title ?? "",
          author: current?.author ?? "",
          coverFile: null,
          coverPreviewUrl: null,
        },
      };
    });
  };

  const handleUpload = async () => {
    const targets = uploadFiles.filter((f) => f.status === "pending" || f.status === "error");
    if (targets.length === 0) return;

    const controller = new AbortController();
    abortRef.current = controller;
    setIsUploading(true);
    setUploadFiles((prev) =>
      prev.map((f) =>
        targets.some((t) => t.id === f.id)
          ? { ...f, status: "uploading" as const, progress: 0, error: undefined }
          : f
      )
    );

    let successCount = 0;
    let failureCount = 0;

    for (const fileInfo of targets) {
      try {
        const draft = metadata[fileInfo.id];
        await uploadNovel(fileInfo.file, {
          signal: controller.signal,
          title: draft?.title.trim() || undefined,
          author: draft?.author.trim() || undefined,
          cover: draft?.coverFile ?? null,
        });
        successCount += 1;
        setUploadFiles((prev) =>
          prev.map((f) =>
            f.id === fileInfo.id
              ? { ...f, status: "success" as const, progress: 100, error: undefined }
              : f
          )
        );
      } catch (error) {
        if (controller.signal.aborted) {
          setUploadFiles((prev) =>
            prev.map((f) =>
              f.id === fileInfo.id ? { ...f, status: "pending" as const, progress: 0 } : f
            )
          );
          break;
        }
        failureCount += 1;
        const message = error instanceof Error ? error.message : "上传失败";
        setUploadFiles((prev) =>
          prev.map((f) =>
            f.id === fileInfo.id
              ? { ...f, status: "error" as const, progress: 0, error: message }
              : f
          )
        );
      }
    }

    abortRef.current = null;
    setIsUploading(false);

    if (successCount > 0) {
      toast.success(`成功上传 ${successCount} 本小说`);
      queryClient.invalidateQueries({ queryKey: ["novels"] });
    }
    if (failureCount > 0) toast.error(`${failureCount} 本小说上传失败`);
    if (failureCount === 0) {
      closeUploadFlow();
    }
  };

  const handleCancelUpload = () => {
    abortRef.current?.abort();
  };

  const deleteMutation = useMutation({
    mutationFn: deleteNovel,
    onSuccess: () => {
      toast.success("小说已删除");
      queryClient.invalidateQueries({ queryKey: ["novels"] });
    },
  });

  const handlePrefetchNovel = useCallback(
    (novelId: string) => {
      queryClient.prefetchQuery({
        queryKey: ["novel", novelId],
        queryFn: () => getNovel(novelId),
        staleTime: appConfig.prefetchStaleTime,
      });
    },
    [queryClient]
  );

  const novelCards: NovelCardData[] = useMemo(() => {
    let cards = novels.map((n) => mapNovelToCardData(n));

    // 搜索过滤
    if (searchQuery.trim()) {
      const query = searchQuery.trim().toLowerCase();
      cards = cards.filter(
        (c) =>
          c.title.toLowerCase().includes(query) ||
          (c.author && c.author.toLowerCase().includes(query)) ||
          c.filename.toLowerCase().includes(query)
      );
    }

    // 排序
    cards = [...cards].sort((a, b) => {
      let cmp = 0;
      switch (sortKey) {
        case "title":
          cmp = a.title.localeCompare(b.title, "zh-CN");
          break;
        case "updatedAt":
          cmp = new Date(a.updatedAt).getTime() - new Date(b.updatedAt).getTime();
          break;
        case "wordCount":
          cmp = (a.wordCount ?? 0) - (b.wordCount ?? 0);
          break;
      }
      return sortOrder === "asc" ? cmp : -cmp;
    });

    return cards;
  }, [novels, searchQuery, sortKey, sortOrder]);

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
      {/* 搜索栏和排序 */}
      {!isLoading && novels.length > 0 && (
        <div className="mb-6 flex items-center gap-3">
          <div className="relative flex-1 max-w-xs">
            <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
            <Input
              placeholder="搜索书名、作者..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-8 h-9"
            />
          </div>
          <div className="flex items-center gap-1.5">
            <ArrowUpDown className="h-3.5 w-3.5 text-text-muted" />
            <Select
              value={sortKey}
              onValueChange={(v) => {
                setSortKey(v as SortKey);
                if (v === sortKey) setSortOrder((o) => (o === "asc" ? "desc" : "asc"));
                else setSortOrder("desc");
              }}
            >
              <SelectTrigger className="h-9 w-28">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SORT_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                    {sortKey === opt.value && (
                      <span className="ml-1 text-text-muted">
                        {sortOrder === "asc" ? "↑" : "↓"}
                      </span>
                    )}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      )}

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
              onPrefetch={handlePrefetchNovel}
              onDelete={(id) => {
                const title = novel.title || novel.filename;
                if (window.confirm(`确定要删除「${title}」吗？此操作不可恢复。`)) {
                  deleteMutation.mutate(id);
                }
              }}
            />
          ))}
        </div>
      )}

      <UploadDialog
        open={uploadDialogOpen && !infoDialogOpen}
        onOpenChange={(open) => {
          if (open) openUploadDialog?.();
          else closeUploadDialog?.();
        }}
        files={uploadFiles}
        onFilesChange={setUploadFiles}
        onContinue={openInfoStep}
      />

      <NovelInfoDialog
        open={uploadDialogOpen && infoDialogOpen}
        onOpenChange={(open) => {
          if (open) return;
          abortRef.current?.abort();
          closeUploadFlow();
        }}
        files={uploadFiles}
        metadata={metadata}
        isUploading={isUploading}
        onMetadataChange={updateMetadata}
        onCoverSelect={selectCover}
        onCoverRemove={removeCover}
        onBack={backToFileStep}
        onUpload={handleUpload}
        onCancelUpload={handleCancelUpload}
      />
    </div>
  );
}

export default HomePage;
