"""
Sprint 16 Phase 6 security review -- live attack battery against the
actual, imported production module (app.agents.planner.experiment),
run inside the real backend container. No simulation, no mocking of
the functions under test.
"""
import signal
import sys
import time
import traceback

from app.agents.planner.experiment import (
    EquationParseError,
    _assert_expression_is_safe,
    parse_equation,
    validate_numeric_constraint,
    check_all_constraints,
)
from app.modules.research.experiment_schemas import ExperimentVariable, ExperimentConstraint

results = []


def record(category, expr, fn, *args, timeout=5, **kwargs):
    class TimeoutErr(Exception):
        pass

    def handler(signum, frame):
        raise TimeoutErr()

    old = signal.signal(signal.SIGALRM, handler)
    signal.alarm(timeout)
    start = time.time()
    try:
        out = fn(expr, *args, **kwargs)
        elapsed = time.time() - start
        results.append((category, expr, "NO EXCEPTION", repr(out)[:300], elapsed))
    except TimeoutErr:
        elapsed = time.time() - start
        results.append((category, expr, "TIMEOUT/HANG", f">{timeout}s - DOS RISK", elapsed))
    except EquationParseError as exc:
        elapsed = time.time() - start
        results.append((category, expr, "BLOCKED (EquationParseError)", str(exc)[:200], elapsed))
    except Exception as exc:  # noqa: BLE001 - want to see literally everything
        elapsed = time.time() - start
        results.append((category, expr, f"BLOCKED/ERROR ({type(exc).__name__})", str(exc)[:200], elapsed))
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


# ---------------------------------------------------------------------
# 1. Sandbox-escape gadgets via _assert_expression_is_safe directly
# ---------------------------------------------------------------------
gadgets = [
    "().__class__.__bases__[0].__subclasses__()",
    "(1).__class__.__bases__[0].__subclasses__()",
    "().__class__.__mro__[1].__subclasses__()",
    "(lambda:0).__globals__",
    "(lambda:0).__globals__['__builtins__']",
    "__builtins__",
    "__builtins__['eval']",
    "__builtins__.eval('1')",
    "__import__('os')",
    "__import__('os').system('echo pwned')",
    "getattr(x, '__class__')",
    "getattr(x,y)",
    "setattr(x,'y',1)",
    "eval('1')",
    "exec('1')",
    "open('/etc/passwd')",
    "compile('1','','eval')",
    "[].__class__",
    "{}.__class__",
    "().__reduce__()",
    "().__init_subclass__()",
    "x.__dict__",
    "x.__module__",
]
for g in gadgets:
    record("gadget:_assert_expression_is_safe", g, _assert_expression_is_safe)

for g in gadgets:
    record("gadget:parse_equation", g, parse_equation)

# ---------------------------------------------------------------------
# 2. Unicode / encoding / whitespace bypass attempts against the regex allowlist
# ---------------------------------------------------------------------
unicode_attacks = [
    "․․class․․",       # ONE DOT LEADER lookalikes for '..'/'__'
    "x + 1",                      # non-breaking space
    "x + 1",                      # line separator whitespace
    "＿import＿('os')",             # fullwidth low line U+FF3F looks like _
    "x​.__class__",                    # zero-width space trying to slip past dot regex
    "​x",                              # leading zero-width space
    "＿＿class＿＿",                          # fullwidth underscore characters spelling __class__
    "xㅤ",                              # hangul filler (invisible-ish)
    "𝟏𝟐𝟑",                                    # mathematical bold digits (not ASCII 0-9)
    "x۱",                              # extended arabic-indic digit one
]
for u in unicode_attacks:
    record("unicode-bypass:_assert_expression_is_safe", u, _assert_expression_is_safe)

# ---------------------------------------------------------------------
# 3. Resource exhaustion / DoS via legitimate-looking math
# ---------------------------------------------------------------------
dos_exprs = [
    "Y = factorial(100000)",
    "Y = factorial(factorial(20))",
    "Y = 2**2**2**2**2**2**2",
    "Y = 9**9**9**9",
    "Y = (((((((((((((((((((((((((((((x)))))))))))))))))))))))))))))",
    "Y = " + "x+" * 5000 + "1",
    "Y = " + "(" * 2000 + "x" + ")" * 2000,
    "Y = summation(1/n, (n, 1, oo))",
    "Y = integrate(1/x, x)",
    "Y = " + "x*" * 20000 + "1",
]
for d in dos_exprs:
    label = d if len(d) <= 80 else d[:77] + "..."
    record("dos:parse_equation", d, parse_equation, timeout=6)

# ---------------------------------------------------------------------
# 4. Malformed parser inputs
# ---------------------------------------------------------------------
malformed = [
    "",
    "   ",
    "Y = ",
    "Y = )(",
    "Y = 1//0",
    "Y = @#$%^&",
    None,
]
for m in malformed:
    if m is None:
        results.append(("malformed:parse_equation", "None", "SKIPPED", "not a str, would TypeError at call site", 0))
        continue
    record("malformed:parse_equation", m, parse_equation)

# ---------------------------------------------------------------------
# 5. constraint-path attacks (validate_numeric_constraint / check_all_constraints)
# ---------------------------------------------------------------------
for g in gadgets[:8]:
    record("gadget:validate_numeric_constraint", g, validate_numeric_constraint, {})

# check_all_constraints with a malicious constraint expression embedded in an ExperimentConstraint
try:
    var = ExperimentVariable(name="x", role="input", mutable="mutable", mutability_reason="t", mutability_evidence="none", current_value="1")
    bad_constraint = ExperimentConstraint(
        expression="().__class__.__bases__[0].__subclasses__()",
        description="malicious",
        source="user_constraint",
    )
    viol = check_all_constraints([var], [bad_constraint])
    results.append(("gadget:check_all_constraints", bad_constraint.expression, "NO EXCEPTION (constraint silently skipped, not evaluated)", repr(viol), 0))
except Exception as exc:
    results.append(("gadget:check_all_constraints", "subclasses-gadget", f"ERROR ({type(exc).__name__})", str(exc)[:200], 0))

# ---------------------------------------------------------------------
# 6. Legitimate math -- must still work
# ---------------------------------------------------------------------
legit = [
    "Y = (a*X + b) / (c*X + d)",
    "Y = aX + b",  # implicit multiplication shorthand
    "Y = 2.5*X + 3.14159",
    "Y = X**2 + 1",
    "learning_rate > 0",
    "threshold >= 0.5",
    "Y = sin(X) + cos(X)",
    "Y = sqrt(X**2 + 1)",
    "Y = exp(-X) / (1 + exp(-X))",  # sigmoid
    "Y = 1.5e10 * X",  # scientific notation
    "Y = -X + 1",
    "c*X + d != 0",
]
for l in legit:
    record("legit-math:parse_equation", l, parse_equation)

for l in ["learning_rate > 0", "threshold >= 0.5", "c*X + d != 0"]:
    try:
        if l == "learning_rate > 0":
            ok = validate_numeric_constraint(l, {"learning_rate": 0.01})
        elif l == "threshold >= 0.5":
            ok = validate_numeric_constraint(l, {"threshold": 0.7})
        else:
            ok = validate_numeric_constraint(l, {"c": 1.0, "X": 2.0, "d": 3.0})
        results.append(("legit-math:validate_numeric_constraint", l, "OK", str(ok), 0))
    except Exception as exc:
        results.append(("legit-math:validate_numeric_constraint", l, f"UNEXPECTED ERROR ({type(exc).__name__})", str(exc)[:200], 0))

# ---------------------------------------------------------------------
# Print report
# ---------------------------------------------------------------------
print("=" * 100)
for category, expr, outcome, detail, elapsed in results:
    e = expr if len(str(expr)) <= 70 else str(expr)[:67] + "..."
    print(f"[{category}] expr={e!r}\n  -> {outcome} ({elapsed:.3f}s) :: {detail}")
print("=" * 100)
print(f"TOTAL: {len(results)}")
