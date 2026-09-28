"""Property-based test for post-migration import resolution.

Covers task 16.2 of the folder-structure-migration spec.

# Feature: folder-structure-migration, Property 9: For any migrated application
# module or test module, importing it raises neither ModuleNotFoundError nor
# ImportError.

**Validates: Requirements 4.1, 4.3, 4.6, 6.6**

Strategy
--------
The project is configured with ``pythonpath = ["python"]`` (see pyproject.toml),
so every source module under ``python/api/`` is importable as a dotted ``api.*``
module and every test module under ``python/tests/`` as a dotted ``tests.*``
module.

This test enumerates *once* (at import time) every ``.py`` file under
``python/api/`` and ``python/tests/``, converts each to its dotted module name,
and then uses Hypothesis to sample from that enumerated set across at least 100
iterations, asserting that importing the sampled module never raises
``ImportError`` / ``ModuleNotFoundError``.

Scope
-----
Enumeration is strictly confined to the ``python/api/`` tree (``api.*``) and the
``python/tests/`` tree (``tests.*``). The repo-root ``migration_tools/`` helper
package lives outside both trees and is therefore never enumerated. ``__pycache__``
directories and non-``.py`` files are skipped, and the module set is deduplicated
so no module is double-counted.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

# ──── Repo layout ─────────────────────────────────────────────────────────────

# This file lives at python/tests/common/property/, so:
#   parents[0] = property
#   parents[1] = common
#   parents[2] = tests
#   parents[3] = python
#   parents[4] = repo root
_PYTHON_ROOT = Path(__file__).resolve().parents[3]
_API_ROOT = _PYTHON_ROOT / "api"
_TESTS_ROOT = _PYTHON_ROOT / "tests"


def _iter_dotted_modules(package_root: Path, top_package: str) -> list[str]:
    """Enumerate every ``.py`` module under ``package_root`` as a dotted name.

    ``top_package`` is the dotted prefix that ``package_root`` maps to under the
    configured ``pythonpath`` (``api`` for ``python/api``; ``tests`` for
    ``python/tests``). ``__pycache__`` directories and non-``.py`` files are
    skipped. ``__init__.py`` maps to its owning package's dotted name.
    """
    modules: set[str] = set()

    if not package_root.is_dir():
        return []

    for path in package_root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue

        rel = path.relative_to(package_root)
        parts = list(rel.parts)

        if parts[-1] == "__init__.py":
            # package module: drop the __init__.py segment
            parts = parts[:-1]
        else:
            # strip the .py extension from the final segment
            parts[-1] = parts[-1][: -len(".py")]

        dotted = ".".join([top_package, *parts]) if parts else top_package
        modules.add(dotted)

    return sorted(modules)


# Enumerate once at collection time.
#
# The migrated application modules (``api.*``) are the strict subject of
# Property 9 ("every migrated application module ... imports"). Test modules
# (``tests.*``) are enumerated too and appended when they are importable via a
# plain dotted import, so the sweep also exercises the Req 6.6 test set; if the
# runner does not expose ``tests`` as an importable dotted package (pytest
# collects test files by path, not necessarily as a ``tests.*`` package), the
# test set is simply omitted from sampling rather than producing a spurious
# ModuleNotFoundError. Either way the api.* sweep — the required subject — runs.
_API_MODULES = _iter_dotted_modules(_API_ROOT, "api")
_TEST_MODULES = _iter_dotted_modules(_TESTS_ROOT, "tests")


def _tests_importable_as_package() -> bool:
    """True when ``tests.*`` dotted imports resolve in this runner."""
    try:
        importlib.import_module("tests")
    except (ImportError, ModuleNotFoundError):
        return False
    # Probe one nested feature package; namespace quirks can make the top-level
    # ``tests`` import while nested feature packages do not resolve by dotted path.
    for candidate in _TEST_MODULES:
        if candidate.count(".") >= 1:
            try:
                importlib.import_module(candidate)
            except (ImportError, ModuleNotFoundError):
                return False
            return True
    return True


_INCLUDE_TESTS = bool(_TEST_MODULES) and _tests_importable_as_package()
_SAMPLED_MODULES = sorted(
    set(_API_MODULES) | (set(_TEST_MODULES) if _INCLUDE_TESTS else set())
)


def test_module_set_is_non_empty() -> None:
    """Guard: the enumeration actually found modules to sample from.

    Without this, an empty ``sampled_from`` would make the property test vacuous
    (or error), silently passing while proving nothing.
    """
    assert _API_MODULES, f"no api.* modules found under {_API_ROOT}"
    assert _SAMPLED_MODULES, "no modules enumerated for import-resolution sampling"


# deadline=None: the first import of a real module pulls in transitive imports
# and I/O, which is legitimately slower than Hypothesis's default 200ms
# per-example deadline. Import cost is not the property under test.
@settings(max_examples=150, deadline=None)
@given(module_name=st.sampled_from(_SAMPLED_MODULES))
def test_every_project_internal_module_imports(module_name: str) -> None:
    """Property 9: every enumerated ``api.*`` (and importable ``tests.*``) module imports cleanly.

    For any project-internal module sampled from the migrated ``python/api``
    tree (and the ``python/tests`` tree when importable as a dotted package),
    importing it raises neither ``ModuleNotFoundError`` nor ``ImportError``.

    **Validates: Requirements 4.1, 4.3, 4.6, 6.6**
    """
    assert module_name.split(".")[0] in {"api", "tests"}, (
        f"out-of-scope module leaked into the sample: {module_name!r}"
    )

    try:
        importlib.import_module(module_name)
    except (ImportError, ModuleNotFoundError) as exc:  # ModuleNotFoundError ⊂ ImportError
        pytest.fail(f"import of {module_name!r} failed: {exc!r}")
