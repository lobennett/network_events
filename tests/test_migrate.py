"""Tests for network_events.migrate (out-of-scanner + survey only)."""
from network_events.migrate import migrate_out_scanner


def test_migrate_out_scanner_places_practice_under_out_scanner_behavior(tmp_path):
    raw = tmp_path / "raw"; (raw / "s03" / "ses-1" / "practice").mkdir(parents=True)
    (raw / "s03" / "ses-1" / "practice" / "run1.csv").write_text("a,b\n1,2\n")
    out = tmp_path / "sourcedata"
    migrate_out_scanner(raw, out, subjects={"s03"})
    hits = list((out / "out_scanner_behavior").rglob("*.csv"))
    assert hits, "expected a practice csv copied under out_scanner_behavior/"
    assert any("sub-s03" in str(p) or "s03" in str(p) for p in hits)



