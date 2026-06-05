"""
Agent tools — callable by the Claude agent loop.

Tools return plain text consumed by Claude as tool results.
"""

import json
import os
from .gitlab_parser import parse_pipeline_dir, pipeline_summary, deploy_jobs, test_jobs
from .checks import run_all_checks
from .rubric import CHECKS_BY_ID, PILLAR_META


def list_files(path: str) -> str:
    """Discover .gitlab-ci.yml and related pipeline files."""
    lines = [f"Scanning: {os.path.abspath(path)}", ""]
    found = []
    for root, _, files in os.walk(path):
        # Skip hidden dirs and common non-pipeline dirs
        rel = os.path.relpath(root, path)
        if any(p.startswith(".") and p not in (".",) for p in rel.split(os.sep)):
            continue
        for f in sorted(files):
            if f in (".gitlab-ci.yml", ".gitlab-ci.yaml") or f.endswith((".yml", ".yaml")):
                rel_path = os.path.relpath(os.path.join(root, f), path)
                found.append(rel_path)

    if not found:
        return f"No YAML files found in {path}"

    lines.append("Pipeline files found:")
    for f in found[:30]:
        lines.append(f"  {f}")
    if len(found) > 30:
        lines.append(f"  ... and {len(found) - 30} more")

    return "\n".join(lines)


def build_pipeline_graph(path: str) -> str:
    """Parse .gitlab-ci.yml and show the job dependency graph."""
    parsed = parse_pipeline_dir(path)

    lines = [f"Pipeline: {pipeline_summary(parsed)}", ""]

    if parsed["parse_errors"]:
        lines.append("PARSE ERRORS:")
        for e in parsed["parse_errors"]:
            lines.append(f"  ⚠ {e}")
        lines.append("")

    # Stages
    if parsed["stages"]:
        lines.append(f"Stages ({len(parsed['stages'])}): {' → '.join(parsed['stages'])}")
        lines.append("")

    # Global config
    if parsed["global_cache"]:
        lines.append("✓ Global cache configured")
    if parsed["global_image"]:
        lines.append(f"Global image: {parsed['global_image']}")
    lines.append("")

    # Jobs by stage
    from .gitlab_parser import jobs_by_stage
    by_stage = jobs_by_stage(parsed)

    for stage in (parsed["stages"] or sorted(by_stage.keys())):
        stage_jobs = by_stage.get(stage, [])
        if not stage_jobs:
            continue
        lines.append(f"[{stage.upper()}]")
        for job in stage_jobs:
            flags = []
            if job.get("when") == "manual":       flags.append("manual")
            if job.get("allow_failure") is True:   flags.append("allow_failure")
            if job.get("interruptible"):            flags.append("interruptible")
            if job.get("retry"):                   flags.append(f"retry:{job['retry'].get('max',1)}")
            if job.get("parallel"):                flags.append(f"parallel:{job['parallel']}")
            if job.get("cache"):                   flags.append("cache")
            if job.get("artifacts"):               flags.append("artifacts")
            if job.get("environment"):
                env_name = job["environment"].get("name", "") if isinstance(job["environment"], dict) else job["environment"]
                flags.append(f"env:{env_name}")
            if job.get("needs"):                   flags.append(f"needs:{','.join(job['needs'][:3])}")
            if job.get("timeout"):                 flags.append(f"timeout:{job['timeout']}")

            img = job.get("image") or parsed.get("global_image") or ""
            flag_str = f" [{', '.join(flags)}]" if flags else ""
            img_str  = f" ({img})" if img else ""
            lines.append(f"  • {job['name']}{img_str}{flag_str}")

            # Show first 3 script lines
            for cmd in job.get("script", [])[:3]:
                lines.append(f"      $ {cmd[:80]}")
            if len(job.get("script", [])) > 3:
                lines.append(f"      ... +{len(job['script'])-3} more commands")
        lines.append("")

    # Cross-job signals
    signals = []
    d_jobs = deploy_jobs(parsed)
    t_jobs = test_jobs(parsed)

    if d_jobs and not t_jobs:
        signals.append("⚠️  RISK: Deploy jobs found but NO test jobs detected")
    if d_jobs and t_jobs:
        test_names = {j["name"] for j in t_jobs}
        for dj in d_jobs:
            needs = set(dj.get("needs", []))
            if needs and not needs.intersection(test_names):
                signals.append(f"⚠️  RISK: Deploy job '{dj['name']}' bypasses test jobs via needs:")

    no_cache_jobs = [
        j["name"] for j in parsed["jobs"].values()
        if any(k in " ".join(j.get("script", [])) for k in ["npm install", "pip install", "bundle install"])
        and not j.get("cache") and not parsed.get("global_cache")
    ]
    if no_cache_jobs:
        signals.append(f"⚠️  RISK: Install jobs without cache: {', '.join(no_cache_jobs)}")

    if not any(j.get("needs") for j in parsed["jobs"].values()) and len(parsed.get("stages", [])) >= 4:
        signals.append(f"⚠️  RISK: {len(parsed['stages'])} stages but no needs: — all jobs wait for full stage completion")

    if signals:
        lines.append("Cross-job signals:")
        lines.extend(f"  {s}" for s in signals)

    return "\n".join(lines)


def run_pipeline_checks(path: str) -> str:
    """Run all 21 deterministic checks and return scored results."""
    parsed = parse_pipeline_dir(path)

    if parsed["parse_errors"] and not parsed["jobs"]:
        return "FATAL: " + "; ".join(parsed["parse_errors"])

    results = run_all_checks(parsed)

    # Group by pillar
    by_pillar: dict = {}
    for r in results:
        by_pillar.setdefault(r["pillar"], []).append(r)

    lines = []
    passing = 0
    total = 0
    status_order = {"fail": 0, "warn": 1, "pass": 2, "info": 3}

    for pillar_num in sorted(by_pillar.keys()):
        meta = PILLAR_META[pillar_num]
        pillar_results = sorted(by_pillar[pillar_num], key=lambda r: status_order.get(r["status"], 9))
        p_pass = sum(1 for r in pillar_results if r["status"] == "pass")
        p_total = sum(1 for r in pillar_results if r["status"] != "info")

        lines.append(f"\nPillar {pillar_num} — {meta['name']} (DORA: {meta['dora_metric']})")
        lines.append(f"  {p_pass}/{p_total} checks passing")

        for r in pillar_results:
            emoji = {"pass": "✅", "fail": "❌", "warn": "⚠️", "info": "ℹ️"}.get(r["status"], "?")
            lines.append(f"  {emoji} {r['status'].upper()} [{r['id']}] {r['name']}")
            lines.append(f"       → {r['detail']}")

        passing += p_pass
        total   += p_total

    lines.append(f"\nTOTAL: {passing}/{total} checks passing")

    dora_profile = _dora_profile(passing, total)
    lines.append(f"DORA profile: {dora_profile}")

    return "\n".join(lines)


def read_file(path: str, file_path: str) -> str:
    """Read a specific pipeline file for detailed inspection."""
    full_path = os.path.join(path, file_path) if not os.path.isabs(file_path) else file_path
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
        lines = content.splitlines()
        numbered = "\n".join(f"{i+1:4d}  {l}" for i, l in enumerate(lines))
        return f"File: {file_path} ({len(lines)} lines)\n\n{numbered}"
    except FileNotFoundError:
        return f"File not found: {file_path}"
    except Exception as exc:
        return f"Error reading {file_path}: {exc}"


def _dora_profile(passing: int, total: int) -> str:
    if total == 0:
        return "Unknown"
    pct = passing / total * 100
    if pct >= 80:
        return "Elite performer"
    if pct >= 60:
        return "High performer"
    if pct >= 40:
        return "Medium performer"
    return "Low performer"
