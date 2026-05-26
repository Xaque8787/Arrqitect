"""
Frozen Phase 1 status vocabulary.

These enums are the canonical source of truth for all status values
stored in the database and returned by the API. Application code must
import from here — bare string literals for statuses are prohibited.

Step status semantics:
  SUCCESS          — step completed successfully
  CONTINUE_SUCCESS — step failed but on_error: continue allowed execution to proceed;
                     satisfies dependency requirements but is NOT success for metrics
  FAILED           — blocking failure; downstream steps are skipped
  TIMEOUT          — timed out; treated as FAILED for dependency purposes
  SKIPPED          — did not execute (when: false, or unsatisfied dependency);
                     "not executed" = "not available downstream" regardless of cause
  OBSOLETE         — reserved for Phase 5 reconcile supersession; not used in Phase 1

Job status semantics:
  PENDING   — enqueued, not yet running
  RUNNING   — currently executing
  SUCCESS   — all steps succeeded (no CONTINUE_SUCCESS steps)
  DEGRADED  — completed but one or more steps reached CONTINUE_SUCCESS
  FAILED    — job could not complete
  CANCELLED — explicitly cancelled
  OBSOLETE  — reserved Phase 5

Dependency satisfaction table:
  SUCCESS          → satisfies downstream
  CONTINUE_SUCCESS → satisfies downstream (but job is DEGRADED)
  FAILED           → does NOT satisfy; downstream → SKIPPED
  TIMEOUT          → does NOT satisfy; downstream → SKIPPED
  SKIPPED          → does NOT satisfy; downstream → SKIPPED
  OBSOLETE         → does NOT satisfy
"""

from enum import Enum


class StepStatus(str, Enum):
    SUCCESS          = "success"
    CONTINUE_SUCCESS = "continue_success"
    FAILED           = "failed"
    TIMEOUT          = "timeout"
    SKIPPED          = "skipped"
    OBSOLETE         = "obsolete"


class JobStatus(str, Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    SUCCESS   = "success"
    DEGRADED  = "degraded"
    FAILED    = "failed"
    CANCELLED = "cancelled"
    OBSOLETE  = "obsolete"


class ValidatorSeverity(str, Enum):
    ERROR   = "error"    # template rejected
    WARNING = "warning"  # template accepted, surfaced prominently
    INFO    = "info"     # advisory only


# Steps that allow downstream execution
DEPENDENCY_SATISFYING: frozenset[StepStatus] = frozenset([
    StepStatus.SUCCESS,
    StepStatus.CONTINUE_SUCCESS,
])

# Steps that are terminal (will not transition further)
TERMINAL_STEPS: frozenset[StepStatus] = frozenset([
    StepStatus.SUCCESS,
    StepStatus.CONTINUE_SUCCESS,
    StepStatus.FAILED,
    StepStatus.TIMEOUT,
    StepStatus.SKIPPED,
    StepStatus.OBSOLETE,
])
