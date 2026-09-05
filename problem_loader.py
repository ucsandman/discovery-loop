"""Import discovery-loop problem plugins without sharing bare helper modules."""

import importlib
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PROBLEMS = ROOT / "problems"
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]*\Z")


def load_problem(name):
    """Return ``problems.<name>.problem`` using normal package import semantics.

    Loading helpers through their qualified package names prevents one plugin's
    ``records`` or ``verify`` module from being reused by another plugin in the
    same interpreter.
    """
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ValueError(f"invalid problem name: {name!r}")
    plugin = PROBLEMS / name
    if not plugin.is_dir() or not (plugin / "problem.py").is_file():
        raise ModuleNotFoundError(f"unknown problem plugin: {name}")
    return importlib.import_module(f"problems.{name}.problem")
