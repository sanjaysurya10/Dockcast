"""Static results page (``make results``; PRD 17 M5) → ``reports/site/index.html``.

Renders the generated reports (``reports/experiments.md``, ``reports/error_analysis.md``) into
one self-contained HTML file (figures inlined), so every number on the page is the one the
pipeline wrote, with its MLflow run ID. Only the Markdown those generators emit is supported:
headings, paragraphs, bullet lists, pipe tables, images, ``**bold**`` and ``code``.
"""

import base64
import html
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from dockcast.evaluation.reports import REPORTS, git_commit

SOURCES = ("experiments.md", "error_analysis.md")
OUT = REPORTS / "site" / "index.html"
CSS = """
:root{--ground:#F4F5F2;--surface:#FFFFFF;--ink:#15201B;--muted:#5A6560;--line:#DDE2DE;
--brand:#0F766E;--brand-ink:#0F5F58;--brand-tint:#E3F1EE}
@media (prefers-color-scheme:dark){:root{--ground:#101614;--surface:#18201D;--ink:#E8ECEA;
--muted:#A3ADA8;--line:#2C3632;--brand:#2DB3A6;--brand-ink:#7FD6CC;--brand-tint:#16302C}}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);
font:16px/1.5 'IBM Plex Sans',system-ui,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px}
section{background:var(--surface);border:1px solid var(--line);border-radius:12px;
padding:16px 24px;margin:0 0 24px}
h1{font-size:1.75rem;margin:0 0 4px}h2{color:var(--brand-ink);margin-top:32px}
code,td{font-family:'IBM Plex Mono',ui-monospace,monospace;font-size:.85rem}
code{background:var(--brand-tint);padding:0 4px;border-radius:4px}
.table{overflow-x:auto}table{border-collapse:collapse;margin:8px 0 16px}
th,td{border-bottom:1px solid var(--line);padding:4px 8px;text-align:left;white-space:nowrap}
th{font-size:.8rem;color:var(--muted)}td.n{text-align:right}
img{max-width:100%;height:auto;border-radius:8px}
p.meta,footer{color:var(--muted);font-size:.875rem}
"""


def _inline(text: str) -> str:
    out = html.escape(text, quote=False)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    return re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _image(src: str, alt: str, base: Path) -> str:
    path = base / src
    if not path.exists():
        return f"<p>missing figure {html.escape(src)}</p>"
    data = base64.b64encode(path.read_bytes()).decode()
    return f'<img src="data:image/png;base64,{data}" alt="{html.escape(alt or path.stem)}">'


def _table(lines: Sequence[str]) -> str:
    head = _cells(lines[0])
    align = ["n" if c.endswith(":") else "" for c in _cells(lines[1])]
    rows = ["<tr>" + "".join(f'<th scope="col">{_inline(h)}</th>' for h in head) + "</tr>"]
    for line in lines[2:]:
        cells = _cells(line)
        rows.append(
            "<tr>"
            + "".join(
                f'<td class="{align[i] if i < len(align) else ""}">{_inline(c)}</td>'
                for i, c in enumerate(cells)
            )
            + "</tr>"
        )
    return '<div class="table"><table>' + "".join(rows) + "</table></div>"


def markdown_to_html(text: str, base: Path) -> str:
    """Convert the generated-report Markdown subset to HTML.

    Args:
        text: Markdown.
        base: Directory that image paths are relative to.

    Returns:
        HTML fragment.
    """
    out: list[str] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("|"):
            block = []
            while i < len(lines) and lines[i].startswith("|"):
                block.append(lines[i])
                i += 1
            out.append(_table(block))
            continue
        if line.startswith("- "):
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append(f"<li>{_inline(lines[i][2:])}</li>")
                i += 1
            out.append("<ul>" + "".join(items) + "</ul>")
            continue
        heading = re.match(r"^(#{1,4}) (.*)$", line)
        image = re.match(r"^!\[(.*)\]\((.*)\)$", line)
        if heading:
            level = len(heading.group(1)) + 1  # the page title is the only h1
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
        elif image:
            out.append(_image(image.group(2), image.group(1), base))
        elif line.strip():
            out.append(f"<p>{_inline(line)}</p>")
        i += 1
    return "\n".join(out)


def build_page(reports: Path = REPORTS, sources: Sequence[str] = SOURCES) -> str:
    """The full HTML page."""
    sections = [
        f"<section>{markdown_to_html((reports / s).read_text('utf-8'), reports)}</section>"
        for s in sources
        if (reports / s).exists()
    ]
    stamp = f"{datetime.now(UTC):%Y-%m-%d %H:%M} UTC · git {git_commit()}"
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en"><head><meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width,initial-scale=1">',
            "<title>DockCast results</title>",
            f"<style>{CSS}</style></head><body><main>",
            "<h1>DockCast results</h1>",
            '<p class="meta">Station-level bike availability forecasts for Dublin Bikes. '
            "Generated from <code>reports/*.md</code> — every number comes from the pipeline "
            f"and cites its MLflow run. Page built {html.escape(stamp)}.</p>",
            *sections,
            "<footer>Dublin Bikes data © Dublin City Council / Smart Dublin, CC BY 4.0. "
            "Weather data © Met Éireann. Code MIT.</footer>",
            "</main></body></html>",
        ]
    )


def main() -> None:
    """``make results``."""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build_page(), encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
