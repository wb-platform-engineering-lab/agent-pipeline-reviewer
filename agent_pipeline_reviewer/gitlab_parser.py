"""
Parser for GitLab CI pipeline files (.gitlab-ci.yml + includes).

Returns a structured pipeline graph consumed by the check layer.
"""

import os
import re
from typing import Any

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

# Top-level reserved keywords — everything else is a job or hidden job (. prefix)
_RESERVED = {
    "stages", "variables", "cache", "default", "include",
    "workflow", "image", "services", "before_script", "after_script",
}


def parse_pipeline_dir(path: str) -> dict:
    """
    Find and parse .gitlab-ci.yml (+ local includes) in path.

    Returns:
    {
        "jobs":             { job_name: { stage, image, script, cache, artifacts,
                                          needs, rules, when, allow_failure,
                                          retry, environment, interruptible,
                                          parallel, variables, tags, timeout } },
        "stages":           ["build", "test", "deploy"],
        "global_cache":     dict | None,
        "global_image":     str | None,
        "global_variables": dict,
        "has_rules":        bool,       # any job uses rules:
        "pipeline_files":   ["..."],
        "parse_errors":     ["..."],
    }
    """
    result: dict = {
        "jobs": {},
        "stages": [],
        "global_cache": None,
        "global_image": None,
        "global_variables": {},
        "default_interruptible": False,
        "default_retry": None,
        "workflow_rules": [],
        "has_rules": False,
        "pipeline_files": [],
        "parse_errors": [],
    }

    if not YAML_AVAILABLE:
        result["parse_errors"].append("pyyaml not installed — run: pip install pyyaml")
        return result

    # Find main pipeline file
    candidates = [
        os.path.join(path, ".gitlab-ci.yml"),
        os.path.join(path, ".gitlab-ci.yaml"),
    ]
    main_file = next((f for f in candidates if os.path.isfile(f)), None)

    if not main_file:
        result["parse_errors"].append(
            f"No .gitlab-ci.yml found in {path}"
        )
        return result

    _parse_file(main_file, path, result, depth=0)

    if not result["jobs"] and not result["parse_errors"]:
        result["parse_errors"].append(
            "No jobs found in pipeline. "
            "Check that .gitlab-ci.yml defines at least one job."
        )

    return result


def _parse_file(file_path: str, base_path: str, result: dict, depth: int) -> None:
    """Parse a single YAML file and merge into result."""
    if depth > 5:
        return  # Guard against include cycles

    result["pipeline_files"].append(os.path.relpath(file_path, base_path))

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except FileNotFoundError:
        result["parse_errors"].append(f"File not found: {file_path}")
        return
    except yaml.YAMLError as exc:
        result["parse_errors"].append(f"YAML parse error in {os.path.basename(file_path)}: {exc}")
        return

    if not isinstance(raw, dict):
        result["parse_errors"].append(f"Invalid pipeline file: {os.path.basename(file_path)}")
        return

    # Stages
    if "stages" in raw and not result["stages"]:
        result["stages"] = list(raw["stages"])

    # Global variables
    if "variables" in raw and isinstance(raw["variables"], dict):
        result["global_variables"].update(raw["variables"])

    # Global cache (top-level or default:)
    if "cache" in raw and not result["global_cache"]:
        result["global_cache"] = raw["cache"]

    # default: block
    default = raw.get("default", {}) or {}
    if "cache" in default and not result["global_cache"]:
        result["global_cache"] = default["cache"]
    if "image" in default and not result["global_image"]:
        result["global_image"] = _extract_image(default["image"])
    if default.get("interruptible"):
        result["default_interruptible"] = True
    if "retry" in default and result["default_retry"] is None:
        retry_raw = default["retry"]
        result["default_retry"] = {"max": retry_raw} if isinstance(retry_raw, int) else retry_raw

    # workflow: rules
    workflow = raw.get("workflow", {}) or {}
    if "rules" in workflow and not result["workflow_rules"]:
        result["workflow_rules"] = workflow["rules"] if isinstance(workflow["rules"], list) else []

    # Top-level image
    if "image" in raw and not result["global_image"]:
        result["global_image"] = _extract_image(raw["image"])

    # Local includes
    includes = raw.get("include", [])
    if isinstance(includes, str):
        includes = [{"local": includes}]
    elif isinstance(includes, dict):
        includes = [includes]

    for inc in (includes or []):
        if isinstance(inc, dict) and "local" in inc:
            local_path = os.path.join(base_path, inc["local"].lstrip("/"))
            if os.path.isfile(local_path):
                _parse_file(local_path, base_path, result, depth + 1)

    # Jobs — everything that is not a reserved keyword and not a hidden job
    for key, value in raw.items():
        if key in _RESERVED:
            continue
        if key.startswith("."):
            continue  # template / hidden job
        if not isinstance(value, dict):
            continue
        if "script" not in value and "trigger" not in value and "extends" not in value:
            continue  # not a real job

        job = _extract_job(key, value)
        result["jobs"][key] = job

        if job.get("rules"):
            result["has_rules"] = True

    # Default stages if none declared
    if not result["stages"]:
        seen = {}
        for job in result["jobs"].values():
            s = job.get("stage", "test")
            if s not in seen:
                seen[s] = True
        result["stages"] = list(seen.keys()) or ["test"]


def _extract_job(name: str, raw: dict) -> dict:
    """Normalise a raw job dict into a consistent structure."""
    # needs: can be list of strings or list of dicts
    needs_raw = raw.get("needs", [])
    needs: list = []
    if isinstance(needs_raw, list):
        for n in needs_raw:
            if isinstance(n, str):
                needs.append(n)
            elif isinstance(n, dict) and "job" in n:
                needs.append(n["job"])

    # environment: can be string or dict
    env_raw = raw.get("environment")
    environment = None
    if isinstance(env_raw, str):
        environment = {"name": env_raw}
    elif isinstance(env_raw, dict):
        environment = env_raw

    # retry: can be int or dict
    retry_raw = raw.get("retry")
    retry = None
    if isinstance(retry_raw, int):
        retry = {"max": retry_raw}
    elif isinstance(retry_raw, dict):
        retry = retry_raw

    # cache: can be dict or list of dicts
    cache = raw.get("cache")

    # rules
    rules = raw.get("rules", [])
    if not isinstance(rules, list):
        rules = []

    # parallel: can be int or dict (matrix)
    parallel = raw.get("parallel")

    return {
        "name":          name,
        "stage":         raw.get("stage", "test"),
        "image":         _extract_image(raw.get("image")),
        "script":        _flatten_script(raw.get("script", [])),
        "before_script": _flatten_script(raw.get("before_script", [])),
        "after_script":  _flatten_script(raw.get("after_script", [])),
        "cache":         cache,
        "artifacts":     raw.get("artifacts"),
        "needs":         needs,
        "dependencies":  raw.get("dependencies", []),
        "rules":         rules,
        "only":          raw.get("only"),
        "except":        raw.get("except"),
        "when":          raw.get("when", "on_success"),
        "allow_failure": raw.get("allow_failure", False),
        "retry":         retry,
        "environment":   environment,
        "interruptible": raw.get("interruptible", False),
        "parallel":      parallel,
        "variables":     raw.get("variables", {}),
        "tags":          raw.get("tags", []),
        "timeout":       raw.get("timeout"),
        "trigger":       raw.get("trigger"),
        "extends":       raw.get("extends"),
    }


def _extract_image(image: Any) -> str | None:
    if image is None:
        return None
    if isinstance(image, str):
        return image
    if isinstance(image, dict):
        return image.get("name")
    return str(image)


def _flatten_script(script: Any) -> list:
    if not script:
        return []
    if isinstance(script, str):
        return [script]
    if isinstance(script, list):
        result = []
        for item in script:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, list):
                result.extend(item)
        return result
    return []


# ── Derived helpers ────────────────────────────────────────────────────────────

def jobs_by_stage(parsed: dict) -> dict:
    """Return {stage_name: [job_dicts]}."""
    out: dict = {}
    for job in parsed["jobs"].values():
        s = job["stage"]
        out.setdefault(s, []).append(job)
    return out


def deploy_jobs(parsed: dict) -> list:
    """Return jobs identified as deployment jobs."""
    deploy_keywords = {"deploy", "release", "publish", "production", "prod", "staging", "stage"}
    result = []
    for job in parsed["jobs"].values():
        stage = (job["stage"] or "").lower()
        name  = job["name"].lower()
        if any(k in stage for k in deploy_keywords) or any(k in name for k in deploy_keywords):
            result.append(job)
    return result


def test_jobs(parsed: dict) -> list:
    """Return jobs identified as test / quality jobs."""
    test_keywords = {"test", "spec", "lint", "check", "quality", "coverage", "verify"}
    result = []
    for job in parsed["jobs"].values():
        stage = (job["stage"] or "").lower()
        name  = job["name"].lower()
        if any(k in stage for k in test_keywords) or any(k in name for k in test_keywords):
            result.append(job)
    return result


def stage_index(parsed: dict, stage_name: str) -> int:
    """Return the 0-based index of a stage, or 999 if not found."""
    stages = parsed.get("stages", [])
    try:
        return stages.index(stage_name)
    except ValueError:
        return 999


def pipeline_summary(parsed: dict) -> str:
    """Return a one-line human-readable summary."""
    n_jobs   = len(parsed["jobs"])
    n_stages = len(parsed["stages"])
    n_errors = len(parsed["parse_errors"])
    files    = ", ".join(parsed["pipeline_files"][:3])
    err_note = f", {n_errors} parse error(s)" if n_errors else ""
    return f"{files} — {n_jobs} jobs across {n_stages} stages{err_note}"
