"""Public CLI contracts for the canonical identity workflow."""
from __future__ import annotations

from network_events.cli import main


def test_audit_returns_two_for_identity_errors(tmp_path):
    """A missing behavioral directory must block the identity audit."""
    assert main([
        "audit", "--bids-dir", str(tmp_path),
        "--behavioral-dir", str(tmp_path / "behavioral"),
    ]) == 2


def test_create_refuses_unaudited_identity_errors(tmp_path):
    """Create must not attempt conversions while the shared audit has errors."""
    assert main([
        "create", "--bids-dir", str(tmp_path),
        "--behavioral-dir", str(tmp_path / "behavioral"),
    ]) == 2
