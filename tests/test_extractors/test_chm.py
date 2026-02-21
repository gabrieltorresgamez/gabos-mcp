from pathlib import Path
from unittest.mock import patch

import pytest

from gabos_mcp.extractors.chm import ChmExtractor


@pytest.fixture
def tmp_cache(tmp_path):
    return str(tmp_path / "cache")


@pytest.fixture
def sample_html_dir(tmp_path):
    """Create a directory with sample HTML files simulating CHM extraction output."""
    html_dir = tmp_path / "html"
    html_dir.mkdir()

    (html_dir / "page1.html").write_text(
        "<html><body><h1>Getting Started</h1><p>Welcome to the help file.</p></body></html>"
    )
    (html_dir / "page2.htm").write_text(
        "<html><head><script>alert('x')</script></head>"
        "<body><nav>Nav</nav><h1>API Reference</h1><p>Function details here.</p></body></html>"
    )

    sub = html_dir / "subdir"
    sub.mkdir()
    (sub / "nested.html").write_text("<html><body><h2>Nested Page</h2><p>Some nested content.</p></body></html>")

    # Marker so _extract is considered done
    (html_dir / ".extracted").touch()
    return html_dir


@pytest.fixture
def extractor_with_html(tmp_path, sample_html_dir, tmp_cache):
    """Create an extractor where the HTML extraction step is already done."""
    cache_dir = Path(tmp_cache)
    app = "testapp"
    source = "manual"

    # Symlink the sample HTML into the expected cache location
    chm_cache = cache_dir / app / source / "html"
    chm_cache.parent.mkdir(parents=True, exist_ok=True)
    chm_cache.symlink_to(sample_html_dir)

    chm_path = tmp_path / "test.chm"
    chm_path.touch()  # Dummy file, won't actually be extracted

    return ChmExtractor(apps={app: {source: str(chm_path)}}, cache_dir=tmp_cache)


class TestConvert:
    def test_converts_html_to_markdown(self, extractor_with_html, tmp_cache):
        extractor_with_html._ensure_ready("testapp", "manual")
        md_dir = Path(tmp_cache) / "testapp" / "manual" / "markdown"

        assert (md_dir / "page1.md").exists()
        assert (md_dir / "page2.md").exists()
        assert (md_dir / "subdir" / "nested.md").exists()

    def test_strips_script_and_nav_tags(self, extractor_with_html, tmp_cache):
        extractor_with_html._ensure_ready("testapp", "manual")
        md_dir = Path(tmp_cache) / "testapp" / "manual" / "markdown"

        content = (md_dir / "page2.md").read_text()
        assert "alert" not in content
        assert "Nav" not in content
        assert "API Reference" in content

    def test_marker_prevents_reconversion(self, extractor_with_html, tmp_cache):
        extractor_with_html._ensure_ready("testapp", "manual")
        md_dir = Path(tmp_cache) / "testapp" / "manual" / "markdown"

        # Delete an md file, re-run — marker should prevent reconversion
        (md_dir / "page1.md").unlink()
        extractor_with_html._ready.discard("testapp/manual")
        extractor_with_html._ensure_ready("testapp", "manual")
        assert not (md_dir / "page1.md").exists()


class TestIndex:
    def test_builds_searchable_index(self, extractor_with_html, tmp_cache):
        extractor_with_html._ensure_ready("testapp", "manual")
        index_dir = Path(tmp_cache) / "testapp" / "manual" / "index"
        assert (index_dir / ".indexed").exists()

    def test_search_returns_results(self, extractor_with_html):
        extractor_with_html._ensure_ready("testapp", "manual")
        results = extractor_with_html.search("API Reference", app="testapp", source="manual")
        assert len(results) > 0
        assert any("API Reference" in r["title"] for r in results)

    def test_search_includes_app_field(self, extractor_with_html):
        extractor_with_html._ensure_ready("testapp", "manual")
        results = extractor_with_html.search("welcome", app="testapp")
        assert len(results) > 0
        assert all(r["app"] == "testapp" for r in results)

    def test_search_across_all_apps(self, extractor_with_html):
        extractor_with_html._ensure_ready("testapp", "manual")
        results = extractor_with_html.search("welcome")
        assert len(results) > 0

    def test_search_no_results(self, extractor_with_html):
        extractor_with_html._ensure_ready("testapp", "manual")
        results = extractor_with_html.search("xyznonexistent123")
        assert results == []

    def test_search_source_without_app_raises(self, extractor_with_html):
        with pytest.raises(ValueError, match="Cannot specify source without app"):
            extractor_with_html.search("test", source="manual")


class TestReadPage:
    def test_reads_existing_page(self, extractor_with_html):
        extractor_with_html._ensure_ready("testapp", "manual")
        content = extractor_with_html.read_page("testapp", "manual", "page1.md")
        assert "Getting Started" in content

    def test_rejects_path_traversal(self, extractor_with_html):
        extractor_with_html._ensure_ready("testapp", "manual")
        with pytest.raises(ValueError, match="Invalid path"):
            extractor_with_html.read_page("testapp", "manual", "../../etc/passwd")

    def test_raises_on_missing_page(self, extractor_with_html):
        extractor_with_html._ensure_ready("testapp", "manual")
        with pytest.raises(FileNotFoundError):
            extractor_with_html.read_page("testapp", "manual", "nonexistent.md")


class TestListPages:
    def test_lists_all_pages(self, extractor_with_html):
        extractor_with_html._ensure_ready("testapp", "manual")
        pages = extractor_with_html.list_pages("testapp", "manual", limit=100)
        assert len(pages) == 3

    def test_pagination(self, extractor_with_html):
        extractor_with_html._ensure_ready("testapp", "manual")
        page1 = extractor_with_html.list_pages("testapp", "manual", limit=1, offset=0)
        page2 = extractor_with_html.list_pages("testapp", "manual", limit=1, offset=1)
        assert len(page1) == 1
        assert len(page2) == 1
        assert page1[0]["path"] != page2[0]["path"]


class TestListApps:
    def test_lists_configured_apps(self, extractor_with_html):
        assert extractor_with_html.list_apps() == ["testapp"]

    def test_empty_when_no_apps(self, tmp_cache):
        ext = ChmExtractor(apps={}, cache_dir=tmp_cache)
        assert ext.list_apps() == []


class TestListSources:
    def test_lists_sources_for_app(self, extractor_with_html):
        assert extractor_with_html.list_sources("testapp") == ["manual"]

    def test_unknown_app_raises(self, tmp_cache):
        ext = ChmExtractor(apps={}, cache_dir=tmp_cache)
        with pytest.raises(ValueError, match="Unknown app"):
            ext.list_sources("nonexistent")


class TestValidation:
    def test_unknown_app_raises(self, tmp_cache):
        ext = ChmExtractor(apps={}, cache_dir=tmp_cache)
        with pytest.raises(ValueError, match="Unknown app"):
            ext.search("test", app="nonexistent")

    def test_unknown_source_raises(self, extractor_with_html):
        with pytest.raises(ValueError, match="Unknown source"):
            extractor_with_html.read_page("testapp", "nonexistent", "page.md")


class TestExtract:
    def test_calls_7z(self, tmp_path, tmp_cache):
        chm_path = tmp_path / "test.chm"
        chm_path.touch()

        ext = ChmExtractor(apps={"myapp": {"docs": str(chm_path)}}, cache_dir=tmp_cache)
        html_dir = Path(tmp_cache) / "myapp" / "docs" / "html"

        with patch("gabos_mcp.extractors.chm.subprocess.run") as mock_run:
            ext._extract(chm_path, html_dir)
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert args[0] == "7z"
            assert str(chm_path) in args

    def test_raises_when_7z_missing(self, tmp_path, tmp_cache):
        chm_path = tmp_path / "test.chm"
        chm_path.touch()

        ext = ChmExtractor(apps={"myapp": {"docs": str(chm_path)}}, cache_dir=tmp_cache)
        html_dir = Path(tmp_cache) / "myapp" / "docs" / "html"

        with (
            patch("gabos_mcp.extractors.chm.subprocess.run", side_effect=FileNotFoundError),
            pytest.raises(RuntimeError, match="7z is required"),
        ):
            ext._extract(chm_path, html_dir)
