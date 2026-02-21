"""CHM file extraction, conversion, and full-text search."""

import logging
import re
import shutil
import subprocess
import sys
from pathlib import Path

import html2text
from bs4 import BeautifulSoup

from gabos_mcp.utils.search import SearchIndex

logger = logging.getLogger(__name__)

_EMPTY_LINK_RE = re.compile(r"^\s*(\[]\([^)]*\)\s*)+$")


def _clean_markdown(text: str) -> str:
    """Remove CHM navigation artifacts from converted markdown.

    Strips:
    - Navigation breadcrumb lines (starting with **Navigation:**)
    - Lines consisting only of empty markdown links [](url) from image-only nav buttons
    """
    lines = text.splitlines()
    cleaned = [
        line for line in lines if not line.lstrip().startswith("**Navigation:**") and not _EMPTY_LINK_RE.match(line)
    ]
    # Collapse runs of 3+ blank lines down to 2
    result: list[str] = []
    blank_count = 0
    for line in cleaned:
        if line.strip() == "":
            blank_count += 1
            if blank_count <= 2:
                result.append(line)
        else:
            blank_count = 0
            result.append(line)
    return "\n".join(result)


class ChmExtractor:
    """Manages multiple CHM files grouped by application."""

    def __init__(
        self,
        apps: dict[str, dict[str, str]],
        cache_dir: str,
    ):
        """Initialize with app-grouped CHM file mappings.

        Args:
            apps: Mapping of app name -> {source name -> absolute CHM file path}.
            cache_dir: Base directory for extracted/converted/indexed caches.
        """
        self._apps: dict[str, dict[str, Path]] = {
            app: {name: Path(path) for name, path in sources.items()} for app, sources in apps.items()
        }
        self._cache_dir = Path(cache_dir).expanduser()
        self._ready: set[str] = set()

    def _cache_key(self, app: str, source: str) -> str:
        return f"{app}/{source}"

    def _cache_path(self, app: str, source: str) -> Path:
        return self._cache_dir / app / source

    def _validate_app(self, app: str) -> None:
        if app not in self._apps:
            available = ", ".join(sorted(self._apps)) or "(none)"
            raise ValueError(f"Unknown app '{app}'. Available: {available}")

    def _validate_source(self, app: str, source: str) -> None:
        self._validate_app(app)
        if source not in self._apps[app]:
            available = ", ".join(sorted(self._apps[app])) or "(none)"
            raise ValueError(f"Unknown source '{source}' in app '{app}'. Available: {available}")

    def _ensure_ready(self, app: str, source: str) -> None:
        key = self._cache_key(app, source)
        if key in self._ready:
            return
        self._validate_source(app, source)
        cache = self._cache_path(app, source)
        self._extract(self._apps[app][source], cache / "html")
        self._convert(cache / "html", cache / "markdown")
        self._build_index(cache / "markdown", cache / "index")
        self._ready.add(key)

    @staticmethod
    def _find_7z() -> str:
        """Find the 7z executable, checking common install locations on Windows."""
        path = shutil.which("7z")
        if path:
            return path
        if sys.platform == "win32":
            for candidate in [
                Path(r"C:\Program Files\7-Zip\7z.exe"),
                Path(r"C:\Program Files (x86)\7-Zip\7z.exe"),
            ]:
                if candidate.is_file():
                    return str(candidate)
        raise RuntimeError(
            "7z is required to extract CHM files. "
            "Install it with: pacman -S p7zip (Arch) / apt install p7zip-full (Debian) / "
            "brew install p7zip (macOS) / winget install 7zip (Windows)"
        )

    def _extract(self, chm_path: Path, html_dir: Path) -> None:
        marker = html_dir / ".extracted"
        if marker.exists():
            return
        html_dir.mkdir(parents=True, exist_ok=True)
        cmd = self._find_7z()
        subprocess.run(
            [cmd, "x", str(chm_path), f"-o{html_dir}", "-y"],
            check=True,
            capture_output=True,
            text=True,
        )
        marker.touch()

    def _convert(self, html_dir: Path, md_dir: Path) -> None:
        marker = md_dir / ".converted"
        if marker.exists():
            return
        md_dir.mkdir(parents=True, exist_ok=True)

        converter = html2text.HTML2Text()
        converter.body_width = 0
        converter.ignore_images = True
        converter.ignore_links = False

        html_files = list(html_dir.rglob("*.htm")) + list(html_dir.rglob("*.html"))
        for html_file in html_files:
            try:
                raw_html = html_file.read_text(encoding="utf-8", errors="replace")
                soup = BeautifulSoup(raw_html, "html.parser")

                # Strip common CHM navigation/chrome elements
                for tag in soup.find_all(["script", "style", "nav", "header", "footer"]):
                    tag.decompose()

                cleaned_html = str(soup)
                markdown = converter.handle(cleaned_html)
                markdown = _clean_markdown(markdown)

                rel_path = html_file.relative_to(html_dir).with_suffix(".md")
                out_path = md_dir / rel_path
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(markdown, encoding="utf-8")
            except Exception:
                logger.warning("Failed to convert %s, skipping", html_file, exc_info=True)

        marker.touch()

    def _build_index(self, md_dir: Path, index_dir: Path) -> None:
        def documents():
            for md_file in md_dir.rglob("*.md"):
                try:
                    text = md_file.read_text(encoding="utf-8")
                    rel_path = str(md_file.relative_to(md_dir))

                    # Extract title from first non-empty line
                    title = rel_path
                    for line in text.splitlines():
                        line = line.strip()
                        if line:
                            title = line.lstrip("#").strip()
                            break

                    yield rel_path, title, text
                except Exception:
                    logger.warning("Failed to read %s for indexing, skipping", md_file, exc_info=True)

        SearchIndex(index_dir).build(documents())

    def search(self, query: str, app: str | None = None, source: str | None = None, limit: int = 10) -> list[dict]:
        """Search across CHM sources, optionally scoped by app and/or source.

        Args:
            query: Full-text search query.
            app: Scope to a specific app, or None to search all.
            source: Scope to a specific source within an app. Requires app.
            limit: Maximum number of results to return.

        Returns:
            List of dicts with keys: app, source, title, path, score.
        """
        if source and not app:
            raise ValueError("Cannot specify source without app.")

        # Build list of (app, source) pairs to search
        targets: list[tuple[str, str]] = []
        if app and source:
            targets = [(app, source)]
        elif app:
            self._validate_app(app)
            targets = [(app, s) for s in self._apps[app]]
        else:
            for a, sources in self._apps.items():
                targets.extend((a, s) for s in sources)

        results: list[dict] = []
        for a, s in targets:
            self._ensure_ready(a, s)
            index_dir = self._cache_path(a, s) / "index"
            for hit in SearchIndex(index_dir).search(query, limit=limit):
                results.append({"app": a, "source": s, **hit})

        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:limit]

    def read_page(self, app: str, source: str, path: str) -> str:
        """Read a single Markdown page.

        Args:
            app: Application name.
            source: CHM source name within the app.
            path: Relative path to the .md file within the source cache.

        Returns:
            Full Markdown content of the page.

        Raises:
            ValueError: If path attempts directory traversal.
            FileNotFoundError: If the page does not exist.
        """
        self._validate_source(app, source)
        self._ensure_ready(app, source)

        md_dir = self._cache_path(app, source) / "markdown"
        resolved = (md_dir / path).resolve()

        # Path traversal protection
        if not resolved.is_relative_to(md_dir.resolve()):
            raise ValueError("Invalid path: must be within the source's cache directory")

        if not resolved.is_file():
            raise FileNotFoundError(f"Page not found: {path}")

        return resolved.read_text(encoding="utf-8")

    def list_pages(self, app: str, source: str, limit: int = 50, offset: int = 0) -> list[dict]:
        """List pages for a CHM source with pagination.

        Args:
            app: Application name.
            source: CHM source name within the app.
            limit: Maximum number of pages to return.
            offset: Number of pages to skip.

        Returns:
            List of dicts with keys: title, path.
        """
        self._validate_source(app, source)
        self._ensure_ready(app, source)

        md_dir = self._cache_path(app, source) / "markdown"
        pages: list[dict] = []

        for md_file in sorted(md_dir.rglob("*.md")):
            rel_path = str(md_file.relative_to(md_dir))
            title = rel_path
            try:
                for line in md_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line:
                        title = line.lstrip("#").strip()
                        break
            except Exception:
                pass
            pages.append({"title": title, "path": rel_path})

        return pages[offset : offset + limit]

    def list_apps(self) -> list[str]:
        """Return sorted list of configured app names."""
        return sorted(self._apps.keys())

    def list_sources(self, app: str) -> list[str]:
        """Return sorted list of source names for an app.

        Args:
            app: Application name.
        """
        self._validate_app(app)
        return sorted(self._apps[app].keys())
