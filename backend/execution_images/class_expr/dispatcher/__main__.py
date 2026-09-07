"""Sprint 16 Phase 7B.26/7B.27 -- INVENTED across these two phases, not a
pre-existing contract.

Protocol (invented, minimal, stated here so it is never mistaken for a
discovered fact later):

  argv:   python3 -m dispatcher --operation evaluate_expression
          (fixed by execution_launcher/docker_policy.py::_DISPATCH_COMMAND
          -- this module never reads argv beyond --operation)
  input:  ONE JSON object, `{"expression": "2 + 3 * 4"}`, read from
          EITHER of two sources, in this priority order:
            1. the `AIKDAP_EXECUTION_PARAMETERS` environment variable
               (Sprint 16 Phase 7B.27 -- the guard-computed, size-bounded
               channel `execution_launcher/docker_policy.py` now derives
               for CLASS_EXPR; see that module's own docstring for why
               stdin was tried first and found to hang on the real
               daemon's transport)
            2. stdin, read fully (Phase 7B.26's original channel) -- kept
               as a fallback so a caller that does not set the env var
               (or attaches its own stdin directly, e.g. manual
               `docker run -i` testing) still gets the original,
               already-tested behavior, including the empty-stdin ->
               "missing or invalid 'expression' field" normal result.
          No argv-embedded user input, no shell interpretation, either way.
  stdout: exactly one JSON object, either
              {"result": <number or string>, "error": null}
          or  {"result": null, "error": "<message>"}
  exit code: 0 whenever a JSON object was successfully written to stdout
          (this includes an invalid/unparseable expression, and a
          malformed AIKDAP_EXECUTION_PARAMETERS value -- both are
          normal, expected results, not a dispatcher failure). Non-zero
          is reserved for a genuine dispatcher failure: stdin could not
          be read at all, or an exception escapes the code above that
          tries to guarantee a JSON object is always printed.

Evaluator: SymPy's parse_expr with an explicitly emptied `__builtins__`
in its global namespace (SymPy's own default otherwise lets CPython
inject the real builtins into that dict) -- never `eval()` called
directly by this module, never arbitrary attribute access. A `__`
substring is rejected before parsing at all, closing the classic
`().__class__.__bases__` object-introspection sandbox escape that an
emptied `__builtins__` alone does not block. This -- plus the
container's own network=none / read-only / non-root / cap-drop ALL
posture the guard already enforces -- is the actual security boundary;
this module is defense-in-depth on top of it, not a claimed-airtight
sandbox by itself (see the phase report's Remaining Risks).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import sympy
from sympy import Float, Integer, Rational
from sympy.parsing.sympy_parser import parse_expr, standard_transformations

# sympy's parse_expr(), when given an explicit global_dict, uses it
# as-is instead of its own default "from sympy import *" population --
# so the sympy namespace is copied in explicitly here, then
# __builtins__ is forced empty (CPython otherwise auto-injects the
# real builtins into any dict passed to eval/exec that lacks the key).
_SYMPY_GLOBAL_DICT = dict(vars(sympy))
_SYMPY_GLOBAL_DICT["__builtins__"] = {}


def _reject_dunder(expression: str) -> None:
    if "__" in expression:
        raise ValueError("expression must not contain '__'")


def _evaluate_expression(expression: str) -> tuple[object | None, str | None]:
    try:
        _reject_dunder(expression)
        value = parse_expr(
            expression,
            global_dict=_SYMPY_GLOBAL_DICT,
            transformations=standard_transformations,
            evaluate=True,
        )
    except Exception as exc:  # noqa: BLE001 -- any parse/eval failure is a normal invalid-expression result
        return None, f"invalid expression: {exc}"

    if isinstance(value, (Integer, Rational, Float)) or value.is_number:
        try:
            return float(value), None
        except (TypeError, ValueError):
            return str(value), None
    return str(value), None


#: Sprint 16 Phase 7B.27 -- must match
#: execution_launcher/docker_policy.py::_EXPRESSION_PARAMETER_ENV_VAR
#: exactly (not imported -- that module is application code the image
#: never carries; the name is duplicated here deliberately, the same
#: way `_DISPATCH_COMMAND`'s argv shape is duplicated rather than
#: shared).
_ENV_PARAMETERS_VAR = "AIKDAP_EXECUTION_PARAMETERS"


def _read_env_json() -> tuple[dict, str | None] | None:
    """Returns None if the env var is simply absent (caller should fall
    back to stdin); otherwise returns (payload, shape_error) exactly
    like `_read_stdin_json()` -- a malformed value IN the env var is a
    normal bad-input result, not silently swallowed into a stdin
    fallback that could mask a real bug in the caller."""
    raw = os.environ.get(_ENV_PARAMETERS_VAR)
    if raw is None:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {}, f"invalid JSON in {_ENV_PARAMETERS_VAR}: {exc}"
    if not isinstance(payload, dict):
        return {}, f"{_ENV_PARAMETERS_VAR} must be a JSON object"
    return payload, None


class _StdinReadError(Exception):
    """A genuine I/O failure reading stdin -- distinct from stdin being
    readable but containing malformed/wrong-shaped JSON, which is a
    normal bad-input result, not a dispatcher failure."""


def _read_stdin_json() -> tuple[dict, str | None]:
    try:
        raw = sys.stdin.read()
    except Exception as exc:  # noqa: BLE001 -- genuine I/O failure, not an input-shape problem
        raise _StdinReadError(f"failed to read stdin: {exc}") from exc
    if not raw.strip():
        return {}, None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {}, f"invalid JSON input: {exc}"
    if not isinstance(payload, dict):
        return {}, "input JSON must be an object"
    return payload, None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dispatcher")
    parser.add_argument("--operation", required=True, choices=["evaluate_expression"])
    args = parser.parse_args(argv)

    env_result = _read_env_json()
    if env_result is not None:
        payload, shape_error = env_result
    else:
        try:
            payload, shape_error = _read_stdin_json()
        except _StdinReadError as exc:
            # A genuine I/O failure reading stdin at all -- signals
            # dispatcher-level failure via a non-zero exit.
            sys.stdout.write(json.dumps({"result": None, "error": str(exc)}) + "\n")
            return 1

    if shape_error is not None:
        # Malformed JSON / wrong shape -- a normal bad-input result, exit 0.
        sys.stdout.write(json.dumps({"result": None, "error": shape_error}) + "\n")
        return 0

    if args.operation != "evaluate_expression":
        sys.stdout.write(
            json.dumps({"result": None, "error": f"unsupported operation: {args.operation}"}) + "\n"
        )
        return 0

    expression = payload.get("expression")
    if not isinstance(expression, str) or not expression.strip():
        sys.stdout.write(
            json.dumps({"result": None, "error": "missing or invalid 'expression' field"}) + "\n"
        )
        return 0

    result, error = _evaluate_expression(expression)
    sys.stdout.write(json.dumps({"result": result, "error": error}) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
