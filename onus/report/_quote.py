"""Checking that a document quotes a rendered sentence exactly."""


def assert_quoted(doc: str, sentence: str) -> None:
    """Fail unless the text ``doc`` holds ``sentence``, as ``render`` returned it, character for character.

    The check is a plain substring test: nothing is normalized, so a document that wraps the sentence across
    lines, rounds one of its figures, or quotes an older rendering fails. Keep each quoted sentence on one line.
    It looks for no other copy: a document that holds the exact sentence and, elsewhere, a copy with other
    figures passes.

    Raises:
        AssertionError: ``doc`` does not hold ``sentence``, so a test calling this fails.
        TypeError: either argument is not a string.
        ValueError: ``sentence`` is empty, which every document would hold.
    """
    if not isinstance(doc, str) or not isinstance(sentence, str):
        raise TypeError(f"assert_quoted compares text, not {type(doc).__name__} and {type(sentence).__name__}")
    if not sentence:
        raise ValueError("the sentence is empty, which every document holds; pass the sentence render returned")
    if sentence not in doc:
        raise AssertionError(f"the document does not quote the rendered sentence exactly: {sentence!r}")
