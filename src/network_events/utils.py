"""Event processing utilities — ported from discovery_wm/events/utils.py."""
import numpy as np
import pandas as pd


def cal_time_elapsed(df: pd.DataFrame) -> pd.DataFrame:
    """Adjust time_elapsed relative to fMRI trigger."""
    start_point = df.loc[df["trial_id"] == "fmri_trigger_initial"]
    start = start_point["time_elapsed"].values[0]
    df["time_elapsed"] = df["time_elapsed"] - start
    df["time_elapsed"] = df["time_elapsed"] - df["block_duration"]
    return df


def get_neg_rt_correction(df: pd.DataFrame) -> pd.DataFrame:
    """Fix RT estimation errors from cumulative timing drift."""
    df.dropna(subset=["block_duration"], inplace=True)
    negative_rt = df.loc[df["rt"] < -1]
    if not negative_rt.empty:
        i = df.loc[df.rt < -1].index.values.astype(int)[0]
        trial_before = df.loc[i - 1]["time_elapsed"]
        problematic = df.loc[i:]
        block_durations = problematic["block_duration"].to_list()
        new_time_elapsed = []
        for n in range(len(block_durations)):
            if not pd.isna(block_durations[n]):
                new_time_elapsed.append(trial_before + block_durations[n])
                trial_before = trial_before + block_durations[n]
            else:
                new_time_elapsed.append(np.nan)
        new_time = df.loc[: i - 1].time_elapsed.to_list() + new_time_elapsed
        df["time_elapsed"] = new_time
    return df


def add_choice_acc(df: pd.DataFrame) -> pd.DataFrame:
    """Compute binary accuracy column from key_press vs correct_response."""
    df["choice_acc"] = np.where(df["key_press"] == df["correct_response"], 1, 0)
    return df


def find_nonmonotonic_cut(onsets) -> int | None:
    """Positional index of the first onset strictly less than its predecessor.

    A backward step in event onsets means the raw jsPsych ``time_elapsed`` clock
    jumped backward (a logging glitch); trials from that point on have unreliable
    absolute timing. Returns the positional index where the first decrease occurs
    (the truncation point), or ``None`` if onsets are monotonic non-decreasing.
    """
    prev = None
    for i, v in enumerate(onsets):
        if prev is not None and v < prev:
            return i
        prev = v
    return None


# --- Column selection and trial_type construction ---
# (Ported directly from discovery_wm/events/utils.py get_cols_list / get_trial_type / add_cols)

_COMMON_COLS = ["trial_id", "time_elapsed", "rt", "stim_duration", "choice_acc", "key_press", "correct_response"]

_COLS_LOOKUP = {
    "stop_signal_single_task_network__fmri": _COMMON_COLS + ["SS_delay", "SS_duration", "stop_signal_condition", "stop_acc", "go_acc", "stim"],
    "shape_matching_single_task_network__fmri": _COMMON_COLS + ["shape_matching_condition", "probe_id", "target_id", "distractor_id"],
    "n_back_single_task_network__fmri": _COMMON_COLS + ["n_back_condition", "delay", "probe", "letter_case"],
    "go_nogo_single_task_network__fmri": _COMMON_COLS + ["go_nogo_condition"],
    "spatial_task_switching_single_task_network__fmri": _COMMON_COLS + ["task_switch", "whichQuadrant", "predictable_dimension", "number"],
    "cued_task_switching_single_task_network__fmri": _COMMON_COLS + ["cue", "task", "task_condition", "cue_condition", "stim_number"],
    "directed_forgetting_single_task_network__fmri": _COMMON_COLS + ["directed_forgetting_condition", "cue", "top_stim", "bottom_stim"],
    "flanker_single_task_network__fmri": _COMMON_COLS + ["flanker_condition", "center_letter"],
    "directed_forgetting_with_flanker__fmri": _COMMON_COLS + ["flanker_condition", "directed_forgetting_condition"],
    "stop_signal_with_directed_forgetting__fmri": _COMMON_COLS + ["SS_delay", "SS_duration", "stop_signal_condition", "directed_forgetting_condition", "stop_acc"],
    "stop_signal_with_flanker__fmri": _COMMON_COLS + ["SS_delay", "SS_duration", "stop_signal_condition", "flanker_condition", "SSD_congruent", "SSD_incongruent", "stop_acc"],
    "cued_task_switching_with_directed_forgetting__fmri": _COMMON_COLS + ["task_condition", "cue_condition", "task_cue", "directed_forgetting_condition"],
    "spatial_task_switching_with_cued_task_switching__fmri": _COMMON_COLS + ["task_switch", "whichQuadrant", "left_number", "right_number", "curr_cue"],
    "flanker_with_shape_matching__fmri": _COMMON_COLS + ["flanker_condition", "shape_matching_condition", "flankers", "probe", "target", "distractor"],
    "flanker_with_cued_task_switching__fmri": _COMMON_COLS + ["flanker_condition", "cue", "task_condition", "cue_condition", "flanking_number"],
    "flanker_with_cued_task_switching": _COMMON_COLS + ["flanker_condition", "cue", "task_condition", "cue_condition", "flanking_number"],
    "n_back_with_shape_matching__fmri": _COMMON_COLS + ["n_back_condition", "shape_matching_condition", "probe", "distractor", "delay"],
    "shape_matching_with_spatial_task_switching__fmri": _COMMON_COLS + ["shape_matching_condition", "task_switch", "probe", "target", "distractor", "whichQuadrant"],
    "shape_matching_with_spatial_task_switching": _COMMON_COLS + ["shape_matching_condition", "task_switch", "probe", "target", "distractor", "whichQuadrant"],
    "shape_matching_with_cued_task_switching__fmri": _COMMON_COLS + ["cue", "task_condition", "cue_condition", "shape_matching_condition", "probe", "target", "distractor"],
    "shape_matching_with_cued_task_switching": _COMMON_COLS + ["cue", "task_condition", "cue_condition", "shape_matching_condition", "probe", "target", "distractor"],
    "n_back_with_spatial_task_switching__fmri": _COMMON_COLS + ["n_back_condition", "task", "probe", "whichQuadrant"],
}

_TRIAL_TYPE_LOOKUP = {
    "stop_signal_single_task_network__fmri": ["stop_signal_condition"],
    "shape_matching_single_task_network__fmri": ["shape_matching_condition"],
    "n_back_single_task_network__fmri": ["n_back_condition"],
    "go_nogo_single_task_network__fmri": ["go_nogo_condition"],
    "spatial_task_switching_single_task_network__fmri": ["task_switch"],
    "cued_task_switching_single_task_network__fmri": ["task_condition", "cue_condition"],
    "directed_forgetting_single_task_network__fmri": ["directed_forgetting_condition"],
    "flanker_single_task_network__fmri": ["flanker_condition"],
    "directed_forgetting_with_flanker__fmri": ["flanker_condition", "directed_forgetting_condition"],
    "stop_signal_with_directed_forgetting__fmri": ["stop_signal_condition", "directed_forgetting_condition"],
    "stop_signal_with_flanker__fmri": ["stop_signal_condition", "flanker_condition"],
    "cued_task_switching_with_directed_forgetting__fmri": ["directed_forgetting_condition", "task_condition", "cue_condition"],
    "spatial_task_switching_with_cued_task_switching__fmri": ["task_switch"],
    "flanker_with_shape_matching__fmri": ["flanker_condition", "shape_matching_condition"],
    "flanker_with_cued_task_switching__fmri": ["cue_condition", "task_condition", "flanker_condition"],
    "flanker_with_cued_task_switching": ["cue_condition", "task_condition", "flanker_condition"],
    "n_back_with_shape_matching__fmri": ["n_back_condition", "shape_matching_condition", "delay"],
    "shape_matching_with_spatial_task_switching__fmri": ["predictable_condition", "shape_matching_condition"],
    "shape_matching_with_spatial_task_switching": ["predictable_condition", "shape_matching_condition"],
    "shape_matching_with_cued_task_switching__fmri": ["task_condition", "cue_condition", "shape_matching_condition"],
    "n_back_with_spatial_task_switching__fmri": ["n_back_condition", "task_switch_condition"],
}


def add_cols(df: pd.DataFrame, exp_id: str) -> pd.DataFrame:
    """Select task-specific columns and construct trial_type."""
    if "cued_task_switching" in exp_id:
        df["task_condition"] = df["task_condition"].astype(object).replace("na", "n/a")
        df["cue_condition"] = df["cue_condition"].astype(object).replace("na", "n/a")
    if "task_switch" in df.columns:
        df["task_switch"] = df["task_switch"].astype(object).replace("na", "n/a")

    to_add = _COLS_LOOKUP.get(exp_id)
    if to_add is None:
        raise ValueError(f"Unknown exp_id: {exp_id}")
    final = df[to_add]
    trial_types = _TRIAL_TYPE_LOOKUP.get(exp_id)

    df2 = pd.DataFrame()
    if len(trial_types) > 1:
        if exp_id == "cued_task_switching_single_task_network__fmri":
            df2["trial_type"] = "t" + df[trial_types[0]] + "_c" + df[trial_types[1]]
        elif exp_id == "cued_task_switching_with_directed_forgetting__fmri":
            df2["trial_type"] = df[trial_types[0]] + "_t" + df[trial_types[1]] + "_c" + df[trial_types[2]]
        elif exp_id == "shape_matching_with_cued_task_switching__fmri":
            df2["trial_type"] = "t" + df[trial_types[0]] + "_c" + df[trial_types[1]]
        elif exp_id == "flanker_with_cued_task_switching__fmri":
            df2["trial_type"] = "c" + df[trial_types[0]] + "_t" + df[trial_types[1]] + "_" + df[trial_types[2]]
        elif exp_id == "n_back_with_shape_matching__fmri":
            df2["trial_type"] = df[trial_types[0]] + "_" + df[trial_types[1]] + "_" + df[trial_types[2]].astype(str) + "back"
            df2["trial_type"] = df2["trial_type"].str.replace(".0back", "back")
        else:
            df2["trial_type"] = df[trial_types[0]] + "_" + df[trial_types[1]]
    if exp_id == "flanker_with_cued_task_switching__fmri":
        df2["trial_type"] = df2["trial_type"].shift(1)
    if len(trial_types) == 1:
        df2["trial_type"] = df[trial_types[0]]
    if exp_id == "shape_matching_with_spatial_task_switching__fmri":
        df2["trial_type"] = df2["trial_type"].str.split("_").str[2:].str.join("_")
    if exp_id == "spatial_task_switching_single_task_network__fmri":
        final = final.rename(columns={"predictable_dimension": "task_set"})
    if exp_id == "cued_task_switching_with_directed_forgetting__fmri":
        final.loc[final["key_press"] == 84.0, ["rt"]] = pd.NA
        final.loc[final["key_press"] == 84.0, ["key_press"]] = -1

    final = final.assign(trial_type=df2)
    return final


# --- Task-specific cleanup (trial_type relabeling) ---

def _cleanup_stop_signal(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    mask = df["trial_id"] == "test_trial"
    trial_rows = df[mask]
    choice_acc_str = trial_rows["choice_acc"].astype(str)
    conditions = [
        (trial_rows["trial_type"] == "go"),
        (trial_rows["trial_type"] == "stop") & (choice_acc_str == "1"),
        (trial_rows["trial_type"] == "stop") & (choice_acc_str == "0"),
    ]
    values = ["go", "stop_success", "stop_failure"]
    result = np.select(conditions, values, default="unknown")
    df.loc[mask, "trial_type"] = result
    fixation_mask = df["trial_id"] == "test_fixation"
    df.loc[fixation_mask, "trial_type"] = "fixation"
    return df


def _cleanup_go_nogo(df: pd.DataFrame) -> pd.DataFrame:
    choice_acc_str = df["choice_acc"].astype(str)
    conditions = [
        (df["trial_type"] == "nogo") & (choice_acc_str == "1"),
        (df["trial_type"] == "nogo") & (choice_acc_str == "0"),
        (df["trial_type"] == "go"),
    ]
    values = ["nogo_success", "nogo_failure", "go"]
    result = np.select(conditions, values, default="unknown")
    df["trial_type"] = pd.Series(result).astype(object)
    return df


def _cleanup_stop_signal_w_directed_forgetting(df: pd.DataFrame) -> pd.DataFrame:
    mask = df["trial_id"] == "test_trial"
    trial_rows = df[mask]
    conditions = [
        (trial_rows["stop_signal_condition"] == "go") & (trial_rows["directed_forgetting_condition"] == "con"),
        (trial_rows["stop_signal_condition"] == "go") & (trial_rows["directed_forgetting_condition"] == "pos"),
        (trial_rows["stop_signal_condition"] == "go") & (trial_rows["directed_forgetting_condition"] == "neg"),
        (trial_rows["stop_signal_condition"] == "stop") & (trial_rows["directed_forgetting_condition"] == "con") & (trial_rows["stop_acc"] == 1),
        (trial_rows["stop_signal_condition"] == "stop") & (trial_rows["directed_forgetting_condition"] == "pos") & (trial_rows["stop_acc"] == 1),
        (trial_rows["stop_signal_condition"] == "stop") & (trial_rows["directed_forgetting_condition"] == "neg") & (trial_rows["stop_acc"] == 1),
        (trial_rows["stop_signal_condition"] == "stop") & (trial_rows["directed_forgetting_condition"] == "con") & (trial_rows["stop_acc"] == 0),
        (trial_rows["stop_signal_condition"] == "stop") & (trial_rows["directed_forgetting_condition"] == "pos") & (trial_rows["stop_acc"] == 0),
        (trial_rows["stop_signal_condition"] == "stop") & (trial_rows["directed_forgetting_condition"] == "neg") & (trial_rows["stop_acc"] == 0),
        (trial_rows["trial_type"] == "memory_cue"),
    ]
    values = ["go_con", "go_pos", "go_neg", "stop_success_con", "stop_success_pos", "stop_success_neg", "stop_failure_con", "stop_failure_pos", "stop_failure_neg", "memory_cue"]
    result = np.select(conditions, values, default="unknown")
    df.loc[mask, "trial_type"] = result
    fixation_mask = df["trial_id"] == "test_fixation"
    df.loc[fixation_mask, "trial_type"] = "fixation"
    return df


def _cleanup_stop_signal_w_flanker(df: pd.DataFrame) -> pd.DataFrame:
    mask = df["trial_id"] == "test_trial"
    trial_rows = df[mask]
    conditions = [
        (trial_rows["stop_signal_condition"] == "go") & (trial_rows["flanker_condition"] == "congruent"),
        (trial_rows["stop_signal_condition"] == "go") & (trial_rows["flanker_condition"] == "incongruent"),
        (trial_rows["stop_signal_condition"] == "stop") & (trial_rows["flanker_condition"] == "congruent") & (trial_rows["stop_acc"] == 1),
        (trial_rows["stop_signal_condition"] == "stop") & (trial_rows["flanker_condition"] == "incongruent") & (trial_rows["stop_acc"] == 1),
        (trial_rows["stop_signal_condition"] == "stop") & (trial_rows["flanker_condition"] == "congruent") & (trial_rows["stop_acc"] == 0),
        (trial_rows["stop_signal_condition"] == "stop") & (trial_rows["flanker_condition"] == "incongruent") & (trial_rows["stop_acc"] == 0),
    ]
    values = ["go_congruent", "go_incongruent", "stop_success_congruent", "stop_success_incongruent", "stop_failure_congruent", "stop_failure_incongruent"]
    result = np.select(conditions, values, default="unknown")
    df.loc[mask, "trial_type"] = result
    fixation_mask = df["trial_id"] == "test_fixation"
    df.loc[fixation_mask, "trial_type"] = "fixation"
    return df


_CLEANUP_DISPATCH = {
    "stopSignal": _cleanup_stop_signal,
    "goNogo": _cleanup_go_nogo,
    "stopSignalWDirectedForgetting": _cleanup_stop_signal_w_directed_forgetting,
    "stopSignalWFlanker": _cleanup_stop_signal_w_flanker,
}


def response_time_and_junk(df: pd.DataFrame, task: str) -> pd.DataFrame:
    """Apply task-specific cleanup and replace empty strings with NaN."""
    cleanup_fn = _CLEANUP_DISPATCH.get(task)
    if cleanup_fn is not None:
        df = cleanup_fn(df)
    df.replace("", np.nan, inplace=True)
    return df
