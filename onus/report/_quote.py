"""Checking that a document quotes a rendered sentence exactly, and quotes its result nowhere else."""

import bisect
import re
from collections.abc import Iterator

# A rendered sentence's verdict, just after its hypothesis's name: an early read's, which its provenance follows at
# once (E8), or a decided read's, which the test's clauses follow. The provenance ends every sentence.
_EARLY = (
    r": read early \(read at [0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{6})?\+00:00; "
    r"window closed at [0-9]{4}-[0-9]{2}-[0-9]{2}T12:00:00\+00:00\); "
)
_DECIDED = ": (?:met|not met); "
_VERDICT = "(?:" + _EARLY + "|" + _DECIDED + ")"
_AFTER_ID = r", data sha256 [0-9a-f]{12} over [0-9]+ units; onus [^;\s]+\."
_PROVENANCE = r"prereg (?P<prereg>.+?@[0-9a-f]{12})" + _AFTER_ID
# The sentence render returns: the hypothesis's name and verdict first, and its record's prereg id near the end.
RENDERED = re.compile("(?P<name>.+?)(?:" + _EARLY + "|" + _DECIDED + ".+; )" + _PROVENANCE)
# The provenance of a rendered sentence anywhere in a text. Its prereg id holds no verdict and no "; prereg ": an id
# running on over a verdict would run into another sentence, and one running on over "; prereg " would run from a
# provenance cut short into the next one. Stopping at the next "; prereg " also keeps the search for bodies linear
# in the length of the text, where an id free to run to its end made it quadratic.
_BODY_PROVENANCE = "prereg (?P<prereg>(?:(?!" + _VERDICT + "|; prereg ).)+?@[0-9a-f]{12})" + _AFTER_ID
# The body of a rendered sentence anywhere in a text: its verdict, then, after a decided one, words that name no
# hypothesis (the template's, its family's, its warnings'), then its provenance. It holds no second verdict, so it
# never runs from one sentence's verdict, or a verdict-like phrase in prose, over another sentence's verdict.
BODY = re.compile("(?:" + _EARLY + "|" + _DECIDED + "(?:(?!" + _VERDICT + ").)+?; )" + _BODY_PROVENANCE)
# What opens a line after a line break, which E9 reads with the break as one space: indentation and '>' markers.
_OPENING = re.compile(r"[ \t]*(?:>[ \t]*)*")
# How every prereg id ends: an '@' and the first 12 hex digits of its record's sha256.
_ID_END = re.compile(r"@[0-9a-f]{12}")


def _word(text: str) -> re.Pattern[str]:
    """Return a pattern finding ``text`` where no word character runs on from either end: "fast" is not in "faster"."""
    left = r"(?<!\w)" if re.match(r"\w", text[0]) else ""
    right = r"(?!\w)" if re.match(r"\w", text[-1]) else ""
    return re.compile(left + re.escape(text) + right)


def _by_end(ids: set[str]) -> dict[str, list[str]]:
    """Return the prereg ids ``ids`` keyed by how each ends, its '@' and 12 hex digits, the longest first in each."""
    known: dict[str, list[str]] = {}
    for each in sorted(ids, key=lambda each: (-len(each), each)):
        known.setdefault(each[-13:], []).append(each)
    return known


def _ids_in(text: str, known: dict[str, list[str]]) -> Iterator[tuple[int, int, str]]:
    """Yield where each prereg id of ``known`` (as ``_by_end`` keys them) stands whole in ``text``: start, end, id.

    At each id's end the longest id that ends there is taken, so where one holds another, as "old-layout@X" holds
    "layout@X", the longer is found and the shorter is not; and the text is read once, whatever the number of ids.
    """
    for end in _ID_END.finditer(text):
        found = next((each for each in known.get(end[0], []) if text.endswith(each, 0, end.end())), None)
        if found is not None:
            yield end.end() - len(found), end.end(), found


def _quotes(line: str, name: str, prereg: str, known: dict[str, list[str]]) -> bool:
    """Return whether ``line`` names hypothesis ``name`` of the record ``prereg``, and so quotes its result.

    Inside the body of any rendered sentence the line holds, the prereg id is the one that body names, and the
    hypothesis name is not looked for, since there it would be a word of the template, a family, or a warning. The
    rest of the line is cut at each id of ``known``, those the document's rendered sentences name, and this one. It
    names ``prereg`` where that id is found whole, not inside a longer one, and stands as a word; and it names the
    name where it stands as a word between the ids, so a record whose file stem is the name does not name it.
    """
    parts = BODY.split(line)
    outside, named = parts[::2], parts[1::2]  # the text around the bodies, and the prereg id each body names
    word, mentioned, between = _word(prereg), False, []
    for text in outside:
        start = 0
        for begin, end, found in _ids_in(text, known):
            mentioned = mentioned or (found == prereg and word.match(text, begin) is not None)
            between.append(text[start:begin])
            start = end
        between.append(text[start:])
    has_prereg = prereg in named or mentioned
    has_name = any(_word(name).search(text) for text in between)
    return has_prereg and has_name


def _continued(line: str) -> str:
    """Return ``line`` as it continues the line before it: its opening dropped, and the break before it one space."""
    opening = _OPENING.match(line)
    assert opening is not None  # the pattern matches the empty string
    return " " + line[opening.end() :]


def _lines(lines: list[str], name: str) -> list[tuple[int, int, str]]:
    """Return the lines a document is read as, each as (first line number, last line number, text).

    ``lines`` are the document's, as ``str.splitlines`` splits it. Each is read as it stands, except that a
    rendered sentence, or anything shaped like one, hard-wrapped over lines is read as one line (E9): there each
    break, with the indentation and any '>' markers that open the next line, is one space. Such a sentence runs
    from its body's verdict, or from ``name`` just before it, to its provenance, as ``BODY`` finds them in the
    whole document read that way.
    """
    if not lines:
        return []
    pieces, breaks, length = [lines[0]], [], len(lines[0])  # the document as one line, and where each break stands
    for line in lines[1:]:
        breaks.append(length)
        pieces.append(_continued(line))
        length += len(pieces[-1])
    whole, head = "".join(pieces), _word(name)
    joined = [False] * len(breaks)  # whether the break after each line falls inside a sentence
    for body in BODY.finditer(whole):
        start = body.start()
        before = head.search(whole, max(0, start - len(name)), start)  # only the name, just before the verdict
        if before is not None:
            start = before.start()
        for i in range(bisect.bisect_left(breaks, start), bisect.bisect_left(breaks, body.end())):
            joined[i] = True
    read: list[tuple[int, int, str]] = []
    first, text = 0, lines[0]
    for i, line in enumerate(lines[1:], start=1):
        if joined[i - 1]:
            text += _continued(line)
            continue
        read.append((first + 1, i, text))
        first, text = i, line
    read.append((first + 1, len(lines), text))
    return read


def assert_quoted(doc: str, sentence: str) -> None:
    """Fail unless every line of the text ``doc`` that quotes ``sentence``'s result holds the sentence exactly.

    ``sentence`` is one ``render`` returned, which is one line. A line quotes its result when it names both the
    sentence's hypothesis and its prereg id. Every such line must hold the whole sentence, character for character,
    after any prefix such as markdown's "- " or "> ", and at least one line must. So a stale copy of the result on
    a line of its own fails, wherever in the document it stands, and so do a rounded figure, another wording, and
    a second read of this hypothesis, such as the one a re-read superseded; nothing else is normalized. Lines are
    split as ``str.splitlines`` splits them, except that a quote may be hard-wrapped (E9): a rendered sentence, or
    a copy shaped like one, that runs over line breaks is read as one line, each break with the indentation and
    any '>' markers that open the next line read as one space. So a correct copy wrapped across lines passes, and
    a stale copy wrapped across lines fails. Where such a line is not the sentence, each line it runs over is also
    read on its own, so no line of the document escapes E1 by being read inside a longer one.

    A line names the prereg id or the name where it stands as a word, with no word character running on from
    either end, so "fast" is not named in "faster" or "layout@..." in "old_layout@...". Inside the body of a
    rendered sentence, from its verdict to its onus version, only the prereg id that body names counts: its other
    words belong to the template, its family, or its warnings, so a hypothesis named "warnings" or "power" is not
    named by another hypothesis's sentence. Elsewhere, a prereg id that a rendered sentence in the document names
    is read whole, the longest first, so no shorter id and no name is named inside it: "layout@..." is not named
    in "old-layout@..." when a sentence of that record stands in the document, and a name is not named inside the
    prereg id, as when the record's file stem is the name.

    Known limits: a line quoting another hypothesis of the same record whose name holds this one's as a word
    ("faster" in "much faster") fails too, as does a line naming "old-layout@..." (or "old layout@...", or any id
    holding this one after a character that is not a word character) when no sentence in the document names it. A
    stale copy passes when it shares a line with the exact sentence, or with a line of a wrapped exact copy, and
    when it is written inside the body of another sentence on its line; so does another wording that is not shaped
    like a rendered sentence, hard-wrapped so that no one line names both.

    Raises:
        AssertionError: no line of ``doc`` names the sentence's hypothesis and prereg id, or a line that names them
            does not hold the sentence; the message names that line.
        TypeError: either argument is not a string.
        ValueError: ``sentence`` is not one ``render`` returns: an empty or exploratory sentence, which names no
            hypothesis and prereg id to look for, or one that spans lines.
    """
    if not isinstance(doc, str) or not isinstance(sentence, str):
        raise TypeError(f"assert_quoted compares text, not {type(doc).__name__} and {type(sentence).__name__}")
    rendered = RENDERED.fullmatch(sentence)
    if rendered is None:
        raise ValueError(
            f"assert_quoted checks a sentence render returned, which names its hypothesis and prereg id; {sentence!r} "
            "does not"
        )
    if sentence.splitlines() != [sentence]:
        raise ValueError(
            f"assert_quoted checks a sentence render returned, which is one line; {sentence!r} spans "
            f"{len(sentence.splitlines())}, so no one line of a document could hold it"
        )
    name, prereg = rendered["name"], rendered["prereg"]
    lines = doc.splitlines()
    read = _lines(lines, name)
    ids = {prereg} | {body["prereg"] for *_, text in read for body in BODY.finditer(text)}
    readings: list[tuple[int, int, str]] = []
    for first, last, text in read:
        readings.append((first, last, text))
        if first < last and sentence not in text:  # E1 still holds each line a wrapped read runs over
            readings += [(number, number, lines[number - 1]) for number in range(first, last + 1)]
    known = _by_end(ids)
    quoting = [(first, last, line) for first, last, line in readings if _quotes(line, name, prereg, known)]
    if not quoting:
        raise AssertionError(
            f"the document does not quote the rendered sentence: no line of it names both {name!r} and {prereg}"
        )
    for first, last, line in quoting:
        if sentence not in line:
            where = f"line {first}" if first == last else f"lines {first} to {last}, read as one,"
            raise AssertionError(
                f"{where} of the document quotes {name!r} of {prereg} other than as rendered: {line!r}; the "
                f"rendered sentence is {sentence!r}"
            )
