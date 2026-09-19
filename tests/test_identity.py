"""Canonical behavioral/BOLD identity audit contracts."""
from __future__ import annotations

import csv
from pathlib import Path

from network_events.identity import audit_dataset


def dataset_with_bold(tmp_path: Path, *, task: str, echoes: tuple[int, ...] = ()):
    bids = tmp_path / "bids"
    behavior = bids / "sourcedata" / "behavioral"
    func = bids / "sub-s01" / "ses-01" / "func"
    behavior.mkdir(parents=True)
    func.mkdir(parents=True)
    echo_suffixes = tuple(f"_echo-{echo}" for echo in echoes) or ("",)
    for suffix in echo_suffixes:
        (func / f"sub-s01_ses-01_task-{task}_run-1{suffix}_bold.nii.gz").touch()
    return bids, behavior


def write_behavior(behavior: Path, name: str) -> Path:
    path = behavior / "sub-s01" / "ses-01" / "beh" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("trial_id\nexample\n")
    return path


def write_exceptions(behavior: Path, rows: list[dict[str, str]]) -> None:
    fields = [
        "subject", "session", "task", "run", "reason", "detail", "reviewed_by", "reviewed_at"
    ]
    with (behavior / "behavioral_exceptions.tsv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def test_audit_groups_three_echoes_as_one_logical_bold(tmp_path):
    bids, behavior = dataset_with_bold(tmp_path, task="nBack", echoes=(1, 2, 3))
    write_behavior(behavior, "sub-s01_ses-01_task-nBack_run-1_beh.csv")
    result = audit_dataset(bids, behavior)
    assert len(result.pairs) == 1
    assert result.errors == ()


def test_audit_requires_behavior_or_reviewed_exception(tmp_path):
    bids, behavior = dataset_with_bold(tmp_path, task="nBack", echoes=(1, 2, 3))
    result = audit_dataset(bids, behavior)
    assert result.errors == (
        "sub-s01/ses-01/task-nBack/run-1: missing behavior and exception",
    )


def test_rest_requires_no_behavior(tmp_path):
    bids, behavior = dataset_with_bold(tmp_path, task="rest", echoes=(1, 2, 3))
    assert audit_dataset(bids, behavior).errors == ()


def test_audit_rejects_unparseable_behavior_files(tmp_path):
    bids, behavior = dataset_with_bold(tmp_path, task="nBack")
    bad = behavior / "sub-s01" / "ses-01" / "beh" / "notes.csv"
    bad.parent.mkdir(parents=True)
    bad.write_text("notes\n")
    result = audit_dataset(bids, behavior)
    assert any("unparseable behavior" in error for error in result.errors)


def test_audit_rejects_behavior_outside_canonical_directory_or_with_mismatched_entities(tmp_path):
    bids, behavior = dataset_with_bold(tmp_path, task="nBack")
    misplaced = behavior / "other" / "sub-s01_ses-01_task-nBack_run-1_beh.csv"
    misplaced.parent.mkdir()
    misplaced.write_text("trial_id\nexample\n")
    mismatch = behavior / "sub-s02" / "ses-01" / "beh" / "sub-s01_ses-01_task-nBack_run-1_beh.csv"
    mismatch.parent.mkdir(parents=True)
    mismatch.write_text("trial_id\nexample\n")
    result = audit_dataset(bids, behavior)
    assert any("noncanonical behavior path" in error for error in result.errors)
    assert result.pairs == ()


def test_duplicate_behavior_is_withheld_from_pairs(tmp_path):
    bids, behavior = dataset_with_bold(tmp_path, task="nBack")
    write_behavior(behavior, "sub-s01_ses-01_task-nBack_run-1_beh.csv")
    duplicate = behavior / "sub-s01" / "ses-01" / "beh-alt" / "sub-s01_ses-01_task-nBack_run-1_beh.csv"
    duplicate.parent.mkdir()
    duplicate.write_text("trial_id\nexample\n")
    result = audit_dataset(bids, behavior)
    assert any("duplicate behavior" in error for error in result.errors)
    assert result.pairs == ()


def test_audit_rejects_orphan_behavior_and_behavior_with_exception(tmp_path):
    bids, behavior = dataset_with_bold(tmp_path, task="nBack")
    write_behavior(behavior, "sub-s01_ses-01_task-nBack_run-1_beh.csv")
    write_behavior(behavior, "sub-s01_ses-01_task-other_run-1_beh.csv")
    write_exceptions(behavior, [{
        "subject": "sub-s01", "session": "ses-01", "task": "nBack", "run": "1",
        "reason": "lost", "detail": "unrecoverable", "reviewed_by": "reviewer", "reviewed_at": "2026-09-18",
    }])
    result = audit_dataset(bids, behavior)
    assert any("orphan behavior" in error for error in result.errors)
    assert any("both behavior and exception" in error for error in result.errors)


def test_audit_accepts_reviewed_exception_and_rejects_malformed_rows(tmp_path):
    bids, behavior = dataset_with_bold(tmp_path, task="nBack")
    write_exceptions(behavior, [{
        "subject": "sub-s01", "session": "ses-01", "task": "nBack", "run": "1",
        "reason": "lost", "detail": "unrecoverable", "reviewed_by": "reviewer", "reviewed_at": "2026-09-18",
    }])
    result = audit_dataset(bids, behavior)
    assert result.errors == ()
    assert len(result.exceptions) == 1

    (behavior / "behavioral_exceptions.tsv").write_text("subject\tsession\ttask\trun\nsub-s01\tses-01\tnBack\t1\n")
    result = audit_dataset(bids, behavior)
    assert any("missing required columns" in error for error in result.errors)


def test_audit_rejects_exception_rows_with_non_bids_identity_labels(tmp_path):
    bids, behavior = dataset_with_bold(tmp_path, task="nBack")
    write_exceptions(behavior, [{
        "subject": "s01", "session": "01", "task": "nBack", "run": "1",
        "reason": "lost", "detail": "unrecoverable", "reviewed_by": "reviewer", "reviewed_at": "2026-09-18",
    }])
    result = audit_dataset(bids, behavior)
    assert any("malformed exception row" in error for error in result.errors)


def test_duplicate_exception_is_withheld_from_exceptions(tmp_path):
    bids, behavior = dataset_with_bold(tmp_path, task="nBack")
    row = {
        "subject": "sub-s01", "session": "ses-01", "task": "nBack", "run": "1",
        "reason": "lost", "detail": "unrecoverable", "reviewed_by": "reviewer", "reviewed_at": "2026-09-18",
    }
    write_exceptions(behavior, [row, row])
    result = audit_dataset(bids, behavior)
    assert any("duplicate exception" in error for error in result.errors)
    assert result.exceptions == ()


def test_audit_rejects_non_alphanumeric_or_empty_entity_labels(tmp_path):
    bids, behavior = dataset_with_bold(tmp_path, task="nBack")
    write_behavior(behavior, "sub-s01_ses-01_task-n Back_run-1_beh.csv")
    write_behavior(behavior, "sub-s01_ses-01_task-nBack_run-_beh.csv")
    result = audit_dataset(bids, behavior)
    assert sum("unparseable behavior" in error for error in result.errors) == 2
