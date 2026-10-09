"""Scrubbers that replace run-to-run values in a text, so that two runs' outputs compare byte for byte.

A scrubber is a named function from a text to a text. ``iso_dates``, ``iso_timestamps``, ``uuids``, and
``hex_ids`` each replace one kind of value with a token numbered by the value, "<date-1>", so the scrubbed text
still shows which values were equal; ``pattern`` does the same for a caller's own regex; ``paths`` replaces each
folder a caller names with that name, unnumbered; ``redactor`` wraps a caller's own function; and ``chain``
applies several in order. No rule for personal data ships, and none for numbers: a statistic that changed must
fail its comparison.
"""

from onus.scrub._scrub import Scrubber, chain, hex_ids, iso_dates, iso_timestamps, paths, pattern, redactor, uuids

__all__ = ["Scrubber", "chain", "hex_ids", "iso_dates", "iso_timestamps", "paths", "pattern", "redactor", "uuids"]
