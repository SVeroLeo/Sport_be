"""Unit tests for post-migration configuration and Handler_Path resolution.

Covers task 15.5 of the folder-structure-migration spec:

- Parse ``pyproject.toml`` (via :mod:`tomllib`) and assert each of the five
  migration-affected settings equals its post-migration value and contains no
  standalone ``src`` path value.
- Assert the CDK ``infra/stacks/app_stack.py`` and
  ``infra/lambda_assets/lambda_bundling.py`` contain zero ``src`` / ``src/**``
  *path* references. Identifier names (e.g. ``_SRC_PATH``) and the ruff
  ``src =`` config key are NOT path references and are explicitly excluded.
- For each of the six Handler_Paths, import the new module and assert a
  ``handler`` attribute exists, is callable, and its first two parameters are
  ``(event, context)``.

Requirements: 5.1, 5.3, 5.5, 7.6
"""

from __future__ import annotations

import importlib
import inspect
import re
import tomllib
from pathlib import Path

import pytest

# ──── Repo layout ─────────────────────────────────────────────────────────────

# This file lives at python/tests/common/unit/ so the repo root is four parents up.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_PYPROJECT = _REPO_ROOT / "pyproject.toml"
_APP_STACK = _REPO_ROOT / "infra" / "stacks" / "app_stack.py"
_LAMBDA_BUNDLING = _REPO_ROOT / "infra" / "lambda_assets" / "lambda_bundling.py"

# ──── pyproject.toml: expected post-migration values ──────────────────────────

# Each entry: (human-readable name, list of table keys, expected value).
_EXPECTED_SETTINGS: list[tuple[str, list[str], object]] = [
    (
        "hatch wheel packages",
        ["tool", "hatch", "build", "targets", "wheel", "packages"],
        ["python"],
    ),
    (
        "pytest pythonpath",
        ["tool", "pytest", "ini_options", "pythonpath"],
        ["python"],
    ),
    (
        "pytest testpaths",
        ["tool", "pytest", "ini_options", "testpaths"],
        ["python/tests"],
    ),
    (
        "mypy mypy_path",
        ["tool", "mypy", "mypy_path"],
        "python",
    ),
    (
        "ruff src",
        ["tool", "ruff", "src"],
        ["python", "python/tests"],
    ),
    (
        "ruff isort known-first-party",
        ["tool", "ruff", "lint", "isort", "known-first-party"],
        ["api"],
    ),
]


def _dig(data: dict, keys: list[str]) -> object:
    """Walk a nested mapping following ``keys``; fail the test if a key is missing."""
    node: object = data
    for key in keys:
        assert isinstance(node, dict), f"expected a table while resolving {keys!r}"
        assert key in node, f"missing pyproject setting: {'.'.join(keys)}"
        node = node[key]
    return node


def _iter_path_values(value: object):
    """Yield every string that represents a path value within ``value``."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_path_values(item)


def _references_src(path_value: str) -> bool:
    """True if a path string refers to a ``src`` directory (``src`` or ``src/...``)."""
    normalized = path_value.replace("\\", "/")
    segments = normalized.split("/")
    return "src" in segments


@pytest.fixture(scope="module")
def pyproject_data() -> dict:
    """Parse pyproject.toml once for the module."""
    assert _PYPROJECT.is_file(), f"pyproject.toml not found at {_PYPROJECT}"
    with _PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)


# The five migration-affected settings the task calls out. (The isort
# known-first-party -> ["api"] change is also asserted for completeness.)
@pytest.mark.parametrize(
    ("name", "keys", "expected"),
    _EXPECTED_SETTINGS,
    ids=[s[0] for s in _EXPECTED_SETTINGS],
)
def test_pyproject_setting_equals_post_migration_value(
    pyproject_data: dict,
    name: str,
    keys: list[str],
    expected: object,
) -> None:
    """Each pyproject setting equals its post-migration value (Req 7.6)."""
    actual = _dig(pyproject_data, keys)
    assert actual == expected, f"{name}: expected {expected!r}, got {actual!r}"


@pytest.mark.parametrize(
    ("name", "keys", "expected"),
    _EXPECTED_SETTINGS,
    ids=[s[0] for s in _EXPECTED_SETTINGS],
)
def test_pyproject_setting_contains_no_src_path(
    pyproject_data: dict,
    name: str,
    keys: list[str],
    expected: object,
) -> None:
    """No migration-affected setting still points at a ``src`` path (Req 7.6)."""
    actual = _dig(pyproject_data, keys)
    offending = [p for p in _iter_path_values(actual) if _references_src(p)]
    assert not offending, f"{name}: stale src path value(s): {offending!r}"


# ──── CDK path-reference scan ─────────────────────────────────────────────────

# Match a quoted string whose value is a src directory path: "src", "src/**",
# 'src/foo', etc. Anchored to a quote so identifiers like _SRC_PATH and the
# ruff `src =` config key are NOT matched (they are not quoted path strings).
_SRC_PATH_LITERAL = re.compile(r"""(['"])(src(?:/[^'"]*)?)\1""")


@pytest.mark.parametrize(
    "cdk_file",
    [_APP_STACK, _LAMBDA_BUNDLING],
    ids=["app_stack.py", "lambda_bundling.py"],
)
def test_cdk_file_has_no_src_path_reference(cdk_file: Path) -> None:
    """CDK files carry zero ``src`` / ``src/**`` path references (Req 5.1, 7.6).

    Identifier names such as ``_SRC_PATH`` / ``_copy_source_tree`` and the local
    ``src`` loop variable are not path references and must not trip this check;
    only quoted ``src`` path literals count.
    """
    assert cdk_file.is_file(), f"CDK file not found: {cdk_file}"
    text = cdk_file.read_text(encoding="utf-8")
    matches = [m.group(2) for m in _SRC_PATH_LITERAL.finditer(text)]
    assert not matches, f"{cdk_file.name}: stale src path literal(s): {matches!r}"


# ──── Handler_Path resolution ─────────────────────────────────────────────────

# The six Handler_Paths wired in app_stack.py (module path, not the .handler tail).
_HANDLER_MODULES = [
    "api.auth.authHandler",
    "api.registration.registrationHandler",
    "api.accountType.accountTypeHandler",
    "api.member.memberHandler",
    "api.registration.postConfirmationHandler",
    "api.socialLogin.oauthHandler",
]


@pytest.mark.parametrize("module_path", _HANDLER_MODULES)
def test_handler_is_callable_with_event_context(module_path: str) -> None:
    """Each Handler_Path resolves to a ``handler(event, context)`` callable.

    Validates Requirements 5.1, 5.3, 5.5: the migrated module imports, exposes a
    ``handler`` attribute, that attribute is callable, and its first two
    positional parameters are named ``event`` and ``context``.
    """
    module = importlib.import_module(module_path)

    assert hasattr(module, "handler"), f"{module_path} has no `handler` attribute"
    handler = module.handler
    assert callable(handler), f"{module_path}.handler is not callable"

    params = list(inspect.signature(handler).parameters)
    assert params[:2] == ["event", "context"], (
        f"{module_path}.handler first two params are {params[:2]!r}, "
        "expected ['event', 'context']"
    )
