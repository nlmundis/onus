"""Checking that a document quotes a rendered sentence exactly, and quotes its result nowhere else."""

import re

# A rendered sentence's verdict, just after its hypothesis's name, and its provenance, which ends it.
_VERDICT = ": (?:met|not met|read early); "
_PROVENANCE = r"; prereg (?P<prereg>.+?@[0-9a-f]{12}), data sha256 [0-9a-f]{12} over [0-9]+ units; onus [^;\s]+\."
# The sentence render returns: the hypothesis's name and verdict first, and its record's prereg id near the end.
RENDERED = re.compile("(?P<name>.+?)" + _VERDICT + ".*" + _PROVENANCE)
# The body of a rendered sentence anywhere in a line: its verdict, then words that name no hypothesis (the
# template's, its family's, its warnings'), then its provenance. It holds no second verdict, so it never runs from
# one sentence's verdict, or a verdict-like phrase in prose, over the text before another sentence's provenance.
BODY = re.compile(_VERDICT + "(?:(?!" + _VERDICT + ").)*?" + _PROVENANCE)


def _word(text: str) -> re.Pattern[str]:
    """Return a pattern finding ``text`` where no word character runs on from either end: "fast" is not in "faster"."""
    left = r"(?<!\w)" if re.match(r"\w", text[0]) else ""
    right = r"(?!\w)" if re.match(r"\w", text[-1]) else ""
    return re.compile(left + re.escape(text) + right)


def _quotes(line: str, name: str, prereg: str) -> bool:
    """Return whether ``line`` names hypothesis ``name`` of the record ``prereg``, and so quotes its result.

    Inside the body of any rendered sentence the line holds, the prereg id is the one that body names, and the
    hypothesis name is not looked for, since there it would be a word of the template, a family, or a warning. The
    rest of the line names the prereg id where it stands as a word, and the name where it stands as a word outside
    the prereg id, so a record whose file stem is the name does not name it.
    """
    parts = BODY.split(line)
    outside, named = parts[::2], parts[1::2]  # the text around the bodies, and the prereg id each body names
    has_prereg = prereg in named or any(_word(prereg).search(text) for text in outside)
    has_name = any(_word(name).search(rest) for text in outside for rest in _word(prereg).split(text))
    return has_prereg and has_name


def assert_quoted(doc: str, sentence: str) -> None:
    """Fail unless every line of the text ``doc`` that quotes ``sentence``'s result holds the sentence exactly.

    ``sentence`` is one ``render`` returned, which is one line. A line quotes its result when it names both the
    sentence's hypothesis and its prereg id. Every such line must hold the whole sentence, character for character,
    after any prefix such as markdown's "- " or "> ", and at least one line must. So a stale copy of the result on
    a line of its own fails, wherever in the document it stands, and so do a rounded figure, another wording, and
    a second read of this hypothesis, such as the one a re-read superseded; nothing is normalized. Lines are split
    as ``str.splitlines`` splits them.

    A line names the prereg id or the name where it stands as a word, with no word character running on from
    either end, so "fast" is not named in "faster" or "layout@..." in "old_layout@...". Inside the body of a
    rendered sentence, from its verdict to its onus version, only the prereg id that body names counts: its other
    words belong to the template, its family, or its warnings, so a hypothesis named "warnings" or "power" is not
    named by another hypothesis's sentence. Nor is a name named inside the prereg id, as when the record's file
    stem is the name.

    Known limits, from reading line by line: a line quoting another hypothesis of the same record whose name holds
    this one's as a word ("faster" in "much faster") fails too. A stale copy passes when it shares a line with the
    exact sentence, when it is hard-wrapped so that no one line names both, and when it is written inside the
    body of another sentence.

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
    quoting = [(i, line) for i, line in enumerate(doc.splitlines(), start=1) if _quotes(line, name, prereg)]
    if not quoting:
        raise AssertionError(
            f"the document does not quote the rendered sentence: no line of it names both {name!r} and {prereg}"
        )
    for number, line in quoting:
        if sentence not in line:
            raise AssertionError(
                f"line {number} of the document quotes {name!r} of {prereg} other than as rendered: {line!r}; the "
                f"rendered sentence is {sentence!r}"
            )
