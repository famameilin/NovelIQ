from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from loguru import logger

from src.api.dependencies import get_novel_service, get_task_manager
from src.api.exceptions import NovelNotFoundError
from src.api.models.responses import (
    BatchDeleteNovelsRequest,
    BatchDeleteNovelsResponse,
    UploadResponse,
)
from src.api.services.novel_service import NovelService
from src.api.services.task_manager import TaskManager

router = APIRouter(prefix="/novels", tags=["novels"])


@router.post("/upload", response_model=UploadResponse)
async def upload_novel(
    file: UploadFile = File(...),
    service: NovelService = Depends(get_novel_service),
) -> UploadResponse:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件内容不能为空")
    novel_id = await service.save_upload(content, file.filename or "unknown.txt")
    return UploadResponse(novel_id=novel_id, filename=file.filename or "unknown.txt")


@router.get("/")
async def list_novels(
    page: int = 1,
    page_size: int = 12,
    service: NovelService = Depends(get_novel_service),
):
    """
    列出所有小说

    2026-08-20 阶段 3.2：消除 N+1 查询，list_novels 已优化为单次 JOIN
    """
    if page < 1:
        raise HTTPException(status_code=422, detail="页码必须大于 0")
    if page_size < 1:
        raise HTTPException(status_code=422, detail="每页数量必须大于 0")
    if page_size > 100:
        raise HTTPException(status_code=422, detail="每页数量不能超过 100")

    novels = service.list_novels()
    total = len(novels)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "items": novels[start:end],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total > 0 else 0,
    }


@router.get("/{novel_id}")
async def get_novel(
    novel_id: str,
    service: NovelService = Depends(get_novel_service),  # noqa: B008
):
    try:
        return service.get_novel(novel_id)
    except NovelNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"小说不存在: {novel_id}") from exc


@router.delete("/{novel_id}")
async def delete_novel(
    novel_id: str,
    service: NovelService = Depends(get_novel_service),  # noqa: B008
    task_manager: TaskManager = Depends(get_task_manager),  # noqa: B008
):
    try:
        service.delete_novel(novel_id, task_manager=task_manager)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"message": "删除成功", "novel_id": novel_id}


@router.post("/batch-delete", response_model=BatchDeleteNovelsResponse)
async def batch_delete_novels(
    request: BatchDeleteNovelsRequest,
    service: NovelService = Depends(get_novel_service),
    task_manager: TaskManager = Depends(get_task_manager),  # noqa: B008
) -> BatchDeleteNovelsResponse:
    """
    批量删除小说

    批量删除指定的小说及其相关数据
    即使部分删除失败，也会继续处理其他小说
    """
    deleted_ids: list[str] = []
    failed_ids: list[dict[str, str]] = []

    for novel_id in request.novel_ids:
        try:
            service.delete_novel(novel_id, task_manager=task_manager)
            deleted_ids.append(novel_id)
            logger.info(f"Batch delete: novel {novel_id} deleted successfully")
        except NovelNotFoundError as e:
            failed_ids.append({"novel_id": novel_id, "reason": str(e)})
            logger.warning(f"Batch delete: novel {novel_id} not found")
        except ValueError as e:
            failed_ids.append({"novel_id": novel_id, "reason": str(e)})
            logger.warning(f"Batch delete: novel {novel_id} rejected - {e}")
        except Exception as e:
            failed_ids.append({"novel_id": novel_id, "reason": f"删除失败: {e}"})
            logger.error(f"Batch delete: failed to delete novel {novel_id}: {e}")

    total_count = len(request.novel_ids)
    deleted_count = len(deleted_ids)
    failed_count = len(failed_ids)

    if deleted_count == total_count:
        message = f"成功删除 {deleted_count} 本小说"
        success = True
    elif deleted_count > 0:
        message = f"部分删除成功: {deleted_count} 本成功, {failed_count} 本失败"
        success = True
    else:
        message = f"删除失败: {failed_count} 本小说无法删除"
        success = False

    return BatchDeleteNovelsResponse(
        success=success,
        message=message,
        deleted_count=deleted_count,
        failed_count=failed_count,
        deleted_ids=deleted_ids,
        failed_ids=failed_ids,
    )
