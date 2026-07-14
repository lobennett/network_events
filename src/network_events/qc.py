"""Behavioral QC: compute metrics, flag exclusions, detect trimming needs."""
import json
import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd

from network_events.qc_globals import (
    STOP_SUCCESS_ACC_LOW_THRESHOLD,
    STOP_SUCCESS_ACC_HIGH_THRESHOLD,
    GO_RT_THRESHOLD_FMRI,
    GONOGO_GO_ACC_THRESHOLD_1,
    GONOGO_NOGO_ACC_THRESHOLD_1,
    GONOGO_GO_ACC_THRESHOLD_2,
    GONOGO_NOGO_ACC_THRESHOLD_2,
    NBACK_1BACK_MATCH_ACC_COMBINED_THRESHOLD_1,
    NBACK_1BACK_MISMATCH_ACC_COMBINED_THRESHOLD_1,
    NBACK_1BACK_MATCH_ACC_COMBINED_THRESHOLD_2,
    NBACK_1BACK_MISMATCH_ACC_COMBINED_THRESHOLD_2,
    NBACK_2BACK_MATCH_ACC_COMBINED_THRESHOLD_1,
    NBACK_2BACK_MISMATCH_ACC_COMBINED_THRESHOLD_1,
    NBACK_2BACK_MATCH_ACC_COMBINED_THRESHOLD_2,
    NBACK_2BACK_MISMATCH_ACC_COMBINED_THRESHOLD_2,
    ACC_THRESHOLD,
    OMISSION_RATE_THRESHOLD,
    LAST_N_TEST_TRIALS,
)

log = logging.getLogger(__name__)


# --- RT tail cutoff detection ---

def detect_rt_tail_cutoff(df: pd.DataFrame, last_n: int = LAST_N_TEST_TRIALS) -> dict | None:
    """Detect if participant stopped responding at the end of a run.

    Returns dict with cutoff info, or None if no cutoff detected.
    """
    df = df.copy()
    if "trial_id" not in df.columns or "rt" not in df.columns:
        return None

    df["rt"] = pd.to_numeric(df["rt"], errors="coerce").fillna(-1)
    test_trials = df[df["trial_id"] == "test_trial"]

    if len(test_trials) < last_n:
        return None

    # Check if last N test trials are all non-responses
    if not (test_trials["rt"].tail(last_n) == -1).all():
        return None

    # Find last valid response across all rows
    valid_mask = df["rt"] != -1
    if not valid_mask.any():
        return None

    last_valid_idx = valid_mask[valid_mask].index[-1]

    # Verify all rows after last valid are -1
    tail = df.loc[last_valid_idx:].iloc[1:]
    if not (tail["rt"] == -1).all():
        return None

    # Compute cutoff position
    cutoff_iloc = df.index.get_loc(last_valid_idx) + 1
    test_trials_included = test_trials[test_trials.index <= last_valid_idx]
    halfway = len(test_trials) / 2.0
    cutoff_before_halfway = len(test_trials_included) < halfway

    # Get onset time at cutoff for NIfTI trimming
    cutoff_onset = None
    if "time_elapsed" in df.columns:
        cutoff_onset = float(df.iloc[cutoff_iloc - 1]["time_elapsed"])

    proportion_blank = (test_trials["rt"] == -1).sum() / len(test_trials)

    return {
        "cutoff_index": cutoff_iloc,
        "cutoff_before_halfway": cutoff_before_halfway,
        "cutoff_onset_ms": cutoff_onset,
        "proportion_blank": float(proportion_blank),
    }


# --- Per-task exclusion checks ---

def check_stop_signal_exclusion(metrics: dict) -> dict | None:
    """Check stop signal exclusion criteria. Returns reason dict or None."""
    reasons = []
    ss_rate = metrics.get("stop_success_rate")
    if ss_rate is not None:
        if ss_rate < STOP_SUCCESS_ACC_LOW_THRESHOLD:
            reasons.append(f"stop_success_rate ({ss_rate:.2f}) < {STOP_SUCCESS_ACC_LOW_THRESHOLD}")
        if ss_rate > STOP_SUCCESS_ACC_HIGH_THRESHOLD:
            reasons.append(f"stop_success_rate ({ss_rate:.2f}) > {STOP_SUCCESS_ACC_HIGH_THRESHOLD}")
    go_rt = metrics.get("go_rt")
    if go_rt is not None and go_rt > GO_RT_THRESHOLD_FMRI:
        reasons.append(f"go_rt ({go_rt:.0f}ms) > {GO_RT_THRESHOLD_FMRI}ms")
    return {"reason": "; ".join(reasons)} if reasons else None


def check_go_nogo_exclusion(metrics: dict) -> dict | None:
    """Check go/nogo dual-rule exclusion. Returns reason dict or None."""
    go_acc = metrics.get("go_acc")
    nogo_acc = metrics.get("nogo_acc")
    if go_acc is None or nogo_acc is None:
        return None
    rule1 = (go_acc <= GONOGO_GO_ACC_THRESHOLD_1) or (nogo_acc <= GONOGO_NOGO_ACC_THRESHOLD_1)
    rule2 = (go_acc <= GONOGO_GO_ACC_THRESHOLD_2) or (nogo_acc <= GONOGO_NOGO_ACC_THRESHOLD_2)
    if rule1 and rule2:
        return {"reason": f"go_acc={go_acc:.2f}, nogo_acc={nogo_acc:.2f} — both exclusion rules triggered"}
    return None


def check_nback_exclusion(metrics: dict, load: int) -> dict | None:
    """Check n-back exclusion for a specific load. Returns reason dict or None."""
    if load not in (1, 2):
        return None
    match_acc = metrics.get(f"match_{load}back_acc")
    mismatch_acc = metrics.get(f"mismatch_{load}back_acc")
    if match_acc is None or mismatch_acc is None:
        return None
    if load == 1:
        t1_match, t1_mismatch = NBACK_1BACK_MATCH_ACC_COMBINED_THRESHOLD_1, NBACK_1BACK_MISMATCH_ACC_COMBINED_THRESHOLD_1
        t2_match, t2_mismatch = NBACK_1BACK_MATCH_ACC_COMBINED_THRESHOLD_2, NBACK_1BACK_MISMATCH_ACC_COMBINED_THRESHOLD_2
    else:
        t1_match, t1_mismatch = NBACK_2BACK_MATCH_ACC_COMBINED_THRESHOLD_1, NBACK_2BACK_MISMATCH_ACC_COMBINED_THRESHOLD_1
        t2_match, t2_mismatch = NBACK_2BACK_MATCH_ACC_COMBINED_THRESHOLD_2, NBACK_2BACK_MISMATCH_ACC_COMBINED_THRESHOLD_2
    rule1 = (match_acc <= t1_match) or (mismatch_acc <= t1_mismatch)
    rule2 = (match_acc <= t2_match) or (mismatch_acc <= t2_mismatch)
    if rule1 and rule2:
        return {"reason": f"{load}-back match={match_acc:.2f}, mismatch={mismatch_acc:.2f} — exclusion rules triggered"}
    return None


def check_other_exclusion(metrics: dict) -> dict | None:
    """Check accuracy/omission exclusion for non-special tasks."""
    reasons = []
    acc = metrics.get("acc")
    if acc is not None and acc < ACC_THRESHOLD:
        reasons.append(f"accuracy ({acc:.2f}) < {ACC_THRESHOLD}")
    omission = metrics.get("omission_rate")
    if omission is not None and omission > OMISSION_RATE_THRESHOLD:
        reasons.append(f"omission_rate ({omission:.2f}) > {OMISSION_RATE_THRESHOLD}")
    return {"reason": "; ".join(reasons)} if reasons else None


# --- Metric computation from sourcedata CSV ---

def compute_metrics_from_csv(csv_path: Path, task_name: str) -> dict:
    """Compute behavioral QC metrics from a sourcedata CSV.

    Args:
        csv_path: Path to the behavioral CSV
        task_name: BIDS task name (e.g., "stopSignal", "goNogo")

    Returns:
        Dict of metric_name -> value
    """
    df = pd.read_csv(csv_path)
    if "rt" not in df.columns or "trial_id" not in df.columns:
        log.warning("CSV missing required columns (rt, trial_id): %s", csv_path)
        return {}

    df["rt"] = pd.to_numeric(df["rt"], errors="coerce").fillna(-1)
    test_rows = df[df["trial_id"] == "test_trial"]
    if len(test_rows) == 0:
        return {}

    metrics = {}

    if "stopSignal" in task_name:
        if "stop_signal_condition" not in test_rows.columns:
            log.warning("stopSignal task missing stop_signal_condition column: %s", csv_path)
            return metrics
        go_trials = test_rows[test_rows["stop_signal_condition"] == "go"]
        stop_trials = test_rows[test_rows["stop_signal_condition"] == "stop"]
        if len(go_trials) > 0:
            valid_go = go_trials[go_trials["rt"] != -1]
            metrics["go_rt"] = float(valid_go["rt"].mean()) if len(valid_go) > 0 else None
            metrics["go_acc"] = float((go_trials["key_press"] == go_trials["correct_response"]).mean())
        if len(stop_trials) > 0 and "stop_acc" in stop_trials.columns:
            metrics["stop_success_rate"] = float((stop_trials["stop_acc"] == 1).mean())

    elif "goNogo" in task_name:
        if "go_nogo_condition" not in test_rows.columns:
            log.warning("goNogo task missing go_nogo_condition column: %s", csv_path)
            return metrics
        go_trials = test_rows[test_rows["go_nogo_condition"] == "go"]
        nogo_trials = test_rows[test_rows["go_nogo_condition"] == "nogo"]
        if len(go_trials) > 0:
            metrics["go_acc"] = float((go_trials["key_press"] == go_trials["correct_response"]).mean())
        if len(nogo_trials) > 0:
            metrics["nogo_acc"] = float((nogo_trials["rt"] == -1).mean())

    elif "nBack" in task_name:
        if "n_back_condition" not in test_rows.columns:
            log.warning("nBack task missing n_back_condition column: %s", csv_path)
            return metrics
        condition = test_rows["n_back_condition"].astype(str)
        for load in [1, 2]:
            load_str = f"{load}.0back"
            load_mask = condition.str.contains(load_str, na=False)
            load_trials = test_rows[load_mask]
            if len(load_trials) == 0:
                continue
            load_cond = load_trials["n_back_condition"].astype(str)
            match_mask = load_cond.str.contains("match", na=False) & ~load_cond.str.contains("mismatch", na=False)
            match_trials = load_trials[match_mask]
            mismatch_trials = load_trials[load_cond.str.contains("mismatch", na=False)]
            if len(match_trials) > 0:
                metrics[f"match_{load}back_acc"] = float((match_trials["key_press"] == match_trials["correct_response"]).mean())
            if len(mismatch_trials) > 0:
                metrics[f"mismatch_{load}back_acc"] = float((mismatch_trials["key_press"] == mismatch_trials["correct_response"]).mean())

    else:
        # Generic task: accuracy and omission rate
        valid_trials = test_rows[test_rows["rt"] != -1]
        if len(valid_trials) > 0:
            metrics["acc"] = float((valid_trials["key_press"] == valid_trials["correct_response"]).mean())
        metrics["omission_rate"] = float((test_rows["rt"] == -1).sum() / len(test_rows))

    return metrics


def determine_exclusion(task_name: str, metrics: dict) -> dict | None:
    """Determine if a run should be excluded based on task-specific criteria."""
    if "stopSignal" in task_name:
        return check_stop_signal_exclusion(metrics)
    elif "goNogo" in task_name:
        return check_go_nogo_exclusion(metrics)
    elif "nBack" in task_name:
        for load in [1, 2]:
            result = check_nback_exclusion(metrics, load)
            if result is not None:
                return result
        return None
    else:
        return check_other_exclusion(metrics)


def run_qc(
    behavioral_dir: Path,
    bids_dir: Path,
    subjects: list[str] | None = None,
) -> tuple[list[dict], list[dict]]:
    """Run behavioral QC on sourcedata CSVs.

    Returns:
        (exclusion_entries, trim_entries) — lists of dicts for the exclusions system and trim list
    """
    exclusion_entries = []
    trim_entries = []
    qc_output_dir = bids_dir / "sourcedata" / "behavioral_qc"
    qc_output_dir.mkdir(parents=True, exist_ok=True)

    for sub_dir in sorted(behavioral_dir.glob("sub-*")):
        if subjects and sub_dir.name not in subjects:
            continue
        for ses_dir in sorted(sub_dir.glob("ses-*")):
            beh_dir = ses_dir / "beh"
            if not beh_dir.exists():
                continue
            for csv_file in sorted(beh_dir.glob("*.csv")):
                m = re.search(r"task-([^_]+)", csv_file.name)
                if not m:
                    continue
                task_name = m.group(1)
                run_m = re.search(r"run-(\d+)", csv_file.name)
                run_label = f"run-{run_m.group(1)}" if run_m else "run-1"

                # Compute metrics
                metrics = compute_metrics_from_csv(csv_file, task_name)

                # Detect RT tail cutoff
                df = pd.read_csv(csv_file)
                cutoff_info = detect_rt_tail_cutoff(df)

                if cutoff_info is not None:
                    if cutoff_info["cutoff_before_halfway"]:
                        exclusion_entries.append({
                            "subject": sub_dir.name,
                            "session": ses_dir.name,
                            "task": task_name,
                            "run": run_label,
                            "action": "exclude",
                            "source": "behavioral-qc",
                            "reason": f"RT tail cutoff before halfway (proportion_blank={cutoff_info['proportion_blank']:.2f})",
                        })
                    else:
                        trim_entries.append({
                            "subject": sub_dir.name,
                            "session": ses_dir.name,
                            "task": task_name,
                            "cutoff_onset_ms": cutoff_info["cutoff_onset_ms"],
                            "proportion_blank": cutoff_info["proportion_blank"],
                        })

                # Check exclusion criteria
                excl = determine_exclusion(task_name, metrics)
                if excl is not None:
                    exclusion_entries.append({
                        "subject": sub_dir.name,
                        "session": ses_dir.name,
                        "task": task_name,
                        "run": "run-1",
                        "action": "exclude",
                        "source": "behavioral-qc",
                        "reason": excl["reason"],
                    })

    # Write trim list
    trim_path = qc_output_dir / "trim_list.json"
    with open(trim_path, "w") as f:
        json.dump(trim_entries, f, indent=2)
    log.info("Wrote trim list: %s (%d entries)", trim_path, len(trim_entries))

    return exclusion_entries, trim_entries
