"""Dual-task create.py fixups and declared-alias parity.

Composite-condition tasks need post-processing beyond the generic
``add_cols``/``_rename_cells`` machinery:

  * ``flanker_with_cued_task_switching`` (cuedTSWFlanker) -- the cued-task-switch
    factor lands only on the ``test_cue`` row; the modeled ``test_trial`` row
    must carry the switch trial_type of its preceding cue, with the flanker
    factor left in its own column.
  * ``shape_matching_with_spatial_task_switching`` (spatialTSWShapeMatching) --
    the acquisition's ``predictable_condition`` carries a ``td_{same,diff,na}``
    task-dimension prefix that the modeled switch-by-shape cells do not.
  * ``n_back_with_spatial_task_switching`` (nBackWSpatialTS) -- the raw
    ``n_back_condition`` mixes case (``Mismatch`` vs ``mismatch``), so the
    composite ``trial_type`` on ``test_trial`` rows must be lowercased for
    consistent cells.

Several exp_ids are declared in both a ``__fmri`` and a bare spelling. As declared
aliases, both must emit the vocabulary the downstream GLM task
config already selects on. ``_GLM_*_SUBSETS`` below are the literal ``subset``
expressions from that config, evaluated with ``DataFrame.query`` exactly as the
consumer does; they are quoted here because this repository does not depend on
the GLM package.

Fixtures are built locally; this package has no raw-jsPsych test helpers to share.
"""
import numpy as np
import pandas as pd
import pytest

from network_events.config import N_DUMMY, TR_SECONDS

_TRIGGER_MS = 60000.0
_DUMMY_MS = N_DUMMY * TR_SECONDS * 1000.0
_BLOCK_MS = 2000.0


def _te(onset_s: float) -> float:
    """Plant time_elapsed so create_events_df recovers events onset ``onset_s``."""
    return _TRIGGER_MS + _BLOCK_MS + _DUMMY_MS + onset_s * 1000.0


def _write_cued_ts_flanker_csv(path, cue_switch_pairs, flankers, cue_correct_response=np.nan, suffix=""):
    """Raw flanker_with_cued_task_switching export.

    The cued-task-switch factor (cue_condition / task_condition) lives ONLY on
    the ``test_cue`` row; ``flanker_condition`` is on both the cue and the
    following ``test_trial`` row. Rows are ordered cue-then-trial per trial, as
    in the real export. ``cue_correct_response`` plants a raw value on the cue
    row, which admits no response. ``suffix`` selects the declared spelling of
    the exp_id; both name the same acquisition.
    """
    exp_id = f"flanker_with_cued_task_switching{suffix}"
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
                "correct_response": cue_correct_response,
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


_SHAPE_CELLS = [
    f"{switch}_{shape}"
    for switch in ("tstay_cstay", "tstay_cswitch", "tswitch_cswitch")
    for shape in ("SSS", "SDD", "SNN", "DSD", "DNN", "DDD", "DDS")
]


def _write_shape_spatial_ts_csv(path, suffix="", feedback=()):
    """Raw shape_matching_with_spatial_task_switching export.

    One correct test_trial per modeled switch-by-shape cell. The acquisition's
    ``makeTaskSwitches`` writes ``predictable_condition`` as
    ``td_{same,diff,na}_<switch cell>``; the task-dimension prefix is cycled
    here so the emitted cells cannot depend on which one a row carried.
    ``feedback`` appends ``(stimulus_text,)`` rows after the trials.
    """
    exp_id = f"shape_matching_with_spatial_task_switching{suffix}"
    base = {
        "exp_id": exp_id,
        "block_duration": _BLOCK_MS,
        "shape_matching_condition": np.nan,
        "task_switch": np.nan,
        "probe": np.nan,
        "target": np.nan,
        "distractor": np.nan,
        "whichQuadrant": np.nan,
        "predictable_condition": np.nan,
        "stimulus": np.nan,
    }
    rows = [{
        **base, "trial_id": "fmri_trigger_initial", "time_elapsed": _TRIGGER_MS,
        "rt": int(_BLOCK_MS), "stim_duration": np.nan,
        "key_press": np.nan, "correct_response": np.nan,
    }]
    onset = 5.0
    dimensions = ("same", "diff", "na")
    for n, cell in enumerate(_SHAPE_CELLS):
        switch, shape = cell.rsplit("_", 1)
        rows.append({
            **base, "trial_id": "test_trial", "time_elapsed": _te(onset),
            "rt": 700, "stim_duration": 1000.0,
            "key_press": 71.0, "correct_response": 71.0,
            "shape_matching_condition": shape,
            "task_switch": "switch" if switch.startswith("tswitch") else "stay",
            "probe": "p", "target": "t", "distractor": "d", "whichQuadrant": 1.0,
            "predictable_condition": f"td_{dimensions[n % 3]}_{switch}",
            "stimulus": "shapes",
        })
        onset += 1.5
    for text in feedback:
        rows.append({
            **base, "trial_id": "feedback_block", "time_elapsed": _te(onset),
            "rt": -1, "stim_duration": 6000.0, "key_press": -1, "correct_response": -1,
            # A break inherits the preceding trial's factors in the raw export.
            "shape_matching_condition": "DDS", "task_switch": "switch",
            "predictable_condition": "td_na_tswitch_cswitch", "stimulus": text,
        })
        onset += 7.0
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
@pytest.mark.parametrize("suffix", ["__fmri", ""])
class TestCuedTSWFlankerSwitchFactorOnTestTrial:
    def test_switch_factor_propagated_to_following_test_trial(self, tmp_path, suffix):
        from network_events.create import create_events_df

        raw = _write_cued_ts_flanker_csv(
            tmp_path / "raw_cuedtsflanker.csv",
            suffix=suffix,
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


@pytest.mark.parametrize("suffix", ["__fmri", ""])
class TestCuedTSWFlankerCueResponsePlaceholder:
    def test_cue_rows_take_the_no_response_placeholder(self, tmp_path, suffix):
        """Both declared spellings apply the cue placeholder."""
        from network_events.create import create_events_df

        raw = _write_cued_ts_flanker_csv(
            tmp_path / "raw_cuedtsflanker_cueresp.csv",
            suffix=suffix,
            cue_switch_pairs=[("switch", "stay"), ("stay", "stay")],
            flankers=["incongruent", "congruent"],
            cue_correct_response=71.0,
        )
        events = create_events_df(raw, "flankerWCuedTS").reset_index(drop=True)

        cues = events[events["trial_id"] == "test_cue"]
        trials = events[events["trial_id"] == "test_trial"]
        assert len(cues) == 2 and len(trials) == 2
        # A cue screen accepts no response, so its raw correct_response is
        # replaced rather than emitted as a modelable answer.
        assert cues["correct_response"].tolist() == ["n/a", "n/a"]
        assert trials["correct_response"].tolist() == [71.0, 71.0]
        # The placeholder is cosmetic: accuracy was already scored from raw values.
        assert cues["acc"].tolist() == [0, 0]
        assert trials["acc"].tolist() == [1, 1]


# --------------------------------------------------------------------------- #
# Declared-alias parity against the downstream GLM subset contract
# --------------------------------------------------------------------------- #
# Verbatim `subset` expressions from the GLM task config. cuedTSWFlanker.yaml
# crosses the propagated switch trial_type with the separate flanker_condition
# column; spatialTSWShapeMatching.yaml selects the 21 composite cells directly.
_GLM_CUEDTSWFLANKER_SUBSETS = {
    "cstay_tstay_congruent": "trial_type == 'stay_stay' and flanker_condition == 'congruent' and key_press == correct_response and response_time >= 0.2",
    "cstay_tstay_incongruent": "trial_type == 'stay_stay' and flanker_condition == 'incongruent' and key_press == correct_response and response_time >= 0.2",
    "cswitch_tstay_congruent": "trial_type == 'switch_stay' and flanker_condition == 'congruent' and key_press == correct_response and response_time >= 0.2",
    "cswitch_tstay_incongruent": "trial_type == 'switch_stay' and flanker_condition == 'incongruent' and key_press == correct_response and response_time >= 0.2",
    "cswitch_tswitch_congruent": "trial_type == 'switch_switch' and flanker_condition == 'congruent' and key_press == correct_response and response_time >= 0.2",
    "cswitch_tswitch_incongruent": "trial_type == 'switch_switch' and flanker_condition == 'incongruent' and key_press == correct_response and response_time >= 0.2",
}

_GLM_SHAPE_SUBSET = "trial_type == '{cell}' and key_press == correct_response and response_time >= 0.2"
_GLM_PERFORMANCE_FEEDBACK_SUBSET = "trial_id == 'break_with_performance_feedback'"


def _as_consumer_reads_it(events, path):
    """Serialize to BIDS TSV and reload the way the GLM runner does."""
    events.to_csv(path, sep="\t", index=False, na_rep="n/a")
    return pd.read_csv(path, sep="\t")


@pytest.mark.parametrize("suffix", ["__fmri", ""])
def test_cued_ts_flanker_aliases_fill_all_six_modeled_cells(tmp_path, suffix):
    from network_events.create import create_events_df

    raw = _write_cued_ts_flanker_csv(
        tmp_path / "raw_cuedtsflanker_glm.csv",
        suffix=suffix,
        cue_switch_pairs=[
            ("stay", "stay"), ("stay", "stay"),
            ("switch", "stay"), ("switch", "stay"),
            ("switch", "switch"), ("switch", "switch"),
        ],
        flankers=["congruent", "incongruent"] * 3,
    )
    events = create_events_df(raw, "flankerWCuedTS")
    tsv = _as_consumer_reads_it(events, tmp_path / "events.tsv")

    trials = tsv[tsv.trial_id == "test_trial"]
    assert trials.trial_type.tolist() == [
        "stay_stay", "stay_stay", "switch_stay",
        "switch_stay", "switch_switch", "switch_switch",
    ]
    # The flanker factor stays in its own column rather than being folded into
    # the trial_type, so each of the six crossed cells selects exactly one trial.
    assert trials.flanker_condition.tolist() == ["congruent", "incongruent"] * 3
    for cell, subset in _GLM_CUEDTSWFLANKER_SUBSETS.items():
        assert len(tsv.query(subset)) == 1, f"{cell} matched no trial for {suffix!r}"
    assert trials.duration.tolist() == [1.0] * 6
    assert tsv.onset.is_monotonic_increasing


@pytest.mark.parametrize("suffix", ["__fmri", ""])
def test_shape_spatial_ts_aliases_fill_all_twenty_one_modeled_cells(tmp_path, suffix):
    from network_events.create import create_events_df

    raw = _write_shape_spatial_ts_csv(tmp_path / "raw_shapespatialts.csv", suffix=suffix)
    events = create_events_df(raw, "spatialTSWShapeMatching")
    tsv = _as_consumer_reads_it(events, tmp_path / "events.tsv")

    # The td_{same,diff,na} task dimension is dropped; the switch-by-shape cell
    # survives whichever prefix the raw row carried.
    assert tsv.trial_type.tolist() == _SHAPE_CELLS
    for cell in _SHAPE_CELLS:
        assert len(tsv.query(_GLM_SHAPE_SUBSET.format(cell=cell))) == 1, cell
    assert tsv.duration.tolist() == [1.0] * 21
    assert tsv.onset.tolist() == pytest.approx([5.0 + 1.5 * n for n in range(21)])


@pytest.mark.parametrize("suffix", ["__fmri", ""])
def test_shape_spatial_ts_aliases_scope_their_breaks(tmp_path, suffix):
    from network_events.create import create_events_df

    raw = _write_shape_spatial_ts_csv(
        tmp_path / "raw_shapespatialts_breaks.csv",
        suffix=suffix,
        feedback=("You completed a block.", "Your accuracy was low."),
    )
    events = create_events_df(raw, "spatialTSWShapeMatching")
    tsv = _as_consumer_reads_it(events, tmp_path / "events.tsv")

    assert events.loc[events.trial_id != "test_trial", "trial_type"].tolist() == ["n/a"] * 2
    breaks = tsv[tsv.trial_id != "test_trial"]
    assert breaks.trial_id.tolist() == ["break", "break_with_performance_feedback"]
    # Neither spelling may leave the inherited tswitch_cswitch_DDS cell on a
    # break, which would otherwise select into a modeled trial regressor.
    assert breaks.trial_type.isna().all()
    assert breaks.duration.tolist() == [6.0, 6.0]
    assert len(tsv.query(_GLM_SHAPE_SUBSET.format(cell="tswitch_cswitch_DDS"))) == 1
    assert len(tsv.query(_GLM_PERFORMANCE_FEEDBACK_SUBSET)) == 1


@pytest.mark.parametrize("suffix", ["__fmri", ""])
@pytest.mark.parametrize("condition, expected", [
    ("td_same_tstay_cswitch", "tstay_cswitch_SSS"),
    ("td_diff_tstay_cswitch", "tstay_cswitch_SSS"),
    ("td_na_tstay_cswitch", "tstay_cswitch_SSS"),
    ("tstay_cswitch", "tstay_cswitch_SSS"),
    ("td_other_tstay_cswitch", "td_other_tstay_cswitch_SSS"),
    ("legacy_td_same_tstay_cswitch", "legacy_td_same_tstay_cswitch_SSS"),
])
def test_shape_spatial_aliases_strip_only_acquisition_prefix(tmp_path, suffix, condition, expected):
    from tests.test_event_semantics import _canonical_run, _create

    raw, output, _ = _canonical_run(tmp_path, task="spatialTSWShapeMatching")
    _write_shape_spatial_ts_csv(raw, suffix=suffix)
    # Minimal trigger + genuine trial, varying only the raw condition field.
    frame = pd.read_csv(raw).iloc[:2].copy()
    frame.loc[1, "predictable_condition"] = condition
    frame.to_csv(raw, index=False)

    _create(tmp_path)
    events = pd.read_csv(output, sep="\t")
    assert events.trial_id.tolist() == ["test_trial"]
    assert events.trial_type.tolist() == [expected]
    assert events.onset.tolist() == pytest.approx([5.0])
    assert events.duration.tolist() == [1.0]
    assert events.response_time.tolist() == [0.7]
    assert events.key_press.tolist() == events.correct_response.tolist() == [71.0]
    assert events.acc.tolist() == [1]
    assert events.shape_matching_condition.tolist() == ["SSS"]
    subset = _GLM_SHAPE_SUBSET.format(cell="tstay_cswitch_SSS")
    assert len(events.query(subset)) == (1 if expected == "tstay_cswitch_SSS" else 0)
