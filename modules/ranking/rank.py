"""
Модуль ranking: ранжирование и обоснование гипотез, преимущественно НЕ-LLM методами.

Вход: raw_hypotheses (schemas/raw_hypotheses.schema.json), constraints (то же, что
query.constraints в retrieval_result.schema.json).
Выход: dict, валидный по schemas/ranked_hypotheses.schema.json.

Статус на сейчас (скелет):
  - novelty     — эмбеддинг-близость: считаем псевдо-эмбеддинги (детерминированные
                  случайные векторы, засеянные хэшем текста) и берём 1 - средняя
                  косинусная близость к остальным гипотезам (чем более уникальна
                  формулировка среди кандидатов — тем выше новизна).
                  TODO: заменить псевдо-эмбеддинги на реальные эмбеддинги из
                  rag_core/Yandex text-embeddings, когда rag_core их подключит.
  - feasibility — rule-based: доля материалов/оборудования из constraints,
                  упомянутых в тексте гипотезы.
  - expected_value — rule-based: максимальный процент, найденный в target_property_impact.
  - risk        — rule-based: наличие рискованных маркеров (патент, автоклав,
                  капитальные затраты, регуляторика) в тексте.
  - overall     — взвешенная сумма (novelty, feasibility, expected_value, 1-risk).
  - roadmap     — шаблонные шаги проверки (лаб. испытания -> пилот), не LLM-генерация.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

import numpy as np

WEIGHTS = {"novelty": 0.25, "feasibility": 0.3, "expected_value": 0.3, "risk_inverse": 0.15}

RISK_KEYWORDS = [
    "патент", "автоклав", "капитальн", "лицензи", "дорог", "регламент",
    "цианид", "давлени", "новое оборудование",
]

EMBEDDING_DIM = 64


def _pseudo_embedding(text: str) -> np.ndarray:
    """Детерминированный псевдо-эмбеддинг на основе хэша текста.
    TODO: заменить на реальные эмбеддинги (Yandex text-embeddings через rag_core)."""
    seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16) % (2**32)
    rng = np.random.default_rng(seed)
    vector = rng.normal(size=EMBEDDING_DIM)
    return vector / np.linalg.norm(vector)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.clip(np.dot(a, b), -1.0, 1.0))


def _compute_novelty_scores(hypotheses: list[dict[str, Any]]) -> dict[str, float]:
    if len(hypotheses) <= 1:
        return {h["hyp_id"]: 0.7 for h in hypotheses}

    embeddings = {h["hyp_id"]: _pseudo_embedding(h["statement"]) for h in hypotheses}
    novelty_scores: dict[str, float] = {}
    for h in hypotheses:
        this_id = h["hyp_id"]
        similarities = [
            _cosine(embeddings[this_id], embeddings[other_id])
            for other_id in embeddings
            if other_id != this_id
        ]
        avg_similarity = sum(similarities) / len(similarities)
        novelty = 1.0 - (avg_similarity + 1) / 2  # приводим косинус [-1,1] к близости [0,1], затем инвертируем
        novelty_scores[this_id] = float(np.clip(novelty, 0.0, 1.0))
    return novelty_scores


def _compute_feasibility(hypothesis: dict[str, Any], constraints: dict[str, Any]) -> float:
    text = (hypothesis["statement"] + " " + hypothesis["mechanism"]).lower()
    keywords = [kw.lower() for kw in (constraints.get("materials", []) + constraints.get("equipment", []))]
    if not keywords:
        return 0.6
    matches = sum(1 for kw in keywords if kw in text)
    return float(np.clip(0.4 + 0.6 * matches / len(keywords), 0.0, 1.0))


def _compute_expected_value(hypothesis: dict[str, Any]) -> float:
    numbers = re.findall(r"\d+(?:[.,]\d+)?", hypothesis.get("target_property_impact", ""))
    if not numbers:
        return 0.5
    max_value = max(float(n.replace(",", ".")) for n in numbers)
    return float(np.clip(max_value / 30.0, 0.0, 1.0))  # 30%+ считаем максимальной ценностью


def _compute_risk(hypothesis: dict[str, Any]) -> float:
    text = (hypothesis["statement"] + " " + hypothesis["mechanism"] + " "
            + hypothesis.get("target_property_impact", "")).lower()
    matches = sum(1 for kw in RISK_KEYWORDS if kw in text)
    return float(np.clip(0.15 + 0.2 * matches, 0.0, 1.0))


def _build_roadmap(hypothesis: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "step": f"Лабораторные испытания гипотезы: {hypothesis['statement'][:100]}",
            "resources": "Лаборатория, небольшая проба сырья, 3-5 дней",
            "success_criteria": f"Подтверждение эффекта: {hypothesis.get('target_property_impact', 'не указан')}",
        },
        {
            "step": "Пилотные испытания на укрупнённой пробе",
            "resources": "Опытный участок, 1-2 недели",
            "success_criteria": "Подтверждение эффекта в масштабе, приемлемая экономика",
        },
    ]


def _build_risk_notes(hypothesis: dict[str, Any], risk_score: float) -> str:
    if risk_score >= 0.5:
        return "Повышенный риск: гипотеза требует значимых капзатрат, лицензирования или нового оборудования."
    if risk_score >= 0.3:
        return "Умеренный риск: требуется дополнительная проверка регуляторных или экономических аспектов."
    return "Низкий риск: изменение затрагивает преимущественно режимные параметры существующего процесса."


def rank(raw_hypotheses: dict[str, Any], constraints: dict[str, Any]) -> dict[str, Any]:
    """Ранжирует гипотезы. constraints — тот же объект, что query.constraints в retrieval_result."""
    hypotheses = raw_hypotheses["hypotheses"]
    novelty_scores = _compute_novelty_scores(hypotheses)

    ranked: list[dict[str, Any]] = []
    for h in hypotheses:
        novelty = novelty_scores[h["hyp_id"]]
        feasibility = _compute_feasibility(h, constraints)
        expected_value = _compute_expected_value(h)
        risk = _compute_risk(h)

        overall = (
            WEIGHTS["novelty"] * novelty
            + WEIGHTS["feasibility"] * feasibility
            + WEIGHTS["expected_value"] * expected_value
            + WEIGHTS["risk_inverse"] * (1 - risk)
        )

        ranked.append(
            {
                "hyp_id": h["hyp_id"],
                "statement": h["statement"],
                "mechanism": h["mechanism"],
                "sources": [
                    {"doc_id": s["doc_id"], "citation": s["citation"]} for s in h.get("sources", [])
                ],
                "scores": {
                    "novelty": round(novelty, 4),
                    "feasibility": round(feasibility, 4),
                    "expected_value": round(expected_value, 4),
                    "risk": round(risk, 4),
                    "overall": round(float(np.clip(overall, 0.0, 1.0)), 4),
                },
                "risk_notes": _build_risk_notes(h, risk),
                "roadmap": _build_roadmap(h),
            }
        )

    ranked.sort(key=lambda h: h["scores"]["overall"], reverse=True)
    return {"hypotheses": ranked}


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    mock_raw_path = (
        Path(__file__).resolve().parents[2]
        / "mock_data"
        / "raw_hypotheses"
        / "raw_hypotheses_regrind.json"
    )
    if len(sys.argv) > 1:
        mock_raw_path = Path(sys.argv[1])

    raw = json.loads(mock_raw_path.read_text(encoding="utf-8"))
    demo_constraints = {
        "materials": ["лежалые хвосты флотации", "известь", "ксантогенат"],
        "budget": "до 5 млн руб.",
        "equipment": ["шаровая мельница", "флотомашина"],
        "regulatory": [],
    }
    print(json.dumps(rank(raw, demo_constraints), ensure_ascii=False, indent=2))
