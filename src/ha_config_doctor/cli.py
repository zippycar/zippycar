"""The commands you type: check, tidy and list-checks."""

from __future__ import annotations

import argparse
import os
import sys
import webbrowser
from pathlib import Path

from . import __version__
from .catalog import CHECKS, ERROR, SEVERITIES, TIDY, WARNING

EXIT_OK, EXIT_ERRORS_FOUND, EXIT_PROBLEM = 0, 1, 2
DEFAULT_REPORT_FOLDER = "ha-config-doctor-report"


def _clean_path(text: str) -> Path:
    """Forgive the usual copy-and-paste slips: stray quotes, spaces, a trailing backslash."""

    value = text.strip().strip('"').strip("'").strip()
    value = os.path.expandvars(os.path.expanduser(value))
    if len(value) > 3 and value.endswith(("\\", "/")):
        value = value.rstrip("\\/")
    return Path(value)


def _config_folder(text: str) -> Path | None:
    path = _clean_path(text)
    if path.is_file() and path.name.lower().endswith((".yaml", ".yml")):
        path = path.parent  # they pointed at configuration.yaml itself
    if not path.is_dir():
        print(f'I can\'t find a folder called "{path}".')
        print('Check the spelling, and put the whole folder path in "double quotes".')
        return None
    return path.resolve()


def _inside(child: Path, parent: Path) -> bool:
    child, parent = child.resolve(), parent.resolve()
    return child == parent or parent in child.parents


def _say_counts(findings) -> None:
    counts = {s: findings.count(s) for s in SEVERITIES}
    print(f"Result: {counts[ERROR]} Error(s), {counts[WARNING]} Warning(s), {counts[TIDY]} Tidy-up(s).")


def _examine(root: Path, args: argparse.Namespace):
    from .doctor import examine
    from .rules import RulesProblem

    rules_file = _clean_path(args.rules) if getattr(args, "rules", None) else None
    try:
        return examine(root, ha_version=getattr(args, "ha_version", None), rules_file=rules_file)
    except RulesProblem as err:
        print(str(err))
        return None


def _say_version(result) -> None:
    version = result.version
    if version.source == "assumed":
        print(f"No .HA_VERSION file was found, so Home Assistant {version.text} is assumed "
              "(add --ha-version 2026.10.4, for example, to say which version you have).")
    else:
        print(f"Checked against Home Assistant {version.text}.")
    if version.newer_than_rules:
        print("Your Home Assistant is newer than the doctor's rules, so very recent changes may be missing.")


def _prepare_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # never crash on an unusual character in a Windows console
        except (AttributeError, ValueError):
            pass


def cmd_check(args: argparse.Namespace) -> int:
    from .report import write_reports

    root = _config_folder(args.config_folder)
    if root is None:
        return EXIT_PROBLEM
    report_folder = _clean_path(args.report_folder) if args.report_folder else Path.cwd() / DEFAULT_REPORT_FOLDER
    if _inside(report_folder, root):
        print("The report can't be saved inside the configuration folder — the doctor never writes there.")
        print("Go to another folder first (for example type:  cd $HOME ) or use --report-folder to choose one.")
        return EXIT_PROBLEM
    print(f"ha-config-doctor {__version__}")
    print(f'Looking at "{root.name}" (read-only: nothing in that folder will be changed)...')
    result = _examine(root, args)
    if result is None:
        return EXIT_PROBLEM
    model = result.model
    print(f"Read {len(result.config.files)} file(s): {len(model.automations)} automation(s), "
          f"{len(model.scripts)} script(s), {len(model.helpers)} helper(s).")
    if result.registry.has_entities:
        print("Home Assistant's entity list (.storage) was found, so every entity name was cross-checked.")
    else:
        print("No .storage folder with an entity list was found, so entity names were only partly checked.")
    _say_version(result)
    _say_counts(result.findings)
    if result.unfinished:
        print("Note: some checks couldn't finish because of a problem in the doctor itself (not in your files). "
              "The report says which.")
    try:
        html_path, md_path = write_reports(result, report_folder)
    except OSError as err:
        print(f"Sorry, the report couldn't be saved in {report_folder}: {err.strerror or err}.")
        return EXIT_PROBLEM
    print("")
    print("Your report is ready:")
    print(f"  {html_path}")
    print(f"  {md_path}")
    if args.open:
        webbrowser.open(html_path.resolve().as_uri())
    else:
        print("(Add --open to the end of the command to open it straight away.)")
    return EXIT_ERRORS_FOUND if result.findings.count(ERROR) else EXIT_OK


def cmd_tidy(args: argparse.Namespace) -> int:
    from .report import write_change_log
    from .tidy import OutputFolderProblem, check_output_folder, tidy

    root = _config_folder(args.config_folder)
    if root is None:
        return EXIT_PROBLEM
    out = _clean_path(args.output_folder)
    try:
        check_output_folder(root, out)
    except OutputFolderProblem as err:
        print(str(err))
        return EXIT_PROBLEM
    print(f"ha-config-doctor {__version__}")
    print(f'Reading "{root.name}" (read-only: nothing in that folder will be changed)...')
    result = _examine(root, args)
    if result is None:
        return EXIT_PROBLEM
    try:
        report = tidy(result, out, keep_order=args.keep_order)
        html_path, md_path = write_change_log(report, result)
    except OutputFolderProblem as err:
        print(str(err))
        return EXIT_PROBLEM
    except OSError as err:
        print(f"Sorry, the tidied copy couldn't be written: {err.strerror or err}.")
        return EXIT_PROBLEM
    print(f"Tidied copies of {len(report.changed)} file(s) were written to:")
    print(f"  {report.out_dir}")
    if report.skipped:
        print(f"{len(report.skipped)} file(s) were left alone to be safe (the change log says why).")
    print("What changed, and why:")
    print(f"  {html_path}")
    print(f"  {md_path}")
    print("Nothing in your original folder was changed. Read the change log before copying anything back.")
    if args.open:
        webbrowser.open(html_path.resolve().as_uri())
    return EXIT_OK


def cmd_list_rules(args: argparse.Namespace) -> int:
    from .rules import RulesProblem, judge, load_rules, parse_version

    try:
        book = load_rules(_clean_path(args.rules) if args.rules else None)
    except RulesProblem as err:
        print(str(err))
        return EXIT_PROBLEM
    version = parse_version(args.ha_version) if args.ha_version else book.newest_release_known
    if version is None:
        print(f'"{args.ha_version}" isn\'t a Home Assistant version. Write it like 2026.10.4.')
        return EXIT_PROBLEM
    print(f"Rules file: {book.path}")
    print(f"Last reviewed {book.as_of}; {len(book.unverified)} of {len(book.rules)} rules not yet checked against the official release notes.")
    for rule in book.rules:
        verdict = judge(rule, version)
        print(f"\n[{verdict.severity}] {rule.id} ({rule.verification}, from {rule.basis})")
        print(f"    {verdict.when}")
        print(f"    {rule.explanation}")
        print(f"    Source: {rule.source}")
    return EXIT_OK


def cmd_list_checks(args: argparse.Namespace) -> int:
    from .report import checks_markdown

    if args.markdown:
        print(checks_markdown())
        return EXIT_OK
    for check in CHECKS.values():
        tidy = "  (tidy mode fixes this)" if check.tidy_fixes else ""
        print(f"[{check.severity}] {check.title}{tidy}")
        print(f"    code: {check.code}")
    print(f"\n{len(CHECKS)} checks in total.")
    return EXIT_OK


def _version_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--ha-version", metavar="VERSION",
                        help="the Home Assistant version to check against, such as 2026.10.4 (default: read from the folder's .HA_VERSION file)")
    parser.add_argument("--rules", metavar="FILE", help="use a different rules file instead of the built-in data/ha_rules.yaml")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ha-config-doctor",
        description="A careful, read-only health check for a copy of your Home Assistant configuration folder.",
    )
    parser.add_argument("--version", action="version", version=f"ha-config-doctor {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="command")

    check = sub.add_parser("check", help="check a configuration folder and write a report")
    check.add_argument("config_folder", help='the folder that holds configuration.yaml, in "double quotes"')
    check.add_argument("--report-folder", help=f'where to save the report (default: a folder called "{DEFAULT_REPORT_FOLDER}" here)')
    check.add_argument("--open", action="store_true", help="open the report in your web browser when it's ready")
    _version_options(check)
    check.set_defaults(func=cmd_check)

    tidy = sub.add_parser("tidy", help="write a tidied COPY of the files into a new folder")
    tidy.add_argument("config_folder", help='the folder that holds configuration.yaml, in "double quotes"')
    tidy.add_argument("output_folder", help="a NEW (or empty) folder for the tidied copies")
    tidy.add_argument("--keep-order", action="store_true", help="don't change the order of anything")
    tidy.add_argument("--open", action="store_true", help="open the change log in your web browser")
    _version_options(tidy)
    tidy.set_defaults(func=cmd_tidy)

    rules = sub.add_parser("list-rules", help="list the rules about removed and retired features, and what they mean for a version")
    _version_options(rules)
    rules.set_defaults(func=cmd_list_rules)

    listing = sub.add_parser("list-checks", help="list every check the doctor makes")
    listing.add_argument("--markdown", action="store_true", help="print the full descriptions as Markdown")
    listing.set_defaults(func=cmd_list_checks)
    return parser


def main(argv: list[str] | None = None) -> int:
    _prepare_output()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return EXIT_PROBLEM
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
