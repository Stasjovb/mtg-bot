"""Tests for LogBuffer — the silent-mode switch behind state.log.

Search rollouts disable the buffer to skip log-string allocation at
the ~300 engine sites that append to it. When enabled (the default),
the buffer behaves like a normal list[str].
"""

from mtg_bot.game import GameState, LogBuffer


def test_default_enabled_buffer_accepts_appends() -> None:
    state = GameState()
    assert isinstance(state.log, LogBuffer)
    assert state.log.enabled is True

    state.log.append("hello")
    state.log.append("world")

    assert len(state.log) == 2
    assert state.log[0] == "hello"
    assert state.log[-1] == "world"


def test_disabled_buffer_drops_appends() -> None:
    state = GameState()
    state.log.enabled = False

    for i in range(50):
        state.log.append(f"msg {i}")

    assert len(state.log) == 0


def test_re_enabling_resumes_capture() -> None:
    state = GameState()
    state.log.append("before")

    state.log.enabled = False
    state.log.append("dropped-1")
    state.log.append("dropped-2")
    assert len(state.log) == 1

    state.log.enabled = True
    state.log.append("after")

    assert list(state.log) == ["before", "after"]


def test_log_buffer_is_a_list() -> None:
    """Non-append list operations still work — tests that index/slice
    the log keep working when the buffer is enabled."""
    lb = LogBuffer(["a", "b", "c"])
    assert lb[0] == "a"
    assert lb[-1] == "c"
    assert list(lb[1:]) == ["b", "c"]
    assert len(lb) == 3
    assert "b" in lb


def test_standalone_log_buffer_disable_enable() -> None:
    """LogBuffer works the same way outside a GameState."""
    lb = LogBuffer()
    lb.append("x")
    lb.enabled = False
    lb.append("y")
    assert list(lb) == ["x"]
    lb.enabled = True
    lb.append("z")
    assert list(lb) == ["x", "z"]
