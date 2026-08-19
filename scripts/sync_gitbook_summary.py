"""Ensure the generated reference page has an entry in a GitBook SUMMARY.md.

GitBook builds its navigation (and its URLs) from SUMMARY.md, so a page that is
not listed there is invisible. This inserts one nested bullet under the Python
SDK section, immediately after the hand-written reference, and is a no-op when
the entry is already present.
"""

import argparse
import sys
from pathlib import Path

ANCHOR = "* [Interactive Apps in Notebooks](api/sdk-notebook-apps.md)"


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


def remove(summary: Path, target: str) -> bool:
    """Drop the entry for a retired page. Returns True when the file changed."""
    with summary.open(newline="") as handle:
        raw = handle.read()
    newline = "\r\n" if "\r\n" in raw else "\n"
    lines = raw.splitlines()
    kept = [line for line in lines if f"({target})" not in line]
    if len(kept) == len(lines):
        return False
    with summary.open("w", newline="") as handle:
        handle.write(newline.join(kept) + newline)
    return True


def set_children(summary: Path, parent: str, children: list[tuple[str, str]]) -> bool:
    """Replace the nested entries under a parent page. Returns True when changed.

    GitBook derives both the navigation and the child URLs from this nesting, so
    the whole block is rewritten: a page that no longer exists loses its entry
    instead of leaving a dead link in the sidebar.
    """
    with summary.open(newline="") as handle:
        raw = handle.read()
    newline = "\r\n" if "\r\n" in raw else "\n"
    lines = raw.splitlines()

    for index, line in enumerate(lines):
        if f"({parent})" not in line:
            continue
        indent = len(line) - len(line.lstrip())
        end = index + 1
        while end < len(lines) and lines[end].strip() and (len(lines[end]) - len(lines[end].lstrip())) > indent:
            end += 1
        wanted = [f"{' ' * (indent + 2)}* [{title}]({path})" for path, title in children]
        if lines[index + 1:end] == wanted:
            return False
        lines[index + 1:end] = wanted
        with summary.open("w", newline="") as handle:
            handle.write(newline.join(lines) + newline)
        return True

    raise SystemExit(f"Could not find an entry for {parent} in {summary}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summary", type=Path, help="Path to the docs repo's SUMMARY.md")
    parser.add_argument("--target", required=True, help="Repo-relative path of the generated page")
    parser.add_argument("--title", default="Python API Reference", help="Nav title for the page")
    parser.add_argument(
        "--remove", action="store_true",
        help="Drop the entry for a retired page instead of ensuring it exists.",
    )
    parser.add_argument(
        "--child", action="append", default=[], metavar="PATH|TITLE",
        help="A page to nest under --target. Repeatable; the whole child block is replaced.",
    )
    args = parser.parse_args()

    if args.child:
        children = []
        for spec in args.child:
            path, _, title = spec.partition("|")
            if not title:
                raise SystemExit(f'--child needs "path|Title", got "{spec}"')
            children.append((path, title))
        if set_children(args.summary, args.target, children):
            print(f"Nested {len(children)} pages under {args.target} in {args.summary}")
        else:
            print(f"The {len(children)} pages under {args.target} are already listed")
        return 0

    if args.remove:
        if remove(args.summary, args.target):
            print(f"Removed {args.target} from {args.summary}")
        else:
            print(f"{args.target} is not in {args.summary}")
        return 0

    if sync(args.summary, args.target, args.title):
        print(f"Added {args.target} to {args.summary}")
    else:
        print(f"{args.target} is already in {args.summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
