"""
Streamlit UI: оркестрация пайплайна "Фабрика гипотез".

Форма ввода (целевое свойство, ограничения, загрузка файлов базы знаний) ->
вызов всей цепочки модулей через mock_pipeline.run_pipeline() -> список
гипотез из ranked_hypotheses.schema.json в читаемом виде + экспорт в JSON.

Запуск: `streamlit run modules/orchestrator_ui/app.py` из корня репозитория.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from modules.orchestrator_ui.mock_pipeline import ingest_uploaded_files, run_pipeline  # noqa: E402

st.set_page_config(page_title="Фабрика гипотез", layout="wide")
st.title("Фабрика гипотез")
st.caption(
    "Целевое технологическое свойство + ограничения + база знаний -> "
    "проверяемые гипотезы с обоснованием, ссылками, оценкой новизны/рисков/ценности."
)

with st.form("hypothesis_form"):
    target_property = st.text_input(
        "Целевое технологическое свойство",
        value="Повысить извлечение золота из лежалых хвостов флотации на 15%",
    )

    col1, col2 = st.columns(2)
    with col1:
        materials = st.text_area("Доступное сырьё/реагенты (по одному на строку)", value="")
        equipment = st.text_area("Доступное оборудование (по одному на строку)", value="")
    with col2:
        budget = st.text_input("Бюджет", value="")
        regulatory = st.text_area("Регуляторные ограничения (по одному на строку)", value="")

    uploaded_files = st.file_uploader(
        "Файлы базы знаний (.docx, .pdf) — необязательно, без загрузки используются мок-документы",
        type=["docx", "pdf", "xlsx", "png", "jpg"],
        accept_multiple_files=True,
    )

    submitted = st.form_submit_button("Сгенерировать гипотезы")

if submitted:
    constraints = {
        "materials": [line.strip() for line in materials.splitlines() if line.strip()],
        "budget": budget.strip() or None,
        "equipment": [line.strip() for line in equipment.splitlines() if line.strip()],
        "regulatory": [line.strip() for line in regulatory.splitlines() if line.strip()],
    }

    documents = None
    if uploaded_files:
        with tempfile.TemporaryDirectory() as tmp_dir:
            saved_paths = []
            for uploaded_file in uploaded_files:
                tmp_path = Path(tmp_dir) / uploaded_file.name
                tmp_path.write_bytes(uploaded_file.getvalue())
                saved_paths.append(str(tmp_path))

            documents, warnings = ingest_uploaded_files(saved_paths)
            for warning in warnings:
                st.warning(warning)

            if not documents:
                st.info("Ни один файл не был успешно распознан — используются мок-документы.")
                documents = None

    with st.spinner("Запускаю пайплайн: retrieval -> генерация гипотез -> ранжирование..."):
        ranked_result = run_pipeline(target_property, constraints, documents)

    st.session_state["ranked_result"] = ranked_result

if "ranked_result" in st.session_state:
    ranked_result = st.session_state["ranked_result"]
    hypotheses = ranked_result["hypotheses"]

    st.subheader(f"Гипотезы ({len(hypotheses)})")

    for i, h in enumerate(hypotheses, start=1):
        scores = h["scores"]
        with st.expander(f"{i}. {h['statement']}  —  overall={scores['overall']:.2f}"):
            st.markdown(f"**Механизм:** {h['mechanism']}")
            st.markdown(
                f"**Scores:** новизна={scores['novelty']:.2f} · "
                f"реализуемость={scores['feasibility']:.2f} · "
                f"ценность={scores['expected_value']:.2f} · "
                f"риск={scores['risk']:.2f}"
            )
            st.markdown(f"**Риски:** {h['risk_notes']}")

            if h["sources"]:
                st.markdown("**Источники:**")
                for s in h["sources"]:
                    st.markdown(f"- {s['citation']} (`doc_id={s['doc_id']}`)")

            if h["roadmap"]:
                st.markdown("**Дорожная карта проверки:**")
                for step in h["roadmap"]:
                    st.markdown(f"- {step['step']} — *{step['resources']}* -> {step['success_criteria']}")

    st.download_button(
        "Экспорт в JSON",
        data=json.dumps(ranked_result, ensure_ascii=False, indent=2),
        file_name="ranked_hypotheses.json",
        mime="application/json",
    )
