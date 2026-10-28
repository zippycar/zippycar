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


@dataclass
class Result:
    root: Path
    config: ConfigSet
    registry: Registry
    model: Model
    findings: Findings
    when: datetime
    unfinished: list[str]


def examine(root: Path) -> Result:
    """Read the folder (never changing anything) and run all the checks."""

    findings = Findings()
    config = ConfigSet(Path(root), findings).load()
    registry = Registry(config.root)
    model = Model(config, registry, findings).build()
    unfinished = run_all(Ctx(config, model, registry, findings))
    return Result(config.root, config, registry, model, findings, datetime.now(), unfinished)
