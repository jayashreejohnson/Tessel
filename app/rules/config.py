# Tunable thresholds for the deterministic rule engine. Kept as plain
# constants (not DB config) since they're evaluation policy, not applicant data.

# An income-free stretch shorter than this isn't flagged as a gap at all —
# short lags between paychecks are normal and shouldn't enter the evidence trail.
MIN_GAP_DAYS = 14

# How much slack to allow when checking whether a gap falls inside an
# authorized-interruption span, to absorb normal reporting/processing lag
# rather than treating a few-day mismatch as a hard misalignment.
INTERRUPTION_ALIGNMENT_TOLERANCE_DAYS = 7

# Window padding around a gap when searching for transfers "during" it —
# a transfer that lands just before/after the gap's recorded edges can still
# plausibly belong to it.
TRANSFER_WINDOW_BUFFER_DAYS = 7
