"""Dual-task create.py fixups ported from the neuro_workflow monolith.

Two composite-condition tasks need a post-processing fix beyond the generic
``add_cols``/``_rename_cells`` machinery:

  * ``flanker_with_cued_task_switching`` (cuedTSWFlanker) -- the cued-task-switch
    factor lands only on the ``test_cue`` row (its exp_id lacks the ``__fmri``
    suffix the ``add_cols`` shift special-case checks, so the shift never
    fires); the modeled ``test_trial`` row must carry the switch trial_type of
    its preceding cue.
  * ``n_back_with_spatial_task_switching`` (nBackWSpatialTS) -- the raw
    ``n_back_condition`` mixes case (``Mismatch`` vs ``mismatch``), so the
    composite ``trial_type`` on ``test_trial`` rows must be lowercased for
    consistent cells.

Mirrors the fixture style of neuro_workflow's tests/analysis/test_raw_jspsych.py
(``_write_cued_ts_flanker_csv`` / ``_write_nback_spatial_ts_csv``), rebuilt
locally since network_events has no dependency on neuro_workflow's raw-jsPsych
testing helpers.
"""
import numpy as np
import pandas as pd

from network_events.config import N_DUMMY, TR_SECONDS

_TRIGGER_MS = 60000.0
_DUMMY_MS = N_DUMMY * TR_SECONDS * 1000.0
_BLOCK_MS = 2000.0


def _te(onset_s: float) -> float:
    """Plant time_elapsed so create_events_df recovers events onset ``onset_s``."""
    return _TRIGGER_MS + _BLOCK_MS + _DUMMY_MS + onset_s * 1000.0


def _write_cued_ts_flanker_csv(path, cue_switch_pairs, flankers):
    """Raw flanker_with_cued_task_switching export.

    The cued-task-switch factor (cue_condition / task_condition) lives ONLY on
    the ``test_cue`` row; ``flanker_condition`` is on both the cue and the
    following ``test_trial`` row. Rows are ordered cue-then-trial per trial, as
    in the real export.
    """
    exp_id = "flanker_with_cued_task_switching"
    trig = {
        "exp_id": exp_id,
        "trial_id": "fmri_trigger_initial",
        "time_elapsed": _TRIGGER_MS,
        "block_duration": _BLOCK_MS,
        "rt": int(_BLOCK_MS),
        "stim_duration": np.nan,
        "key_press": np.nan,
        "correct_response": np.nan,
        "flanker_condition": np.nan,
        "cue": np.nan,
        "task_condition": np.nan,
        "cue_condition": np.nan,
        "flanking_number": np.nan,
    }
    rows = [trig]
    onset = 5.0
    for (cue_cond, task_cond), flk in zip(cue_switch_pairs, flankers, strict=False):
        rows.append(
            {
                "exp_id": exp_id,
                "trial_id": "test_cue",
                "time_elapsed": _te(onset),
                "block_duration": _BLOCK_MS,
                "rt": -1,
                "stim_duration": 500.0,
                "key_press": -1,
                "correct_response": np.nan,
                "flanker_condition": flk,
                "cue": "Parity",
                "task_condition": task_cond,
                "cue_condition": cue_cond,
                "flanking_number": np.nan,
            }
        )
        onset += 1.5
        rows.append(
            {
                "exp_id": exp_id,
                "trial_id": "test_trial",
                "time_elapsed": _te(onset),
                "block_duration": _BLOCK_MS,
                "rt": 700,
                "stim_duration": 1000.0,
                "key_press": 71.0,
                "correct_response": 71.0,
                "flanker_condition": flk,
                "cue": "Parity",
                "task_condition": np.nan,  # switch factor absent on trial row
                "cue_condition": np.nan,
                "flanking_number": 5.0,
            }
        )
        onset += 1.5
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _write_nback_spatial_ts_csv(path, nback_conditions, task_switch_condition="tswitch_cswitch"):
    """Raw n_back_with_spatial_task_switching export.

    trial_type is built as ``n_back_condition + '_' + task_switch_condition`` on
    the ``test_trial`` rows; ``n_back_condition`` mixes case in the real export
    (e.g. ``Mismatch`` vs ``mismatch``).
    """
    exp_id = "n_back_with_spatial_task_switching__fmri"
    trig = {
        "exp_id": exp_id,
        "trial_id": "fmri_trigger_initial",
        "time_elapsed": _TRIGGER_MS,
        "block_duration": _BLOCK_MS,
        "rt": int(_BLOCK_MS),
        "stim_duration": np.nan,
        "key_press": np.nan,
        "correct_response": np.nan,
        "n_back_condition": np.nan,
        "task": np.nan,
        "probe": np.nan,
        "whichQuadrant": np.nan,
        "task_switch_condition": np.nan,
    }
    rows = [trig]
    onset = 5.0
    for nb in nback_conditions:
        rows.append(
            {
                "exp_id": exp_id,
                "trial_id": "test_trial",
                "time_elapsed": _te(onset),
                "block_duration": _BLOCK_MS,
                "rt": 650,
                "stim_duration": 1000.0,
                "key_press": 71.0,
                "correct_response": 71.0,
                "n_back_condition": nb,
                "task": "spatial",
                "probe": "probe",
                "whichQuadrant": 1.0,
                "task_switch_condition": task_switch_condition,
            }
        )
        onset += 1.5
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


# --------------------------------------------------------------------------- #
# flanker_with_cued_task_switching — switch-factor propagation onto test_trial
# --------------------------------------------------------------------------- #
class TestCuedTSWFlankerSwitchFactorOnTestTrial:
    def test_switch_factor_propagated_to_following_test_trial(self, tmp_path):
        from network_events.create import create_events_df

        raw = _write_cued_ts_flanker_csv(
            tmp_path / "raw_cuedtsflanker.csv",
            cue_switch_pairs=[
                ("switch", "stay"),  # -> switch_stay
                ("stay", "stay"),  # -> stay_stay
                ("switch", "switch"),  # -> switch_switch
                ("na", "na"),  # -> n/a_n/a
            ],
            flankers=["incongruent", "congruent", "incongruent", "congruent"],
        )
        events = create_events_df(raw, "flankerWCuedTS").reset_index(drop=True)

        onsets = pd.to_numeric(events["onset"])
        assert onsets.is_monotonic_increasing

        # Every test_trial carries the switch trial_type of its preceding cue
        # (no n/a left over), and flanker_condition stays on the trial row.
        last_cue_tt = None
        seen_switch_stay = False
        for _, row in events.iterrows():
            if row["trial_id"] == "test_cue":
                last_cue_tt = row["trial_type"]
            elif row["trial_id"] == "test_trial":
                assert row["trial_type"] == last_cue_tt, (
                    f"test_trial trial_type {row['trial_type']!r} != preceding cue "
                    f"{last_cue_tt!r}"
                )
                assert row["trial_type"] != "n/a"
                assert row["flanker_condition"] in {"congruent", "incongruent"}
                if last_cue_tt == "switch_stay":
                    seen_switch_stay = True
        assert seen_switch_stay, "expected a test_trial following a switch_stay cue"


# --------------------------------------------------------------------------- #
# n_back_with_spatial_task_switching — trial_type lowercase normalization
# --------------------------------------------------------------------------- #
class TestNBackWSpatialTSTrialTypeLowercase:
    def test_test_trial_rows_lowercased(self, tmp_path):
        from network_events.create import create_events_df

        raw = _write_nback_spatial_ts_csv(
            tmp_path / "raw_nback_spatialts.csv",
            nback_conditions=["Match", "Mismatch", "match", "mismatch"],
        )
        events = create_events_df(raw, "nBackWSpatialTS").reset_index(drop=True)

        test_trials = events[events["trial_id"] == "test_trial"]
        assert len(test_trials) == 4
        for tt in test_trials["trial_type"]:
            assert tt == tt.lower(), f"trial_type {tt!r} was not lowercased"
        # Mixed-case raw inputs normalize onto the SAME lowercase cells.
        assert set(test_trials["trial_type"]) == {
            "match_tswitch_cswitch",
            "mismatch_tswitch_cswitch",
        }
