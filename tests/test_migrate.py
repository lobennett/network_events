"""Tests for network_events.migrate (moved from scripts/migrate_behavioral.py)."""
import json
from pathlib import Path


def _write_manifest(tmp_path, rows):
    """Write a TSV manifest file."""
    manifest = tmp_path / "manifest.tsv"
    header = "subject\tsession\ttask\tstatus\taction\tdest_session\tdest_run\traw_path\tbold_path\tsame_task_other_sessions\tnotes"
    lines = [header]
    for r in rows:
        lines.append("\t".join(str(r.get(c, "")) for c in header.split("\t")))
    manifest.write_text("\n".join(lines) + "\n")
    return manifest


def test_migrate_copies_matched_files(tmp_path):
    from network_events.migrate import migrate_from_manifest

    raw_csv = tmp_path / "raw" / "s03" / "ses-01" / "go-nogo.csv"
    raw_csv.parent.mkdir(parents=True)
    raw_csv.write_text("trial,rt\n1,500\n")

    output_dir = tmp_path / "sourcedata"

    manifest = _write_manifest(tmp_path, [{
        "subject": "s03", "session": "ses-01", "task": "goNogo",
        "status": "matched", "action": "copy", "dest_session": "ses-01",
        "raw_path": str(raw_csv), "bold_path": "", "same_task_other_sessions": "",
        "notes": "",
    }])

    report = migrate_from_manifest(manifest, output_dir)

    expected = output_dir / "in_scanner_behavior" / "sub-s03" / "ses-01" / "beh" / "sub-s03_ses-01_task-goNogo_beh.csv"
    assert expected.exists()
    assert expected.read_text() == "trial,rt\n1,500\n"
    assert report["copied"] == 1


def test_migrate_skips_pending(tmp_path):
    from network_events.migrate import migrate_from_manifest

    output_dir = tmp_path / "sourcedata"

    manifest = _write_manifest(tmp_path, [{
        "subject": "s29", "session": "ses-01", "task": "cuedTS",
        "status": "bold_without_behavioral", "action": "pending",
        "dest_session": "ses-01", "raw_path": "", "bold_path": "",
        "same_task_other_sessions": "", "notes": "",
    }])

    report = migrate_from_manifest(manifest, output_dir)

    assert report["copied"] == 0
    assert report["skipped_pending"] == 1


def test_migrate_fails_on_unresolved_pending(tmp_path):
    import pytest
    from network_events.migrate import migrate_from_manifest

    output_dir = tmp_path / "sourcedata"

    manifest = _write_manifest(tmp_path, [{
        "subject": "s29", "session": "ses-01", "task": "cuedTS",
        "status": "bold_without_behavioral", "action": "pending",
        "dest_session": "ses-01", "raw_path": "", "bold_path": "",
        "same_task_other_sessions": "", "notes": "",
    }])

    with pytest.raises(SystemExit):
        migrate_from_manifest(manifest, output_dir, strict=True)


def test_migrate_respects_dest_session_override(tmp_path):
    from network_events.migrate import migrate_from_manifest

    raw_csv = tmp_path / "raw" / "s03" / "ses-02" / "nback.csv"
    raw_csv.parent.mkdir(parents=True)
    raw_csv.write_text("trial,rt\n1,600\n")

    output_dir = tmp_path / "sourcedata"

    manifest = _write_manifest(tmp_path, [{
        "subject": "s03", "session": "ses-02", "task": "nBack",
        "status": "matched", "action": "copy", "dest_session": "ses-01",
        "raw_path": str(raw_csv), "bold_path": "", "same_task_other_sessions": "",
        "notes": "",
    }])

    migrate_from_manifest(manifest, output_dir)

    expected = output_dir / "in_scanner_behavior" / "sub-s03" / "ses-01" / "beh" / "sub-s03_ses-01_task-nBack_beh.csv"
    assert expected.exists()


def test_migrate_skips_irreconcilable(tmp_path):
    from network_events.migrate import migrate_from_manifest

    output_dir = tmp_path / "sourcedata"

    manifest = _write_manifest(tmp_path, [{
        "subject": "s29", "session": "ses-01", "task": "cuedTS",
        "status": "bold_without_behavioral", "action": "irreconcilable",
        "dest_session": "", "raw_path": "", "bold_path": "",
        "same_task_other_sessions": "", "notes": "",
    }])

    report = migrate_from_manifest(manifest, output_dir)

    assert report["copied"] == 0
    assert report["skipped_irreconcilable"] == 1


def test_migrate_skips_skip_action(tmp_path):
    from network_events.migrate import migrate_from_manifest

    output_dir = tmp_path / "sourcedata"

    manifest = _write_manifest(tmp_path, [{
        "subject": "s29", "session": "ses-01", "task": "cuedTS",
        "status": "behavioral_without_bold", "action": "skip",
        "dest_session": "", "raw_path": "/some/path.csv", "bold_path": "",
        "same_task_other_sessions": "", "notes": "",
    }])

    report = migrate_from_manifest(manifest, output_dir)

    assert report["copied"] == 0
    assert report["skipped_skip"] == 1


def test_migrate_uses_dest_run(tmp_path):
    from network_events.migrate import migrate_from_manifest

    raw_csv = tmp_path / "raw" / "s29" / "ses-03" / "spatialTS.csv"
    raw_csv.parent.mkdir(parents=True)
    raw_csv.write_text("trial,rt\n1,500\n")

    output_dir = tmp_path / "sourcedata"

    manifest = _write_manifest(tmp_path, [{
        "subject": "s29", "session": "ses-03", "task": "spatialTS",
        "status": "matched", "action": "copy", "dest_session": "ses-03",
        "dest_run": "2",
        "raw_path": str(raw_csv), "bold_path": "", "same_task_other_sessions": "",
        "notes": "",
    }])

    migrate_from_manifest(manifest, output_dir)

    expected = output_dir / "in_scanner_behavior" / "sub-s29" / "ses-03" / "beh" / "sub-s29_ses-03_task-spatialTS_run-2_beh.csv"
    assert expected.exists()


from pathlib import Path
from network_events.migrate import migrate_out_scanner

def test_migrate_out_scanner_places_practice_under_out_scanner_behavior(tmp_path):
    raw = tmp_path / "raw"; (raw / "s03" / "ses-1" / "practice").mkdir(parents=True)
    (raw / "s03" / "ses-1" / "practice" / "run1.csv").write_text("a,b\n1,2\n")
    out = tmp_path / "sourcedata"
    migrate_out_scanner(raw, out, subjects={"s03"})
    hits = list((out / "out_scanner_behavior").rglob("*.csv"))
    assert hits, "expected a practice csv copied under out_scanner_behavior/"
    assert any("sub-s03" in str(p) or "s03" in str(p) for p in hits)
