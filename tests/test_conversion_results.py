"""Structured results keep failed behavioral conversions visible."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from network_events.identity import RunIdentity
from tests.test_nonmonotonic import _make_flanker_csv
from tests.helpers import audited_create, write_bold


def expected_events_path(bids: Path, identity: RunIdentity) -> Path:
    return (
        bids / identity.subject / identity.session / "func"
        / f"{identity.subject}_{identity.session}_task-{identity.task}_run-{identity.run}_events.tsv"
    )


def _expected_qc_path(bids: Path, identity: RunIdentity) -> Path:
    return (
        bids / "sourcedata" / "events_qc" / identity.subject / identity.session
        / f"{identity.subject}_{identity.session}_task-{identity.task}_run-{identity.run}_desc-truncation.json"
    )


def _pair(tmp_path: Path, *, valid: bool) -> tuple[Path, tuple[RunIdentity, Path]]:
    bids = tmp_path / "bids"
    identity = RunIdentity("sub-s01", "ses-01", "flanker", "1")
    behavior = (
        bids / "sourcedata" / "behavioral" / identity.subject / identity.session / "beh"
        / f"{identity.subject}_{identity.session}_task-{identity.task}_run-{identity.run}_beh.csv"
    )
    behavior.parent.mkdir(parents=True)
    write_bold(bids / identity.subject / identity.session / "func"
               / "sub-s01_ses-01_task-flanker_run-1_bold.nii.gz")
    if valid:
        _make_flanker_csv(behavior, n_trials=3)
    else:
        behavior.write_text("trial_id\ntime_elapsed\ntest_trial\n20000\n")
    return bids, (identity, behavior)


def invalid_behavior_pair(tmp_path: Path) -> tuple[Path, tuple[RunIdentity, Path]]:
    return _pair(tmp_path, valid=False)


def valid_behavior_pair(tmp_path: Path) -> tuple[Path, tuple[RunIdentity, Path]]:
    return _pair(tmp_path, valid=True)


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def test_conversion_failure_writes_evidence_not_empty_events(tmp_path):
    bids, pair = invalid_behavior_pair(tmp_path)
    events_path = expected_events_path(bids, pair[0])
    qc_path = _expected_qc_path(bids, pair[0])
    events_path.write_text("stale events\n")
    qc_path.parent.mkdir(parents=True)
    qc_path.write_text("{}")

    results = audited_create(bids)

    assert results[0].status == "failed"
    assert results[0].events_file is None
    assert results[0].qc_file is None
    assert results[0].error is not None
    assert not events_path.exists()
    assert not qc_path.exists()
    rows = read_tsv(bids / "sourcedata/events_qc/conversion_errors.tsv")
    assert rows == [{
        "subject": "sub-s01",
        "session": "ses-01",
        "task": "flanker",
        "run": "1",
        "source_path": str(pair[1]),
        "exception_class": "KeyError",
        "message": "'exp_id'",
    }]


def test_success_is_atomic_and_writes_truncation_evidence(tmp_path):
    bids, pair = valid_behavior_pair(tmp_path)
    result, = audited_create(bids)

    assert result.status == "created"
    assert result.events_file == expected_events_path(bids, pair[0])
    assert result.events_file.is_file()
    assert result.qc_file == _expected_qc_path(bids, pair[0])
    assert result.qc_file.is_file()
    assert not result.events_file.with_suffix(result.events_file.suffix + ".tmp").exists()
    assert not result.qc_file.with_suffix(result.qc_file.suffix + ".tmp").exists()
    sidecar = json.loads(result.qc_file.read_text())
    assert sidecar["NTestTrialsExpected"] == 3
