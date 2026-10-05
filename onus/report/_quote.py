"""Checking that every marked quote in a document is a rendered sentence, and that every sentence is quoted."""

import re

OPEN = "<!-- onus:quote -->"
CLOSE = "<!-- /onus:quote -->"
# What both markers hold, and nothing else in a document may: wherever it stands, in any case, a marker was meant.
_MENTION = re.compile("onus:quote", re.IGNORECASE)


def _line(doc: str, position: int) -> int:
    """Return the number of the line of ``doc`` that holds ``position``, counting line feeds from 1."""
    return doc.count("\n", 0, position) + 1


def _one_spaced(text: str) -> str:
    """Return ``text`` with its ends stripped and every run of whitespace, as ``str.split`` reads it, as one space."""
    return " ".join(text.split())


def _stands(doc: str, marker: str, mention: int) -> bool:
    """Return whether ``marker`` stands in ``doc`` exactly, with its "onus:quote" at ``mention``."""
    start = mention - marker.index("onus:quote")
    return start >= 0 and doc.startswith(marker, start)


def _spans(doc: str) -> list[tuple[int, str]]:
    """Return each marked span of ``doc``: the line of its opening marker, and the text between its two markers.

    Raises:
        AssertionError: "onus:quote" stands, in any case, anywhere but in an exact marker; a closing marker has no
            opening one before it; an opening marker stands inside a span; or a span is never closed. Each would
            leave text that was meant as a quote unchecked.
    """
    spans: list[tuple[int, str]] = []
    opened: tuple[int, int] | None = None  # where the open span's opening marker starts and ends
    for mention in _MENTION.finditer(doc):
        where = f"line {_line(doc, mention.start())} of the document"
        marker = next((each for each in (OPEN, CLOSE) if _stands(doc, each, mention.start())), None)
        if marker is None:
            raise AssertionError(
                f"{where} mentions {mention[0]!r} outside an exact marker, {OPEN!r} or {CLOSE!r}: a marker that is "
                "not exact marks nothing, and its quote would go unchecked"
            )
        start = mention.start() - marker.index("onus:quote")
        if marker == OPEN:
            if opened is not None:
                raise AssertionError(
                    f"{where} opens a quote inside the one opened at line {_line(doc, opened[0])}, which has no "
                    f"{CLOSE!r} yet"
                )
            opened = (start, start + len(OPEN))
        else:
            if opened is None:
                raise AssertionError(f"{where} closes a quote that no {OPEN!r} opened")
            spans.append((_line(doc, opened[0]), doc[opened[1] : start]))
            opened = None
    if opened is not None:
        raise AssertionError(f"the quote opened at line {_line(doc, opened[0])} of the document is never closed")
    return spans


def assert_quoted(doc: str, sentences: list[str] | tuple[str, ...]) -> None:
    """Fail unless the quotes marked in the text ``doc`` are exactly the rendered ``sentences``.

    A quote is marked by hand: the comment ``<!-- onus:quote -->`` before it and ``<!-- /onus:quote -->`` after it,
    which Markdown and HTML do not show. Every marked span must hold one of ``sentences``, and every sentence must
    stand in at least one span. So a stale copy inside markers fails, whatever record or read it came from, since
    it is none of the sentences; a rounded figure or another wording fails; and a sentence the document never
    quotes fails. The sentences are what ``render`` and ``render_exploratory`` returned; none is parsed.

    A span is compared with a sentence after the ends of each are stripped and every run of whitespace in each, as
    ``str.split`` reads it, is read as one space. So a quote may be hard-wrapped or indented, and nothing else may
    differ: not a character, and not a ``>`` that a wrapped line inside a blockquote would open with.

    Only marked text is checked. A copy of a result outside any markers is not found, and is not this function's to
    find: mark every quote. So that no quote goes unmarked by a slip, "onus:quote" may stand in the document only
    inside an exact marker: a marker with other spacing, in another case, or left unfinished fails, and so does
    prose that names the marker, or shows it as an example outside a span.

    Raises:
        AssertionError: a span holds none of the sentences; a sentence stands in no span; or the markers are
            malformed: "onus:quote" outside an exact marker, a closing marker with no opening one, an opening
            marker inside a span, or a span never closed. The message names the line.
        TypeError: ``doc`` is not a string, or ``sentences`` is not a list or tuple of strings; a single string is
            refused, not read as its characters.
        ValueError: ``sentences`` is empty, or one of them is empty, is only whitespace, or holds "onus:quote".
    """
    if not isinstance(doc, str):
        raise TypeError(f"assert_quoted reads a document's text, not {type(doc).__name__}")
    if not isinstance(sentences, (list, tuple)) or not all(isinstance(each, str) for each in sentences):
        raise TypeError("assert_quoted takes the rendered sentences as a list or tuple of strings")
    if not sentences:
        raise ValueError("assert_quoted needs at least one rendered sentence: with none, no quote could be right")
    wanted: dict[str, str] = {}
    for sentence in sentences:
        if not sentence.strip() or _MENTION.search(sentence):
            raise ValueError(
                f"{sentence!r} is not a sentence a document can quote: it is empty, or it holds the marker's own "
                'words, "onus:quote"'
            )
        wanted[_one_spaced(sentence)] = sentence
    found: set[str] = set()
    for line, text in _spans(doc):
        quote = _one_spaced(text)
        if quote not in wanted:
            raise AssertionError(
                f"the quote marked at line {line} of the document is none of the rendered sentences: {quote!r}"
            )
        found.add(quote)
    missing = [sentence for quote, sentence in wanted.items() if quote not in found]
    if missing:
        raise AssertionError(f"the document marks no quote of the rendered sentence {missing[0]!r}")
