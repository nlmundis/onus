"""Sentences that quote a result: a pre-registered verdict only against its recorded read, and exploratory ones.

``render`` re-derives a hypothesis's verdict from the data with ``onus.prereg.evaluate`` and renders it only when
the reads file holds the line its receipt names and that line records this very evaluation, so a hand-built
receipt or a hand-edited evaluation cannot be rendered. Its sentence carries the counts, the sidedness, the
family correction, the minimum detectable effect whenever a read that is not early is not met, and the
provenance; an early read's says only when it was read and when its window closed, beside the provenance. A
re-read on different data, early or not, names the first read; one of the same data under a different record
does once it is not early. It reads no clock. ``receipt_from_line`` gives a second process the receipt of a
recorded read. ``render_exploratory`` quotes a test result no rule registered, with no verdict.
"""

from onus.report._receipts import receipt_from_line
from onus.report._render import MDE_POWER, render, render_exploratory

__all__ = ["MDE_POWER", "receipt_from_line", "render", "render_exploratory"]
