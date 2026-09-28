"""Property-based test for CDK Handler_Path callable resolution.

Feature: folder-structure-migration, Property 11: Every Handler_Path resolves
to a ``handler(event, context)`` callable. For any of the six CDK Handler_Paths
after migration, the dotted path resolves to a callable attribute named
``handler`` whose first two positional parameters are named ``event`` and
``context`` in that order.

Validates: Requirements 5.1, 5.3, 5.5, 5.6

This is the Hypothesis PROPERTY version of the Handler_Path resolution check.
An example-based unit variant already exists in
``python/tests/common/unit/test_config_and_handler_resolution.py`` (task 15.5);
this file samples over the six Handler_Paths with Hypothesis so the invariant is
exercised as a universal property (min 100 iterations).

The six Handler_Paths are DERIVED by parsing the CDK stack
``infra/stacks/app_stack.py`` rather than hardcoded, so the test stays coupled
to the actual CDK wiring: if a handler string changes in the stack, this test
follows it automatically (and fails loudly if the count is no longer six).
"""

from __future__ import annotations

import ast
import importlib
import inspect
import re
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

# ──── Repo layout ─────────────────────────────────────────────────────────────

# This file lives at python/tests/common/property/ so the repo root is four
# parents up: property -> common -> tests -> python -> <repo root>.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_APP_STACK = _REPO_ROOT / "infra" / "stacks" / "app_stack.py"

# A Handler_Path is a dotted module-and-function string ending in ``.handler``
# and rooted at the ``api`` package under the new ``python/`` source root.
_HANDLER_PATH_RE = re.compile(r"^api(?:\.[A-Za-z_][A-Za-z0-9_]*)+\.handler$")

_EXPECTED_HANDLER_COUNT = 6


def _derive_handler_paths(stack_source: str) -> list[str]:
    """Extract the CDK Handler_Path dotted strings from ``app_stack.py``.

    Parses the module with :mod:`ast` and collects every string literal that
    matches the Handler_Path shape (``api.<...>.handler``). This keeps the test
    coupled to the actual CDK wiring: the handler strings are read from the
    source of truth, not restated here.
    """
    tree = ast.parse(stack_source)
    found: list[str] = []
    seen: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
            if _HANDLER_PATH_RE.match(value) and value not in seen:
                seen.add(value)
                found.append(value)
    return found


# Derived once at import time so the sampled strategy and the count assertion
# share a single source of truth.
# Read with utf-8-sig so a leading BOM (present in app_stack.py) is stripped
# before ast.parse, which rejects a U+FEFF byte-order mark.
_HANDLER_PATHS = _derive_handler_paths(_APP_STACK.read_text(encoding="utf-8-sig"))


def test_exactly_six_handler_paths_are_wired() -> None:
    """The CDK stack wires exactly six Handler_Paths (guards the derivation).

    Property 11 quantifies over "the six CDK Handler_Paths". This precondition
    asserts the derivation actually found six, so the property below cannot pass
    vacuously if the parse ever stops matching the handler strings.
    """
    assert len(_HANDLER_PATHS) == _EXPECTED_HANDLER_COUNT, (
        f"expected {_EXPECTED_HANDLER_COUNT} Handler_Paths derived from "
        f"{_APP_STACK}, found {len(_HANDLER_PATHS)}: {_HANDLER_PATHS!r}"
    )


@settings(max_examples=100)
@given(handler_path=st.sampled_from(_HANDLER_PATHS))
def test_handler_path_resolves_to_event_context_callable(handler_path: str) -> None:
    """Property 11: every Handler_Path resolves to a ``handler(event, context)``.

    For any sampled Handler_Path, splitting off the trailing ``.handler``
    attribute and importing the module must yield a callable ``handler`` whose
    first two positional parameters are named ``event`` and ``context`` in that
    order (Req 5.1, 5.3, 5.5). A path that cannot be resolved to such a callable
    is a Property 11 / Req 5.6 violation and fails the test.
    """
    module_path, _, attr_name = handler_path.rpartition(".")
    assert attr_name == "handler", (
        f"Handler_Path {handler_path!r} does not end in `.handler`"
    )

    module = importlib.import_module(module_path)

    assert hasattr(module, "handler"), (
        f"{module_path} exposes no `handler` attribute (Req 5.1/5.3)"
    )
    handler = module.handler
    assert callable(handler), (
        f"{handler_path} does not resolve to a callable (Req 5.3/5.6)"
    )

    params = list(inspect.signature(handler).parameters)
    assert params[:2] == ["event", "context"], (
        f"{handler_path} first two params are {params[:2]!r}, "
        "expected ['event', 'context'] (Req 5.5)"
    )
