"""Company Rules & Standards package.

Prefer importing from ``refactory.company`` — this namespace is reserved
for a future thin alias only. The broken PolicyEngine stub was removed.
"""

from refactory.company import (
    CompanyRulesChecker,
    GateOutcome,
    GateResult,
)

__all__ = [
    "CompanyRulesChecker",
    "GateOutcome",
    "GateResult",
]
