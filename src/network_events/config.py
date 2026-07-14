"""Vendored study acquisition constants (from neuro_workflow.core.acquisition).

These are r01network acquisition facts, kept here so network_events has no
dependency on network_fmri for two numbers.
"""
TR_SECONDS = 1.49   # repetition time of the BOLD acquisition (seconds)
N_DUMMY = 7         # dummy volumes discarded upstream (trim_bold)
