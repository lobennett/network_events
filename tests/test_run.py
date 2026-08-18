"""The orchestrator no longer reconciles or migrates in-scanner data."""
import pytest

from network_events import run as run_mod


def _bids(tmp_path, subjects=("s03",)):
    for sub in subjects:
        (tmp_path / "sourcedata" / f"sub-{sub}" / "ses-01" / "beh").mkdir(parents=True)
    return tmp_path


def test_subjects_in_reads_the_cleaned_tree(tmp_path):
    bids = _bids(tmp_path, ("s03", "s10"))
    assert run_mod.subjects_in(bids / "sourcedata") == {"s03", "s10"}


def test_run_refuses_when_sourcedata_is_empty(tmp_path):
    (tmp_path / "sourcedata").mkdir()
    with pytest.raises(SystemExit, match="behavior-clean"):
        run_mod.run(behavioral_dir=tmp_path, bids_dir=tmp_path)


def test_run_points_create_and_qc_at_sourcedata(tmp_path, monkeypatch):
    bids = _bids(tmp_path)
    seen = {}
    monkeypatch.setattr(run_mod, "migrate_out_scanner", lambda **k: seen.setdefault("mig", k))
    monkeypatch.setattr(run_mod, "run_create_events", lambda **k: seen.setdefault("create", k))
    monkeypatch.setattr(run_mod, "run_qc", lambda **k: seen.setdefault("qc", k))
    monkeypatch.setattr(run_mod, "run_trim", lambda **k: seen.setdefault("trim", k))
    run_mod.run(behavioral_dir=tmp_path, bids_dir=bids)
    assert seen["create"]["behavioral_dir"] == bids / "sourcedata"
    assert seen["qc"]["behavioral_dir"] == bids / "sourcedata"
    assert seen["mig"]["subjects"] == {"s03"}
    assert "trim" in seen


def test_run_skips_survey_when_not_given(tmp_path, monkeypatch):
    bids = _bids(tmp_path)
    called = []
    monkeypatch.setattr(run_mod, "migrate_out_scanner", lambda **k: None)
    monkeypatch.setattr(run_mod, "migrate_survey", lambda **k: called.append(k))
    for fn in ("run_create_events", "run_qc", "run_trim"):
        monkeypatch.setattr(run_mod, fn, lambda **k: None)
    run_mod.run(behavioral_dir=tmp_path, bids_dir=bids)
    assert called == []
