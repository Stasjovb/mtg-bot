# Project rules for Claude

## Development workflow

- **Every new feature must be developed on its own branch off `main`.** Do not commit feature work directly to `main`.
- Branch naming: `feature/<short-name>` (e.g. `feature/flying-keyword`, `feature/etb-triggers`).
- **Commit as you go.** Each unit of work is its own commit on the feature branch. Do not batch everything into one monster commit.
- **Tests must pass before every commit.** Run the full test suite; if anything fails, fix it before committing.
- **Do not merge to `main` yourself.** Push the branch for review and wait for the user to approve. Only after explicit approval, merge into `main`.

## Testing

- Use `pytest`. Tests live under `tests/`.
- **Target coverage: high 90s (≥95%).** Run `pytest --cov=mtg_bot` to check. Before declaring a feature complete, verify coverage has not regressed.
- Every new module needs its own `test_<module>.py`. Cover the happy path, meaningful edge cases, and error paths (invalid inputs, exceptional states).

## Running things

- Virtual env is at `.venv/`. Use `.venv/Scripts/python.exe` on Windows / `.venv/bin/python` on macOS-Linux.
- Run tests: `.venv/Scripts/python.exe -m pytest`
  (Python 3.13 + coverage.py can intermittently segfault deep in the simulation
  sweep tests. The crash is not reproducible in isolation and no local code
  change fixes it. If pytest exits with an access violation, run
  `.venv/Scripts/python.exe scripts/run_tests.py` — it retries on segfault.)
- Run browser-driven E2E tests (opt-in, skipped by default):
  `MTG_BOT_E2E=1 .venv/Scripts/python.exe -m pytest tests/test_e2e.py`
  First time only: `.venv/Scripts/python.exe -m pip install playwright`
  then `.venv/Scripts/python.exe -m playwright install chromium`.
- Run a game: `.venv/Scripts/python.exe -m mtg_bot`
- Run the UI (localhost): `.venv/Scripts/python.exe -m mtg_bot.ui`
- Run the UI over Tailscale (reachable from phone/laptop on the tailnet):
  `powershell -ExecutionPolicy Bypass -File scripts\serve.ps1`
  First-time firewall rule setup needs an elevated PowerShell.
- Warm the card-image cache (optional, for nicer first-load):
  `.venv/Scripts/python.exe scripts/fetch_card_images.py`
- Ad-hoc screenshot the live UI:
  `.venv/Scripts/python.exe scripts/screenshot_ui.py --url http://127.0.0.1:5002 --out ui.png`

## Scope reminders

- Card pool target: **Edge of Eternities** (Scryfall set code `eoe`). Raw data is cached at `data/edge_of_eternities.json`; regenerate via `scripts/fetch_eoe.py`.
- Real EoE cards come online as mechanics are implemented. Until then, Stage-1 uses synthetic vanilla creatures defined in `src/mtg_bot/cards.py`.
- Architectural decisions that are locked in: full stack-and-priority simulation (not resolve-immediately); Scryfall JSON as the card data source.
