"""Financial calculations for OneJournal.

Current implementation focuses on deterministic FIFO lot matching from confirmed
fills. This module supports CON-03 groundwork and must be aligned with approved
financial contracts before publication-grade use.
"""

from .calculations import (
    FIFO_CALCULATION_VERSION,
    ClosedLotAllocation,
    PnLCalculationResult,
    PnLGroupResult,
    LotAllocationError,
    calculate_fifo_pnl_from_fills,
    build_instrument_key,
)

__all__ = [
    "FIFO_CALCULATION_VERSION",
    "ClosedLotAllocation",
    "PnLCalculationResult",
    "PnLGroupResult",
    "LotAllocationError",
    "calculate_fifo_pnl_from_fills",
    "build_instrument_key",
]
