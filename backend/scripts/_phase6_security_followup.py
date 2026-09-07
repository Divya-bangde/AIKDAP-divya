"""Follow-up probes: (1) does unicode whitespace that slips the charset
gate actually reach parse_equation and do anything unexpected, (2) does
the DoS class reach the constraint-validation path too (which already
passes evaluate=False), (3) how long does the hang actually go if given
more rope, (4) exact scale of the no-length-cap growth risk."""
import signal
import time

from app.agents.planner.experiment import parse_equation, validate_numeric_constraint, EquationParseError


def with_timeout(fn, *a, timeout=15, **k):
    class T(Exception):
        pass

    def h(s, f):
        raise T()

    old = signal.signal(signal.SIGALRM, h)
    signal.alarm(timeout)
    t0 = time.time()
    try:
        r = fn(*a, **k)
        return ("OK", repr(r)[:200], time.time() - t0)
    except T:
        return ("TIMEOUT", f">{timeout}s", time.time() - t0)
    except Exception as exc:
        return (type(exc).__name__, str(exc)[:200], time.time() - t0)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


print("--- unicode whitespace through full parse_equation ---")
for expr in ["Y = x\xa0+\xa01", "Y = x + 1"]:
    print(repr(expr), "->", with_timeout(parse_equation, expr))

print("\n--- DoS class via constraint path (already has evaluate=False) ---")
for expr in ["9**9**9**9 > 0", "factorial(factorial(20)) > 0"]:
    print(repr(expr), "->", with_timeout(validate_numeric_constraint, expr, {}, timeout=8))

print("\n--- exact hang duration, longer rope ---")
print("9**9**9**9 with 20s budget ->", with_timeout(parse_equation, "Y = 9**9**9**9", timeout=20))

print("\n--- no length cap: does a 200,000-char expression even get this far? ---")
big = "Y = " + "x+" * 100000 + "1"
print(f"length={len(big)} ->", with_timeout(parse_equation, big, timeout=15))
