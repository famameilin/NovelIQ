"""预处理恢复条件；完整性由工作流按当前配置判定"""

from src.config import settings
from src.storage import Storage


def is_preprocess_complete(session: Storage, run_id: str) -> bool:
    """
    检查预处理阶段是否完成

    当当前配置要求语义原文定位时，完成判定不再只看正文切片，
    而是要求 paragraph embedding schema 与数据完整就绪，
    避免半成品 run 被误判为 preprocess 已完成

    RAG 粒度固定为一个自然段：只检查 paragraph embeddings，不再检查 chunk embeddings
    """
    if not session.chapters.has_chapters(run_id):
        return False

    # 段落事实源完整性：paragraphs 是 run 内段落身份的唯一事实源（设计文档 ），
    # 无段落行的 run 一律视为 preprocess 未完成，避免旧 run 缺段落仍被判定为可跳过
    paragraph_repo = session.paragraphs
    if not paragraph_repo.has_paragraphs(run_id):
        return False

    # 指标与曲线在 paragraphs 提交之后才分段提交，中间存在纯 CPU 窗口；
    # 只查段落行会把"窗口内被杀/崩溃的半成品 run"误判为 preprocess 完成，
    # 导致段落指标/曲线永久缺失。有段落行就必然有指标与曲线行（preprocess 无条件生成），
    # 二者缺一即判定未完成，触发完整重跑补全。
    if not paragraph_repo.has_paragraph_metrics(run_id):
        return False
    if not paragraph_repo.has_paragraph_curves(run_id):
        return False

    if not settings.models.paragraph_embedding.semantic_enabled:
        return True

    try:
        session.validate_paragraph_vectors()
    except ValueError:
        # 只要当前运行环境要求语义原文定位，而 schema 尚未就绪，就不能跳过 preprocess；
        # 否则会把缺向量的半成品 run 当成完成态，后续直接卡在 readiness
        return False

    if not session.paragraphs.has_paragraph_embeddings(run_id):
        return False
    if session.paragraphs.get_incomplete_paragraph_embedding_paragraph_ids(run_id):
        return False
    return True
