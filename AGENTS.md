# Project agent memory

- See [CONTRIBUTING.md](CONTRIBUTING.md) for locked setup, tests, and immutable
  dependency publication. Use `uv run --frozen pytest -q` to test this checkout.
- [README.md](README.md) owns the canonical-input, timing, and QC contracts;
  run/session pairing is settled upstream, and exclusion policy belongs to `network_qa`.
- [docs/CODE-REVIEW.md](docs/CODE-REVIEW.md) records the event-semantics audit and
  its limits. [tests/test_event_semantics.py](tests/test_event_semantics.py) provides
  synthetic raw-to-BIDS regressions; use synthetic data for new fixtures.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
