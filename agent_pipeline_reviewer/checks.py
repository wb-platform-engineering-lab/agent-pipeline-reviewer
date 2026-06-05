"""
Deterministic check layer — 21 checks across 4 DORA pillars.

Each function takes the parsed pipeline dict and returns (status, detail).
Status: "pass" | "fail" | "warn" | "info"
"""

import re
from .gitlab_parser import deploy_jobs, test_jobs, stage_index

# Package manager install commands that benefit from caching
_INSTALL_CMDS = [
    "npm install", "npm ci", "yarn install", "pnpm install",
    "pip install", "pip3 install", "poetry install", "pipenv install",
    "bundle install", "gem install",
    "mvn ", "gradle ", "./gradlew",
    "composer install", "go mod download", "cargo build",
    "apt-get install", "apk add",
]

_SECURITY_KEYWORDS = [
    "sast", "dast", "dependency_scan", "container_scan", "secret_scan",
    "trivy", "snyk", "bandit", "semgrep", "sonar", "gitleaks",
    "checkov", "tfsec", "grype",
]

_LINT_KEYWORDS = [
    "lint", "flake8", "pylint", "eslint", "tslint", "rubocop",
    "golangci", "shellcheck", "hadolint", "yamllint", "black",
    "prettier", "stylelint", "markdownlint", "mypy",
]

_SMOKE_KEYWORDS = [
    "smoke", "health", "sanity", "verify", "post_deploy",
    "post-deploy", "e2e", "acceptance", "ping",
]

_ROLLBACK_KEYWORDS = [
    "rollback", "revert", "undo", "restore", "previous",
]

_NOTIFY_KEYWORDS = [
    "notify", "notification", "alert", "slack", "teams",
    "pagerduty", "email", "webhook",
]


def _script_contains(job: dict, keywords: list) -> bool:
    text = " ".join(job.get("script", []) + job.get("before_script", []))
    return any(k.lower() in text.lower() for k in keywords)


def _name_contains(job: dict, keywords: list) -> bool:
    name = job["name"].lower()
    stage = (job.get("stage") or "").lower()
    return any(k.lower() in name or k.lower() in stage for k in keywords)


def _image_is_untagged(image: str | None) -> bool:
    if not image:
        return False
    # Strip registry prefix: registry.example.com/org/name:tag → name:tag
    name = image.split("/")[-1]
    return ":" not in name or name.endswith(":latest")


# ── Pillar 1 — Lead Time ──────────────────────────────────────────────────────

def check_p1_001(parsed: dict) -> tuple:
    """No cache on dependency installation jobs."""
    global_cache = parsed.get("global_cache")
    offenders = []
    for job in parsed["jobs"].values():
        if job.get("trigger"):
            continue
        has_install = _script_contains(job, _INSTALL_CMDS)
        if not has_install:
            continue
        has_cache = bool(job.get("cache") or global_cache)
        if not has_cache:
            offenders.append(job["name"])

    if offenders:
        return "fail", f"Jobs installing dependencies with no cache: {', '.join(offenders)}"
    if not any(_script_contains(j, _INSTALL_CMDS) for j in parsed["jobs"].values()):
        return "info", "No dependency installation commands detected"
    return "pass", "All install jobs have cache configured"


def check_p1_002(parsed: dict) -> tuple:
    """Docker images using 'latest' or no tag."""
    offenders = []
    for job in parsed["jobs"].values():
        if job.get("trigger"):
            continue
        image = job.get("image") or parsed.get("global_image")
        if image and _image_is_untagged(image):
            offenders.append(f"{job['name']} ({image})")

    global_img = parsed.get("global_image")
    if global_img and _image_is_untagged(global_img):
        offenders.append(f"global image ({global_img})")

    if offenders:
        return "fail", f"Untagged or ':latest' images: {', '.join(offenders)}"
    return "pass", "All Docker images are pinned to specific versions"


def check_p1_003(parsed: dict) -> tuple:
    """No interruptible: true on build/test jobs."""
    # If default: sets interruptible: true, all jobs inherit it
    if parsed.get("default_interruptible"):
        return "pass", "interruptible: true set in default: block — applies to all jobs"

    build_test_stages = {"build", "test", "lint", "compile", "quality"}
    candidates = [
        j for j in parsed["jobs"].values()
        if (j.get("stage") or "").lower() in build_test_stages
        and not j.get("trigger")
        and not j.get("interruptible")
    ]
    if not candidates:
        candidates = [
            j for j in parsed["jobs"].values()
            if not j.get("trigger") and not j.get("interruptible")
            and j.get("when") != "manual"
        ]

    if candidates:
        names = [j["name"] for j in candidates[:5]]
        more = f" (+{len(candidates)-5} more)" if len(candidates) > 5 else ""
        return "warn", f"Jobs without interruptible: true — {', '.join(names)}{more}"
    return "pass", "All jobs have interruptible: true configured"


def check_p1_004(parsed: dict) -> tuple:
    """Artifacts stored without expire_in."""
    offenders = []
    for job in parsed["jobs"].values():
        artifacts = job.get("artifacts")
        if isinstance(artifacts, dict) and "paths" in artifacts:
            if not artifacts.get("expire_in"):
                offenders.append(job["name"])

    if offenders:
        return "warn", f"Jobs producing artifacts without expire_in: {', '.join(offenders)}"
    return "pass", "All artifact-producing jobs have expire_in configured"


def check_p1_005(parsed: dict) -> tuple:
    """Pipeline has 4+ stages but no job uses needs:."""
    stages = parsed.get("stages", [])
    jobs = parsed["jobs"]
    if len(stages) < 4:
        return "pass", f"Pipeline has {len(stages)} stages — needs: DAG not critical"

    any_needs = any(bool(j.get("needs")) for j in jobs.values())
    if not any_needs:
        return "fail", (
            f"Pipeline has {len(stages)} stages ({', '.join(stages)}) "
            f"but no job uses needs: — all jobs wait for full stage completion"
        )
    return "pass", "Pipeline uses needs: to optimise job start times"


def check_p1_006(parsed: dict) -> tuple:
    """Single test job with no parallel: matrix."""
    t_jobs = [
        j for j in parsed["jobs"].values()
        if _name_contains(j, ["test", "spec", "rspec", "pytest", "jest"])
        and not j.get("trigger")
    ]
    if not t_jobs:
        return "info", "No test jobs detected to evaluate parallelism"

    single_without_parallel = [j for j in t_jobs if not j.get("parallel")]
    if len(single_without_parallel) == len(t_jobs) == 1:
        return "warn", (
            f"Single test job '{t_jobs[0]['name']}' with no parallel: matrix — "
            f"consider splitting the test suite"
        )
    return "pass", "Test jobs are parallelised or multiple test jobs defined"


# ── Pillar 2 — Change Failure Rate ────────────────────────────────────────────

def check_p2_001(parsed: dict) -> tuple:
    """No test job found in pipeline."""
    t_jobs = test_jobs(parsed)
    if not t_jobs:
        return "fail", "No test job found — code is deployed without automated validation"
    names = [j["name"] for j in t_jobs[:5]]
    return "pass", f"Test jobs found: {', '.join(names)}"


def check_p2_002(parsed: dict) -> tuple:
    """Deploy job bypasses test stage via needs:."""
    d_jobs = deploy_jobs(parsed)
    t_jobs = test_jobs(parsed)
    if not d_jobs or not t_jobs:
        return "info", "Cannot evaluate — no deploy or test jobs identified"

    test_names = {j["name"] for j in t_jobs}
    jobs_by_name = parsed["jobs"]

    def _reaches_test(job_name: str, visited: set) -> bool:
        """BFS: does job_name transitively depend on a test job?"""
        if job_name in visited:
            return False
        visited.add(job_name)
        job = jobs_by_name.get(job_name, {})
        for needed in job.get("needs", []):
            if needed in test_names:
                return True
            if _reaches_test(needed, visited):
                return True
        return False

    offenders = []
    for dj in d_jobs:
        needs = dj.get("needs", [])
        if not needs:
            continue  # no needs: — stage ordering ensures tests run first
        if not _reaches_test(dj["name"], set()):
            offenders.append(dj["name"])

    if offenders:
        return "fail", (
            f"Deploy jobs with needs: that bypass test jobs: {', '.join(offenders)} — "
            f"deployment can proceed without tests passing"
        )
    return "pass", "Deploy jobs correctly depend on test jobs (directly or transitively)"


def check_p2_003(parsed: dict) -> tuple:
    """No smoke test or health check after deployment."""
    d_jobs = deploy_jobs(parsed)
    if not d_jobs:
        return "info", "No deploy jobs detected"

    max_deploy_idx = max(
        stage_index(parsed, j["stage"]) for j in d_jobs
    )
    post_deploy = [
        j for j in parsed["jobs"].values()
        if stage_index(parsed, j["stage"]) > max_deploy_idx
        or _name_contains(j, _SMOKE_KEYWORDS)
    ]

    if not post_deploy:
        return "warn", (
            "No smoke test or health check job found after the deploy stage — "
            "deployment failures may go undetected"
        )
    names = [j["name"] for j in post_deploy[:3]]
    return "pass", f"Post-deploy validation jobs found: {', '.join(names)}"


def check_p2_004(parsed: dict) -> tuple:
    """Critical job (test or deploy) has allow_failure: true."""
    critical = test_jobs(parsed) + deploy_jobs(parsed)
    offenders = [
        j["name"] for j in critical
        if j.get("allow_failure") is True
    ]
    if offenders:
        return "fail", (
            f"Critical jobs with allow_failure: true: {', '.join(offenders)} — "
            f"failures are silently ignored"
        )
    return "pass", "No critical jobs have allow_failure: true"


def check_p2_005(parsed: dict) -> tuple:
    """No security scanning job."""
    security = [
        j for j in parsed["jobs"].values()
        if _name_contains(j, _SECURITY_KEYWORDS)
        or _script_contains(j, _SECURITY_KEYWORDS)
    ]
    # Also accept GitLab's built-in include templates
    if any("Security" in str(j) for j in parsed.get("pipeline_files", [])):
        return "pass", "Security scanning via GitLab include template detected"

    if not security:
        return "warn", (
            "No SAST, dependency scan, or container scan job found — "
            "vulnerabilities are not detected before deployment"
        )
    names = [j["name"] for j in security[:3]]
    return "pass", f"Security scanning jobs found: {', '.join(names)}"


def check_p2_006(parsed: dict) -> tuple:
    """No linting or code quality job."""
    lint = [
        j for j in parsed["jobs"].values()
        if _name_contains(j, _LINT_KEYWORDS)
        or _script_contains(j, _LINT_KEYWORDS)
    ]
    if not lint:
        return "warn", (
            "No linting or static analysis job found — "
            "syntax errors are caught late in the pipeline"
        )
    names = [j["name"] for j in lint[:3]]
    return "pass", f"Linting jobs found: {', '.join(names)}"


# ── Pillar 3 — Deployment Frequency ──────────────────────────────────────────

def check_p3_001(parsed: dict) -> tuple:
    """All deployments require manual trigger."""
    d_jobs = deploy_jobs(parsed)
    if not d_jobs:
        return "info", "No deploy jobs detected"

    manual = [j for j in d_jobs if j.get("when") == "manual"]
    auto   = [j for j in d_jobs if j.get("when") != "manual"]

    if manual and not auto:
        names = [j["name"] for j in manual]
        return "warn", (
            f"All deploy jobs require manual trigger: {', '.join(names)} — "
            f"deployment frequency is gated by human availability"
        )
    if manual and auto:
        return "pass", (
            f"Mixed: {len(auto)} auto-deploy job(s), {len(manual)} manual — "
            f"acceptable pattern (e.g. auto-staging, manual-prod)"
        )
    return "pass", "Deploy jobs run automatically on pipeline success"


def check_p3_002(parsed: dict) -> tuple:
    """No merge request pipeline configured."""
    def _has_mr_condition(rules: list) -> bool:
        for rule in rules:
            if isinstance(rule, dict):
                condition = str(rule.get("if", ""))
                if "merge_request_event" in condition or "merge_request" in condition.lower():
                    return True
        return False

    # Check workflow: rules first (preferred pattern)
    if _has_mr_condition(parsed.get("workflow_rules", [])):
        return "pass", "Merge request pipeline configured via workflow: rules"

    # Check individual job rules
    for job in parsed["jobs"].values():
        if _has_mr_condition(job.get("rules", [])):
            return "pass", "Merge request pipeline configured via job-level rules"

    return "warn", (
        "No MR pipeline trigger found (workflow: rules or job rules) — "
        "code is not validated on MR creation"
    )


def check_p3_003(parsed: dict) -> tuple:
    """No pipeline triggered on push to default branch."""
    # If no jobs have rules at all → pipeline runs on everything (OK)
    if not parsed.get("has_rules"):
        return "pass", "No rules: configured — pipeline runs on all pushes (including default branch)"

    has_main_rule = False
    for job in parsed["jobs"].values():
        for rule in job.get("rules", []):
            if isinstance(rule, dict):
                condition = str(rule.get("if", ""))
                if any(kw in condition for kw in [
                    "CI_DEFAULT_BRANCH", "$CI_COMMIT_BRANCH",
                    '"main"', '"master"', "'main'", "'master'",
                ]):
                    has_main_rule = True
                    break
        if has_main_rule:
            break

    if not has_main_rule:
        return "warn", (
            "Pipeline uses rules: but no rule triggers on push to the default branch — "
            "merged code may not be automatically built and deployed"
        )
    return "pass", "Pipeline configured to run on push to default branch"


def check_p3_004(parsed: dict) -> tuple:
    """No environment: defined on deploy jobs."""
    d_jobs = deploy_jobs(parsed)
    if not d_jobs:
        return "info", "No deploy jobs detected"

    no_env = [j["name"] for j in d_jobs if not j.get("environment")]
    if no_env:
        return "warn", (
            f"Deploy jobs without environment: {', '.join(no_env)} — "
            f"GitLab cannot track deployment history or enforce protections"
        )
    return "pass", "All deploy jobs declare an environment"


# ── Pillar 4 — MTTR ───────────────────────────────────────────────────────────

def check_p4_001(parsed: dict) -> tuple:
    """No rollback job or environment on_stop defined."""
    rollback = [
        j for j in parsed["jobs"].values()
        if _name_contains(j, _ROLLBACK_KEYWORDS)
        or _script_contains(j, _ROLLBACK_KEYWORDS)
    ]
    on_stop = [
        j for j in parsed["jobs"].values()
        if isinstance(j.get("environment"), dict)
        and j["environment"].get("action") == "stop"
    ]
    if not rollback and not on_stop:
        return "warn", (
            "No rollback job and no environment on_stop: configured — "
            "recovery from a bad deploy requires manual intervention"
        )
    found = [j["name"] for j in (rollback + on_stop)[:3]]
    return "pass", f"Rollback mechanism found: {', '.join(found)}"


def check_p4_002(parsed: dict) -> tuple:
    """No failure notification job."""
    notify = [
        j for j in parsed["jobs"].values()
        if j.get("when") == "on_failure"
        or (_name_contains(j, _NOTIFY_KEYWORDS) and j.get("when") in ("on_failure", "always"))
    ]
    if not notify:
        return "warn", (
            "No job runs when: on_failure — "
            "the team is not automatically notified of pipeline failures"
        )
    names = [j["name"] for j in notify[:3]]
    return "pass", f"Failure notification jobs found: {', '.join(names)}"


def check_p4_003(parsed: dict) -> tuple:
    """No retry: on deploy jobs."""
    d_jobs = deploy_jobs(parsed)
    if not d_jobs:
        return "info", "No deploy jobs detected"

    # If default: configures retry, all jobs inherit it
    if parsed.get("default_retry"):
        return "pass", "retry: set in default: block — applies to all deploy jobs"

    no_retry = [j["name"] for j in d_jobs if not j.get("retry")]
    if no_retry:
        return "warn", (
            f"Deploy jobs without retry: {', '.join(no_retry)} — "
            f"transient failures cause full pipeline failures requiring manual re-runs"
        )
    return "pass", "All deploy jobs have retry: configured"


def check_p4_004(parsed: dict) -> tuple:
    """No environment URL defined."""
    d_jobs = [j for j in deploy_jobs(parsed) if j.get("environment")]
    if not d_jobs:
        return "info", "No deploy jobs with environment: detected"

    no_url = [
        j["name"] for j in d_jobs
        if isinstance(j.get("environment"), dict)
        and not j["environment"].get("url")
    ]
    if no_url:
        return "info", (
            f"Deploy jobs with environment but no url: {', '.join(no_url)} — "
            f"add url: to enable one-click access from the GitLab pipeline view"
        )
    return "pass", "All environments have a URL configured"


def check_p4_005(parsed: dict) -> tuple:
    """No timeout defined on long-running jobs."""
    long_stages = {"build", "test", "deploy", "integration"}
    no_timeout = [
        j["name"] for j in parsed["jobs"].values()
        if (j.get("stage") or "").lower() in long_stages
        and not j.get("timeout")
        and not j.get("trigger")
    ]
    if no_timeout:
        names = no_timeout[:5]
        more = f" (+{len(no_timeout)-5} more)" if len(no_timeout) > 5 else ""
        return "warn", (
            f"Long-running jobs without timeout: {', '.join(names)}{more} — "
            f"hung jobs block the pipeline for up to 60 minutes"
        )
    return "pass", "All long-running jobs have a timeout configured"


# ── Dispatcher ────────────────────────────────────────────────────────────────

_CHECK_FN = {
    "P1-001": check_p1_001,
    "P1-002": check_p1_002,
    "P1-003": check_p1_003,
    "P1-004": check_p1_004,
    "P1-005": check_p1_005,
    "P1-006": check_p1_006,
    "P2-001": check_p2_001,
    "P2-002": check_p2_002,
    "P2-003": check_p2_003,
    "P2-004": check_p2_004,
    "P2-005": check_p2_005,
    "P2-006": check_p2_006,
    "P3-001": check_p3_001,
    "P3-002": check_p3_002,
    "P3-003": check_p3_003,
    "P3-004": check_p3_004,
    "P4-001": check_p4_001,
    "P4-002": check_p4_002,
    "P4-003": check_p4_003,
    "P4-004": check_p4_004,
    "P4-005": check_p4_005,
}


def run_all_checks(parsed: dict) -> list:
    """
    Run all 21 checks against parsed pipeline.
    Returns list of {id, pillar, status, detail} dicts.
    """
    from .rubric import CHECKS
    results = []
    for check in CHECKS:
        fn = _CHECK_FN.get(check["id"])
        if fn:
            try:
                status, detail = fn(parsed)
            except Exception as exc:
                status, detail = "info", f"Check error: {exc}"
        else:
            status, detail = "info", "Check not implemented"
        results.append({
            "id":     check["id"],
            "pillar": check["pillar"],
            "name":   check["name"],
            "status": status,
            "detail": detail,
        })
    return results
