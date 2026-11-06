# KVM trace analysis

- Observed span: 2.000818148 s
- vCPU TIDs: [1564]
- Event count: 9869
- Timing degraded: False
- Warnings: {'trailing_exit_without_entry': 1}

- Synthetic input remains synthetic; this analyzer cannot establish provenance.
- Entry/exit intervals are wall time, not pure guest CPU time or pure exit handling cost.
- Scheduler latencies require a synchronized cross-CPU trace clock and both scheduler events.
- Rates use first/last relevant events, not requested recording duration.
- One-second bins are sparse; missing rows mean zero; first/last bins may be partial.
- Loss reported only on stderr/collection.log must also be reviewed by the operator.
