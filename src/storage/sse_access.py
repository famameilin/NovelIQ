"""实际展示消息的持久化接口"""

from src.storage.input_boundary import plain_inputs
from src.storage.repositories.event_outbox import OutboxRecords, replay_candidates


@plain_inputs
class SseAccess:
    def __init__(self, runner):
        self._runner = runner

    def reserve_sequence(self, task_id: str, message_id: str) -> int:
        "仅分配展示游标，消息主键仍由 Storage 生成"
        return self._runner.run(lambda session: OutboxRecords(session).reserve_sequence(task_id, message_id))

    def emit(self, task_id: str, event_type: str, data: dict, *, sequence: int | None = None) -> dict:
        "原始消息字节、路由和幂等键在一个事务内保存"
        return self._runner.run(
            lambda session: OutboxRecords(session).emit(task_id, event_type, data, sequence=sequence)
        )

    def replay_candidates(
        self,
        run_id: str,
        after_seq: int,
        restart_sequence: int,
        chapter_resets: dict,
        task_state_events: set,
        *,
        limit: int = 128,
    ):
        "按固定路由条件分页读取普通消息记录"
        return self._runner.run(
            lambda session: replay_candidates(
                session, run_id, after_seq, restart_sequence, chapter_resets, task_state_events, limit
            ),
            read_only=True,
        )
