from pathlib import Path
import pytest
from network_events import run as nerun

def test_run_stops_for_review_when_no_manifest(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(nerun, "reconcile", lambda **k: (calls.append("reconcile"), k["output"])[1])
    monkeypatch.setattr(nerun, "migrate_from_manifest", lambda **k: calls.append("migrate"))
    monkeypatch.setattr(nerun, "run_create_events", lambda **k: calls.append("create"))
    (tmp_path / "beh").mkdir(); (tmp_path / "bids").mkdir()
    # no --manifest and reconcile produced a manifest that needs review -> stop after reconcile
    with pytest.raises(SystemExit):
        nerun.run(behavioral_dir=tmp_path / "beh", bids_dir=tmp_path / "bids", manifest=None, survey_root=None)
    assert calls == ["reconcile"]  # did NOT proceed to migrate/create

def test_run_full_pipeline_with_reviewed_manifest(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(nerun, "migrate_from_manifest", lambda **k: calls.append("migrate"))
    monkeypatch.setattr(nerun, "migrate_out_scanner", lambda **k: calls.append("out"))
    monkeypatch.setattr(nerun, "migrate_survey", lambda **k: calls.append("survey"))
    monkeypatch.setattr(nerun, "run_create_events", lambda **k: calls.append("create"))
    monkeypatch.setattr(nerun, "run_qc", lambda **k: calls.append("qc"))
    monkeypatch.setattr(nerun, "run_trim", lambda **k: calls.append("trim"))
    m = tmp_path / "reviewed.tsv"; m.write_text("subject\tsession\tstatus\ns03\t01\tresolved\n")
    (tmp_path / "beh").mkdir(); (tmp_path / "bids").mkdir()
    nerun.run(behavioral_dir=tmp_path / "beh", bids_dir=tmp_path / "bids", manifest=m, survey_root=None)
    assert calls == ["migrate", "create", "qc", "trim"]  # survey skipped (no survey_root)
