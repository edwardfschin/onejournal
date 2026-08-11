"""Financial calculations for OneJournal.

Current implementation provides deterministic FIFO lot matching from confirmed
fills and approved option lifecycle allocations. Raw or review-required broker
evidence remains outside financial calculations.
"""

from .calculations import (
    FIFO_CALCULATION_VERSION,
    OPTION_LIFECYCLE_CALCULATION_VERSION,
    ApprovedOptionLifecycleEvent,
    ClosedLotAllocation,
    LifecycleLotAllocation,
    PnLCalculationResult,
    PnLGroupResult,
    LotAllocationError,
    calculate_fifo_pnl_from_fills,
    calculate_fifo_pnl_with_lifecycle_events,
    build_instrument_key,
    build_fill_input_fingerprint,
    build_lifecycle_input_fingerprint,
)

__all__ = [
    "FIFO_CALCULATION_VERSION",
    "OPTION_LIFECYCLE_CALCULATION_VERSION",
    "ApprovedOptionLifecycleEvent",
    "ClosedLotAllocation",
    "LifecycleLotAllocation",
    "PnLCalculationResult",
    "PnLGroupResult",
    "LotAllocationError",
    "calculate_fifo_pnl_from_fills",
    "calculate_fifo_pnl_with_lifecycle_events",
    "build_instrument_key",
    "build_fill_input_fingerprint",
    "build_lifecycle_input_fingerprint",
]
