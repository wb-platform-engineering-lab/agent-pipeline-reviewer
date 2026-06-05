"""
HTML report generator for agent-pipeline-reviewer.
Adapted from agent-terraform-cost-reviewer with 4-pillar DORA layout.
"""

import os
import re
from datetime import datetime


PILLAR_META = {
    1: {"name": "Lead Time",            "icon": "fa-gauge-high",       "color": "#6366f1"},
    2: {"name": "Change Failure Rate",  "icon": "fa-shield-halved",    "color": "#ef4444"},
    3: {"name": "Deployment Frequency", "icon": "fa-rocket",           "color": "#10b981"},
    4: {"name": "MTTR",                 "icon": "fa-arrow-rotate-left", "color": "#f59e0b"},
}

DORA_LEVELS = [
    (80, "Elite",  "#16a34a", "bg-emerald-100 text-emerald-800"),
    (60, "High",   "#3b82f6", "bg-blue-100 text-blue-800"),
    (40, "Medium", "#fb923c", "bg-orange-100 text-orange-700"),
    (0,  "Low",    "#dc2626", "bg-red-100 text-red-800"),
]


def _dora_level(pct: int):
    for threshold, label, color, cls in DORA_LEVELS:
        if pct >= threshold:
            return label, color, cls
    return "Low", "#dc2626", "bg-red-100 text-red-800"


# ── Markdown → HTML ────────────────────────────────────────────────────────────

def _inline(text: str) -> str:
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = text.replace("✅ PASS", '<span class="inline-flex px-2 py-0.5 rounded-full text-xs font-bold bg-emerald-100 text-emerald-800">PASS</span>')
    text = text.replace("❌ FAIL", '<span class="inline-flex px-2 py-0.5 rounded-full text-xs font-bold bg-red-100 text-red-800">FAIL</span>')
    text = text.replace("⚠️ WARN", '<span class="inline-flex px-2 py-0.5 rounded-full text-xs font-bold bg-yellow-100 text-yellow-800">WARN</span>')
    text = text.replace("ℹ️ INFO", '<span class="inline-flex px-2 py-0.5 rounded-full text-xs font-bold bg-blue-100 text-blue-800">INFO</span>')
    text = re.sub(r"\*\*(.+?)\*\*", r'<strong class="font-semibold">\1</strong>', text)
    text = re.sub(r"`([^`]+)`", r'<code class="bg-gray-100 dark:bg-gray-700 text-xs px-1.5 py-0.5 rounded font-mono">\1</code>', text)
    text = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2" class="text-blue-500 hover:underline">\1</a>', text)
    return text


def md_to_html(text: str) -> str:
    lines = text.split("\n")
    html = []
    in_code = False
    in_table = False
    code_lines: list = []
    i = 0

    while i < len(lines):
        line = lines[i]
        s = line.strip()

        if s.startswith("```"):
            if not in_code:
                in_code = True
                code_lines = []
            else:
                in_code = False
                escaped = "\n".join(code_lines).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                html.append(
                    f'<div class="relative group my-3">'
                    f'<pre class="bg-gray-900 text-green-300 text-xs rounded-xl p-4 overflow-x-auto font-mono leading-relaxed">{escaped}</pre>'
                    f'<button onclick="copyPre(this)" class="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity bg-gray-700 hover:bg-gray-600 text-gray-300 text-xs px-2 py-1 rounded">'
                    f'<i class="fas fa-copy mr-1"></i>Copy</button></div>'
                )
                code_lines = []
            i += 1
            continue

        if in_code:
            code_lines.append(line)
            i += 1
            continue

        if s.startswith("|") and s.endswith("|"):
            if re.match(r"^\|[\s\-:|]+\|$", s):
                i += 1
                continue
            if not in_table:
                in_table = True
                html.append('<div class="overflow-x-auto my-3"><table class="w-full text-sm border-collapse">')
                cells = [c.strip() for c in s.strip("|").split("|")]
                html.append("<thead><tr>" + "".join(
                    f'<th class="px-3 py-2 bg-gray-100 dark:bg-gray-700 font-semibold text-left border border-gray-200 dark:border-gray-600 text-xs uppercase tracking-wider">{_inline(c)}</th>'
                    for c in cells
                ) + "</tr></thead><tbody>")
            else:
                cells = [c.strip() for c in s.strip("|").split("|")]
                html.append("<tr>" + "".join(
                    f'<td class="px-3 py-2 border border-gray-100 dark:border-gray-700 align-top">{_inline(c)}</td>'
                    for c in cells
                ) + "</tr>")
            i += 1
            continue
        else:
            if in_table:
                html.append("</tbody></table></div>")
                in_table = False

        m = re.match(r"^(#{1,4})\s+(.+)", s)
        if m:
            level = len(m.group(1))
            sizes = {1: "text-2xl font-black", 2: "text-xl font-bold", 3: "text-base font-bold", 4: "text-sm font-semibold"}
            mt = "mt-6" if level <= 2 else "mt-4"
            html.append(f'<h{level} class="{sizes.get(level,"text-sm font-semibold")} {mt} mb-2 text-gray-900 dark:text-white">{_inline(m.group(2))}</h{level}>')
            i += 1
            continue

        if re.match(r"^[-*]\s+", s):
            items = []
            while i < len(lines) and re.match(r"^[-*]\s+", lines[i].strip()):
                items.append(_inline(re.sub(r"^[-*]\s+", "", lines[i].strip())))
                i += 1
            html.append('<ul class="list-disc pl-5 space-y-1 my-2 text-sm text-gray-700 dark:text-gray-300">' + "".join(f"<li>{it}</li>" for it in items) + "</ul>")
            continue

        if re.match(r"^\d+[.)]\s+", s):
            items = []
            while i < len(lines) and re.match(r"^\d+[.)]\s+", lines[i].strip()):
                items.append(_inline(re.sub(r"^\d+[.)]\s+", "", lines[i].strip())))
                i += 1
            html.append('<ol class="list-decimal pl-5 space-y-1 my-2 text-sm text-gray-700 dark:text-gray-300">' + "".join(f"<li>{it}</li>" for it in items) + "</ol>")
            continue

        if not s or re.match(r"^[-─═]{3,}$", s):
            html.append('<div class="h-2"></div>')
            i += 1
            continue

        html.append(f'<p class="text-sm text-gray-700 dark:text-gray-300 mb-2">{_inline(s)}</p>')
        i += 1

    if in_table:
        html.append("</tbody></table></div>")
    return "\n".join(html)


# ── Parser ─────────────────────────────────────────────────────────────────────

def parse_report(text: str) -> dict:
    """Extract structured check data and pillar scores from report text."""
    checks: list = []
    overall_score = None
    action_items: list = []
    seen_ids: set = set()
    in_actions = False

    for line in text.split("\n"):
        s = line.strip()
        if not s:
            continue

        if not overall_score:
            m = (re.search(r"(\d+)\s*/\s*(\d+)\s+checks?\s+pass", s, re.IGNORECASE)
                 or re.search(r"TOTAL[^\d]*(\d+)\s*/\s*(\d+)", s))
            if m:
                overall_score = (int(m.group(1)), int(m.group(2)))

        # Inline check: ❌ FAIL [P1-001] ...
        m = re.match(r"(❌|⚠️|✅|ℹ️)\s*(FAIL|WARN|PASS|INFO)\s+\[?(P\d-\d+)\]?\s*(.*)", s)
        if m:
            _, status_str, check_id, name = m.group(1), m.group(2), m.group(3), m.group(4)
            pillar = int(check_id[1])
            if check_id not in seen_ids:
                seen_ids.add(check_id)
                checks.append({"status": status_str.lower(), "id": check_id,
                               "pillar": pillar, "name": name or check_id})
            continue

        # Detail line → attach to last check
        if checks and re.match(r"→\s+", s):
            checks[-1].setdefault("detail", s.lstrip("→").strip())

        # Action items
        if re.search(r"(top \d|priority|highest.impact|action)", s, re.IGNORECASE):
            in_actions = True
            continue
        if in_actions:
            if re.match(r"^\d+[.)]\s+", s):
                action_items.append(re.sub(r"^\d+[.)]\s+", "", s))

    # Group into pillars
    pillar_map: dict = {}
    for c in checks:
        pillar_map.setdefault(c["pillar"], []).append(c)

    passing = sum(1 for c in checks if c["status"] == "pass")
    total   = overall_score[1] if overall_score else max(len(checks), 21)

    pillars = []
    for pnum in sorted(PILLAR_META.keys()):
        pchecks = pillar_map.get(pnum, [])
        p_pass  = sum(1 for c in pchecks if c["status"] == "pass")
        p_total = sum(1 for c in pchecks if c["status"] != "info")
        pillars.append({
            "num": pnum,
            "name": PILLAR_META[pnum]["name"],
            "pass": p_pass,
            "total": p_total,
            "checks": pchecks,
        })

    return {
        "pillars": pillars,
        "overall_score": overall_score or (passing, total),
        "action_items": action_items[:5],
        "raw": text,
    }


# ── HTML generation ────────────────────────────────────────────────────────────

def _pillar_card(p: dict) -> str:
    meta = PILLAR_META[p["num"]]
    pct  = int(p["pass"] / p["total"] * 100) if p["total"] else 0
    level, color, badge_cls = _dora_level(pct)

    checks_html = ""
    for c in p["checks"]:
        cfg = {
            "pass": ("fa-circle-check text-emerald-500", "bg-emerald-100 text-emerald-800", "PASS"),
            "fail": ("fa-circle-xmark text-red-500",     "bg-red-100 text-red-800",         "FAIL"),
            "warn": ("fa-triangle-exclamation text-amber-500", "bg-amber-100 text-amber-800", "WARN"),
            "info": ("fa-circle-info text-blue-500",     "bg-blue-100 text-blue-800",        "INFO"),
        }
        icon_cls, bc, label = cfg.get(c["status"], cfg["info"])
        detail = c.get("detail", "")
        detail_html = ""
        if detail:
            detail_html = (
                f'<div class="check-detail pl-12 pb-3 border-t border-gray-50 dark:border-gray-700/50" style="display:none">'
                f'<p class="text-xs text-gray-500 dark:text-gray-400 pt-2">{_inline(detail)}</p></div>'
            )
        clickable = 'onclick="toggleCheck(this)" class="flex items-center gap-3 px-4 py-3 w-full text-left hover:bg-gray-50 dark:hover:bg-gray-700/30 transition-colors cursor-pointer"' if detail else 'class="flex items-center gap-3 px-4 py-3"'
        chevron = '<i class="fas fa-chevron-down text-gray-300 text-xs flex-shrink-0 check-chevron -rotate-90"></i>' if detail else ""
        checks_html += (
            f'<div class="border-b border-gray-50 dark:border-gray-700/50 last:border-0">'
            f'<{"button " + clickable if detail else "div " + clickable}>'
            f'<i class="fas {icon_cls} flex-shrink-0 text-sm"></i>'
            f'<span class="inline-flex justify-center px-2 py-0.5 rounded-full text-xs font-bold {bc} flex-shrink-0 w-11">{label}</span>'
            f'<span class="font-mono text-xs text-gray-400 flex-shrink-0 w-16">{c["id"]}</span>'
            f'<span class="text-sm text-gray-800 dark:text-gray-200 flex-1 min-w-0">{c["name"]}</span>'
            f'{chevron}'
            f'{"</button>" if detail else "</div>"}'
            f'{detail_html}'
            f'</div>'
        )

    if not checks_html:
        checks_html = '<p class="text-sm text-gray-400 py-4 px-4">No checks recorded.</p>'

    return (
        f'<div class="bg-white dark:bg-gray-800 rounded-2xl shadow-sm overflow-hidden" id="pillar-{p["num"]}">'
        f'<div class="flex items-center justify-between px-6 py-4 border-b border-gray-100 dark:border-gray-700" style="border-left:4px solid {meta["color"]}">'
        f'<div class="flex items-center gap-3">'
        f'<div class="w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0" style="background:{meta["color"]}">'
        f'<i class="fas {meta["icon"]} text-sm text-white"></i></div>'
        f'<div><div class="font-bold text-gray-900 dark:text-white">Pillar {p["num"]} — {p["name"]}</div>'
        f'<div class="text-xs text-gray-400">{p["pass"]}/{p["total"]} checks passing</div></div></div>'
        f'<span class="text-xs font-bold px-3 py-1 rounded-full {badge_cls}">{level} · {pct}%</span>'
        f'</div>'
        f'<div>{checks_html}</div>'
        f'</div>'
    )


def generate_html(report_text: str, target_path: str) -> str:
    data = parse_report(report_text)
    timestamp   = datetime.now().strftime("%B %d, %Y · %H:%M")
    target_name = os.path.basename(os.path.abspath(target_path))

    score    = data["overall_score"]
    score_pct = int(score[0] / score[1] * 100) if score[1] else 0
    grade, score_color, grade_cls = _dora_level(score_pct)

    # DORA radar cards
    radar_cards = ""
    for p in data["pillars"]:
        meta  = PILLAR_META[p["num"]]
        pct   = int(p["pass"] / p["total"] * 100) if p["total"] else 0
        lv, lc, lbadge = _dora_level(pct)
        r, circ = 28, 175.9
        offset = circ - (pct / 100) * circ
        radar_cards += (
            f'<div class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm flex items-center gap-4">'
            f'<div class="w-16 h-16 relative flex-shrink-0">'
            f'<svg class="-rotate-90" viewBox="0 0 70 70">'
            f'<circle cx="35" cy="35" r="{r}" stroke="#e5e7eb" stroke-width="8" fill="none"/>'
            f'<circle cx="35" cy="35" r="{r}" stroke="{meta["color"]}" stroke-width="8" '
            f'stroke-dasharray="{circ}" stroke-dashoffset="{offset:.1f}" stroke-linecap="round" fill="none"/>'
            f'</svg>'
            f'<div class="absolute inset-0 flex items-center justify-center text-sm font-bold text-gray-900 dark:text-white">{pct}%</div>'
            f'</div>'
            f'<div><div class="text-xs font-bold text-gray-500 uppercase tracking-wider">{meta["name"]}</div>'
            f'<span class="text-xs font-semibold px-2 py-0.5 rounded-full mt-1 inline-block {lbadge}">{lv}</span></div>'
            f'</div>'
        )

    pillar_sections = "\n".join(_pillar_card(p) for p in data["pillars"])

    nav_items = ""
    for p in data["pillars"]:
        meta = PILLAR_META[p["num"]]
        pct  = int(p["pass"] / p["total"] * 100) if p["total"] else 0
        lv, _, _ = _dora_level(pct)
        dot  = "text-emerald-500" if pct >= 80 else ("text-amber-400" if pct >= 40 else "text-red-500")
        nav_items += (
            f'<a href="#pillar-{p["num"]}" class="flex items-center gap-2 px-3 py-2 rounded-lg text-gray-400 hover:bg-gray-800 hover:text-white transition text-sm">'
            f'<i class="fas {meta["icon"]} text-xs {dot} w-4 flex-shrink-0"></i>'
            f'<span class="truncate">P{p["num"]} — {p["name"]}</span></a>'
        )

    actions_html = ""
    if data["action_items"]:
        rows = ""
        urgencies = [
            ("High",   "bg-red-100 text-red-700",        "fa-circle-exclamation text-red-500"),
            ("Medium", "bg-yellow-100 text-yellow-700",   "fa-triangle-exclamation text-yellow-500"),
            ("Low",    "bg-emerald-100 text-emerald-700", "fa-circle-check text-emerald-500"),
        ]
        for i, item in enumerate(data["action_items"]):
            label, bc, ic = urgencies[min(i, 2)]
            clean = re.sub(r"\*\*(.+?)\*\*", r"\1", item)
            rows += (
                f'<div class="flex items-start gap-4 p-4 border-b border-gray-100 dark:border-gray-700 last:border-0">'
                f'<div class="w-8 h-8 rounded-full bg-gray-900 flex items-center justify-center text-white text-sm font-bold flex-shrink-0">{i+1}</div>'
                f'<div class="flex-1"><div class="text-sm text-gray-800 dark:text-gray-200 mb-1">{clean}</div>'
                f'<span class="inline-flex items-center gap-1 text-xs font-semibold px-2 py-0.5 rounded-full {bc}"><i class="fas {ic} text-xs"></i>{label} priority</span>'
                f'</div></div>'
            )
        actions_html = (
            f'<div class="bg-white dark:bg-gray-800 rounded-2xl shadow-sm overflow-hidden" id="actions">'
            f'<div class="flex items-center gap-3 px-6 py-4 border-b border-gray-100 dark:border-gray-700 bg-gray-900">'
            f'<i class="fas fa-bullseye text-white"></i><h3 class="text-white font-semibold">Priority Actions</h3></div>'
            f'{rows}</div>'
        )

    full_report_html = md_to_html(report_text)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Pipeline Review — {target_name}</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.7.2/css/all.min.css"/>
</head>
<body class="bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-white">
<div class="flex min-h-screen">

  <!-- SIDEBAR -->
  <aside class="w-72 bg-gray-950 flex flex-col border-r border-gray-800 fixed top-0 left-0 h-screen overflow-y-auto z-10">
    <div class="p-5 border-b border-gray-800">
      <div class="flex items-center gap-3">
        <div class="w-10 h-10 rounded-full bg-indigo-600 flex items-center justify-center shadow flex-shrink-0">
          <i class="fas fa-rocket text-white"></i>
        </div>
        <div>
          <div class="text-sm font-bold text-white">Pipeline Reviewer</div>
          <div class="text-xs text-gray-500">DORA Metrics · GitLab CI</div>
        </div>
      </div>
    </div>
    <nav class="flex-1 p-4 space-y-0.5">
      <div class="text-xs font-bold uppercase tracking-widest text-gray-600 px-3 pt-1 pb-2">Overview</div>
      <a href="#summary" class="flex items-center gap-2 px-3 py-2 rounded-lg text-gray-400 hover:bg-gray-800 hover:text-white transition text-sm">
        <i class="fas fa-chart-pie text-xs w-4 text-gray-500"></i><span>Executive Summary</span>
      </a>
      <a href="#actions" class="flex items-center gap-2 px-3 py-2 rounded-lg text-gray-400 hover:bg-gray-800 hover:text-white transition text-sm">
        <i class="fas fa-bullseye text-xs w-4 text-gray-500"></i><span>Priority Actions</span>
      </a>
      <div class="text-xs font-bold uppercase tracking-widest text-gray-600 px-3 pt-3 pb-2">DORA Pillars</div>
      {nav_items}
      <div class="text-xs font-bold uppercase tracking-widest text-gray-600 px-3 pt-3 pb-2">Details</div>
      <a href="#raw" class="flex items-center gap-2 px-3 py-2 rounded-lg text-gray-400 hover:bg-gray-800 hover:text-white transition text-sm">
        <i class="fas fa-file-lines text-xs w-4 text-gray-500"></i><span>Full Analysis</span>
      </a>
    </nav>
    <div class="p-4 border-t border-gray-800 text-xs text-gray-600">
      <a href="https://github.com/wb-platform-engineering-lab/agent-pipeline-reviewer" class="hover:text-gray-400 transition">
        <i class="fab fa-github mr-1"></i>agent-pipeline-reviewer
      </a>
    </div>
  </aside>

  <!-- MAIN -->
  <main class="flex-1 ml-72 p-6 lg:p-10 space-y-8">

    <!-- HERO -->
    <div class="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-2xl p-8 shadow-sm" id="summary">
      <div class="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-6">
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2 mb-2">
            <i class="fas fa-rocket text-indigo-500"></i>
            <span class="text-xs font-bold text-indigo-500 uppercase tracking-wider">GitLab CI · DORA Metrics Review</span>
          </div>
          <h1 class="text-2xl font-black mb-3 text-gray-900 dark:text-white">Pipeline Review Report</h1>
          <div class="flex items-center gap-2 bg-gray-100 dark:bg-gray-700 rounded-lg px-3 py-1.5 w-fit mb-3">
            <i class="fas fa-folder-open text-gray-400 text-xs"></i>
            <code class="text-gray-600 dark:text-gray-300 text-xs">{os.path.abspath(target_path)}</code>
          </div>
          <div class="text-gray-400 text-sm">
            <i class="fas fa-clock mr-1"></i>{timestamp}
            &nbsp;·&nbsp;<i class="fas fa-robot mr-1"></i>claude-haiku-4-5
          </div>
        </div>
        <div class="flex-shrink-0 bg-gray-50 dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded-2xl p-6 text-center min-w-[160px]">
          <div class="text-xs text-gray-400 uppercase tracking-wider font-semibold mb-1">DORA Score</div>
          <div class="text-5xl font-black" style="color:{score_color}">{score_pct}%</div>
          <div class="text-gray-400 text-xs mt-1">{score[0]}/{score[1]} checks passing</div>
          <span class="mt-2 inline-block px-4 py-1 rounded-full text-sm font-bold {grade_cls}">{grade}</span>
        </div>
      </div>
    </div>

    <!-- DORA PILLAR SCORES -->
    <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
      {radar_cards}
    </div>

    <!-- PRIORITY ACTIONS -->
    {actions_html}

    <!-- PILLAR DETAILS -->
    <div>
      <h2 class="text-xs font-bold text-gray-500 dark:text-gray-400 mb-4 flex items-center gap-2 uppercase tracking-wider">
        <i class="fas fa-magnifying-glass"></i> Detailed Findings
      </h2>
      <div class="space-y-4">{pillar_sections}</div>
    </div>

    <!-- FULL ANALYSIS -->
    <div class="bg-white dark:bg-gray-800 rounded-2xl shadow-sm overflow-hidden" id="raw">
      <button type="button"
        class="w-full flex justify-between items-center px-6 py-4 text-left font-semibold text-gray-900 dark:text-white border-b border-gray-100 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700/50 transition"
        onclick="this.nextElementSibling.classList.toggle('hidden');this.querySelector('i.chevron').classList.toggle('rotate-180')">
        <span class="flex items-center gap-2 text-sm"><i class="fas fa-file-lines text-gray-400"></i>Claude's Full Analysis</span>
        <i class="fas fa-chevron-down text-gray-400 chevron transition-transform duration-300"></i>
      </button>
      <div class="hidden px-6 py-6">{full_report_html}</div>
    </div>

    <!-- FOOTER -->
    <div class="text-center text-xs text-gray-400 pt-4 pb-8 border-t border-gray-100 dark:border-gray-700">
      Generated by <a href="https://github.com/wb-platform-engineering-lab/agent-pipeline-reviewer" class="text-blue-500 hover:underline">agent-pipeline-reviewer</a>
      · claude-haiku-4-5 · {timestamp}
    </div>
  </main>
</div>

<script>
  function toggleCheck(btn) {{
    const detail = btn.nextElementSibling;
    const chevron = btn.querySelector('.check-chevron');
    if (!detail) return;
    const hidden = detail.style.display === 'none';
    detail.style.display = hidden ? 'block' : 'none';
    if (chevron) chevron.classList.toggle('-rotate-90', !hidden);
  }}
  function copyPre(btn) {{
    navigator.clipboard.writeText(btn.previousElementSibling.textContent).then(() => {{
      btn.innerHTML = '<i class="fas fa-check mr-1"></i>Copied';
      setTimeout(() => btn.innerHTML = '<i class="fas fa-copy mr-1"></i>Copy', 2000);
    }});
  }}
  const sections = document.querySelectorAll('[id^="pillar-"], #summary, #actions, #raw');
  const links = document.querySelectorAll('aside nav a');
  new IntersectionObserver(entries => {{
    entries.forEach(e => {{
      if (e.isIntersecting) {{
        links.forEach(l => l.classList.remove('bg-gray-800','text-white'));
        const a = document.querySelector(`aside nav a[href="#${{e.target.id}}"]`);
        if (a) a.classList.add('bg-gray-800','text-white');
      }}
    }});
  }}, {{rootMargin:'-20% 0px -70% 0px'}}).observe(...sections);
</script>
</body>
</html>"""


def save_report(report_text: str, target_path: str, output_dir: str = ".",
                base_name: str | None = None) -> str:
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = base_name or f"pipeline_review_{ts}"
    path = os.path.join(output_dir, f"{name}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(generate_html(report_text, target_path))
    return path
