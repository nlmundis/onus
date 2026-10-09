"""Tier-1 approval testing: outputs held to committed files that a working session may re-record.

``ApprovedMixin.assertApproved`` runs a producer, scrubs its output, and compares it byte for byte with an
approved file committed beside the tests; a mismatch fails with a diff, and a missing file fails, never skips.
Recording happens only when ``ONUS_APPROVE_ROOT`` names the checkout, as a project's ``make approve`` target
would set it, so the pull request's diff of the approved files is the review. Each approved file has a record beside it of the producer, its arguments'
hash, and the scrubbers; ``ApprovedProducersAreReal`` fails on a record that names a mock or a function written
among the tests. Ground truth that only a person may approve belongs to ``onus.signoff``, not here.
"""

from onus.baseline._approved import APPROVE_ROOT, ApprovedMixin, ApprovedProducersAreReal

__all__ = ["APPROVE_ROOT", "ApprovedMixin", "ApprovedProducersAreReal"]
