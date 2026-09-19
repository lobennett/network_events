"""Generate BIDS _events.tsv files from behavioral CSVs.

:func:`create_events_df` applies three timing transformations, all unconditional
data-integrity fixes rather than policy (see README.md for the full reasoning):

1. shift onsets by the trimmed dummy volumes, per-run from the BOLD sidecar;
2. truncate at the first backward ``time_elapsed`` step, past which behavioural time
   no longer maps to the scanner;
3. clip to the acquired scan length, so an aborted run cannot contribute trials that
   were never imaged.

Both truncations drop trials and neither decides whether the survivor is usable --
that is ``network_qa``'s call. :func:`create_events` writes the cost of each to
``sourcedata/events_qc/<sub>/<ses>/..._desc-truncation.json`` for it to threshold on.
"""
import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

import nibabel as nib
import numpy as np
import pandas as pd

from network_events.config import N_DUMMY, TR_SECONDS
from network_events.identity import RunIdentity, discover_bold_groups
from network_events.utils import (
    get_neg_rt_correction,
    cal_time_elapsed,
    add_choice_acc,
    add_cols,
    find_nonmonotonic_cut,
    response_time_and_junk,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class EventResult:
    """The output (or recorded failure) for one audited behavioral run."""

    identity: RunIdentity
    status: Literal["created", "failed"]
    behavior_file: Path
    events_file: Path | None
    qc_file: Path | None
    error: str | None

# --- Rename cells (trial_id label standardization) ---

_RENAME_CELLS_LOOKUP = {
    "stop_signal_single_task_network__fmri": {"fixation": "test_fixation", "practice-no-stop-feedback": "break"},
    "shape_matching_single_task_network__fmri": {"fixation": "test_fixation", "mask": "test_mask", "practice-no-stop-feedback": "break"},
    "n_back_single_task_network__fmri": {"practice-no-stop-feedback": "break", "fixation": "test_fixation"},
    "go_nogo_single_task_network__fmri": {"update_correct_response": "test_fixation", "feedback_block": "break"},
    "spatial_task_switching_single_task_network__fmri": {"feedback_block": "break", "practice_cue": "blank_screen"},
    "cued_task_switching_single_task_network__fmri": {"practice-stop-feedback": "break"},
    "directed_forgetting_single_task_network__fmri": {"fixation": "test_fixation", "stim": "test_stim", "cue": "test_cue", "test_feedback": "break"},
    "flanker_single_task_network__fmri": {"practice-no-stop-feedback": "break"},
    "directed_forgetting_with_flanker__fmri": {"test_start_fixation": "test_fixation", "test_feedback": "break"},
    "stop_signal_with_directed_forgetting__fmri": {"ITI_fixation": "test_fixation", "stim": "test_stim", "cue": "test_cue", "fixation": "test_fixation", "feedback_block": "break"},
    "stop_signal_with_flanker__fmri": {"feedback_block": "break", "fixation": "test_fixation"},
    "cued_task_switching_with_directed_forgetting__fmri": {"test_start_fixation": "test_fixation", "test_feedback": "break"},
    "spatial_task_switching_with_cued_task_switching__fmri": {"test_cue_block": "test_cue", "fixation": "test_fixation", "feedback_block": "break"},
    "flanker_with_shape_matching__fmri": {"feedback_block": "break"},
    "flanker_with_cued_task_switching__fmri": {"practice-stop-feedback": "break"},
    "flanker_with_cued_task_switching": {"practice-stop-feedback": "break"},
    "n_back_with_shape_matching__fmri": {"feedback_block": "break", "fixation": "test_fixation"},
    "shape_matching_with_spatial_task_switching__fmri": {"feedback_block": "break", "fixation": "test_fixation"},
    "shape_matching_with_spatial_task_switching": {"feedback_block": "break", "fixation": "test_fixation"},
    "shape_matching_with_cued_task_switching__fmri": {"fixation": "test_fixation", "cue": "test_cue", "feedback_block": "break"},
    "shape_matching_with_cued_task_switching": {"fixation": "test_fixation", "cue": "test_cue", "feedback_block": "break"},
    "n_back_with_spatial_task_switching__fmri": {"feedback_block": "break", "fixation": "test_fixation"},
}


# Cued-task-switching exp_ids (both the ``__fmri`` spelling and the bare alias)
# whose ``test_cue`` row shows the upcoming task cue and admits no response, so
# any raw ``correct_response`` on it is meaningless.
_CUE_RESPONSE_PLACEHOLDER_EXP_IDS = frozenset({
    "cued_task_switching_single_task_network__fmri",
    "cued_task_switching_with_directed_forgetting__fmri",
    "spatial_task_switching_with_cued_task_switching__fmri",
    "flanker_with_cued_task_switching__fmri",
    "flanker_with_cued_task_switching",
    "shape_matching_with_cued_task_switching__fmri",
    "shape_matching_with_cued_task_switching",
})

# Rest/feedback rows must not inherit a stimulus-trial condition; dedicated
# nontrial regressors can still select them by trial_id.
_BREAK_TRIAL_IDS = ("break", "break_with_performance_feedback")


def _rename_cells(df: pd.DataFrame, exp_id: str) -> pd.DataFrame:
    change = _RENAME_CELLS_LOOKUP.get(exp_id)
    if change is None:
        log.warning("No rename_cells mapping for exp_id: %s", exp_id)
        return df
    for key, value in change.items():
        df["trial_id"] = df["trial_id"].replace(key, value)
    if exp_id in _CUE_RESPONSE_PLACEHOLDER_EXP_IDS:
        df["correct_response"] = df["correct_response"].astype(object)
        df.loc[df["trial_id"] == "test_cue", "correct_response"] = "n/a"
    return df


DUMMY_OFFSET_S = N_DUMMY * TR_SECONDS  # Default only for pure dataframe transformations.


class TimingEvidenceError(ValueError):
    """The run cannot be aligned without complete, consistent BOLD timing evidence."""


def _positive_number(value: object) -> bool:
    return (
        isinstance(value, (int, float)) and not isinstance(value, bool)
        and math.isfinite(value) and value > 0
    )


def _read_run_timing(files: tuple[Path, ...]) -> tuple[float, float]:
    """Read every physical image and its sidecar; echoes must agree on timing.

    NIfTI volume counts describe the acquired (already trimmed) run. The sidecar
    must explicitly record zero discarded volumes for an untrimmed image.
    """
    if not files:
        raise TimingEvidenceError("no BOLD images available for this run")
    reference: tuple[int, float, int] | None = None
    for path in files:
        sidecar = path.with_name(path.name.split(".nii")[0] + ".json")
        try:
            meta = json.loads(sidecar.read_text())
            if not isinstance(meta, dict):
                raise ValueError("sidecar must contain a JSON object")
            discarded = meta.get("NumberOfVolumesDiscardedByUser")
            tr = meta.get("RepetitionTime")
            if type(discarded) is not int or discarded < 0:
                raise ValueError("NumberOfVolumesDiscardedByUser must be a nonnegative integer")
            if not _positive_number(tr):
                raise ValueError("RepetitionTime must be a finite positive number")
        except (OSError, ValueError) as exc:
            raise TimingEvidenceError(f"{sidecar}: invalid or unreadable timing sidecar: {exc}") from exc
        try:
            img = nib.load(path)
            if len(img.shape) != 4 or any(n <= 0 for n in img.shape):
                raise ValueError("BOLD must be a nonempty 4-D image")
            volumes = img.shape[3]
            header_tr = float(img.header.get_zooms()[3])
            unit = img.header.get_xyzt_units()[1]
            # Preserve seconds for older headers with unspecified units.
            scale = {"unknown": 1, "sec": 1, "msec": 0.001, "usec": 0.000001}.get(unit)
            if scale is None:
                raise ValueError(f"unsupported NIfTI temporal units: {unit}")
            header_tr *= scale
            if not _positive_number(header_tr):
                raise ValueError("NIfTI TR must be a finite positive number")
            if not math.isclose(header_tr, tr, rel_tol=1e-6, abs_tol=1e-6):
                raise ValueError("NIfTI TR conflicts with sidecar RepetitionTime")
            # Read the last volume as well as the header, detecting missing/truncated data.
            np.asanyarray(img.dataobj[..., -1])
        except (OSError, ValueError, EOFError, nib.filebasedimages.ImageFileError) as exc:
            raise TimingEvidenceError(f"{path}: invalid or unreadable BOLD duration: {exc}") from exc
        timing = (discarded, float(tr), volumes)
        if reference is not None and timing != reference:
            raise TimingEvidenceError(f"{path}: conflicting timing evidence across BOLD echoes")
        reference = timing
    discarded, tr, volumes = reference
    # Use the common header TR for acquired duration, as in the original timing transform.
    duration = volumes * header_tr
    offset = discarded * tr
    if not math.isfinite(duration) or not math.isfinite(offset):
        raise TimingEvidenceError("BOLD duration and onset shift must be finite")
    return offset, duration


def _scan_overrun(df: pd.DataFrame, scan_s: float | None):
    """``(n_kept, n_total, n_test_dropped, n_test_total)`` for scan clipping."""
    n_total = len(df)
    n_test_total = int((df["trial_id"] == "test_trial").sum())
    if scan_s is None:
        return n_total, n_total, 0, n_test_total
    keep = df["onset"] < scan_s
    n_test_dropped = int((df.loc[~keep, "trial_id"] == "test_trial").sum())
    return int(keep.sum()), n_total, n_test_dropped, n_test_total


def _set_default_event_cols(df: pd.DataFrame, offset_s: float = DUMMY_OFFSET_S) -> pd.DataFrame:
    df = df[df.time_elapsed >= 0]
    df = df.rename(columns={"time_elapsed": "onset", "choice_acc": "acc", "stim_duration": "duration", "rt": "response_time"})
    df["onset"] = df["onset"] / 1000
    df["duration"] = df["duration"] / 1000
    df["response_time"] = df["response_time"] / 1000
    df["response_time"] = df["response_time"].replace(-0.001, np.nan)

    # Adjust onsets for volumes the imaging pipeline discarded (per-run, from the
    # sidecar).
    df["onset"] = df["onset"] - offset_s
    df = df[df["onset"] >= 0]
    first_columns = ["onset", "duration", "response_time", "trial_id", "trial_type", "key_press", "correct_response"]
    new_column_order = first_columns + [col for col in df.columns if col not in first_columns]
    df = df[new_column_order]
    return df


def _flagged_feedback(text_content: object) -> bool:
    if not isinstance(text_content, str):
        return False
    keywords = ["accuracy", "slowly", "respond", "response"]
    return any(keyword in text_content.lower() for keyword in keywords)


def _get_rows_with_feedback(df: pd.DataFrame, original_df: pd.DataFrame):
    feedback_block_rows = original_df[original_df["trial_id"] == "test_feedback"]
    if len(feedback_block_rows) == 0:
        feedback_block_rows = original_df[original_df["trial_id"] == "feedback_block"]
    if len(feedback_block_rows) == 0 and "stimulus" in original_df.columns:
        stimulus_col = original_df["stimulus"].astype(str)
        feedback_block_rows = original_df[stimulus_col.str.contains("completed", na=False)]
    indices_to_change = []
    for index, row in feedback_block_rows.iterrows():
        stimulus = row.get("stimulus")
        if _flagged_feedback(stimulus):
            indices_to_change.append(index)
    return feedback_block_rows, indices_to_change


def _build_events_df(filename: Path, short_name: str,
                     offset_s: float = DUMMY_OFFSET_S) -> pd.DataFrame:
    """Build the events dataframe up to (but excluding) non-monotonic truncation."""
    original_df = pd.read_csv(filename)
    exp_id = original_df["exp_id"][0]
    log.info("Processing %s for %s", filename, exp_id)
    df = original_df.copy()
    df = get_neg_rt_correction(df)
    df = cal_time_elapsed(df)
    df = add_choice_acc(df)
    df = add_cols(df, exp_id)
    # Standardize trial_id first: the task cleanups key off canonical ids
    # (test_fixation, break), which only exist after this rename.
    df = _rename_cells(df, exp_id)
    df = response_time_and_junk(df, short_name)
    df = _set_default_event_cols(df, offset_s)

    # cuedTSWFlanker: switch factors are recorded on test_cue rows; test_trial
    # rows may carry only flanker_condition. Fill missing switch fields from
    # the most recent preceding cue so the GLM can cross them with the separate
    # flanker factor without overwriting values already present on the trial.
    if "flanker_with_cued_task_switching" in exp_id:
        is_cue = df["trial_id"] == "test_cue"
        is_trial = df["trial_id"] == "test_trial"
        for col in ("trial_type", "cue_condition", "task_condition"):
            if col not in df.columns:
                continue
            carried = df[col].where(is_cue).ffill()
            fill = is_trial & df[col].isna()
            df.loc[fill, col] = carried[fill]

    # nBackWSpatialTS: raw n_back_condition mixes case (Mismatch vs mismatch),
    # so the composite trial_type does too. Normalize to lowercase on test_trial
    # rows for consistent cells. str.lower() leaves genuine NaN as NaN (it does
    # not create the string "nan").
    if "n_back_with_spatial_task_switching" in exp_id:
        is_trial = df["trial_id"] == "test_trial"
        df.loc[is_trial, "trial_type"] = df.loc[is_trial, "trial_type"].str.lower()

    # Convert all columns to object dtype before filling NaN with "n/a"
    # (newer pandas refuses to fill float columns with string values)
    for col in df.columns:
        if df[col].isna().any():
            df[col] = df[col].astype(object)
    df.fillna("n/a", inplace=True)

    # Fix spatialTS "na" trial_type
    if "spatial_task_switching" in exp_id:
        df.loc[(df["trial_id"] == "test_trial") & (df["trial_type"] == "na"), "trial_type"] = "tn/a_cn/a"
        df.loc[(df["trial_id"] == "test_trial") & (df["trial_type"] == "tn/a_cn/a"), "task_switch"] = "tn/a_cn/a"

    # Detect performance feedback blocks (only for rows still in df after filtering)
    feedback_block_rows, indices_to_change = _get_rows_with_feedback(df, original_df)
    for index in indices_to_change:
        if index in df.index:
            df.loc[index, "trial_id"] = "break_with_performance_feedback"

    # A break shows no stimulus to classify, so any condition it inherited is
    # provenance only; the source column keeps it, trial_type must not.
    df.loc[df["trial_id"].isin(_BREAK_TRIAL_IDS), "trial_type"] = "n/a"

    return df


def _nonmonotonic_truncation(df: pd.DataFrame):
    """Locate the non-monotonic-onset truncation point and its test-trial cost.

    Returns ``(cut, n_test_total, n_test_dropped)`` where ``cut`` is the
    positional index of the first backward onset step (or ``None`` if monotonic).
    """
    cut = find_nonmonotonic_cut(df["onset"])
    n_test_total = int((df["trial_id"] == "test_trial").sum())
    if cut is None:
        return None, n_test_total, 0
    n_test_dropped = int((df["trial_id"].iloc[cut:] == "test_trial").sum())
    return cut, n_test_total, n_test_dropped


def create_events_df(filename: Path, short_name: str,
                     offset_s: float = DUMMY_OFFSET_S,
                     scan_s: float | None = None) -> pd.DataFrame:
    """Create a BIDS events dataframe from a behavioral CSV.

    Two truncations, both timing-driven:

    * the first non-monotonic onset (a backward ``time_elapsed`` clock glitch) —
      trials after the jump have unreliable absolute timing, so the clean monotonic
      prefix is kept;
    * ``scan_s``, the acquired scan length, when given. A run the scanner aborted
      leaves the behavioural session running, so the CSV describes trials that were
      never imaged; keeping them puts regressors past the end of the timeseries.

    Trial-retention metrics for both are exposed by :func:`events_truncation_stats`
    for ``network_qa`` to act on; this function makes no exclusion decision.
    """
    df = _build_events_df(filename, short_name, offset_s)
    cut, n_total, n_dropped = _nonmonotonic_truncation(df)
    if cut is not None:
        log.warning(
            "Non-monotonic onset in %s at row %d — truncating %d trailing rows "
            "(%d/%d test trials dropped)",
            short_name,
            cut,
            len(df) - cut,
            n_dropped,
            n_total,
        )
        df = df.iloc[:cut].reset_index(drop=True)
    if scan_s is not None:
        n_kept, n_rows, n_test_dropped, n_test = _scan_overrun(df, scan_s)
        if n_kept < n_rows:
            log.warning(
                "%s events run past the end of the scan (%.1fs) — dropping %d rows "
                "(%d/%d test trials)",
                short_name, scan_s, n_rows - n_kept, n_test_dropped, n_test,
            )
            df = df[df["onset"] < scan_s].reset_index(drop=True)
    return df


def events_truncation_stats(filename: Path, short_name: str,
                            offset_s: float = DUMMY_OFFSET_S,
                            scan_s: float | None = None) -> dict:
    """Truncation stats for a behavioral CSV (no side effects).

    Returns the non-monotonic-onset metrics plus, when ``scan_s`` is given, what
    clipping to the acquired scan costs (``scan_*`` keys). These are the
    trial-retention metrics surfaced to ``network_qa``: no >50% (or any other)
    exclusion threshold is applied here.
    """
    df = _build_events_df(filename, short_name, offset_s)
    cut, n_total, n_dropped = _nonmonotonic_truncation(df)
    frac = (n_dropped / n_total) if n_total else 0.0
    if cut is not None:
        df = df.iloc[:cut]
    n_kept, n_rows, n_test_dropped, n_test = _scan_overrun(df, scan_s)
    return {
        "cut": cut,
        "n_test_total": n_total,
        "n_test_dropped": n_dropped,
        "fraction_test_dropped": frac,
        "scan_duration_s": scan_s,
        "scan_rows_dropped": n_rows - n_kept,
        "scan_test_dropped": n_test_dropped,
        "fraction_scan_test_dropped": (n_test_dropped / n_test) if n_test else 0.0,
    }


def truncation_sidecar_path(
    bids_dir: Path, sub: str, ses: str, task: str, run: int | str
) -> Path:
    """Resolve the truncation-QC sidecar path for a given scan.

    The sidecar lives OUTSIDE the BIDS ``func/`` tree, under
    ``sourcedata/events_qc/<sub>/<ses>/`` with a non-reserved
    ``_desc-truncation.json`` name. This keeps it clear of the BIDS-reserved
    ``_events.json`` filename (which bids-validator interprets as an
    events-column description and rejects for this content), while remaining a
    validator-ignored ``sourcedata/`` file.
    """
    return (
        bids_dir
        / "sourcedata"
        / "events_qc"
        / sub
        / ses
        / f"{sub}_{ses}_task-{task}_run-{run}_desc-truncation.json"
    )


def _write_truncation_sidecar(sidecar_path: Path, tstats: dict) -> Path:
    """Write both truncations' trial cost to the QC sidecar.

    The machine-readable seam ``network_qa`` reads to apply its own threshold; none is
    applied here. ``FractionTestTrialsDropped`` is the non-monotonic cut, the ``Scan*``
    keys the clip to the acquired scan. Lives under ``sourcedata/events_qc/`` rather than
    ``func/`` so bids-validator does not reject it.
    """
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    n_total = tstats["n_test_total"]
    n_dropped = tstats["n_test_dropped"]
    sidecar = {
        "NTestTrialsExpected": n_total,
        "NTestTrialsRetained": n_total - n_dropped,
        "FractionTestTrialsDropped": tstats["fraction_test_dropped"],
        "ScanDurationSeconds": tstats["scan_duration_s"],
        "NScanTestTrialsDropped": tstats["scan_test_dropped"],
        "FractionScanTestTrialsDropped": tstats["fraction_scan_test_dropped"],
    }
    tmp_path = sidecar_path.with_suffix(sidecar_path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as stream:
        json.dump(sidecar, stream, indent=2)
        stream.flush()
    tmp_path.replace(sidecar_path)
    return sidecar_path


def _events_path(bids_dir: Path, identity: RunIdentity) -> Path:
    return (
        bids_dir / identity.subject / identity.session / "func"
        / f"{identity.subject}_{identity.session}_task-{identity.task}_run-{identity.run}_events.tsv"
    )


def _write_events(events_path: Path, df: pd.DataFrame) -> Path:
    """Atomically replace one events TSV after its complete contents are flushed."""
    events_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = events_path.with_suffix(events_path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8", newline="") as stream:
        df.to_csv(stream, sep="\t", index=False, na_rep="n/a")
        stream.flush()
    tmp_path.replace(events_path)
    return events_path


def _write_conversion_errors(bids_dir: Path, errors: list[dict[str, str]]) -> Path:
    """Publish one run-level conversion error table after all pairs were attempted."""
    error_path = bids_dir / "sourcedata" / "events_qc" / "conversion_errors.tsv"
    error_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = error_path.with_suffix(error_path.suffix + ".tmp")
    columns = (
        "subject", "session", "task", "run", "source_path", "exception_class", "message"
    )
    with tmp_path.open("w", encoding="utf-8", newline="") as stream:
        import csv

        writer = csv.DictWriter(stream, fieldnames=columns, delimiter="\t")
        writer.writeheader()
        writer.writerows(errors)
        stream.flush()
    tmp_path.replace(error_path)
    return error_path


def create_events(
    bids_dir: Path,
    pairs: Iterable[tuple[RunIdentity, Path]],
) -> tuple[EventResult, ...]:
    """Convert exact audited pairs and account for every pair in the returned results."""
    bids_dir = Path(bids_dir)
    groups, inventory_errors = discover_bold_groups(bids_dir)
    bold_files = {group.identity: group.files for group in groups}
    results: list[EventResult] = []
    errors: list[dict[str, str]] = []

    for identity, behavior_file in pairs:
        behavior_file = Path(behavior_file)
        events_path = _events_path(bids_dir, identity)
        qc_path = truncation_sidecar_path(
            bids_dir, identity.subject, identity.session, identity.task, identity.run
        )
        try:
            if inventory_errors:
                raise TimingEvidenceError("; ".join(inventory_errors))
            offset_s, scan_s = _read_run_timing(bold_files.get(identity, ()))
            df = create_events_df(behavior_file, identity.task, offset_s, scan_s)
            tstats = events_truncation_stats(behavior_file, identity.task, offset_s, scan_s)
            _write_events(events_path, df)
            _write_truncation_sidecar(qc_path, tstats)
        except Exception as exc:
            events_path.unlink(missing_ok=True)
            qc_path.unlink(missing_ok=True)
            error = f"{type(exc).__name__}: {exc}"
            log.warning("Failed to process %s: %s", behavior_file, error)
            errors.append({
                "subject": identity.subject,
                "session": identity.session,
                "task": identity.task,
                "run": identity.run,
                "source_path": str(behavior_file),
                "exception_class": type(exc).__name__,
                "message": str(exc),
            })
            results.append(EventResult(
                identity=identity,
                status="failed",
                behavior_file=behavior_file,
                events_file=None,
                qc_file=None,
                error=error,
            ))
        else:
            results.append(EventResult(
                identity=identity,
                status="created",
                behavior_file=behavior_file,
                events_file=events_path,
                qc_file=qc_path,
                error=None,
            ))

    _write_conversion_errors(bids_dir, errors)
    return tuple(results)
