"""Vendored study acquisition constants (from the source repo's core.acquisition
module).

These are r01network acquisition facts, kept here so network_events has no
cross-package dependency for two numbers.
"""
TR_SECONDS = 1.49   # repetition time of the BOLD acquisition (seconds)
N_DUMMY = 7         # dummy volumes discarded upstream (trim_bold)
