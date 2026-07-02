.PHONY: install test run-pipeline ui validate-mock-data

install:
	pip install -r requirements.txt

test:
	pytest -v

run-pipeline:
	python scripts/run_pipeline.py

ui:
	streamlit run modules/orchestrator_ui/app.py

validate-mock-data:
	python schemas/validate_schema.py document mock_data/documents/doc_report_tailings.json
	python schemas/validate_schema.py retrieval_result mock_data/retrieval_results/retrieval_regrind.json
	python schemas/validate_schema.py raw_hypotheses mock_data/raw_hypotheses/raw_hypotheses_regrind.json
	python schemas/validate_schema.py ranked_hypotheses mock_data/ranked_hypotheses/ranked_hypotheses_example.json
