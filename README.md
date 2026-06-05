# agent-pipeline-reviewer

An AI agent that reviews GitLab CI pipelines for DORA metric anti-patterns.

It runs 21 deterministic checks across the four DORA pillars (Lead Time, Change Failure Rate, Deployment Frequency, MTTR), then uses Claude to generate a narrated report with specific fixes and expected metric impact.

---

## Quick start

Requires **Python 3.10+**. The recommended install method is `pipx`, which manages an isolated virtualenv automatically:

```bash
# Install pipx if needed
brew install pipx && pipx ensurepath

# Install the tool
pipx install -e .

pipeline-review ./path/to/repo --checks-only    # no API key required
pipeline-review ./path/to/repo                  # full AI report (requires ANTHROPIC_API_KEY)
```

**Alternative — virtualenv:**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
pipeline-review ./path/to/repo --checks-only
```

---

## How it works

```
.gitlab-ci.yml
      │
      ▼
gitlab_parser.py   ← parses YAML, resolves includes, builds job graph
      │
      ▼
checks.py          ← 21 deterministic checks (P1-001 → P4-005)
      │
      ▼
Claude (Haiku)     ← narrates findings, suggests YAML fixes
      │
      ▼
HTML + JSON report
```

The deterministic layer is always authoritative. Claude adds narration — it cannot invent passing checks.

---

## DORA pillar mapping

| Pillar | DORA Metric | Checks |
|--------|-------------|--------|
| P1 — Lead Time | Lead Time for Changes | Caching, image pinning, interruptible, artifact expiry, DAG (needs:), parallelism |
| P2 — Change Failure Rate | Change Failure Rate | Tests present, deploy bypasses tests, smoke tests, allow_failure on critical jobs, security scanning, linting |
| P3 — Deployment Frequency | Deployment Frequency | Manual-only deploys, MR pipeline, push-to-main trigger, environment defined |
| P4 — MTTR | Time to Restore | Rollback job, failure notification, retry on deploy, environment URL, timeouts |

### Maturity levels

| Score | Grade |
|-------|-------|
| ≥ 80% | Elite performer |
| ≥ 60% | High performer |
| ≥ 40% | Medium performer |
| < 40% | Low performer |

---

## CLI reference

```
usage: pipeline-review [-h] [--checks-only] [--fail-under N]
                       [--output-dir DIR] [--output-file NAME] [--quiet]
                       path

positional arguments:
  path               Directory containing .gitlab-ci.yml

options:
  --checks-only      Run deterministic checks only — no AI, no API key required
  --fail-under N     Exit 1 if score is below N%  (useful in CI)
  --output-dir DIR   Directory for report files (default: current directory)
  --output-file NAME Base name for report files (without extension)
  --quiet            Suppress live output
```

### Examples

```bash
# Checks only, fail CI if score < 60%
pipeline-review . --checks-only --fail-under 60

# Full AI report saved to reports/
pipeline-review . --output-dir reports/

# Quiet mode with custom file name
pipeline-review . --quiet --output-file my-pipeline-review
```

---

## CI/CD integration

### GitLab CI

```yaml
pipeline-review:
  stage: quality
  image: python:3.11-alpine
  before_script:
    - pip install agent-pipeline-reviewer
  script:
    - pipeline-review . --checks-only --fail-under 60 --output-dir reports/
  artifacts:
    paths:
      - reports/
    expire_in: 1 week
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
```

### GitHub Actions

```yaml
- name: Review pipeline
  run: |
    pip install agent-pipeline-reviewer
    pipeline-review . --checks-only --fail-under 60
```

---

## Check reference

### Pillar 1 — Lead Time

| ID | Name | Severity |
|----|------|----------|
| P1-001 | No cache on dependency installation | fail |
| P1-002 | Untagged or `:latest` Docker image | fail |
| P1-003 | No `interruptible: true` on build/test jobs | warn |
| P1-004 | Artifacts without `expire_in` | warn |
| P1-005 | 4+ stages but no `needs:` DAG | fail |
| P1-006 | Single test job with no parallel matrix | warn |

### Pillar 2 — Change Failure Rate

| ID | Name | Severity |
|----|------|----------|
| P2-001 | No test job found | fail |
| P2-002 | Deploy job bypasses tests via `needs:` | fail |
| P2-003 | No smoke test or health check after deploy | warn |
| P2-004 | Critical job has `allow_failure: true` | fail |
| P2-005 | No security scanning job | warn |
| P2-006 | No linting or code quality job | warn |

### Pillar 3 — Deployment Frequency

| ID | Name | Severity |
|----|------|----------|
| P3-001 | All deployments require manual trigger | warn |
| P3-002 | No MR pipeline configured | warn |
| P3-003 | No push-to-main pipeline trigger | warn |
| P3-004 | Deploy jobs without `environment:` | warn |

### Pillar 4 — MTTR

| ID | Name | Severity |
|----|------|----------|
| P4-001 | No rollback job or `on_stop` defined | warn |
| P4-002 | No failure notification job | warn |
| P4-003 | No `retry:` on deploy jobs | warn |
| P4-004 | Environment without URL | info |
| P4-005 | Long-running jobs without `timeout:` | warn |

---

## Output

Every run produces:

- **JSON** — machine-readable score and check results (`--checks-only` or full run)
- **HTML** — human-readable report with per-pillar DORA gauges and expandable check rows (full AI run)

---

## Development

```bash
make install       # creates .venv and installs the package (requires Python 3.10+)
make demo-bad      # run checks against examples/bad_pipeline
make demo-good     # run checks against examples/good_pipeline
make demo-bad-ai   # full AI review of bad_pipeline (needs ANTHROPIC_API_KEY)
```

### Project structure

```
agent_pipeline_reviewer/
├── __init__.py
├── rubric.py         # Check metadata (21 checks × 4 pillars)
├── gitlab_parser.py  # YAML parser + job graph builder
├── checks.py         # 21 deterministic check functions
├── tools.py          # Agent tools (list_files, build_graph, run_checks, read_file)
├── cli.py            # Agent loop + CLI entry point
└── report.py         # HTML report generator

examples/
├── bad_pipeline/     # Violates all 21 checks (score ≈ 15%)
└── good_pipeline/    # Passes all checks (score ≈ 90%)
```

---

## Cost

Uses `claude-haiku-4-5` by default. A typical pipeline review costs < $0.01 per run.

---

## License

MIT
