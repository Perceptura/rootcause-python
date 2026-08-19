# SDK documentation source

The authored SDK documentation lives here, one markdown file per page. These
files are the single source of truth: CI publishes them to the GitBook docs repo
(`perceptura/public-material/gitbooks-docs`, into `api/`) and builds them into
the mkdocs site alongside the machine-generated API reference.

Filenames match their published path in the docs repo, so the relative links
between pages work in both places unchanged. Two links point outside this set
(`api-access.md` and `rest-api-reference.md`, both pages of the wider docs); the
mkdocs build rewrites those to absolute docs.rootcause.ai URLs, and leaves them
relative for GitBook.

- `sdk-getting-started.md` is the top page: what the SDK is, plus the quickstart.
- The API reference is not here: `scripts/generate_gitbook_reference.py` builds
  it from the docstrings on every pipeline run. It publishes a landing page at
  `sdk-api-reference.md`, the path the hand-written page used to occupy, plus one
  page per module under `sdk-reference/`. The argument tables come from the
  `Args:` sections in the SDK's own docstrings, so edit those rather than the
  output.
