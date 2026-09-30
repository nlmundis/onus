"""Binding a rendered verdict to its recorded read: the receipt, the reads file, and the line they both name."""

from pathlib import Path

from onus.prereg import Evaluation, Horizon, PreregError, ReadReceipt
from onus.prereg._evaluate import read_early
from onus.prereg._reads import ReadLine, find_line, read_file


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


def bound_read(evaluation: Evaluation, *, horizon: Horizon, receipt: ReadReceipt, reads_path: str | Path) -> ReadLine:
    """Return the recorded read that ``receipt`` names, once its line is shown to record ``evaluation``.

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
    line = find_line(read_file(path), receipt.line_sha256, path)
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
    return line
