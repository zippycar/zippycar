"""Run every check on a configuration folder and return the results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .catalog import Findings
from .checks import run_all
from .checks.common import Ctx
from .configtree import ConfigSet
from .model import Model
from .registry import Registry
from .rules import HAVersion, RuleBook, ha_version_for, load_rules


@dataclass
class Result:
    root: Path
    config: ConfigSet
    registry: Registry
    model: Model
    findings: Findings
    when: datetime
    unfinished: list[str]
    rules: RuleBook
    version: HAVersion


def examine(root: Path, ha_version: str | None = None, rules_file: Path | None = None) -> Result:
    """Read the folder (never changing anything) and run all the checks.

    ha_version overrides the version in the folder's .HA_VERSION file; rules_file replaces
    the built-in data/ha_rules.yaml. Raises RulesProblem if either is unusable.
    """

    rules = load_rules(rules_file)
    version = ha_version_for(Path(root), ha_version, rules)
    findings = Findings()
    config = ConfigSet(Path(root), findings).load()
    registry = Registry(config.root)
    model = Model(config, registry, findings, rules, version.parts).build()
    unfinished = run_all(Ctx(config, model, registry, findings, rules, version))
    return Result(config.root, config, registry, model, findings, datetime.now(), unfinished, rules, version)
