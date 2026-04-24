"""Tests for ``Budget``."""

import time

from mtg_bot.search import Budget


def test_node_cap_exhausts_after_n_calls():
    b = Budget(max_nodes=5)
    b.start()
    assert b.exhausted() is False
    for _ in range(5):
        b.consume_node()
    assert b.exhausted() is True


def test_no_caps_never_exhaust():
    b = Budget()
    b.start()
    for _ in range(1000):
        b.consume_node()
    assert b.exhausted() is False


def test_time_cap_exhausts_after_deadline():
    b = Budget(max_seconds=0.01)
    b.start()
    assert b.exhausted() is False
    time.sleep(0.02)
    assert b.exhausted() is True


def test_both_caps_first_wins():
    b = Budget(max_seconds=10.0, max_nodes=3)
    b.start()
    for _ in range(3):
        b.consume_node()
    assert b.exhausted()


def test_diagnostics():
    b = Budget(max_nodes=2)
    b.start()
    assert b.nodes_expanded() == 0
    b.consume_node()
    assert b.nodes_expanded() == 1
    assert b.elapsed() >= 0.0


def test_restart_resets_state():
    b = Budget(max_nodes=1)
    b.start()
    b.consume_node()
    assert b.exhausted()
    b.start()
    assert not b.exhausted()
    assert b.nodes_expanded() == 0
