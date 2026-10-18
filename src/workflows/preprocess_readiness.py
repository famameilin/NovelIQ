"""预处理恢复条件；完整性由工作流按当前配置判定"""

from sqlalchemy.orm import Session

from src.config import settings
from src.storage.repositories.chapter_repository import ChapterRepository
from src.storage.repositories.paragraph import (
    get_incomplete_paragraph_embedding_paragraph_ids,
    has_paragraph_embeddings,
)
from src.storage.repositories.paragraph_repository import ParagraphRepository
from src.storage.vector_schema import validate_paragraph_embeddings_schema


def is_preprocess_complete(session: Session, run_id: str) -> bool:
    """
    检查预处理阶段是否完成

    当当前配置要求语义原文定位时，完成判定要求正文切片与 paragraph embedding
    schema/数据完整就绪，避免半成品 run 被误判为 preprocess 已完成

    RAG 粒度固定为一个自然段：只检查 paragraph embeddings
    """
    if not ChapterRepository(session).has_chapters(run_id):
        return False

    # 段落事实源完整性：paragraphs 是 run 内段落身份的唯一事实源，
    # 无段落行的 run 一律视为 preprocess 未完成，避免旧 run 缺段落仍被判定为可跳过
    paragraph_repo = ParagraphRepository(session)
    if not paragraph_repo.has_paragraphs(run_id):
        return False

    # 指标与曲线在 paragraphs 提交之后才分段提交，二者缺一即判定未完成
    # （preprocess 无条件生成，缺行说明是崩溃窗口内的半成品 run），触发完整重跑补全
    if not paragraph_repo.has_paragraph_metrics(run_id):
        return False
    if not paragraph_repo.has_paragraph_curves(run_id):
        return False

    if not settings.models.paragraph_embedding.semantic_enabled:
        return True

    try:
        validate_paragraph_embeddings_schema(session)
    except ValueError:
        # 只要当前运行环境要求语义原文定位，而 schema 尚未就绪，就不能跳过 preprocess；
        # 否则会把缺向量的半成品 run 当成完成态，后续直接卡在 readiness
        return False

    if not has_paragraph_embeddings(session, run_id):
        return False
    if get_incomplete_paragraph_embedding_paragraph_ids(session, run_id):
        return False
    return True
