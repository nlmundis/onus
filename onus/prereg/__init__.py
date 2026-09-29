"""Pre-registered rules: a record fixed before the data, its evaluation, and a receipt for every read.

A rule is a ``prereg/1`` JSON record, named by ``prereg_id``: its file's stem and the first twelve hex digits of
its sha256, so any edit gives it a new id. ``load`` refuses a key the schema does not define, a float where an
exact number belongs, and a bound artifact whose content has changed. ``evaluate`` is pure: it refuses before
the horizon, uses exactly the units the horizon names, and adjusts each declared family. ``record_read`` is the
write, appending to a reads file and returning a receipt. Amendments, bound by sign-offs, arrive with
``onus.signoff``.
"""

from onus.prereg._evaluate import Evaluation, HypothesisResult, ReadReceipt, evaluate, record_read, status
from onus.prereg._rule import (
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
