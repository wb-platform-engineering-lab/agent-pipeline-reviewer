.PHONY: install demo-bad demo-good demo-bad-ai demo-good-ai test clean

install:
	python3 -m venv .venv
	.venv/bin/pip install -e .

demo-bad:
	pipeline-review examples/bad_pipeline --checks-only

demo-good:
	pipeline-review examples/good_pipeline --checks-only

demo-bad-ai:
	pipeline-review examples/bad_pipeline --output-dir /tmp

demo-good-ai:
	pipeline-review examples/good_pipeline --output-dir /tmp

test:
	python -m pytest tests/ -v

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -f pipeline_review_*.json pipeline_review_*.html
