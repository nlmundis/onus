"""Pre-registered rules: a record fixed before the data, its evaluation, and a receipt for every read.

A rule is a ``prereg/1`` JSON record, named by ``prereg_id``: its file's stem and the first twelve hex digits of
its sha256, so any edit gives it a new id. ``load`` refuses a key the schema does not define, a float where an
exact number belongs, and a bound artifact whose content has changed. ``evaluate`` is pure: it refuses before
the horizon, uses exactly the units the horizon names, and adjusts each declared family. ``record_read`` is the
write: under a lock, it appends a ``read/3`` line to a reads file, with the read time from onus's own clock and
a flag for a read made before a days window closed everywhere, and returns a receipt. It refuses a re-read on
different data unless the line names the first read it supersedes and why. An amendment is a dated file beside
the record holding a whole new record; ``load`` applies it only once an ``onus.signoff`` ledger says it is signed,
and each read labels post hoc the hypotheses an amendment touched that was signed after they were first read.
"""

from onus.prereg._evaluate import Evaluation, HypothesisResult, ReadReceipt, evaluate, record_read, status
from onus.prereg._rule import (
    Amendment,
    BoundArtifactError,
    Horizon,
    HorizonNotReachedError,
    Hypothesis,
    PreregError,
    Rule,
    load,
    prereg_id,
)

__all__ = [
    "Amendment",
    "BoundArtifactError",
    "Evaluation",
    "Horizon",
    "HorizonNotReachedError",
    "Hypothesis",
    "HypothesisResult",
    "PreregError",
    "ReadReceipt",
    "Rule",
    "evaluate",
    "load",
    "prereg_id",
    "record_read",
    "status",
]
