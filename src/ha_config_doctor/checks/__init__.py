"""All the checks, run in a sensible order."""

from __future__ import annotations

from . import automations, files_and_old, interactions, references, templates_check
from .common import Ctx

MODULES = (files_and_old, automations, interactions, templates_check, references)


def run_all(ctx: Ctx) -> list[str]:
    """Run every group of checks. A bug in one group never stops the others; it is reported instead."""

    unfinished: list[str] = []
    for module in MODULES:
        try:
            module.run(ctx)
        except Exception as err:  # pragma: no cover - only reached if the doctor itself has a bug
            unfinished.append(f"{module.__name__.rsplit('.', 1)[-1]} ({type(err).__name__})")
    return unfinished
