from pathlib import Path

import pytest

from dockcast.serving.results_page import build_page, markdown_to_html

pytestmark = pytest.mark.unit
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)


def test_markdown_subset_renders_tables_lists_and_inline(tmp_path: Path) -> None:
    (tmp_path / "f.png").write_bytes(PNG)
    md = "\n".join(
        [
            "## E1 — results",
            "MLflow run `abc` · **met** <script>",
            "",
            "| model | MAE |",
            "|---|---:|",
            "| lgbm | 1.461 |",
            "",
            "- one",
            "- two",
            "![](f.png)",
        ]
    )
    out = markdown_to_html(md, tmp_path)
    assert "<h3>E1 — results</h3>" in out
    assert "<code>abc</code>" in out and "<strong>met</strong>" in out
    assert "&lt;script&gt;" in out and "<script>" not in out
    assert '<td class="n">1.461</td>' in out and '<th scope="col">MAE</th>' in out
    assert out.count("<li>") == 2
    assert 'src="data:image/png;base64,' in out


def test_page_includes_every_report_and_credits(tmp_path: Path) -> None:
    (tmp_path / "experiments.md").write_text("# Experiments\nrun `r1`\n", encoding="utf-8")
    (tmp_path / "error_analysis.md").write_text("# Error analysis\nrun `r1`\n", encoding="utf-8")
    page = build_page(tmp_path)
    assert page.startswith("<!doctype html>") and page.count("<section>") == 2
    assert "CC BY 4.0" in page and "Met Éireann" in page
    assert "prefers-color-scheme" in page
