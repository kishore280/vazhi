import uuid

from vazhi.knowledge.eval.benchmark_generation import generate_benchmark
from vazhi.knowledge.eval.evaluator import evaluate_question
from vazhi.knowledge.eval.metrics import calculate_overall_score
from vazhi.repositories.eval_run_repository import EvalRunRepository
from vazhi.services.knowledge_service import _get_owned_knowledge_base
from vazhi.storage.postgres.manager import get_postgres_manager


async def run_evaluation(*, uid: str, kb_id: str, num_questions: int = 5) -> dict:
    await _get_owned_knowledge_base(uid=uid, kb_id=kb_id)

    benchmark = await generate_benchmark(kb_id, num_questions=num_questions)

    manager = get_postgres_manager()
    async with manager.get_session() as db:
        repo = EvalRunRepository(db)
        run = await repo.create(run_id=uuid.uuid4().hex, kb_id=kb_id, created_by=uid, total_items=len(benchmark))
        await db.commit()
        run_id = run.run_id

    item_metrics = []
    for idx, item in enumerate(benchmark):
        result = await evaluate_question(
            uid=uid,
            kb_id=kb_id,
            query=item["query"],
            gold_answer=item["gold_answer"],
            gold_chunk_ids=item["gold_chunk_ids"],
        )
        item_metrics.append(result["metrics"])

        async with manager.get_session() as db:
            repo = EvalRunRepository(db)
            run = await repo.get_by_run_id(run_id)
            await repo.add_item(run, item_index=idx, item_data=result)
            await db.commit()

    overall_score = calculate_overall_score(item_metrics)
    aggregate_metrics = {}
    if item_metrics:
        for key in item_metrics[0]:
            aggregate_metrics[key] = sum(m.get(key, 0.0) for m in item_metrics) / len(item_metrics)

    async with manager.get_session() as db:
        repo = EvalRunRepository(db)
        run = await repo.get_by_run_id(run_id)
        await repo.finalize(run, overall_score=overall_score, metrics=aggregate_metrics)
        await db.commit()
        return run.to_dict()


async def list_evaluation_runs(*, uid: str, kb_id: str) -> list[dict]:
    await _get_owned_knowledge_base(uid=uid, kb_id=kb_id)
    manager = get_postgres_manager()
    async with manager.get_session() as db:
        runs = await EvalRunRepository(db).list_by_kb(kb_id)
        return [r.to_dict() for r in runs]


async def get_evaluation_run(*, uid: str, kb_id: str, run_id: str) -> dict | None:
    await _get_owned_knowledge_base(uid=uid, kb_id=kb_id)
    manager = get_postgres_manager()
    async with manager.get_session() as db:
        run = await EvalRunRepository(db).get_with_items(run_id)
        if run is None or run.kb_id != kb_id:
            return None
        result = run.to_dict()
        result["items"] = [item.to_dict() for item in sorted(run.items, key=lambda i: i.item_index)]
        return result
