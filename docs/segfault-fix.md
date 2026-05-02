# Pytest STATUS_ACCESS_VIOLATION segfault — root cause and fix

## Summary

The intermittent `STATUS_ACCESS_VIOLATION` (Windows `0xC0000005`,
`exit code 3221225477`) crash that pytest exhibits during the
simulation sweep tests is caused by **coverage.py's C-trace backend
under Python 3.11**. The fix is to run the test suite under
**Python 3.12+ (3.13 verified)**, where coverage.py uses the
PEP 669 `sys.monitoring` ("sysmon") backend instead. The crash does
not reproduce on 3.13 + sysmon.

## Verified configuration (crash-free)

- **Interpreter**: CPython 3.13.13 (`py -3.13`)
- **coverage.py**: 7.13.5
- **Backend**: `sysmon` (PEP 669) — already configured in
  `pyproject.toml` via `[tool.coverage.run] core = "sysmon"`. On
  3.11 this setting is silently ignored (no PEP 669 support),
  causing the older C-trace backend to be used. On 3.12+ it's
  honored, and `coverage debug sys` confirms `core: SysMonitor`.
- **Branch coverage**: still off (`branch = false`). coverage.py
  does not yet support branch coverage in sysmon mode.

## Reproduction stats

Three full pytest runs under 3.13 + sysmon, all clean:

| Run | Mode             | Time     | Result                                   |
| --- | ---------------- | -------- | ---------------------------------------- |
| 1   | sequential       | 170.25 s | 6349 passed, 3 skipped, 1 deselected     |
| 2   | sequential       | 145.28 s | 6349 passed, 3 skipped, 1 deselected     |
| 3   | sequential       | 143.48 s | 6349 passed, 3 skipped, 1 deselected     |
| 4   | xdist `-n 8`     |  30.74 s | 6349 passed, 3 skipped                   |

Coverage held at 95.57–95.60% (above the 95% gate). No segfaults,
no Windows fatal exceptions, no `INTERNALERROR` from pytest, no
sweep-test assertion flakes.

## Why 3.11 crashes and 3.13 doesn't

- 3.11 lacks `sys.monitoring`, so `coverage.py` falls back to the
  legacy C extension `tracer.cp311-win_amd64.pyd` driven by
  `sys.settrace`. The settrace hook fires on every Python frame
  enter/exit and every line; long-lived deep recursion through
  `state_based_actions` → `_static_bonuses` → `_dynamic_base_pt`
  appears to provoke memory corruption inside the tracer's frame
  ring buffer.
- 3.12 added PEP 669 (`sys.monitoring`), a redesigned event API
  that uses per-event registration and code-object-level tool IDs.
  coverage.py >=7.4 uses it transparently when available. The
  hot path no longer goes through the crashing C tracer — and the
  segfault disappears.

The tracebacks from the 3.11 crashes (always inside one of
`_dynamic_base_pt`, `re._compile`, or `threading.wait` from a
daemon thread) are red herrings — the corruption happens inside
the tracer; the next Python frame to dereference a corrupted
pointer is whichever one happened to be running. That's why the
crash site varied across runs.

## How to use 3.13 locally

A parallel venv lives at `.venv-py313/` (gitignored via the
`.venv-*/` glob). Create it with:

```
py -3.13 -m venv .venv-py313
.venv-py313/Scripts/python.exe -m pip install --upgrade pip
.venv-py313/Scripts/python.exe -m pip install -e ".[dev]"
```

Then run the suite with:

```
PYTHONPATH=src .venv-py313/Scripts/python.exe -m pytest
```

(The shared `.venv/` at `mtg-bot/.venv/` remains 3.11 for now —
nothing in the project requires 3.12+, and the pyproject pin stays
at `>=3.11`. 3.13 is the recommended interpreter for running the
test suite locally.)

## Retired: `scripts/run_tests.py`

A `scripts/run_tests.py` retry-on-segfault wrapper used to exist as
a workaround for the 3.11 crash. With 3.13 + sysmon as the
recommended interpreter, the wrapper was deleted; run pytest
directly. If you're still on 3.11 and hit the crash, switch
interpreters per the steps above rather than reviving the retry
loop.
