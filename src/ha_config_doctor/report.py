"""Write the findings as one readable HTML page and a Markdown file.

Both start with a one-page summary, then list everything grouped by
severity (Errors, then Warnings, then Tidy-ups). Every piece of text from the
configuration is escaped and passed through the redaction filter again.
"""

from __future__ import annotations

import html
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING

from . import __version__
from .catalog import CHECKS, ERROR, SEVERITIES, SEVERITY_MEANING, TIDY, WARNING, Finding
from .redact import redact_text

if TYPE_CHECKING:  # pragma: no cover
    from .doctor import Result
    from .tidy import TidyReport

HEADINGS = {ERROR: "Errors — fix these first", WARNING: "Warnings — worth a look", TIDY: "Tidy-ups — when you have time"}
COLOURS = {ERROR: "#b3261e", WARNING: "#8a5300", TIDY: "#1d5aa6"}
PRIVACY_NOTE = ("The doctor only reads your files; it never changes them. It never reads the values in secrets.yaml "
                "(only the names), never opens Home Assistant's login or password files, and hides anything that looks like "
                "a password, token, e-mail address or network address in this report.")


def _place(finding: Finding) -> str:
    if not finding.file:
        return "Made in the Home Assistant screens" if "screens" in finding.detail else "Whole configuration"
    if finding.line <= 0:
        return f"{finding.file} (whole file)"
    return f"{finding.file}, line {finding.line}"


def _grouped(findings: list[Finding]) -> "OrderedDict[str, OrderedDict[str, list[Finding]]]":
    out: OrderedDict[str, OrderedDict[str, list[Finding]]] = OrderedDict((s, OrderedDict()) for s in SEVERITIES)
    for finding in sorted(findings, key=Finding.sort_key):
        out[finding.severity].setdefault(finding.code, []).append(finding)
    return out


def _start_here(findings: list[Finding], limit: int = 5) -> list[Finding]:
    picked: list[Finding] = []
    used: set[str] = set()
    for finding in sorted(findings, key=Finding.sort_key):
        if finding.severity == TIDY or finding.code in used:
            continue
        picked.append(finding)
        used.add(finding.code)
        if len(picked) == limit:
            break
    return picked


def summary_facts(result: "Result") -> dict:
    findings = result.findings.items
    counts = {s: sum(1 for f in findings if f.severity == s) for s in SEVERITIES}
    if counts[ERROR]:
        verdict = (f"{counts[ERROR]} thing{'s' if counts[ERROR] != 1 else ''} need{'' if counts[ERROR] != 1 else 's'} fixing. "
                   "Start with the list below.")
    elif counts[WARNING]:
        verdict = "Nothing is broken, but there are some things worth a look."
    elif counts[TIDY]:
        verdict = "Good news: nothing is broken. There are only tidy-ups."
    else:
        verdict = "Good news: the doctor found nothing to fix."
    reg = result.registry
    if reg.has_entities:
        registry = (f"Found — every entity name was cross-checked against Home Assistant's list of "
                    f"{len(reg.entities)} entities" + (" and its saved states." if reg.restore is not None else "."))
    elif reg.has_storage:
        registry = "The .storage folder is there, but it has no entity list, so entity names could only be partly checked."
    else:
        registry = ("Not found — entity names could only be partly checked. Copy the hidden-looking .storage folder "
                    "along with the rest of your configuration to have every entity name checked.")
    model = result.model
    return {
        "counts": counts,
        "verdict": verdict,
        "folder": result.root.name,
        "when": result.when.strftime("%d %B %Y at %H:%M"),
        "version": result.config.ha_version,
        "files": len([f for f in result.config.files.values() if f.role == "config"]),
        "automations": len(model.automations),
        "scripts": len(model.scripts),
        "helpers": len(model.helpers),
        "mentions": len({r.entity_id for r in model.refs}),
        "registry": registry,
        "start_here": _start_here(findings),
        "unfinished": (
            "Some checks couldn't finish because of a problem in the doctor itself (not in your files): "
            + ", ".join(result.unfinished) + ". Everything else was checked."
        ) if result.unfinished else "",
    }


# ------------------------------------------------------------------ Markdown

def _md(text: object) -> str:
    value = redact_text(text)
    return value.replace("\\", "\\\\").replace("*", "\\*").replace("`", "\\`").replace("<", "&lt;").replace("|", "\\|")


def render_markdown(result: "Result") -> str:
    facts = summary_facts(result)
    counts = facts["counts"]
    out: list[str] = []
    out.append("# Home Assistant check-up")
    out.append("")
    out.append(f"Folder checked: **{_md(facts['folder'])}** · {facts['when']}"
               + (f" · Home Assistant {_md(facts['version'])}" if facts["version"] else "")
               + f" · ha-config-doctor {__version__}")
    out.append("")
    out.append("## Summary")
    out.append("")
    out.append(f"**{facts['verdict']}**")
    out.append("")
    out.append("| What | How many | What it means |")
    out.append("|---|---|---|")
    for severity in SEVERITIES:
        out.append(f"| {severity}s | {counts[severity]} | {SEVERITY_MEANING[severity]} |")
    out.append("")
    if facts["start_here"]:
        out.append("### Start here")
        out.append("")
        for index, finding in enumerate(facts["start_here"], start=1):
            out.append(f"{index}. **{_md(finding.title)}** — {_md(_place(finding))}"
                       + (f" — {_md(finding.where)}" if finding.where else ""))
        out.append("")
    out.append("### What was checked")
    out.append("")
    out.append(f"- {facts['files']} configuration file(s), {facts['automations']} automation(s), "
               f"{facts['scripts']} script(s), {facts['helpers']} helper(s), {facts['mentions']} different entity name(s).")
    out.append(f"- Home Assistant's own entity list: {facts['registry']}")
    out.append(f"- {PRIVACY_NOTE}")
    if facts["unfinished"]:
        out.append(f"- **{_md(facts['unfinished'])}**")
    out.append("")
    grouped = _grouped(result.findings.items)
    for severity in SEVERITIES:
        checks = grouped[severity]
        total = sum(len(v) for v in checks.values())
        out.append(f"## {HEADINGS[severity]} ({total})")
        out.append("")
        if not checks:
            out.append("None.")
            out.append("")
            continue
        out.append(f"_{SEVERITY_MEANING[severity]}_")
        out.append("")
        for code, items in checks.items():
            meta = CHECKS[code]
            out.append(f"### {_md(meta.title)} ({len(items)})")
            out.append("")
            out.append(f"**Why this matters:** {_md(meta.why)}")
            out.append("")
            out.append(f"**How to fix it:** {_md(meta.fix)}")
            if meta.tidy_fixes:
                out.append("")
                out.append("**Tidy mode can make this change for you** (in a copy of your files).")
            out.append("")
            for finding in items:
                line = f"- **{_md(_place(finding))}**"
                if finding.where:
                    line += f" — {_md(finding.where)}"
                line += f": {_md(finding.detail)}"
                if finding.fix and finding.fix != meta.fix:
                    line += f" *Suggested fix:* {_md(finding.fix)}"
                out.append(line)
            out.append("")
    out.append("---")
    out.append("")
    out.append("Made by ha-config-doctor, which only reads your files. Line numbers count from 1 at the top of each file.")
    out.append("")
    return "\n".join(out)


# ------------------------------------------------------------------ HTML

_CSS = """
:root { --bg:#ffffff; --fg:#1b1b1b; --muted:#555; --card:#f6f7f9; --line:#d9dce1; --err:#b3261e; --warn:#8a5300; --tidy:#1d5aa6; }
@media (prefers-color-scheme: dark) { :root { --bg:#16181c; --fg:#eceff3; --muted:#b5bac2; --card:#20242a; --line:#3a3f47; --err:#ff8a80; --warn:#ffc266; --tidy:#8ab4ff; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font: 18px/1.55 "Segoe UI", system-ui, -apple-system, Arial, sans-serif; overflow-wrap: anywhere; }
main { max-width: 980px; margin: 0 auto; padding: 24px 16px 64px; }
h1 { font-size: 2rem; margin: 0 0 4px; } h2 { font-size: 1.5rem; margin: 40px 0 8px; border-bottom: 2px solid var(--line); padding-bottom: 6px; }
h3 { font-size: 1.2rem; margin: 28px 0 6px; }
.meta { color: var(--muted); margin: 0 0 18px; }
.verdict { font-size: 1.35rem; font-weight: 600; margin: 8px 0 18px; }
.counts { display:flex; gap:12px; flex-wrap:wrap; margin: 0 0 18px; }
.count { flex: 1 1 200px; border:1px solid var(--line); border-radius:10px; padding:12px 14px; background:var(--card); }
.count b { display:block; font-size: 2rem; line-height:1.1; }
.count.e b { color: var(--err); } .count.w b { color: var(--warn); } .count.t b { color: var(--tidy); }
.count span { color: var(--muted); font-size: .95rem; }
.badge { display:inline-block; font-size:.8rem; font-weight:700; padding:2px 8px; border-radius:999px; color:#fff; vertical-align: middle; }
.badge.e { background:#b3261e; } .badge.w { background:#8a5300; } .badge.t { background:#1d5aa6; }
.check { border:1px solid var(--line); border-radius:10px; padding: 4px 16px 12px; margin: 16px 0; background: var(--card); }
.check p { margin: 6px 0; }
.places { list-style: none; padding: 0; margin: 8px 0 0; }
.places li { border-top: 1px solid var(--line); padding: 8px 0; }
.place { font-weight: 600; font-family: Consolas, "Cascadia Mono", monospace; font-size: .95rem; }
.where { color: var(--muted); }
.fix { margin-top: 4px; }
.code { color: var(--muted); font-size: .8rem; }
.tidyfix { color: var(--tidy); font-weight: 600; }
ol.start li { margin: 6px 0; }
.summary { page-break-after: always; break-after: page; }
.note { color: var(--muted); font-size: .95rem; }
code { font-family: Consolas, "Cascadia Mono", monospace; }
@media print { body { font-size: 12pt; } .check { break-inside: avoid; } }
"""

_SEV_CLASS = {ERROR: "e", WARNING: "w", TIDY: "t"}


def _h(text: object) -> str:
    return html.escape(redact_text(text), quote=True)


def _page(title: str, body: str) -> str:
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{html.escape(title)}</title>\n<style>{_CSS}</style>\n</head>\n<body>\n<main>\n{body}\n</main>\n</body>\n</html>\n"
    )


def render_html(result: "Result") -> str:
    facts = summary_facts(result)
    counts = facts["counts"]
    parts: list[str] = ['<section class="summary">', "<h1>Home Assistant check-up</h1>"]
    meta = f"Folder checked: <b>{_h(facts['folder'])}</b> · {_h(facts['when'])}"
    if facts["version"]:
        meta += f" · Home Assistant {_h(facts['version'])}"
    parts.append(f'<p class="meta">{meta} · ha-config-doctor {__version__}</p>')
    parts.append(f'<p class="verdict">{_h(facts["verdict"])}</p>')
    parts.append('<div class="counts">')
    for severity in SEVERITIES:
        cls = _SEV_CLASS[severity]
        parts.append(f'<div class="count {cls}"><b>{counts[severity]}</b>{_h(severity)}s<br><span>{_h(SEVERITY_MEANING[severity])}</span></div>')
    parts.append("</div>")
    if facts["start_here"]:
        parts.append("<h3>Start here</h3><ol class=\"start\">")
        for finding in facts["start_here"]:
            anchor = f"check-{finding.code}"
            parts.append(f'<li><span class="badge {_SEV_CLASS[finding.severity]}">{_h(finding.severity)}</span> '
                         f'<a href="#{anchor}">{_h(finding.title)}</a> — {_h(_place(finding))}'
                         + (f' — <span class="where">{_h(finding.where)}</span>' if finding.where else "") + "</li>")
        parts.append("</ol>")
    parts.append("<h3>What was checked</h3><ul>")
    parts.append(f"<li>{facts['files']} configuration file(s), {facts['automations']} automation(s), {facts['scripts']} script(s), "
                 f"{facts['helpers']} helper(s), {facts['mentions']} different entity name(s).</li>")
    parts.append(f"<li>Home Assistant's own entity list: {_h(facts['registry'])}</li>")
    parts.append(f"<li>{_h(PRIVACY_NOTE)}</li>")
    if facts["unfinished"]:
        parts.append(f"<li><b>{_h(facts['unfinished'])}</b></li>")
    parts.append("</ul>")
    parts.append('<p class="note">Line numbers count from 1 at the top of each file. In Notepad, press Ctrl+G to jump to a line '
                 "(if that's greyed out, turn off Format &gt; Word Wrap first).</p>")
    parts.append("</section>")

    grouped = _grouped(result.findings.items)
    for severity in SEVERITIES:
        checks = grouped[severity]
        total = sum(len(v) for v in checks.values())
        cls = _SEV_CLASS[severity]
        parts.append(f'<h2 id="{cls}"><span class="badge {cls}">{_h(severity)}</span> {_h(HEADINGS[severity])} ({total})</h2>')
        if not checks:
            parts.append("<p>None.</p>")
            continue
        parts.append(f'<p class="note">{_h(SEVERITY_MEANING[severity])}</p>')
        for code, items in checks.items():
            meta_check = CHECKS[code]
            parts.append(f'<div class="check" id="check-{code}">')
            parts.append(f"<h3>{_h(meta_check.title)} <span class=\"code\">({len(items)} · {code})</span></h3>")
            parts.append(f"<p><b>Why this matters:</b> {_h(meta_check.why)}</p>")
            parts.append(f"<p><b>How to fix it:</b> {_h(meta_check.fix)}</p>")
            if meta_check.tidy_fixes:
                parts.append('<p class="tidyfix">Tidy mode can make this change for you, in a copy of your files.</p>')
            parts.append('<ul class="places">')
            for finding in items:
                row = f'<li><span class="place">{_h(_place(finding))}</span>'
                if finding.where:
                    row += f' — <span class="where">{_h(finding.where)}</span>'
                row += f"<br>{_h(finding.detail)}"
                if finding.fix and finding.fix != meta_check.fix:
                    row += f'<div class="fix"><b>Suggested fix:</b> {_h(finding.fix)}</div>'
                parts.append(row + "</li>")
            parts.append("</ul></div>")
    parts.append('<p class="note">Made by ha-config-doctor, which only reads your files.</p>')
    return _page("Home Assistant check-up", "\n".join(parts))


def write_reports(result: "Result", folder: Path) -> tuple[Path, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    html_path = folder / "report.html"
    md_path = folder / "report.md"
    html_path.write_bytes(render_html(result).encode("utf-8"))
    md_path.write_bytes(render_markdown(result).encode("utf-8"))
    return html_path, md_path


# ------------------------------------------------------------------ tidy change log

BEFORE_YOU_COPY = [
    "Make a backup first: in Home Assistant go to Settings > System > Backups and choose Back up now.",
    "Copy only the files you want to use, into the same place in your configuration folder (replacing the old ones).",
    "In Home Assistant go to Developer tools > YAML and press Check configuration. If it shows a problem, put the backup back.",
    "If the check is fine, press Restart.",
]


def _unchanged_findings(result: "Result") -> list[Finding]:
    return [f for f in result.findings.sorted() if not f.check.tidy_fixes or (f.code == "old-platform-key" and "by hand" in f.fix)]


def render_changes_markdown(report: "TidyReport", result: "Result") -> str:
    out = ["# Tidied copy — what changed and why", ""]
    out.append(f"Your original folder (**{_md(result.root.name)}**) was not changed. This folder holds tidied copies of "
               f"{len(report.changed)} file(s). {len([f for f in report.files if f.status == 'unchanged'])} file(s) needed no changes "
               f"and {len(report.skipped)} were left alone to be safe.")
    out.append("")
    out.append("## Before you copy anything back")
    out.append("")
    for index, step in enumerate(BEFORE_YOU_COPY, start=1):
        out.append(f"{index}. {step}")
    out.append("")
    out.append("## What changed in each file")
    out.append("")
    if not report.changed:
        out.append("Nothing needed changing.")
        out.append("")
    for item in report.changed:
        out.append(f"### {_md(item.rel)}")
        out.append("")
        if item.note:
            out.append(f"_{_md(item.note)}_")
            out.append("")
        for change in item.changes:
            where = f"Line {change.line}: " if change.line else ""
            out.append(f"- {where}**{_md(change.what)}** {_md(change.why)}")
        out.append("")
    if report.skipped:
        out.append("## Files left exactly as they were")
        out.append("")
        for item in report.skipped:
            out.append(f"- **{_md(item.rel)}** — {_md(item.reason)}")
        out.append("")
    leftovers = _unchanged_findings(result)
    out.append("## Not changed — these need your decision")
    out.append("")
    out.append("Tidy mode only makes changes that are certain to mean the same thing. These were only reported "
               "(see report.html from the check command for the full explanation of each):")
    out.append("")
    for finding in leftovers:
        out.append(f"- {finding.severity}: **{_md(finding.title)}** — {_md(_place(finding))}" + (f" — {_md(finding.where)}" if finding.where else ""))
    out.append("")
    out.append("Line numbers above are for your original files.")
    out.append("")
    return "\n".join(out)


def render_changes_html(report: "TidyReport", result: "Result") -> str:
    parts = ["<h1>Tidied copy — what changed and why</h1>"]
    parts.append(f"<p class=\"verdict\">Your original folder (<b>{_h(result.root.name)}</b>) was not changed.</p>")
    parts.append(f"<p>This folder holds tidied copies of {len(report.changed)} file(s). "
                 f"{len([f for f in report.files if f.status == 'unchanged'])} file(s) needed no changes and "
                 f"{len(report.skipped)} were left alone to be safe.</p>")
    parts.append("<h2>Before you copy anything back</h2><ol class=\"start\">")
    parts.extend(f"<li>{_h(step)}</li>" for step in BEFORE_YOU_COPY)
    parts.append("</ol><h2>What changed in each file</h2>")
    if not report.changed:
        parts.append("<p>Nothing needed changing.</p>")
    for item in report.changed:
        parts.append(f'<div class="check"><h3><code>{_h(item.rel)}</code></h3>')
        if item.note:
            parts.append(f'<p class="note">{_h(item.note)}</p>')
        parts.append('<ul class="places">')
        for change in item.changes:
            where = f'<span class="place">Line {change.line}</span> — ' if change.line else ""
            parts.append(f"<li>{where}<b>{_h(change.what)}</b><br>{_h(change.why)}</li>")
        parts.append("</ul></div>")
    if report.skipped:
        parts.append("<h2>Files left exactly as they were</h2><ul>")
        parts.extend(f"<li><code>{_h(item.rel)}</code> — {_h(item.reason)}</li>" for item in report.skipped)
        parts.append("</ul>")
    parts.append("<h2>Not changed — these need your decision</h2>")
    parts.append("<p>Tidy mode only makes changes that are certain to mean the same thing. These were only reported "
                 "(run the check command and open report.html for the full explanation of each):</p><ul class=\"places\">")
    for finding in _unchanged_findings(result):
        parts.append(f'<li><span class="badge {_SEV_CLASS[finding.severity]}">{_h(finding.severity)}</span> '
                     f'<b>{_h(finding.title)}</b> — <span class="place">{_h(_place(finding))}</span>'
                     + (f' — <span class="where">{_h(finding.where)}</span>' if finding.where else "") + "</li>")
    parts.append("</ul><p class=\"note\">Line numbers are for your original files.</p>")
    return _page("Tidied copy — changes", "\n".join(parts))


def write_change_log(report: "TidyReport", result: "Result") -> tuple[Path, Path]:
    html_path = report.out_dir / "CHANGES.html"
    md_path = report.out_dir / "CHANGES.md"
    html_path.write_bytes(render_changes_html(report, result).encode("utf-8"))
    md_path.write_bytes(render_changes_markdown(report, result).encode("utf-8"))
    return html_path, md_path


def checks_markdown() -> str:
    """The full list of checks, for docs/CHECKS.md."""

    out = ["# Every check ha-config-doctor makes", "",
           "This file is produced from the program itself (`py -m ha_config_doctor list-checks --markdown`).", ""]
    groups: OrderedDict[str, list] = OrderedDict()
    for check in CHECKS.values():
        groups.setdefault(check.group, []).append(check)
    for group, checks in groups.items():
        out.append(f"## {group}")
        out.append("")
        for check in checks:
            out.append(f"### {check.title}")
            out.append("")
            out.append(f"- **Usual severity:** {check.severity}" + ("  ·  **Tidy mode fixes this**" if check.tidy_fixes else ""))
            out.append(f"- **Code:** `{check.code}`")
            out.append(f"- **Why it matters:** {check.why}")
            out.append(f"- **How to fix it:** {check.fix}")
            out.append("")
    return "\n".join(out)
