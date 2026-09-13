import json_repair

from vazhi.models.chat import get_chat_model

JUDGE_PROMPT = """You are a fair judge. Evaluate whether the AI-generated answer is factually consistent with \
the standard answer for the given question. Ignore wording, punctuation, and formatting differences \
- only judge whether the core facts match.

Question: {question}
Standard answer: {gold_answer}
AI-generated answer: {generated_answer}

Return JSON only: {{"score": 1.0, "reasoning": "..."}}. score must be exactly 1.0 or 0.0.
"""


def precision_at_k(retrieved_ids: list[str], relevant_ids: list[str], k: int) -> float:
    top_k = retrieved_ids[:k]
    if not top_k:
        return 0.0
    return len(set(top_k) & set(relevant_ids)) / k


def recall_at_k(retrieved_ids: list[str], relevant_ids: list[str], k: int) -> float:
    if not relevant_ids:
        return 0.0
    return len(set(retrieved_ids[:k]) & set(relevant_ids)) / len(set(relevant_ids))


def f1_score_at_k(retrieved_ids: list[str], relevant_ids: list[str], k: int) -> float:
    p = precision_at_k(retrieved_ids, relevant_ids, k)
    r = recall_at_k(retrieved_ids, relevant_ids, k)
    if p + r == 0:
        return 0.0
    return 2 * p * r / (p + r)


def calculate_retrieval_metrics(
    retrieved_ids: list[str], relevant_ids: list[str], k_values: list[int] | None = None
) -> dict[str, float]:
    k_values = k_values or [1, 3, 5, 10]
    metrics: dict[str, float] = {}
    for k in k_values:
        metrics[f"recall@{k}"] = recall_at_k(retrieved_ids, relevant_ids, k)
        metrics[f"f1@{k}"] = f1_score_at_k(retrieved_ids, relevant_ids, k)
    return metrics


async def judge_correctness(question: str, gold_answer: str, generated_answer: str) -> dict:
    model = get_chat_model()
    prompt = JUDGE_PROMPT.format(question=question, gold_answer=gold_answer, generated_answer=generated_answer)
    response = await model.ainvoke(prompt)
    content = response.content if isinstance(response.content, str) else str(response.content)
    content = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    parsed = json_repair.loads(content)
    if not isinstance(parsed, dict):
        return {"score": 0.0, "reasoning": "Could not parse judge response"}
    return {"score": float(parsed.get("score", 0.0)), "reasoning": str(parsed.get("reasoning", ""))}


def calculate_overall_score(item_metrics: list[dict]) -> float:
    judge_scores = [m["judge_score"] for m in item_metrics if "judge_score" in m]
    if judge_scores:
        return sum(judge_scores) / len(judge_scores)

    recall_10_scores = [m.get("recall@10", 0.0) for m in item_metrics]
    if not recall_10_scores:
        return 0.0
    return sum(recall_10_scores) / len(recall_10_scores)
