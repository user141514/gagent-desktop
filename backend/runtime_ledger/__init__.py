"""Runtime Ledger: standard JSONL trajectory events for harness observability.

This package records what actually happened during an agent run. It is not a
prompt or memory layer. It is the factual event ledger that later modules can
query for failure experience, decision quality, and smoke-test evidence.
"""

from .ledger import (
    LedgerEvent,
    default_ledger_dir,
    new_run_id,
    read_run_events,
    summarize_run,
    write_event,
)

__all__ = [
    "LedgerEvent",
    "default_ledger_dir",
    "new_run_id",
    "read_run_events",
    "summarize_run",
    "write_event",
]
