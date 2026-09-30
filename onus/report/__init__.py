"""Sentences that quote a result: a pre-registered verdict only against its recorded read, and exploratory ones.

``render`` re-derives a hypothesis's verdict from the data with ``onus.prereg.evaluate`` and renders it only when
the reads file holds the line its receipt names and that line records this very evaluation, so a hand-built
receipt or a hand-edited evaluation cannot be rendered. Its sentence carries the counts, the sidedness, the
family correction, the minimum detectable effect whenever a read that is not early is not met, and the
provenance, and it reads no clock. ``receipt_from_line`` gives a second process the receipt of a recorded read.
``render_exploratory`` quotes a test result no rule registered, with no verdict. ``assert_quoted`` fails a test
whose document does not quote a rendered sentence exactly, or quotes its result on any line other than that way.
"""

from onus.report._quote import assert_quoted
from onus.report._receipts import receipt_from_line
from onus.report._render import MDE_POWER, render, render_exploratory

__all__ = ["MDE_POWER", "assert_quoted", "receipt_from_line", "render", "render_exploratory"]
