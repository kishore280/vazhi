from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from vazhi.storage.postgres.models import EvaluationRun, EvaluationRunItem, utc_now_naive


class EvalRunRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, *, run_id: str, kb_id: str, created_by: str, total_items: int) -> EvaluationRun:
        run = EvaluationRun(run_id=run_id, kb_id=kb_id, created_by=created_by, total_items=total_items)
        self.db.add(run)
        await self.db.flush()
        return run

    async def add_item(self, run: EvaluationRun, *, item_index: int, item_data: dict) -> EvaluationRunItem:
        item = EvaluationRunItem(
            run_id=run.id,
            item_index=item_index,
            query_text=item_data["query_text"],
            gold_chunk_ids=item_data["gold_chunk_ids"],
            gold_answer=item_data["gold_answer"],
            generated_answer=item_data["generated_answer"],
            retrieved_chunk_ids=item_data["retrieved_chunk_ids"],
            metrics=item_data["metrics"],
        )
        self.db.add(item)
        run.completed_items += 1
        await self.db.flush()
        return item

    async def finalize(self, run: EvaluationRun, *, overall_score: float, metrics: dict) -> None:
        run.status = "completed"
        run.overall_score = overall_score
        run.metrics = metrics
        run.completed_at = utc_now_naive()
        await self.db.flush()

    async def get_by_run_id(self, run_id: str) -> EvaluationRun | None:
        result = await self.db.execute(select(EvaluationRun).where(EvaluationRun.run_id == run_id))
        return result.scalar_one_or_none()

    async def list_by_kb(self, kb_id: str) -> list[EvaluationRun]:
        result = await self.db.execute(
            select(EvaluationRun).where(EvaluationRun.kb_id == kb_id).order_by(EvaluationRun.started_at.desc())
        )
        return list(result.scalars().all())

    async def get_with_items(self, run_id: str) -> EvaluationRun | None:
        result = await self.db.execute(
            select(EvaluationRun)
            .options(selectinload(EvaluationRun.items))
            .where(EvaluationRun.run_id == run_id)
        )
        return result.scalar_one_or_none()
