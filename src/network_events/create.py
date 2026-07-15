"""Generate BIDS _events.tsv files from behavioral CSVs.

Non-monotonic-onset truncation
-------------------------------
Occasionally the raw jsPsych ``time_elapsed`` clock jumps backward mid-run (an
unrecoverable ExpFactory logging glitch we cannot trace or fix at the source).
Trials after that jump have unreliable absolute timing, so :func:`create_events_df`
truncates the run at the first backward step and keeps only the clean monotonic
prefix. This is always applied -- it is a data-integrity fix, not a policy
decision.

Trial-retention metric (the network_qa seam)
---------------------------------------------
Every truncation drops some number of ``test_trial`` rows. :func:`create_events_df`
does not know (and does not decide) whether that loss is small enough to salvage
the run or large enough to exclude it -- that call belongs to a separate package,
``network_qa``. What this module does is *measure* the loss and expose it in
machine-readable form: :func:`run_create_events` writes a ``NTestTrialsExpected``
/ ``NTestTrialsRetained`` / ``FractionTestTrialsDropped`` JSON sidecar next to
each ``_events.tsv`` (see :func:`events_truncation_stats`). ``network_qa`` (or any
downstream consumer) reads that sidecar to apply its own exclusion threshold
(e.g. the monolith's ">50% of test trials dropped" rule); this package makes no
such call.
"""
import json
import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd

from network_events.config import N_DUMMY, TR_SECONDS
from network_events.utils import (
    get_neg_rt_correction,
    cal_time_elapsed,
    add_choice_acc,
    add_cols,
    find_nonmonotonic_cut,
    response_time_and_junk,
)

log = logging.getLogger(__name__)

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
    "shape_matching_with_cued_task_switching__fmri": {"fixation": "test_fixation", "cue": "test_cue", "feedback_block": "break"},
    "shape_matching_with_cued_task_switching": {"fixation": "test_fixation", "cue": "test_cue", "feedback_block": "break"},
    "n_back_with_spatial_task_switching__fmri": {"feedback_block": "break", "fixation": "test_fixation"},
}


def _rename_cells(df: pd.DataFrame, exp_id: str) -> pd.DataFrame:
    change = _RENAME_CELLS_LOOKUP.get(exp_id)
    if change is None:
        log.warning("No rename_cells mapping for exp_id: %s", exp_id)
        return df
    for key, value in change.items():
        df["trial_id"] = df["trial_id"].replace(key, value)
    if "cued_task_switching_" in exp_id:
        df["correct_response"] = df["correct_response"].astype(object)
        df.loc[df["trial_id"] == "test_cue", "correct_response"] = "n/a"
    return df


DUMMY_OFFSET_S = N_DUMMY * TR_SECONDS  # 10.43s (N_DUMMY/TR_SECONDS from core.acquisition)


def _set_default_event_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df[df.time_elapsed > 0]
    df = df.rename(columns={"time_elapsed": "onset", "choice_acc": "acc", "stim_duration": "duration", "rt": "response_time"})
    df["onset"] = df["onset"] / 1000
    df["duration"] = df["duration"] / 1000
    df["response_time"] = df["response_time"] / 1000
    df["response_time"] = df["response_time"].replace(-0.001, np.nan)

    # Adjust onsets for trimmed dummy volumes (7 * 1.49s = 10.43s)
    df["onset"] = df["onset"] - DUMMY_OFFSET_S
    df = df[df["onset"] >= 0]
    first_columns = ["onset", "duration", "response_time", "trial_id", "trial_type", "key_press", "correct_response"]
    new_column_order = first_columns + [col for col in df.columns if col not in first_columns]
    df = df[new_column_order]
    return df


def _flagged_feedback(text_content: str) -> bool:
    keywords = ["accuracy", "slowly", "respond", "response"]
    return any(keyword in text_content.lower() for keyword in keywords)


def create_empty_events_df() -> pd.DataFrame:
    """Create empty events DataFrame with required BIDS columns."""
    return pd.DataFrame(columns=[
        "onset",
        "duration",
        "trial_id",
        "trial_type",
        "response_time",
        "key_press",
        "correct_response",
    ])


def _get_rows_with_feedback(df: pd.DataFrame, original_df: pd.DataFrame):
    feedback_block_rows = original_df[original_df["trial_id"] == "test_feedback"]
    if len(feedback_block_rows) == 0:
        feedback_block_rows = original_df[original_df["trial_id"] == "feedback_block"]
    if len(feedback_block_rows) == 0 and "stimulus" in original_df.columns:
        stimulus_col = original_df["stimulus"].astype(str)
        feedback_block_rows = original_df[stimulus_col.str.contains("completed", na=False)]
    indices_to_change = []
    for index, row in feedback_block_rows.iterrows():
        stimulus = row["stimulus"]
        if _flagged_feedback(stimulus):
            indices_to_change.append(index)
    return feedback_block_rows, indices_to_change


def _build_events_df(filename: Path, short_name: str) -> pd.DataFrame:
    """Build the events dataframe up to (but excluding) non-monotonic truncation."""
    original_df = pd.read_csv(filename)
    exp_id = original_df["exp_id"][0]
    log.info("Processing %s for %s", filename, exp_id)
    df = original_df.copy()
    df = get_neg_rt_correction(df)
    df = cal_time_elapsed(df)
    df = add_choice_acc(df)
    df = add_cols(df, exp_id)
    df = response_time_and_junk(df, short_name)
    df = _set_default_event_cols(df)
    df = _rename_cells(df, exp_id)

    # cuedTSWFlanker: the cued-task-switch factor (composite trial_type +
    # cue_condition/task_condition) lands only on the test_cue row, while the
    # modeled test_trial row carries just flanker_condition. (The exp_id lacks
    # the "__fmri" suffix the add_cols special-case checks, so its shift never
    # fires.) Propagate the switch factor from each test_cue onto the
    # immediately following test_trial, only where the test_trial value is
    # missing — so test_trial rows carry the switch trial_type like every other
    # dual task.
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


def create_events_df(filename: Path, short_name: str) -> pd.DataFrame:
    """Create a BIDS events dataframe from a behavioral CSV.

    Truncates at the first non-monotonic onset (a backward ``time_elapsed`` clock
    glitch): trials after the jump have unreliable absolute timing, so the clean
    monotonic prefix is kept. The complementary trial-retention metric is exposed
    by :func:`events_truncation_stats` for downstream QC (``network_qa``) to act
    on; this function makes no exclusion decision.
    """
    df = _build_events_df(filename, short_name)
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
    return df


def events_truncation_stats(filename: Path, short_name: str) -> dict:
    """Non-monotonic-onset truncation stats for a behavioral CSV (no side effects).

    Returns ``{cut, n_test_total, n_test_dropped, fraction_test_dropped}``. This is
    the trial-retention metric surfaced to ``network_qa``: no >50% (or any other)
    exclusion threshold is applied here.
    """
    df = _build_events_df(filename, short_name)
    cut, n_total, n_dropped = _nonmonotonic_truncation(df)
    frac = (n_dropped / n_total) if n_total else 0.0
    return {
        "cut": cut,
        "n_test_total": n_total,
        "n_test_dropped": n_dropped,
        "fraction_test_dropped": frac,
    }


def discover_nifti_tasks(func_dir: Path) -> set[str]:
    """Non-rest task labels that have a BOLD NIfTI in ``func_dir``.

    Events are generated for every such task. Scan exclusion is intentionally
    NOT applied here: the authoritative mechanism is the compiled-exclusions
    system (enforced downstream at lev1), so ``.bidsignore`` is not consulted at
    the events stage. (A prior ``.bidsignore`` filter here was a silent no-op —
    its greedy task token, e.g. ``flanker_run``, never matched the bare task
    ``flanker`` discovered here — so it is removed rather than resurrected.)
    """
    tasks: set[str] = set()
    for nii in func_dir.glob("*.nii.gz"):
        m = re.search(r"task-([^_]+)", nii.name)
        if m and m.group(1) != "rest":
            tasks.add(m.group(1))
    return tasks


def group_csvs_by_task(
    beh_dir: Path, allowed_tasks: set[str]
) -> list[tuple[str, int, Path]]:
    """Group behavioral CSVs by ``(task, run)``, keeping only ``allowed_tasks``.

    Run number is read from a ``run-<n>`` token in the filename, defaulting to 1.
    """
    out: list[tuple[str, int, Path]] = []
    for csv_file in sorted(beh_dir.glob("*.csv")):
        m = re.search(r"task-([^_]+)", csv_file.name)
        if not m:
            continue
        task_name = m.group(1)
        if task_name not in allowed_tasks:
            continue
        run_m = re.search(r"run-(\d+)", csv_file.name)
        run_num = int(run_m.group(1)) if run_m else 1
        out.append((task_name, run_num, csv_file))
    return out


def _write_truncation_sidecar(events_tsv_path: Path, tstats: dict) -> Path:
    """Write the trial-retention metric next to an ``_events.tsv`` as its JSON sidecar.

    This is the machine-readable seam ``network_qa`` (or any other downstream
    consumer) reads to apply its own exclusion policy (e.g. the monolith's
    ">50% of test trials dropped" rule) -- no threshold is applied here.
    """
    sidecar_path = events_tsv_path.with_suffix(".json")
    n_total = tstats["n_test_total"]
    n_dropped = tstats["n_test_dropped"]
    sidecar = {
        "NTestTrialsExpected": n_total,
        "NTestTrialsRetained": n_total - n_dropped,
        "FractionTestTrialsDropped": tstats["fraction_test_dropped"],
    }
    sidecar_path.write_text(json.dumps(sidecar, indent=2))
    return sidecar_path


def run_create_events(
    behavioral_dir: Path,
    bids_dir: Path,
    subjects: list[str] | None = None,
    sessions: list[str] | None = None,
) -> None:
    """Walk sourcedata behavioral CSVs and write BIDS event files.

    Args:
        behavioral_dir: Path to sourcedata/ with sub-*/ses-*/beh/*.csv
        bids_dir: Path to BIDS dataset root (events written to func/ dirs)
        subjects: Optional list of subjects to process (default: all)
        sessions: Optional list of sessions to process (default: all)

    Alongside each ``_events.tsv``, writes a ``_events.json`` sidecar carrying the
    non-monotonic-truncation trial-retention metric (see
    :func:`events_truncation_stats` / :func:`_write_truncation_sidecar`). No
    exclusion decision is made here -- that is ``network_qa``'s job.
    """
    for sub_dir in sorted(behavioral_dir.glob("sub-*")):
        if subjects and sub_dir.name not in subjects:
            continue
        for ses_dir in sorted(sub_dir.glob("ses-*")):
            if sessions and ses_dir.name not in sessions:
                continue
            beh_dir = ses_dir / "beh"
            if not beh_dir.exists():
                continue
            func_dir = bids_dir / sub_dir.name / ses_dir.name / "func"
            if not func_dir.exists():
                log.warning("No func dir for %s %s, skipping", sub_dir.name, ses_dir.name)
                continue

            nifti_tasks = discover_nifti_tasks(func_dir)
            task_run_files = group_csvs_by_task(beh_dir, nifti_tasks)

            tasks_with_events = set()

            for task_name, run_num, csv_file in task_run_files:
                outname = f"{sub_dir.name}_{ses_dir.name}_task-{task_name}_run-{run_num}_events.tsv"
                outpath = func_dir / outname

                tstats = None
                try:
                    df = create_events_df(csv_file, task_name)
                    tstats = events_truncation_stats(csv_file, task_name)
                    log.info("Writing events.tsv: %s", outpath)
                except Exception as e:
                    log.warning(
                        "Failed to process %s: %s. Writing empty events.tsv.",
                        csv_file, e,
                    )
                    df = create_empty_events_df()

                df.to_csv(outpath, sep="\t", index=False, na_rep="n/a")
                if tstats is not None:
                    _write_truncation_sidecar(outpath, tstats)
                tasks_with_events.add(task_name)
