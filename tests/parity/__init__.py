"""Phase 5 cross-engine parity test helpers.

Shared support code for cross-engine parity probes (the
``tests/test_parity_smoke.py`` real-EoE probes and the
``tests/test_cross_engine_etb_triggers.py`` bridge-arm pin tests).
Per-probe inline helpers that ended up duplicated across multiple
probes are hoisted here so a single edit propagates.
"""
