"""
CLI entry point and agent loop for agent-pipeline-reviewer.
"""

import argparse
import json
import os
import sys

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

from .tools import list_files, build_pipeline_graph, run_pipeline_checks, read_file
from .gitlab_parser import parse_pipeline_dir, pipeline_summary
from .checks import run_all_checks
from .rubric import PILLAR_META

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────

MODEL             = "claude-haiku-4-5-20251001"
MAX_ITERATIONS    = 20
MAX_TOKENS_INPUT  = 60_000
MAX_OUTPUT_TOKENS = 6144

SYSTEM_PROMPT = """You are an expert DevOps engineer and platform engineering specialist \
reviewing a GitLab CI pipeline for DORA metric impact and operational best practices.

You have access to tools that parse the pipeline configuration and run deterministic checks. \
Your role is to:
1. Understand the pipeline structure and job dependency graph
2. Analyse the deterministic check results across the 4 DORA pillars
3. Write a clear, actionable report explaining:
   - What each failing check means for the team's DORA metrics
   - The specific fix with example YAML
   - The expected impact on Lead Time, Change Failure Rate, Deployment Frequency, or MTTR

Structure your report with sections per DORA pillar. Be specific about job names and \
concrete about fixes. Prioritise the highest-impact findings. End with a prioritised \
action list of the top 3 fixes ranked by DORA impact."""

TOOL_DEFINITIONS = [
    {
        "name": "list_files",
        "description": "Discover .gitlab-ci.yml and related pipeline files in the target directory.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Directory to scan"}},
            "required": ["path"],
        },
    },
    {
        "name": "build_pipeline_graph",
        "description": "Parse .gitlab-ci.yml and return the full job dependency graph with flags.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Directory containing .gitlab-ci.yml"}},
            "required": ["path"],
        },
    },
    {
        "name": "run_pipeline_checks",
        "description": "Run all 21 deterministic DORA checks against the pipeline. Always call this before writing the report.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Directory containing .gitlab-ci.yml"}},
            "required": ["path"],
        },
    },
    {
        "name": "read_file",
        "description": "Read a specific pipeline YAML file with line numbers for detailed inspection.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path":      {"type": "string", "description": "Base directory"},
                "file_path": {"type": "string", "description": "Relative path to the file"},
            },
            "required": ["path", "file_path"],
        },
    },
]


# ─────────────────────────────────────────────
# Agent loop
# ─────────────────────────────────────────────

def run_agent(target_path: str, quiet: bool = False) -> str:
    """Run the full AI-assisted pipeline review. Returns the report text."""
    if not ANTHROPIC_AVAILABLE:
        print("ERROR: anthropic package not installed — run: pip install anthropic", file=sys.stderr)
        sys.exit(1)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print(
            "ERROR: ANTHROPIC_API_KEY not set.\n"
            "Export your key: export ANTHROPIC_API_KEY=your-key-here",
            file=sys.stderr,
        )
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    messages = [{"role": "user", "content": f"Review the GitLab CI pipeline in: {target_path}"}]
    report_text = ""
    token_count = 0
    iteration   = 0

    def _dispatch(name: str, inputs: dict) -> str:
        if name == "list_files":
            return list_files(inputs["path"])
        if name == "build_pipeline_graph":
            return build_pipeline_graph(inputs["path"])
        if name == "run_pipeline_checks":
            return run_pipeline_checks(inputs["path"])
        if name == "read_file":
            return read_file(inputs["path"], inputs["file_path"])
        return f"Unknown tool: {name}"

    while iteration < MAX_ITERATIONS and token_count < MAX_TOKENS_INPUT:
        iteration += 1
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=SYSTEM_PROMPT,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )
        token_count += response.usage.input_tokens + response.usage.output_tokens

        # Collect text and tool calls
        text_parts = []
        tool_uses  = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_uses.append(block)

        text = "\n".join(text_parts).strip()
        if text and not quiet:
            print(text)

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            report_text = text
            break

        if not tool_uses:
            report_text = text
            break

        # Execute tools
        tool_results = []
        for tu in tool_uses:
            if not quiet:
                print(f"\n[Tool: {tu.name}({', '.join(f'{k}={v}' for k, v in tu.input.items())})]\n")
            result = _dispatch(tu.name, tu.input)
            if not quiet:
                print(result[:2000])
                if len(result) > 2000:
                    print(f"... [{len(result)-2000} chars truncated]")
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": result,
            })

        messages.append({"role": "user", "content": tool_results})

    if iteration >= MAX_ITERATIONS and not report_text:
        report_text = f"Review did not complete within {MAX_ITERATIONS} iterations."

    return report_text


# ─────────────────────────────────────────────
# Deterministic-only mode (no API key)
# ─────────────────────────────────────────────

def run_deterministic_review(target_path: str) -> dict:
    """Run deterministic checks only — no Claude, no API key."""
    parsed  = parse_pipeline_dir(target_path)
    results = run_all_checks(parsed)

    by_pillar: dict = {}
    for r in results:
        by_pillar.setdefault(r["pillar"], []).append(r)

    passing = sum(1 for r in results if r["status"] == "pass")
    total   = sum(1 for r in results if r["status"] != "info")
    score_pct = int(passing / total * 100) if total else 0

    if score_pct >= 80:    grade = "Elite performer"
    elif score_pct >= 60:  grade = "High performer"
    elif score_pct >= 40:  grade = "Medium performer"
    else:                  grade = "Low performer"

    pillar_scores = {}
    for pnum, checks in by_pillar.items():
        p_pass  = sum(1 for r in checks if r["status"] == "pass")
        p_total = sum(1 for r in checks if r["status"] != "info")
        pillar_scores[pnum] = {
            "name":       PILLAR_META[pnum]["name"],
            "dora_metric": PILLAR_META[pnum]["dora_metric"],
            "passing":    p_pass,
            "total":      p_total,
            "score_pct":  int(p_pass / p_total * 100) if p_total else 0,
        }

    failing = [r["id"] for r in results if r["status"] == "fail"]
    warning = [r["id"] for r in results if r["status"] == "warn"]

    return {
        "score_pct":     score_pct,
        "grade":         grade,
        "passing":       passing,
        "total":         total,
        "failing_checks": failing,
        "warning_checks": warning,
        "pillar_scores":  pillar_scores,
        "pipeline_files": parsed["pipeline_files"],
        "parse_errors":   parsed["parse_errors"],
        "source":         "deterministic",
        "target":         os.path.abspath(target_path),
    }


# ─────────────────────────────────────────────
# Report saving
# ─────────────────────────────────────────────

def _save_json(data: dict, output_dir: str, base_name: str) -> str:
    from datetime import datetime
    data["generated_at"] = datetime.now().isoformat(timespec="seconds")
    path = os.path.join(output_dir, f"{base_name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return path


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="pipeline-review",
        description="AI agent that reviews GitLab CI pipelines for DORA metric anti-patterns",
    )
    parser.add_argument("path", help="Directory containing .gitlab-ci.yml")
    parser.add_argument(
        "--checks-only", action="store_true",
        help="Run deterministic checks only — no AI narration, no API key required",
    )
    parser.add_argument(
        "--fail-under", type=int, default=0, metavar="N",
        help="Exit with code 1 if score is below N%%",
    )
    parser.add_argument(
        "--output-dir", default=".", metavar="DIR",
        help="Directory for report output (default: current directory)",
    )
    parser.add_argument(
        "--output-file", default=None, metavar="NAME",
        help="Base name for report files (without extension)",
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress live output")
    args = parser.parse_args()

    if not os.path.isdir(args.path):
        print(f"ERROR: Directory not found: {args.path}", file=sys.stderr)
        sys.exit(1)

    os.makedirs(args.output_dir, exist_ok=True)

    from datetime import datetime
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = args.output_file or f"pipeline_review_{ts}"

    # ── Checks-only mode ──────────────────────────────────────────────
    if args.checks_only:
        result = run_deterministic_review(args.path)
        print(f"\nScore: {result['score_pct']}% — {result['grade']}")
        print(f"Passing: {result['passing']}/{result['total']} checks")
        if result["failing_checks"]:
            print(f"Failing: {', '.join(result['failing_checks'])}")
        if result["warning_checks"]:
            print(f"Warnings: {', '.join(result['warning_checks'])}")
        if result["parse_errors"]:
            for e in result["parse_errors"]:
                print(f"WARNING: {e}", file=sys.stderr)

        json_path = _save_json(result, args.output_dir, name)
        print(f"\nJSON report: {json_path}")

        if args.fail_under and result["score_pct"] < args.fail_under:
            print(f"\nFAIL: score {result['score_pct']}% is below threshold {args.fail_under}%")
            sys.exit(1)
        return

    # ── Full AI-assisted review ───────────────────────────────────────
    if not quiet_check(args):
        print(f"Reviewing pipeline in: {args.path}")
        print(f"Model: {MODEL}\n")

    report_text = run_agent(args.path, quiet=args.quiet)

    # Parse score from report for JSON
    import re
    score_match = re.search(r"(\d+)\s*/\s*(\d+)\s+checks?\s+pass", report_text, re.IGNORECASE)
    if not score_match:
        score_match = re.search(r"TOTAL[^\d]*(\d+)\s*/\s*(\d+)", report_text)

    passing_n = int(score_match.group(1)) if score_match else 0
    total_n   = int(score_match.group(2)) if score_match else 21
    score_pct = int(passing_n / total_n * 100) if total_n else 0

    json_data = {
        "score_pct": score_pct,
        "passing":   passing_n,
        "total":     total_n,
        "target":    os.path.abspath(args.path),
        "source":    "agent",
    }
    json_path = _save_json(json_data, args.output_dir, name)

    # HTML report
    try:
        from .report import save_report
        html_path = save_report(report_text, args.path, args.output_dir, name)
        if not args.quiet:
            print(f"\nHTML report: {html_path}")
    except Exception as exc:
        if not args.quiet:
            print(f"WARNING: Could not generate HTML report: {exc}", file=sys.stderr)

    if not args.quiet:
        print(f"JSON report: {json_path}")

    if args.fail_under and score_pct < args.fail_under:
        print(f"\nFAIL: score {score_pct}% is below threshold {args.fail_under}%")
        sys.exit(1)


def quiet_check(args) -> bool:
    return getattr(args, "quiet", False)


if __name__ == "__main__":
    main()
