"""
21 pipeline checks across 4 DORA metric pillars.

Each check targets a GitLab CI anti-pattern that measurably impacts
Lead Time, Change Failure Rate, Deployment Frequency, or MTTR.
"""

CHECKS = [
    # ── Pillar 1 — Lead Time ─────────────────────────────────────────────────
    {
        "id": "P1-001",
        "pillar": 1,
        "dora_metric": "lead_time",
        "name": "No cache on dependency installation",
        "description": (
            "Jobs running npm install, pip install, or similar package managers "
            "without a cache: block. Every pipeline re-downloads all dependencies "
            "from scratch, adding 2–10 minutes per run."
        ),
        "severity": "high",
        "est_saving": "2–10 min per pipeline run",
    },
    {
        "id": "P1-002",
        "pillar": 1,
        "dora_metric": "lead_time",
        "name": "Docker image using 'latest' or untagged",
        "description": (
            "Jobs using image: node or image: node:latest pull an unpredictable "
            "image version on every run. This causes cache misses, breaks "
            "reproducibility, and can add minutes to pipeline startup."
        ),
        "severity": "medium",
        "est_saving": "1–3 min per pipeline run",
    },
    {
        "id": "P1-003",
        "pillar": 1,
        "dora_metric": "lead_time",
        "name": "No interruptible: true on build and test jobs",
        "description": (
            "Without interruptible: true, pushing a new commit while a pipeline "
            "is running does not cancel the old one. Runners are wasted on "
            "outdated pipelines, queuing delays accumulate."
        ),
        "severity": "medium",
        "est_saving": "Eliminates queued pipeline waste",
    },
    {
        "id": "P1-004",
        "pillar": 1,
        "dora_metric": "lead_time",
        "name": "Artifacts stored without expire_in",
        "description": (
            "Jobs producing artifacts without expire_in store them indefinitely. "
            "This increases storage costs and slows artifact download for downstream "
            "jobs as the artifact store grows."
        ),
        "severity": "low",
        "est_saving": "Reduced artifact download time",
    },
    {
        "id": "P1-005",
        "pillar": 1,
        "dora_metric": "lead_time",
        "name": "Pipeline has 4+ stages but no job uses needs:",
        "description": (
            "With 4+ sequential stages and no needs: keyword, every job waits for "
            "its entire preceding stage to complete. Using needs: allows jobs to "
            "start as soon as their direct dependencies finish, cutting wait time."
        ),
        "severity": "high",
        "est_saving": "5–20 min per pipeline run",
    },
    {
        "id": "P1-006",
        "pillar": 1,
        "dora_metric": "lead_time",
        "name": "Single test job with no parallel: matrix",
        "description": (
            "A single test job runs the entire test suite sequentially. Using "
            "parallel: N or a matrix splits the suite across N runners, dividing "
            "test time by N."
        ),
        "severity": "medium",
        "est_saving": "50–80% reduction in test stage duration",
    },

    # ── Pillar 2 — Change Failure Rate ───────────────────────────────────────
    {
        "id": "P2-001",
        "pillar": 2,
        "dora_metric": "change_failure_rate",
        "name": "No test job found in pipeline",
        "description": (
            "The pipeline has no job identifiable as running tests. Code is "
            "deployed without automated validation, directly increasing the "
            "probability of production failures."
        ),
        "severity": "critical",
        "est_saving": "Directly reduces change failure rate",
    },
    {
        "id": "P2-002",
        "pillar": 2,
        "dora_metric": "change_failure_rate",
        "name": "Deploy job bypasses test stage via needs:",
        "description": (
            "A deploy job uses needs: that does not include any test job, allowing "
            "it to start before tests complete. Code can be deployed with failing "
            "tests."
        ),
        "severity": "critical",
        "est_saving": "Prevents deploying untested code",
    },
    {
        "id": "P2-003",
        "pillar": 2,
        "dora_metric": "change_failure_rate",
        "name": "No smoke test or health check after deployment",
        "description": (
            "No job runs after the deploy stage to verify the deployment succeeded. "
            "Silent failures go undetected until users report them."
        ),
        "severity": "high",
        "est_saving": "Faster detection of broken deployments",
    },
    {
        "id": "P2-004",
        "pillar": 2,
        "dora_metric": "change_failure_rate",
        "name": "Critical job has allow_failure: true",
        "description": (
            "A test or deploy job has allow_failure: true, meaning the pipeline "
            "reports success even when that job fails. Failures are silently ignored."
        ),
        "severity": "critical",
        "est_saving": "Prevents false green pipelines",
    },
    {
        "id": "P2-005",
        "pillar": 2,
        "dora_metric": "change_failure_rate",
        "name": "No security scanning job (SAST / dependency scan)",
        "description": (
            "No SAST, dependency scan, or container scan job is configured. "
            "Vulnerabilities are not detected before deployment."
        ),
        "severity": "medium",
        "est_saving": "Catches vulnerabilities before production",
    },
    {
        "id": "P2-006",
        "pillar": 2,
        "dora_metric": "change_failure_rate",
        "name": "No linting or code quality job",
        "description": (
            "No lint, format, or static analysis job runs before tests. Syntax "
            "errors and style violations are caught late, wasting test runner time."
        ),
        "severity": "low",
        "est_saving": "Catches trivial errors before test stage",
    },

    # ── Pillar 3 — Deployment Frequency ──────────────────────────────────────
    {
        "id": "P3-001",
        "pillar": 3,
        "dora_metric": "deployment_frequency",
        "name": "All deployments require manual trigger",
        "description": (
            "Every deploy job has when: manual with no automated path to production. "
            "Deployment frequency is gated by human availability rather than pipeline "
            "readiness."
        ),
        "severity": "medium",
        "est_saving": "Enables continuous deployment",
    },
    {
        "id": "P3-002",
        "pillar": 3,
        "dora_metric": "deployment_frequency",
        "name": "No merge request pipeline configured",
        "description": (
            "No job uses rules: with $CI_PIPELINE_SOURCE == 'merge_request_event'. "
            "Code is not validated on MR creation — feedback arrives only after merge."
        ),
        "severity": "high",
        "est_saving": "Shifts feedback left, reduces review cycle time",
    },
    {
        "id": "P3-003",
        "pillar": 3,
        "dora_metric": "deployment_frequency",
        "name": "No pipeline triggered on push to default branch",
        "description": (
            "Pipeline rules do not include a condition for pushes to main/master. "
            "Merged code is not automatically built and deployed."
        ),
        "severity": "high",
        "est_saving": "Enables automatic deployment on merge",
    },
    {
        "id": "P3-004",
        "pillar": 3,
        "dora_metric": "deployment_frequency",
        "name": "No environment: defined on deploy jobs",
        "description": (
            "Deploy jobs do not declare an environment:, so GitLab cannot track "
            "deployment history, approval requirements, or protected environments. "
            "Deployment visibility is lost."
        ),
        "severity": "low",
        "est_saving": "Deployment tracking and governance",
    },

    # ── Pillar 4 — MTTR ───────────────────────────────────────────────────────
    {
        "id": "P4-001",
        "pillar": 4,
        "dora_metric": "mttr",
        "name": "No rollback job or environment on_stop defined",
        "description": (
            "No rollback job exists and no environment has on_stop: configured. "
            "Recovery from a bad deployment requires manual intervention with no "
            "automated path back to the previous version."
        ),
        "severity": "high",
        "est_saving": "Reduces recovery time from minutes to seconds",
    },
    {
        "id": "P4-002",
        "pillar": 4,
        "dora_metric": "mttr",
        "name": "No failure notification job",
        "description": (
            "No job uses when: on_failure to send alerts on pipeline failure. "
            "The team is not notified of broken pipelines unless they actively "
            "check GitLab."
        ),
        "severity": "high",
        "est_saving": "Faster detection of broken pipelines",
    },
    {
        "id": "P4-003",
        "pillar": 4,
        "dora_metric": "mttr",
        "name": "No retry: on deploy jobs",
        "description": (
            "Deploy jobs have no retry: configured. Transient infrastructure "
            "failures (network blips, registry timeouts) cause full pipeline "
            "failures requiring manual re-runs."
        ),
        "severity": "low",
        "est_saving": "Eliminates manual re-runs for transient failures",
    },
    {
        "id": "P4-004",
        "pillar": 4,
        "dora_metric": "mttr",
        "name": "No environment URL defined",
        "description": (
            "Deploy jobs declare an environment but no url:. The team cannot "
            "one-click open the deployed application from the GitLab pipeline view "
            "to verify or diagnose issues."
        ),
        "severity": "low",
        "est_saving": "Faster access to deployed environment",
    },
    {
        "id": "P4-005",
        "pillar": 4,
        "dora_metric": "mttr",
        "name": "No timeout defined on long-running jobs",
        "description": (
            "Jobs have no timeout: set. A hung job (network wait, deadlock) blocks "
            "the pipeline for the GitLab project default timeout (60 min), delaying "
            "detection and recovery."
        ),
        "severity": "medium",
        "est_saving": "Reduces time stuck on hung pipelines",
    },
]

CHECKS_BY_ID = {c["id"]: c for c in CHECKS}

PILLAR_META = {
    1: {"name": "Lead Time",            "dora_metric": "lead_time",            "icon": "fa-gauge-high",      "color": "#6366f1"},
    2: {"name": "Change Failure Rate",  "dora_metric": "change_failure_rate",  "icon": "fa-shield-halved",   "color": "#ef4444"},
    3: {"name": "Deployment Frequency", "dora_metric": "deployment_frequency", "icon": "fa-rocket",          "color": "#10b981"},
    4: {"name": "MTTR",                 "dora_metric": "mttr",                 "icon": "fa-arrow-rotate-left","color": "#f59e0b"},
}
