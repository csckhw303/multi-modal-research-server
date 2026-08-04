.PHONY: collect eval full clean
collect:
	poetry run python evaluation/scripts/collect_data.py

eval:
	poetry run python evaluation/scripts/run_evaluation.py

full: collect eval

clean:
	rm -f evaluation/datasets/ragas_evaluation_dataset-1.json
	rm -f evaluation/datasets/results.csv		