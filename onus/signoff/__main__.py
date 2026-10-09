"""The command line of onus.signoff: ``python -m onus.signoff record|revoke|check``."""

import argparse
import sys
from collections.abc import Sequence

from onus.signoff._ledger import SignoffError, Status, check_signoff, record, revoke

# No verdict shares an exit code with a usage error (2) or a crash (1).
EXIT = {Status.SIGNED: 0, Status.UNSIGNED: 10, Status.CHANGED: 11, Status.REVOKED: 12, Status.CORRUPT: 13}
EXIT_REFUSED = 20


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command and return its exit code: 0 only for a line written or an artifact that is SIGNED."""
    parser = argparse.ArgumentParser(prog="python -m onus.signoff", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    signing = commands.add_parser("record", help="sign an artifact's content, from a terminal")
    revoking = commands.add_parser("revoke", help="revoke an artifact's newest sign-off, from a terminal")
    checking = commands.add_parser("check", help="say what the ledger records of an artifact")
    for command in (signing, revoking, checking):
        command.add_argument("ledger")
        command.add_argument("artifact")
    for command in (signing, checking):
        command.add_argument("path")
    for command in (signing, revoking):
        command.add_argument("--reviewed-by", required=True, help="the name written into the ledger")
    signing.add_argument("--bind", action="append", default=[], help="a file the approval depends on (repeatable)")
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            check = check_signoff(args.ledger, args.artifact, args.path)
            print(f"{check.status.name}: {check.detail}")
            if check.diff:
                print(check.diff, end="")
            return EXIT[check.status]
        if args.command == "record":
            line = record(args.ledger, args.artifact, args.path, reviewed_by=args.reviewed_by, bind=args.bind)
        else:
            line = revoke(args.ledger, args.artifact, reviewed_by=args.reviewed_by)
    except (SignoffError, NotImplementedError, OSError) as error:
        # An OSError is a ledger, a kept copy, or a content that cannot be read or written: no verdict, no line.
        print(f"refused: {error}", file=sys.stderr)
        return EXIT_REFUSED
    print(f"written: line {line.line_sha256}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
