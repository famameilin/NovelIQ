import { useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { motion } from "framer-motion";
import { Plus, RefreshCw } from "lucide-react";

import { PageContainer } from "@/components/layout/PageContainer";
import { Button } from "@/components/ui/button";
import { HeroSection } from "@/components/home/HeroSection";
import { NovelGrid } from "@/components/home/NovelGrid";
import { UploadDialog, type UploadFileInfo } from "@/components/home/UploadDialog";

import { getNovels, uploadNovel, deleteNovel } from "@/api/novels";
import type { Novel, NovelCardData } from "@/api/types";

/* ------------------------------------------------------------------ */
/*  Utils                                                             */
/* ------------------------------------------------------------------ */

function mapNovelToCardData(novel: Novel): NovelCardData {
  return {
    id: novel.id,
    title: novel.title,
    author: undefined,
    filename: novel.filename,
    status: "pending",
    updatedAt: novel.upload_time,
    themeColor: undefined,
  };
}

/* ------------------------------------------------------------------ */
/*  Component                                                         */
/* ------------------------------------------------------------------ */

export function HomePage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  // State
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false);
  const [uploadFiles, setUploadFiles] = useState<UploadFileInfo[]>([]);

  // Queries
  const {
    data: novels = [],
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: ["novels"],
    queryFn: getNovels,
  });

  // Mutations
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
      const failCount = results.length - successCount;

      if (successCount > 0) {
        toast.success(`成功上传 ${successCount} 本小说`);
        queryClient.invalidateQueries({ queryKey: ["novels"] });
      }

      if (failCount > 0) {
        toast.error(`${failCount} 本小说上传失败`);
      }

      if (failCount === 0) {
        setTimeout(() => {
          setUploadDialogOpen(false);
          setUploadFiles([]);
        }, 1000);
      }
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : "上传失败");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteNovel,
    onSuccess: () => {
      toast.success("小说已删除");
      queryClient.invalidateQueries({ queryKey: ["novels"] });
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : "删除失败");
    },
  });

  // Handlers
  const handleViewNovel = useCallback(
    (id: string) => {
      navigate(`/novels/${id}`);
    },
    [navigate]
  );

  const handleDeleteNovel = useCallback(
    (id: string) => {
      deleteMutation.mutate(id);
    },
    [deleteMutation]
  );

  const handleOpenUpload = useCallback(() => {
    setUploadFiles([]);
    setUploadDialogOpen(true);
  }, []);

  const handleUploadFilesChange = useCallback((files: UploadFileInfo[]) => {
    setUploadFiles(files);
  }, []);

  const handleUpload = useCallback(async () => {
    await uploadMutation.mutateAsync(uploadFiles);
  }, [uploadFiles, uploadMutation]);

  // Map novels to card data
  const novelCards: NovelCardData[] = novels.map(mapNovelToCardData);

  // Error state
  if (isError) {
    return (
      <PageContainer className="flex flex-col items-center justify-center py-20">
        <div className="text-center">
          <h2 className="mb-4 text-2xl font-bold text-text">加载失败</h2>
          <p className="mb-6 text-text-secondary">
            无法加载小说列表，请稍后重试。
          </p>
          <Button onClick={() => refetch()} variant="outline">
            <RefreshCw className="mr-2 h-4 w-4" />
            重试
          </Button>
        </div>
      </PageContainer>
    );
  }

  return (
    <PageContainer>
      {/* Hero Section */}
      <HeroSection
        onUpload={handleOpenUpload}
        novelCount={novels.length}
        className="mb-10"
      />

      {/* Novels Grid Section */}
      <section id="novels-grid" className="scroll-mt-8">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h2 className="text-xl font-semibold text-text">我的小说</h2>
            <p className="text-sm text-text-muted">
              {isLoading ? "加载中..." : `共 ${novels.length} 本小说`}
            </p>
          </div>

          <Button onClick={handleOpenUpload} className="gap-2">
            <Plus className="h-4 w-4" />
            上传小说
          </Button>
        </div>

        <NovelGrid
          novels={novelCards}
          isLoading={isLoading}
          onView={handleViewNovel}
          onDelete={handleDeleteNovel}
          onUpload={handleOpenUpload}
        />
      </section>

      {/* Upload Dialog */}
      <UploadDialog
        open={uploadDialogOpen}
        onOpenChange={setUploadDialogOpen}
        files={uploadFiles}
        onFilesChange={handleUploadFilesChange}
        onUpload={handleUpload}
      />
    </PageContainer>
  );
}

export default HomePage;
