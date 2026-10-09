"""Tier-2 sign-offs: ground truth approved by a person, in a hash-chained ledger extended only from a terminal.

``check_signoff`` says what a ledger records of an artifact: SIGNED, UNSIGNED, CHANGED (with a diff), REVOKED, or
CORRUPT, and it fails closed, so one malformed line or one break in the chain makes every artifact CORRUPT. ``record``
and ``revoke`` add a line only after refusing under each variable, on a short list, that an agent session or an
unattended job sets, opening the controlling terminal, showing what would be signed, and reading the first eight hex
digits of its hash typed there. Those refusals are tripwires against a mistake; the control that keeps agent sessions
from signing lives outside this library. Run it as ``python -m onus.signoff record|revoke|check``.
"""

from onus.signoff._ledger import (
    Check,
    CorruptLedgerError,
    Line,
    SignoffError,
    SignoffRefused,
    Status,
    check_signoff,
    record,
    revoke,
)

__all__ = [
    "Check",
    "CorruptLedgerError",
    "Line",
    "SignoffError",
    "SignoffRefused",
    "Status",
    "check_signoff",
    "record",
    "revoke",
]
