"""Ensure the generated reference page has an entry in a GitBook SUMMARY.md.

GitBook builds its navigation (and its URLs) from SUMMARY.md, so a page that is
not listed there is invisible. This inserts one nested bullet under the Python
SDK section, immediately after the hand-written reference, and is a no-op when
the entry is already present.
"""

import argparse
import sys
from pathlib import Path

ANCHOR = "* [Python API Reference](api/sdk-api-reference.md)"


def sync(summary: Path, target: str, title: str) -> bool:
    """Insert the entry if missing. Returns True when the file changed."""
    # open(newline="") rather than read_text(newline=""): the latter is 3.13+,
    # and this runs on the 3.12 CI image.
    with summary.open(newline="") as handle:
        raw = handle.read()
    # GitBook writes SUMMARY.md with CRLF; rewriting it with LF would turn a
    # one-line insert into a whole-file diff.
    newline = "\r\n" if "\r\n" in raw else "\n"
    lines = raw.splitlines()
    entry_path = f"({target})"
    if any(entry_path in line for line in lines):
        return False

    for index, line in enumerate(lines):
        if line.strip() == ANCHOR:
            indent = line[: len(line) - len(line.lstrip())]
            lines.insert(index + 1, f"{indent}* [{title}]({target})")
            with summary.open("w", newline="") as handle:
                handle.write(newline.join(lines) + newline)
            return True

    raise SystemExit(
        f"Could not find the anchor entry in {summary}:\n  {ANCHOR}\n"
        "The docs repo's SUMMARY.md has been restructured; update ANCHOR in this script."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summary", type=Path, help="Path to the docs repo's SUMMARY.md")
    parser.add_argument("--target", required=True, help="Repo-relative path of the generated page")
    parser.add_argument("--title", default="Generated API Reference", help="Nav title for the page")
    args = parser.parse_args()

    if sync(args.summary, args.target, args.title):
        print(f"Added {args.target} to {args.summary}")
    else:
        print(f"{args.target} is already in {args.summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
