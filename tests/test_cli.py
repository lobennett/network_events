import json
import pytest
from network_events import cli

def test_cli_routes_run(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "_run", lambda a: seen.update(cmd="run", bids=a.bids_dir))
    cli.main(["run", "--behavioral-dir", "/b", "--bids-dir", "/x"])
    assert seen["cmd"] == "run" and seen["bids"] == "/x"

def test_cli_requires_subcommand():
    with pytest.raises(SystemExit):
        cli.main([])

def test_cli_routes_reconcile(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "_reconcile",
                        lambda a: seen.update(bids=a.bids_dir, raw=a.raw_dir,
                                              out=a.output, notes=a.scan_notes))
    cli.main(["reconcile", "--bids-dir", "/x", "--raw-dir", "/r", "--output", "/o"])
    assert seen == {"bids": "/x", "raw": "/r", "out": "/o", "notes": None}

def test_cli_routes_migrate(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "_migrate",
                        lambda a: seen.update(manifest=a.manifest, out=a.output_dir, strict=a.strict))
    cli.main(["migrate", "--manifest", "/m", "--output-dir", "/o"])
    assert seen == {"manifest": "/m", "out": "/o", "strict": False}

def test_cli_routes_migrate_archive(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "_migrate_archive",
                        lambda a: seen.update(raw=a.raw_dir, out=a.output_dir, manifests=a.manifest))
    cli.main(["migrate-archive", "--raw-dir", "/r", "--output-dir", "/o",
              "--manifest", "/m1", "--manifest", "/m2"])
    assert seen == {"raw": "/r", "out": "/o", "manifests": ["/m1", "/m2"]}

def test_cli_routes_migrate_survey(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "_migrate_survey",
                        lambda a: seen.update(survey=a.survey_root, out=a.output_dir, manifests=a.manifest))
    cli.main(["migrate-survey", "--survey-root", "/s", "--output-dir", "/o", "--manifest", "/m1"])
    assert seen == {"survey": "/s", "out": "/o", "manifests": ["/m1"]}

def test_cli_routes_create(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "_create", lambda a: seen.update(src=a.sourcedata, bids=a.bids_dir))
    cli.main(["create", "--sourcedata", "/s", "--bids-dir", "/b"])
    assert seen == {"src": "/s", "bids": "/b"}

def test_cli_routes_qc(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "_qc", lambda a: seen.update(src=a.sourcedata, bids=a.bids_dir))
    cli.main(["qc", "--sourcedata", "/s", "--bids-dir", "/b"])
    assert seen == {"src": "/s", "bids": "/b"}

def test_cli_routes_trim(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "_trim", lambda a: seen.update(bids=a.bids_dir))
    cli.main(["trim", "--bids-dir", "/b"])
    assert seen == {"bids": "/b"}

def _write_manifest(path):
    path.write_text("subject\taction\ns03\tcopy\n")

def test_cli_migrate_archive_copies_and_writes_report(tmp_path):
    # End-to-end through the real handler: practice csv copied + provenance report written.
    raw = tmp_path / "raw"; (raw / "s03" / "ses-1" / "practice").mkdir(parents=True)
    (raw / "s03" / "ses-1" / "practice" / "run1.csv").write_text("a,b\n1,2\n")
    out = tmp_path / "sourcedata"
    manifest = tmp_path / "m.tsv"; _write_manifest(manifest)
    cli.main(["migrate-archive", "--raw-dir", str(raw), "--output-dir", str(out),
              "--manifest", str(manifest)])
    assert list((out / "out_scanner_behavior").rglob("*.csv")), "practice csv not copied"
    report = out / "archive_migration_report.json"
    assert report.exists()
    payload = json.loads(report.read_text())
    assert payload["out_scanner_files"] == 1
    assert payload["subjects"] == ["s03"]
    assert "generated" in payload

def test_cli_migrate_survey_writes_report(tmp_path):
    survey = tmp_path / "survey"
    src = survey / "prescan_surveys" / "raw" / "s03"; src.mkdir(parents=True)
    (src / "q.json").write_text("{}")
    out = tmp_path / "sourcedata"
    manifest = tmp_path / "m.tsv"; _write_manifest(manifest)
    cli.main(["migrate-survey", "--survey-root", str(survey), "--output-dir", str(out),
              "--manifest", str(manifest)])
    report = out / "survey_migration_report.json"
    assert report.exists()
    payload = json.loads(report.read_text())
    assert payload["survey_files"] == 1
    assert payload["subjects"] == ["s03"]
