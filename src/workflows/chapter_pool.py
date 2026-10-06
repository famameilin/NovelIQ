"""角色 work 队列：只按模型池选举结果派发，按 work 成功事务保存"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy.orm import Session

from src.agents.annotation.work import WorkReceipt
from src.event_bus import EventBus, Message
from src.model_pool.capacity import ModelElectionPool
from src.storage.models import AnnotationWork

AgentStatus = Literal["submitted", "retry", "failed"]


class PipelineWorkFailed(RuntimeError):
    """必需 work 未成功保存，阻止进入后续分析阶段"""


class WorkSaveUnconfirmed(PipelineWorkFailed):
    """存储或内存确认仍不明，保留待保存贡献和当前容量，禁止当作模型失败重派"""


class ChapterWorkerPool:
    """队列不选择模型、不扣重派预算、不计算退避、不操作域状态"""

    def __init__(self, *, max_attempts: int = 3, poll_seconds: float = 0.1) -> None:
        self.max_attempts = max_attempts
        self.poll_seconds = poll_seconds
        self.owner = f"worker:{uuid4().hex}"
        self.states: dict[str, str] = {}
        self.invocations: dict[str, str] = {}

    async def run(
        self,
        work: list[WorkReceipt],
        *,
        bus: EventBus,
        session_factory: Callable[[], Session],
        is_cancelled: Callable[[], bool] | None = None,
        on_saved: Callable[[WorkReceipt], Any] | None = None,
    ) -> int:
        if not work:
            return 0
        run_id = work[0].run_id
        address = f"queue:{run_id}"
        models = ModelElectionPool(bus, run_id, max_attempts=self.max_attempts, poll_seconds=self.poll_seconds)
        assignments = bus.subscribe(models.assignment_topic)
        active: dict[str, asyncio.Task[bool]] = {}
        succeeded = 0
        stopping = False
        model_ended = False

        def may_start_save() -> bool:
            return not stopping and not (is_cancelled is not None and is_cancelled())

        async def started(message: Message) -> None:
            if message.work_id not in active:
                raise ValueError(f"未派发 work 的执行身份: {message.work_id}")
            self.invocations[message.work_id] = message.invocation_id

        bus.handle("queue.started", address, started)
        for receipt in work:
            self.states[receipt.work_id] = "queued"
            await bus.request(
                Message(
                    topic="pool.enqueue",
                    source=address,
                    target=models.address,
                    run_id=run_id,
                    work_id=receipt.work_id,
                    payload=receipt,
                )
            )
        model_task = asyncio.create_task(models.run())
        assignment_task = asyncio.create_task(assignments.get())

        async def attempt(receipt: WorkReceipt) -> bool:
            outcome = "failed"
            invocation_id = ""
            release_capacity = True
            try:
                result = await bus.request(
                    Message(
                        topic="agent.execute",
                        source=address,
                        target=f"agent:{run_id}",
                        run_id=run_id,
                        work_id=receipt.work_id,
                        payload=receipt,
                    )
                )
                if model_ended:
                    return False
                invocation_id = result["invocation_id"]
                outcome = result["outcome"]
                if outcome == "retry":
                    self.states[receipt.work_id] = "queued"
                    # 回队头由队列维护，模型池保留此 work 原有预算与失败计数
                    await bus.request(
                        Message(
                            topic="pool.enqueue",
                            source=address,
                            target=models.address,
                            run_id=run_id,
                            work_id=receipt.work_id,
                            payload=receipt,
                        )
                    )
                    return False
                if outcome != "completed":
                    raise PipelineWorkFailed(f"work_id={receipt.work_id} outcome={outcome}")
                self.states[receipt.work_id] = "completed"
                save_task = asyncio.create_task(
                    self._save(
                        bus, address, receipt, invocation_id, session_factory, may_start_save, lambda: model_ended
                    )
                )
                try:
                    await asyncio.shield(save_task)
                except asyncio.CancelledError:
                    # 业务保存已开始，必须先核清实际结果再让取消离开该 work
                    await save_task
                    raise
                if model_ended:
                    return False
                self.states[receipt.work_id] = "saved"
                outcome = "saved"
                if on_saved is not None:
                    await on_saved(receipt)
                return True
            except WorkSaveUnconfirmed:
                # 未确认结果仍保留预留位，分析故障退出时再由模型池统一关闭
                release_capacity = False
                self.states[receipt.work_id] = "save_unconfirmed"
                raise
            finally:
                if release_capacity and not model_ended:
                    await bus.request(
                        Message(
                            topic="pool.feedback",
                            source=address,
                            target=models.address,
                            run_id=run_id,
                            work_id=receipt.work_id,
                            invocation_id=invocation_id,
                            payload={"reservation_id": receipt.payload["reservation_id"], "outcome": outcome},
                        )
                    )

        try:
            while succeeded < len(work):
                if is_cancelled is not None and is_cancelled():
                    raise asyncio.CancelledError("分析已取消")
                done, _ = await asyncio.wait(
                    {model_task, assignment_task, *active.values()},
                    timeout=self.poll_seconds,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if model_task in done:
                    # 模型池结束后不对未终局 work 做状态、停止、保存或域收尾
                    model_ended = True
                    await model_task
                    raise PipelineWorkFailed("模型池意外退出")
                # 旧尝试归还容量后可能立即收到同 work 的新选举，先移除已结束任务
                for work_id, task in list(active.items()):
                    if task in done:
                        succeeded += int(await task)
                        del active[work_id]
                if assignment_task in done:
                    message = assignment_task.result()
                    receipt = message.payload
                    if receipt.work_id in active:
                        raise ValueError(f"同 work 重复在飞派发: {receipt.work_id}")
                    self.states[receipt.work_id] = "running"
                    active[receipt.work_id] = asyncio.create_task(attempt(receipt))
                    assignment_task = asyncio.create_task(assignments.get())
            return succeeded
        except BaseException:
            if not model_ended:
                stopping = True
                models.stop_elections()
                for work_id in active:
                    await bus.request(
                        Message(
                            topic="agent.cancel",
                            source=address,
                            target=f"agent:{run_id}",
                            run_id=run_id,
                            work_id=work_id,
                        )
                    )
            await asyncio.gather(*active.values(), return_exceptions=True)
            raise
        finally:
            assignment_task.cancel()
            model_task.cancel()
            await asyncio.gather(assignment_task, model_task, return_exceptions=True)
            models.close()
            bus.unsubscribe(models.assignment_topic, assignments)
            bus.unhandle("queue.started", address)

    async def _save(
        self,
        bus: EventBus,
        address: str,
        receipt: WorkReceipt,
        invocation_id: str,
        session_factory: Callable[[], Session],
        may_start_save: Callable[[], bool] | None = None,
        has_model_ended: Callable[[], bool] | None = None,
    ) -> None:
        def command(topic: str, payload: Any = None) -> Message:
            return Message(
                topic=topic,
                source=address,
                target=f"agent:{receipt.run_id}",
                run_id=receipt.run_id,
                work_id=receipt.work_id,
                invocation_id=invocation_id,
                payload=payload,
            )

        async def stored() -> bool:
            try:
                with session_factory() as check_session:
                    row = await asyncio.to_thread(check_session.get, AnnotationWork, receipt.work_id)
                    if row is None:
                        return False
                    expected = {
                        "run_id": receipt.run_id,
                        "chapter_id": receipt.payload["chapter_id"],
                        "role": receipt.payload["role"],
                        "invocation_id": invocation_id,
                        "state": "saved",
                    }
                    if any(getattr(row, name) != value for name, value in expected.items()):
                        raise WorkSaveUnconfirmed(f"不可变 work 存储冲突: work_id={receipt.work_id}")
                if not await bus.request(command("agent.check")):
                    raise WorkSaveUnconfirmed(f"组件保存结果不一致: work_id={receipt.work_id}")
                return True
            except WorkSaveUnconfirmed:
                raise
            except Exception as exc:
                raise WorkSaveUnconfirmed(f"保存结果核查失败: work_id={receipt.work_id}: {exc}") from exc

        if has_model_ended is not None and has_model_ended():
            raise asyncio.CancelledError("模型池已结束，不启动业务保存或撤销")
        if may_start_save is not None and not may_start_save():
            # 本次保存尚未开始，执行成功结果也不能因取消被补存
            await bus.request(command("agent.abort"))
            raise asyncio.CancelledError("分析取消，work 保存尚未开始")

        verified = False
        for save_attempt in range(2):
            session = session_factory()
            try:
                existing = await asyncio.to_thread(session.get, AnnotationWork, receipt.work_id)
                if existing is None:
                    session.add(
                        AnnotationWork(
                            work_id=receipt.work_id,
                            run_id=receipt.run_id,
                            chapter_id=receipt.payload["chapter_id"],
                            role=receipt.payload["role"],
                            invocation_id=invocation_id,
                            state="saved",
                        )
                    )
                    await asyncio.to_thread(session.flush)
                    await bus.request(command("agent.save", session))
                    await asyncio.to_thread(session.commit)
            except Exception as exc:
                rollback_error: Exception | None = None
                try:
                    await asyncio.to_thread(session.rollback)
                except Exception as rollback_exc:
                    rollback_error = rollback_exc
                verified = await stored()
                if not verified:
                    if rollback_error is not None:
                        raise WorkSaveUnconfirmed(
                            f"提交与回滚结果仍不明: work_id={receipt.work_id}: {rollback_error}"
                        ) from exc
                    if save_attempt == 0 and isinstance(exc, (OSError, TimeoutError)):
                        # 明确未保存才重投原数据，模型与 invocation 都不重新执行
                        continue
                    await bus.request(command("agent.abort"))
                    raise
            finally:
                session.close()
            break
        if not verified and not await stored():
            raise WorkSaveUnconfirmed(f"提交回执与 work 存储不一致: work_id={receipt.work_id}")
        try:
            await bus.request(command("agent.confirm"))
        except Exception:
            try:
                await bus.request(command("agent.recover", {"mode": "saved_work"}))
                if not await stored():
                    raise WorkSaveUnconfirmed(f"确认恢复后 work 缺失: work_id={receipt.work_id}")
                await bus.request(command("agent.confirm"))
            except Exception as exc:
                raise WorkSaveUnconfirmed(f"已保存 work 内存确认失败: work_id={receipt.work_id}: {exc}") from exc
