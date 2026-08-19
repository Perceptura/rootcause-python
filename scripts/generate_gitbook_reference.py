"""Generate the GitBook API reference page for rootcause-sdk from the source.

GitBook renders markdown out of a git repo, so the built mkdocs HTML site is no
use to it. This script walks the package with griffe (the same static analyser
mkdocstrings uses, so no import side effects at build time) and emits one
GitBook-flavoured markdown page: signatures from the type annotations, prose
from the google-style docstrings.

    python scripts/generate_gitbook_reference.py --output api/sdk-generated-reference.md

The output is machine-written and meant to be overwritten wholesale on every
release; the hand-written reference page in the docs repo is a separate file and
is never touched by this script.
"""

import argparse
import sys
from pathlib import Path

import griffe

REPO_ROOT = Path(__file__).resolve().parent.parent

TITLE = "Python SDK: Generated API Reference"

# (heading, module path, blurb). Order is the reading order of the page.
SECTIONS: list[tuple[str, str, str]] = [
    ("Module functions", "rootcause", "The module-level session and the direct-mode entry points."),
    ("Workspaces and data", "rootcause.workspace", "Workspaces and what lives in them: sources, data views, connectors."),
    ("Twin", "rootcause.twin", "Digital twins: forecast, simulate, intervene, score, update."),
    ("Graph", "rootcause.graph", "Discovered causal graphs, and the domain knowledge pinned onto them."),
    ("Results", "rootcause.results", "The result objects twin operations hand back."),
    ("Ontology", "rootcause.ontology", "Ontology concepts and queries over them."),
    ("Interventions", "rootcause.interventions", "The intervention and metric helpers."),
    ("Notebook apps", "rootcause.jupyter", "Notebook host for the platform's interactive app bundles. Requires the `jupyter` extra."),
    ("Exceptions", "rootcause.errors", "The exception hierarchy every call raises from."),
]

# Internal plumbing that happens not to start with an underscore: used across
# modules inside the package, never part of the user-facing surface.
EXCLUDE = {"compile_where", "compile_do"}

# Names re-exported into `rootcause` but documented under their own module.
TOP_LEVEL_ONLY_FUNCTIONS = [
    "login", "whoami", "workspaces", "workspace", "discover", "load_twin", "render_widget",
]


LINE_LENGTH = 88


def wrap_signature(head: str, params: list[str], tail: str) -> str:
    """One line when it fits, otherwise one parameter per line."""
    single = f"{head}{', '.join(params)}{tail}"
    if len(single) <= LINE_LENGTH:
        return single
    indent = " " * 4
    body = ",\n".join(f"{indent}{param}" for param in params)
    return f"{head}\n{body},\n{tail.lstrip()}"


def signature(obj: griffe.Function, qualifier: str = "") -> str:
    parts = []
    for param in obj.parameters:
        if param.name == "self":
            continue
        if param.kind is griffe.ParameterKind.keyword_only and "*" not in parts:
            parts.append("*")
        rendered = param.name
        if param.annotation is not None:
            rendered += f": {param.annotation}"
        if param.default is not None:
            rendered += f" = {param.default}" if param.annotation is not None else f"={param.default}"
        parts.append(rendered)
    returns = f" -> {obj.returns}" if obj.returns is not None else ""
    return wrap_signature(f"{qualifier}{obj.name}(", parts, f"){returns}")


def render_docstring(obj: griffe.Object) -> list[str]:
    """The docstring as markdown: prose verbatim, sections as tables and blocks."""
    if obj.docstring is None:
        return ["_Undocumented; the signature above is the contract._", ""]

    lines: list[str] = []
    for section in obj.docstring.parsed:
        kind = section.kind
        if kind is griffe.DocstringSectionKind.text:
            lines += [section.value.strip(), ""]
        elif kind is griffe.DocstringSectionKind.parameters:
            lines += ["| Parameter | Type | Default | Description |", "| --- | --- | --- | --- |"]
            for param in section.value:
                annotation = f"`{param.annotation}`" if param.annotation is not None else ""
                default = f"`{param.default}`" if param.default is not None else "required"
                lines.append(
                    f"| `{param.name}` | {annotation} | {default} | {one_line(param.description)} |"
                )
            lines.append("")
        elif kind is griffe.DocstringSectionKind.returns:
            for returned in section.value:
                annotation = f" (`{returned.annotation}`)" if returned.annotation is not None else ""
                lines += [f"**Returns**{annotation}: {one_line(returned.description)}", ""]
        elif kind is griffe.DocstringSectionKind.raises:
            lines += ["**Raises**", ""]
            for raised in section.value:
                lines.append(f"- `{raised.annotation}`: {one_line(raised.description)}")
            lines.append("")
        elif kind is griffe.DocstringSectionKind.examples:
            lines += ["**Examples**", ""]
            for part_kind, part in section.value:
                if part_kind is griffe.DocstringSectionKind.examples:
                    lines += ["```python", part.strip(), "```", ""]
                else:
                    lines += [str(part).strip(), ""]
        else:
            # Any section kind not handled above still reads fine as its own text.
            lines += [str(section.value).strip(), ""]
    return lines


def one_line(text: str) -> str:
    """Collapse a description to one line, safe to drop inside a table cell."""
    return " ".join(text.split()).replace("|", "\\|")


def is_public(name: str) -> bool:
    return not name.startswith("_") and name not in EXCLUDE


def owned_by(obj: griffe.Object, module: griffe.Module) -> bool:
    """True when obj is defined in module, not merely imported into it."""
    return not obj.is_alias and obj.canonical_path.startswith(f"{module.path}.")


def render_function(obj: griffe.Function, qualifier: str, level: int) -> list[str]:
    return [
        f"{'#' * level} {qualifier}{obj.name}",
        "",
        "```python",
        signature(obj, qualifier),
        "```",
        "",
        *render_docstring(obj),
    ]


def render_class(obj: griffe.Class, level: int) -> list[str]:
    lines = [f"{'#' * level} {obj.name}", "", *render_docstring(obj)]
    init = obj.members.get("__init__")
    if isinstance(init, griffe.Function) and init.docstring is not None:
        lines += ["```python", signature(init).replace("__init__", obj.name), "```", "", *render_docstring(init)]

    # griffe models @property as an Attribute labelled "property", not as a
    # Function, so properties have to be collected separately or they vanish.
    properties = [
        member
        for name, member in obj.members.items()
        if is_public(name) and isinstance(member, griffe.Attribute) and "property" in member.labels
    ]
    if properties:
        lines += [f"{'#' * (level + 1)} Properties", ""]
        for prop in sorted(properties, key=lambda m: m.lineno or 0):
            annotation = f" (`{prop.annotation}`)" if prop.annotation is not None else ""
            summary = prop.docstring.value.strip().splitlines()[0] if prop.docstring else ""
            bullet = f"- **{prop.name}**{annotation}"
            lines.append(f"{bullet}: {summary}" if summary else bullet)
        lines.append("")

    methods = [
        member
        for name, member in obj.members.items()
        if is_public(name) and isinstance(member, griffe.Function)
    ]
    for method in sorted(methods, key=lambda m: m.lineno or 0):
        lines += render_function(method, f"{obj.name}.", level + 1)
    return lines


def render_module(module: griffe.Module, heading: str, blurb: str, top_level: bool) -> list[str]:
    lines = [f"## {heading}", "", blurb, ""]
    members = [
        (name, member)
        for name, member in module.members.items()
        if is_public(name) and (top_level or owned_by(member, module))
    ]
    if top_level:
        members = [(n, m) for n, m in members if n in TOP_LEVEL_ONLY_FUNCTIONS]
        members.sort(key=lambda item: TOP_LEVEL_ONLY_FUNCTIONS.index(item[0]))
    else:
        members.sort(key=lambda item: item[1].lineno or 0)
    for name, member in members:
        if isinstance(member, griffe.Function):
            lines += render_function(member, "rc." if top_level else "", 3)
        elif isinstance(member, griffe.Class):
            lines += render_class(member, 3)
    return lines


def build() -> str:
    package = griffe.load(
        "rootcause",
        docstring_parser=griffe.Parser.google,
        resolve_aliases=True,
        search_paths=[str(REPO_ROOT)],
    )
    lines = [f"# {TITLE}", ""]
    for heading, module_path, blurb in SECTIONS:
        module = package if module_path == "rootcause" else package[module_path.split(".", 1)[1]]
        lines += render_module(module, heading, blurb, top_level=module_path == "rootcause")
    text = "\n".join(lines)
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", "-o", type=Path, required=True, help="Path to write the markdown page to.")
    parser.add_argument("--check", action="store_true", help="Exit non-zero when the output would change.")
    args = parser.parse_args()

    rendered = build()
    if args.check:
        current = args.output.read_text() if args.output.exists() else ""
        if current != rendered:
            print(f"{args.output} is stale; regenerate it.", file=sys.stderr)
            return 1
        print(f"{args.output} is up to date.")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered)
    print(f"Wrote {args.output} ({len(rendered.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
