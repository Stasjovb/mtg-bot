"""Unified distributed-iter launcher.

A single, well-tested entrypoint for kicking off an iter_NNN cycle:
parse one TOML config + CLI overrides, register the cycle in
``runs.db`` so the UI shows it ``running`` immediately, render a
per-cycle ephemeral ``shards_config.json``, then spawn
``mtg_bot iterate`` as a child subprocess. The cycle lifecycle
context manager spans the iterate subprocess and writes the terminal
status (``completed`` / ``failed`` / ``killed``) through ONE
finaliser so all exit paths (signal, exception, normal completion,
atexit) keep the UI honest.

Phase A is local-only -- ``--cluster.local-only`` short-circuits any
AWS fleet management. The AWS fields in the TOML are parsed but
unused until Phase B fills in :mod:`mtg_bot.launcher.aws_fleet`.

Sub-modules:

- :mod:`mtg_bot.launcher.config` -- ``LaunchConfig`` dataclass, TOML
  loader, CLI override merge.
- :mod:`mtg_bot.launcher.state` -- per-cycle ephemeral paths +
  shards_config renderer.
- :mod:`mtg_bot.launcher.lifecycle` -- ``cycle_lifecycle`` ctx mgr.

See :mod:`mtg_bot.cli.iterate_distributed` for the CLI dispatcher
that glues these together.
"""
