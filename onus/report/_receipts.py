"""Binding a rendered verdict to its recorded read: the receipt, the reads file, and the line they both name."""

from pathlib import Path

from onus.prereg import Evaluation, Horizon, PreregError, ReadReceipt
from onus.prereg._evaluate import read_early
from onus.prereg._reads import ReadLine, find_line, read_file, related_reads


def receipt_from_line(reads_path: str | Path, line_sha256: str) -> ReadReceipt:
    """Return the receipt for the line of the reads file ``reads_path`` whose sha256 is ``line_sha256``.

    A process other than the one that recorded a read gets the read's receipt here, from the line itself, so no
    one builds a receipt by hand.

    Raises:
        PreregError: there is no reads file at ``reads_path``, it holds a line that is not a read/2 line, or no
            line has that sha256.
    """
    path = Path(reads_path).resolve()  # as record_read names it, so the two receipts of one read are equal
    line = find_line(read_file(path), line_sha256, path)
    return ReadReceipt(line.prereg, line.data_sha256, line.at, line.sha256, path)


def re_read_kind(read: ReadLine, earlier: list[ReadLine]) -> str | None:
    """Return what the recorded ``read`` differed in when it superseded another: "data", "record", or "unknown".

    ``earlier`` are the lines before it in its reads file. Those that count are the ones the seal held it to:
    reads of its experiment, or of a record with its file stem. It is "data" when any of them used other data, by
    its hash, whatever the labels; and "record" when none did and one of them was read under another record,
    which is how the same data comes to be given other labels; that read need not be the first one, which
    ``supersedes`` names. Which of the two it is says nothing about any label, since a read on other data needed
    ``supersedes`` whatever its labels were.

    It is "unknown" when the lines before it show neither, which no reads file written from honest evaluations
    does: a line was removed, or one records labels its data does not give. The read is then still a re-read, and
    is quoted as one, with nothing said about why. It is None for a read that superseded none.
    """
    if read.supersedes is None:
        return None
    related = related_reads(earlier, read.experiment, read.stem)
    if any(line.data_sha256 != read.data_sha256 for line in related):
        return "data"
    if any(line.prereg != read.prereg for line in related):
        return "record"
    return "unknown"


def bound_read(
    evaluation: Evaluation, *, horizon: Horizon, receipt: ReadReceipt, reads_path: str | Path
) -> tuple[ReadLine, list[ReadLine]]:
    """Return the recorded read ``receipt`` names, once its line is shown to record ``evaluation``, and those before it.

    The line's ``early`` must be the one its read time gives under ``horizon``, the rule's (``read_early``), so a
    hand-edited flag can neither state the verdict of a read made before its window closed nor withhold one.

    Raises:
        TypeError: ``receipt`` is not a ReadReceipt.
        PreregError: ``reads_path`` is not the file the receipt names, once both are resolved; that file is missing
            or holds a line that is not a read/2 line; no line has the receipt's sha256; or that line's prereg,
            experiment, data_sha256, n, labels, or at differ from the evaluation's or the receipt's, or its early
            from the one its at gives under ``horizon``.
    """
    if not isinstance(receipt, ReadReceipt):
        raise TypeError(f"render needs the ReadReceipt of a recorded read, not {receipt!r}")
    path = Path(reads_path)
    if path.resolve() != Path(receipt.reads_path).resolve():
        raise PreregError(f"the receipt names the reads file {receipt.reads_path}, not {path}")
    lines = read_file(path)
    line = find_line(lines, receipt.line_sha256, path)
    # Each field as the line records it, then what it must equal: the evaluation re-derived here, the receipt, and
    # the flag the line's own read time gives.
    fields: dict[str, tuple[object, ...]] = {
        "prereg": (line.prereg, evaluation.prereg, receipt.prereg),
        "experiment": (line.experiment, evaluation.experiment),
        "data_sha256": (line.data_sha256, evaluation.data_sha256, receipt.data_sha256),
        "n": (line.n, evaluation.n),
        "labels": (line.labels, evaluation.labels()),
        "at": (line.at, receipt.at),
        "early": (line.early, read_early(horizon, line.at)),
    }
    wrong = [name for name, (recorded, *wanted) in fields.items() if any(value != recorded for value in wanted)]
    if wrong:
        raise PreregError(
            f"the read at line sha256 {line.sha256} does not record this evaluation of this data: its {wrong} differ"
        )
    return line, lines[: lines.index(line)]
