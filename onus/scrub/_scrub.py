"""Scrubbers: each replaces one kind of run-to-run value in a text with a token that is the same on every run."""

import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date

# What a token's name may be, so a token is always one "<name>" or "<name-N>".
_NAME = re.compile(r"[a-z][a-z0-9_]*\Z")
# The folders macOS keeps under /private and also shows at the root, so one temporary folder has two spellings.
_PRIVATE_TWINS = ("/var", "/tmp", "/etc")
# Not inside a longer word or number: neither side may run on into a letter or a digit, of any script.
_BEFORE = r"(?<![^\W_])"
_AFTER = r"(?![^\W_])"
_DATE = r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
# The clock's ranges are spelled out here, not left to datetime, whose reading of "24:00" differs by Python version.
_HOUR = r"(?:[01][0-9]|2[0-3])"
_SIXTY = r"[0-5][0-9]"
_CLOCK = f"[T ]{_HOUR}:{_SIXTY}"
_SECONDS = f"(?::(?:{_SIXTY}|60)(?:[.,][0-9]+)?)?"
_ZONE = f"(?:Z|[+-]{_HOUR}(?::?{_SIXTY})?)?"
_DATES = re.compile(f"{_BEFORE}{_DATE}(?!{_CLOCK}){_AFTER}")
_TIMESTAMPS = re.compile(f"{_BEFORE}{_DATE}{_CLOCK}{_SECONDS}{_ZONE}{_AFTER}")
# Digits alone, or digits then an exponent: a count, or the digits of a float, never an id.
_NUMBER = re.compile(r"[0-9]+(?:[eE][0-9]*)?\Z")
# The token names this module's own scrubbers write, which a caller's pattern may not reuse.
_OWN_NAMES = frozenset({"date", "timestamp", "uuid", "hex"})
# What may stand in a file's name beside letters and digits, so a path next to one of these is part of a longer path.
_IN_A_NAME = r"\w.~+@-"
_UUIDS = re.compile(f"{_BEFORE}[0-9A-Fa-f]{{8}}(?:-[0-9A-Fa-f]{{4}}){{3}}-[0-9A-Fa-f]{{12}}{_AFTER}")
_HEX_RUNS = re.compile(f"{_BEFORE}[0-9A-Fa-f]+{_AFTER}")


@dataclass(frozen=True)
class Scrubber:
    """A named function from a text to the same text with one kind of run-to-run value replaced.

    It is here so that an approved output can record, by name, which scrubbers shaped it. Call it with a string;
    build one with this module's functions, or wrap a function of your own with ``redactor``. The name is a
    label for a reader, not a proof: nothing stops code from building a ``Scrubber`` under any name.
    """

    name: str
    _replace: Callable[[str], str]

    def __call__(self, text: str) -> str:
        """Return ``text`` scrubbed.

        Raises:
            TypeError: ``text`` is not a string, or the wrapped function returned something that is not one.
        """
        if not isinstance(text, str):
            raise TypeError(f"{self.name} scrubs a text, not {type(text).__name__}")
        scrubbed = self._replace(text)
        if not isinstance(scrubbed, str):
            raise TypeError(f"{self.name} must return a text, not {type(scrubbed).__name__}")
        return scrubbed


def _named(name: str) -> str:
    """Return ``name`` when it can stand in a token.

    Raises:
        ValueError: ``name`` is not a lower-case letter followed by lower-case letters, digits, or underscores.
    """
    if not isinstance(name, str) or not _NAME.match(name):
        raise ValueError(f"a token's name is a lower-case letter, then lower-case letters, digits, or _: not {name!r}")
    return name


def _numbered(
    regex: re.Pattern[str], name: str, *, same: Callable[[str], str], real: Callable[[str], bool]
) -> Callable[[str], str]:
    """Return a function replacing each ``real`` match of ``regex`` with "<name-N>", N counting distinct values.

    Values are numbered from 1 in the order they first appear, and two matches are one value when ``same`` gives
    them one key, so the scrubbed text still shows which values were equal. A match that is not ``real`` stays.
    """

    def replace(text: str) -> str:
        numbers: dict[str, int] = {}

        def token(match: re.Match[str]) -> str:
            if not match[0]:
                raise ValueError(
                    f"the {name} pattern {regex.pattern!r} matched an empty text, so it would put a token between "
                    "letters"
                )
            if not real(match[0]):
                return match[0]
            return f"<{name}-{numbers.setdefault(same(match[0]), len(numbers) + 1)}>"

        return regex.sub(token, text)

    return replace


def _is_date(text: str) -> bool:
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True


def _is_timestamp(text: str) -> bool:
    return _is_date(text[:10])


def _as_written(text: str) -> str:
    return text


def iso_dates() -> Scrubber:
    """Return a scrubber replacing each calendar date written YYYY-MM-DD with "<date-N>".

    Only a real date is replaced: "2026-13-45" stays, and so does the date inside a timestamp, which is
    ``iso_timestamps``'s to replace whole, so the two may run in either order. A date followed by a clock time
    that ``iso_timestamps`` does not read, such as "2026-01-08 25:00", is replaced here; one followed by "T" runs
    on into a letter, and stays.
    """
    return Scrubber("iso_dates", _numbered(_DATES, "date", same=_as_written, real=_is_date))


def iso_timestamps() -> Scrubber:
    """Return a scrubber replacing each ISO 8601 date and time with "<timestamp-N>".

    It reads a date, a "T" or a space, hours and minutes, then optionally seconds, a fraction of a second after
    "." or ",", and "Z" or an offset written "+HH:MM", "+HHMM", or "+HH". Only a real moment is replaced:
    "2026-01-08T25:00" and "2026-01-08T24:00" stay, on every Python version. A timestamp is read as far as it is
    written this way, and what follows it stays in the text. Two timestamps are one value when they are written
    alike; the same moment in two zones is two values.
    """
    return Scrubber("iso_timestamps", _numbered(_TIMESTAMPS, "timestamp", same=_as_written, real=_is_timestamp))


def uuids() -> Scrubber:
    """Return a scrubber replacing each UUID, written 8-4-4-4-12 in hex digits of either case, with "<uuid-N>".

    Letter case does not make two values: a UUID in capitals and the same one in lower case share a number.
    """
    return Scrubber("uuids", _numbered(_UUIDS, "uuid", same=str.lower, real=lambda text: True))


def hex_ids(*lengths: int) -> Scrubber:
    """Return a scrubber replacing each run of hex digits of exactly one of ``lengths`` with "<hex-N>".

    A run counts when neither side runs on into a letter or digit, it is exactly as long as one of ``lengths``
    (40 for a git commit, 64 for a sha256), and it is not written like a number: digits alone, or digits, an
    "e", and more digits, as the end of a float in scientific notation is. This module ships no scrubber for
    numbers, since a statistic that changed must fail its comparison. The cost is an id that happens to be
    written like a number, which stays and fails the comparison visibly: about 1 in 130 ids of 12 digits, and
    under 1 in ten million of 40. For short ids, name what stands round them with ``pattern``. Letter case
    does not make two values. In a ``chain``, put ``uuids`` before a ``hex_ids`` of length 8 or 12, which would
    otherwise replace a UUID's first or last group.

    Raises:
        ValueError: no length is given, or one is not an int of at least 8, below which words such as "facade"
            or "decade" would be read as ids.
    """
    if not lengths or not all(type(length) is int and length >= 8 for length in lengths):
        raise ValueError(f"hex_ids takes the lengths of the ids to replace, each an int of at least 8: not {lengths!r}")
    wanted = frozenset(lengths)

    def real(text: str) -> bool:
        return len(text) in wanted and not _NUMBER.match(text)

    listed = ", ".join(str(length) for length in sorted(wanted))
    return Scrubber(f"hex_ids({listed})", _numbered(_HEX_RUNS, "hex", same=str.lower, real=real))


def pattern(regex: str, name: str) -> Scrubber:
    """Return a scrubber replacing each match of ``regex`` with "<name-N>", numbered by the text matched.

    It is the scrubber for a value this module has no name for, such as a short id that always follows "run-".
    Write the regex so that it cannot match a number the output reports. Two matches are one value only when
    their texts are equal, letter case included. Give each pattern in a chain its own name: two scrubbers that
    write one name each number from 1, so two different values would share a token.

    Raises:
        ValueError: ``name`` cannot stand in a token, or is one this module's own scrubbers write ("date",
            "timestamp", "uuid", "hex"); or, when the scrubber runs, ``regex`` matched an empty text.
        TypeError: ``regex`` is not a string.
        re.error: ``regex`` does not compile.
    """
    if not isinstance(regex, str):
        raise TypeError(f"pattern takes the regex as a string, not {type(regex).__name__}")
    if name in _OWN_NAMES:
        raise ValueError(f"{name!r} is a token name this module's own scrubbers write; give the pattern another")
    replace = _numbered(re.compile(regex), _named(name), same=_as_written, real=lambda text: True)
    return Scrubber(f"pattern({regex!r}, {name!r})", replace)


def _spellings(path: str) -> list[str]:
    """Return ``path`` and, when macOS shows it both under /private and at the root, its other spelling."""
    for twin in _PRIVATE_TWINS:
        if path == twin or path.startswith(twin + "/"):
            return [path, "/private" + path]
        if path == "/private" + twin or path.startswith("/private" + twin + "/"):
            return [path, path.removeprefix("/private")]
    return [path]


def paths(mapping: Mapping[str | os.PathLike[str], str]) -> Scrubber:
    """Return a scrubber replacing each path in ``mapping`` with "<name>", the name the mapping gives it.

    A path is replaced where it stands whole: at the start of a longer path too ("/srv/app/x" becomes "<app>/x"),
    but not where its last folder's name runs on ("/srv/app2" stays), nor where it is the end or the middle of
    another path ("/home/u/srv/app" stays, as does the path of a URL). A letter or digit of any script, or one
    of "_", ".", "~", "+", "@", "-", on either side makes it part of something longer, save a full stop that ends
    a sentence; so a path glued to a flag, as in "-I/srv/app", stays too. The longest path is tried first, so a
    folder mapped inside another mapped folder gets its own name. A path under /var, /tmp, or /etc is replaced in
    its /private spelling as well, and the reverse, because macOS reports a temporary folder either way. Two
    paths may share a name. The tokens are not numbered: the caller named each. The scrubber's own name lists
    those names and not the paths, which differ from one machine and one run to the next.

    Raises:
        ValueError: the mapping is empty; a path is not absolute, is "/" alone, or is given twice under two names
            once its spellings are counted; or a name cannot stand in a token.
        TypeError: ``mapping`` is not a mapping, or a path is neither a string nor an ``os.PathLike`` of one.
    """
    if not isinstance(mapping, Mapping):
        raise TypeError(f"paths takes a mapping from each path to its name, not {type(mapping).__name__}")
    if not mapping:
        raise ValueError("paths needs at least one path: with none it would scrub nothing")
    names: dict[str, str] = {}
    for given, name in mapping.items():
        path = os.fspath(given)
        if not isinstance(path, str):
            raise TypeError(f"paths takes each path as text, not {type(path).__name__}")
        path = path.rstrip("/")
        if not path.startswith("/"):
            raise ValueError(f"paths takes absolute paths below the root, not {os.fspath(given)!r}")
        for spelling in _spellings(path):
            if names.setdefault(spelling, _named(name)) != name:
                raise ValueError(f"{spelling!r} is given two names, {names[spelling]!r} and {name!r}")
    longest_first = sorted(names, key=lambda spelling: (-len(spelling), spelling))
    # Not the end of another path, and not where the last folder's name runs on; a full stop that ends a
    # sentence does not run it on.
    starts = f"(?<![{_IN_A_NAME}])"
    ends = f"(?![{_IN_A_NAME}]*[{_IN_A_NAME.replace('.', '')}])"
    regex = re.compile(starts + "(?:" + "|".join(re.escape(spelling) for spelling in longest_first) + ")" + ends)
    listed = ", ".join(sorted(set(names.values())))
    return Scrubber(f"paths({listed})", lambda text: regex.sub(lambda match: f"<{names[match[0]]}>", text))


def redactor(function: Callable[[str], str]) -> Scrubber:
    """Return ``function``, a caller's own text-to-text rule, as a scrubber named after it.

    This module ships no rule for personal data; a project that has one wraps it here, so that it can stand in a
    ``chain`` and an approved output records that it ran.

    Raises:
        TypeError: ``function`` is not callable, or has no module and qualified name to record, as a
            ``functools.partial`` or an instance has none: wrap it in a named function.
        ValueError: ``function`` is a lambda or is defined inside another function, so its name would not tell it
            from the next one written there.
    """
    module, qualname = getattr(function, "__module__", None), getattr(function, "__qualname__", None)
    if not callable(function) or not isinstance(module, str) or not isinstance(qualname, str):
        raise TypeError(f"redactor takes a named function from a text to a text, not {function!r}")
    if "<" in qualname:
        raise ValueError(f"redactor takes a function defined at a module's or a class's top, not {qualname}")
    return Scrubber(f"redactor({module}.{qualname})", function)


def chain(*scrubbers: Scrubber) -> Scrubber:
    """Return one scrubber that applies ``scrubbers`` in the order given, each to the text the one before it left.

    Raises:
        ValueError: no scrubber is given.
        TypeError: one of them is not a ``Scrubber``; wrap a plain function with ``redactor``, so it has a name.
    """
    if not scrubbers:
        raise ValueError("chain needs at least one scrubber")
    for scrubber in scrubbers:
        if not isinstance(scrubber, Scrubber):
            raise TypeError(f"chain takes Scrubbers, not {scrubber!r}: wrap a plain function with redactor")

    def replace(text: str) -> str:
        for scrubber in scrubbers:
            text = scrubber(text)
        return text

    return Scrubber("chain(" + ", ".join(scrubber.name for scrubber in scrubbers) + ")", replace)
