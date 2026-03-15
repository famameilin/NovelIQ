from __future__ import annotations

from fastapi import APIRouter, UploadFile, File, Depends
from pathlib import Path

from src.api.models.responses import UploadResponse
from src.api.services.novel_service import NovelService

router = APIRouter(prefix="/novels", tags=["novels"])

_upload_dir = Path("data/uploads")
_novel_service = NovelService(_upload_dir)


def get_novel_service() -> NovelService:
    return _novel_service


@router.post("/upload", response_model=UploadResponse)
async def upload_novel(
    file: UploadFile = File(...), service: NovelService = Depends(get_novel_service)
) -> UploadResponse:
    content = await file.read()
    novel_id = await service.save_upload(content, file.filename or "unknown.txt")
    return UploadResponse(novel_id=novel_id, filename=file.filename or "unknown.txt")


@router.get("/")
async def list_novels(service: NovelService = Depends(get_novel_service)):
    return service.list_novels()


@router.delete("/{novel_id}")
async def delete_novel(novel_id: str, service: NovelService = Depends(get_novel_service)):
    service.delete_novel(novel_id)
    return {"message": "删除成功", "novel_id": novel_id}
