"""CHM file extraction, conversion, and full-text search."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import operator
import re
import shutil
import sys
import urllib.parse
import warnings
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from collections.abc import Iterator

import aiofiles
import html2text
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from gabos_mcp.utils.search import SearchIndex

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

logger = logging.getLogger(__name__)

_EMPTY_LINK_RE = re.compile(r"^\s*(\[]\([^)]*\)\s*)+$")
_MAX_BLANK_LINES = 2

# Matches markdown links: [display](url) or [display](url "title")
# Display text may contain one level of nested brackets (e.g. [[1]](url) footnotes).
# URL may contain backslash-escaped parentheses.
_LINK_RE = re.compile(
	r"\[(\[?[^\]]*\]?)\]"
	r"\(\s*"
	r'((?:[^\s"\'()>\\]|\\.)+)'
	r'(?:\s+"(?:[^"\\]|\\.)*"'
	r"|\s+\'(?:[^\'\\]|\\.)*\')?"
	r"\s*\)"
)

_MS_ITS_RE = re.compile(r"ms-its:[^:]+::/?(.*)", re.IGNORECASE)

# Unicode bullet characters used as plain-text list markers in CHM HTML
_UNICODE_BULLET_RE = re.compile(r"^(\s*)[•·◦○●◉]\s*", re.MULTILINE)


def _is_external(url: str) -> bool:
	return url.startswith(("http://", "https://", "mailto:", "ftp://"))


def _fix_links(text: str) -> str:
	"""Normalize internal CHM links in converted markdown.

	- Decodes percent-encoded URLs (cp1252 aware, including %91-%94 curly quotes)
	- Strips ms-its: cross-CHM prefixes
	- Converts internal .htm/.html links to .md paths
	- Removes empty-display links (nav image buttons)
	- Leaves external links unchanged

	Returns:
	    Markdown string with normalized links.
	"""

	def replace(m: re.Match[str]) -> str:
		display = m.group(1)
		raw_url = m.group(2).strip()

		# Remove backslash escapes that html2text introduces in URLs
		raw_url = re.sub(r"\\(.)", r"\1", raw_url)

		# Strip cp1252 curly-quote percent-encodings that wrap some URLs
		raw_url = re.sub(r"^(%9[1234])+|(%9[1234])+$", "", raw_url, flags=re.IGNORECASE)

		url = urllib.parse.unquote(raw_url, encoding="cp1252")

		if _is_external(url):
			return f"[{display}]({url})" if display else url

		ms_its = _MS_ITS_RE.match(url)
		if ms_its:
			url = ms_its.group(1)

		anchor = ""
		if "#" in url:
			url, anchor = url.split("#", 1)

		if not url.lower().endswith((".htm", ".html")):
			return m.group(0)

		# Empty display = nav image button → remove entirely
		if not display:
			return ""

		md_path = Path(url).with_suffix(".md")
		anchor_suffix = f"#{anchor}" if anchor else ""
		return f"[{display}]({md_path}{anchor_suffix})"

	return _LINK_RE.sub(replace, text)


def _canonical_key(path: Path) -> tuple[int, str]:
	"""Sort key preferring the base name over numbered variants (e.g. foo.md before foo_10.md).

	Returns:
	    Tuple of (numeric suffix or 0, stem) for stable sorting.
	"""
	m = re.search(r"_(\d+)$", path.stem)
	return (int(m.group(1)) if m else 0, path.stem)


def _deduplicate(md_dir: Path) -> None:
	"""Remove byte-identical markdown files, keeping one canonical copy per unique page.

	CHM authoring tools generate one file per context-sensitive help ID, so many files
	may have identical content. Deduplication prevents search index bloat.
	"""
	by_hash: dict[str, list[Path]] = {}
	for md_file in md_dir.rglob("*.md"):
		digest = hashlib.md5(md_file.read_bytes()).hexdigest()  # noqa: S324
		by_hash.setdefault(digest, []).append(md_file)

	removed = 0
	for files in by_hash.values():
		if len(files) < 2:  # noqa: PLR2004
			continue
		files.sort(key=_canonical_key)
		for dup in files[1:]:
			dup.unlink()
			removed += 1

	if removed:
		logger.info("Removed %d duplicate files (identical content)", removed)


def _clean_markdown(text: str) -> str:
	"""Remove CHM navigation artifacts from converted markdown.

	Strips:
	- Navigation breadcrumb lines (starting with **Navigation:**)
	- Lines consisting only of empty markdown links [](url) from image-only nav buttons

	Returns:
	    Cleaned markdown string with navigation artifacts removed.
	"""
	lines = text.splitlines()
	cleaned = [
		line for line in lines if not line.lstrip().startswith("**Navigation:**") and not _EMPTY_LINK_RE.match(line)
	]
	# Collapse runs of 3+ blank lines down to 2
	result: list[str] = []
	blank_count = 0
	for line in cleaned:
		if not line.strip():
			blank_count += 1
			if blank_count <= _MAX_BLANK_LINES:
				result.append(line)
		else:
			blank_count = 0
			result.append(line)
	joined = "\n".join(result).strip()
	return _UNICODE_BULLET_RE.sub(r"\1- ", joined)


class ChmExtractor:
	"""Manages multiple CHM files grouped by application."""

	def __init__(
		self,
		apps: dict[str, dict[str, str]],
		cache_dir: str,
	) -> None:
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
		self._locks: dict[str, asyncio.Lock] = {}
		self._global_lock = asyncio.Lock()

	@staticmethod
	def _cache_key(app: str, source: str) -> str:
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

	async def _ensure_ready(self, app: str, source: str) -> None:
		key = self._cache_key(app, source)
		if key in self._ready:
			# Re-verify the index marker exists — the cache may have been deleted externally.
			if (self._cache_path(app, source) / "index" / ".indexed").exists():
				return
			self._ready.discard(key)

		async with self._global_lock:
			if key not in self._locks:
				self._locks[key] = asyncio.Lock()
			lock = self._locks[key]

		async with lock:
			if key in self._ready:
				return

			self._validate_source(app, source)
			cache = self._cache_path(app, source)
			await self._extract(self._apps[app][source], cache / "html")
			await asyncio.to_thread(self._convert, cache / "html", cache / "markdown")
			await self._build_index(cache / "markdown", cache / "index")
			self._ready.add(key)

	@staticmethod
	def _find_7z() -> str:
		"""Find the 7z executable, checking common install locations on Windows.

		Returns:
		    Absolute path to the 7z executable.

		Raises:
		    RuntimeError: If 7z cannot be found on this platform.
		"""
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

	async def _extract(self, chm_path: Path, html_dir: Path) -> None:
		marker = html_dir / ".extracted"
		if marker.exists():
			return
		html_dir.mkdir(parents=True, exist_ok=True)
		cmd = self._find_7z()
		process = await asyncio.create_subprocess_exec(
			cmd,
			"x",
			str(chm_path),
			f"-o{html_dir}",
			"-y",
			stdout=asyncio.subprocess.PIPE,
			stderr=asyncio.subprocess.PIPE,
		)
		_stdout, stderr = await process.communicate()
		if process.returncode != 0:
			raise RuntimeError(f"7z extraction failed: {stderr.decode()}")
		marker.touch()

	@staticmethod
	def _convert(html_dir: Path, md_dir: Path) -> None:
		marker = md_dir / ".converted"
		if marker.exists():
			return
		md_dir.mkdir(parents=True, exist_ok=True)

		converter = html2text.HTML2Text()
		converter.body_width = 0
		converter.ignore_images = True
		converter.ignore_links = False
		converter.ul_item_mark = "-"

		html_files = list(html_dir.rglob("*.htm")) + list(html_dir.rglob("*.html"))
		for html_file in html_files:
			try:
				# Read as bytes so lxml can detect charset from <meta charset> (handles cp1252 CHMs)
				raw_bytes = html_file.read_bytes()
				soup = BeautifulSoup(raw_bytes, "lxml")

				for tag in soup.find_all(["script", "style", "nav", "header", "footer"]):
					tag.decompose()

				markdown = converter.handle(str(soup))
				markdown = _clean_markdown(markdown)
				markdown = _fix_links(markdown)

				rel_path = html_file.relative_to(html_dir).with_suffix(".md")
				out_path = md_dir / rel_path
				out_path.parent.mkdir(parents=True, exist_ok=True)
				out_path.write_text(markdown, encoding="utf-8")
			except Exception:
				logger.warning("Failed to convert %s, skipping", html_file, exc_info=True)

		_deduplicate(md_dir)
		marker.touch()

	@staticmethod
	async def _build_index(md_dir: Path, index_dir: Path) -> None:
		def documents() -> Iterator[tuple[str, str, str]]:
			for md_file in md_dir.rglob("*.md"):
				try:
					text = md_file.read_text(encoding="utf-8")
					rel_path = str(md_file.relative_to(md_dir))

					# Extract title from first non-empty line
					title = rel_path
					for raw_line in text.splitlines():
						stripped = raw_line.strip()
						if stripped:
							title = stripped.lstrip("#").strip()
							break

					yield rel_path, title, text
				except Exception:
					logger.warning("Failed to read %s for indexing, skipping", md_file, exc_info=True)

		await SearchIndex(index_dir).build(documents())

	async def search(
		self, query: str, app: str | None = None, source: str | None = None, limit: int = 10
	) -> list[dict]:
		"""Search across CHM sources, optionally scoped by app and/or source.

		Args:
		    query: Full-text search query.
		    app: Scope to a specific app, or None to search all.
		    source: Scope to a specific source within an app. Requires app.
		    limit: Maximum number of results to return.

		Returns:
		    List of dicts with keys: app, source, title, path, score.

		Raises:
		    ValueError: If source is specified without app.
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
			await self._ensure_ready(a, s)
			index_dir = self._cache_path(a, s) / "index"
			hits = await SearchIndex(index_dir).search(query, limit=limit)
			results.extend({"app": a, "source": s, **hit} for hit in hits)

		results.sort(key=operator.itemgetter("score"), reverse=True)
		return results[:limit]

	async def read_page(self, app: str, source: str, path: str) -> str:
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
		await self._ensure_ready(app, source)

		md_dir = self._cache_path(app, source) / "markdown"
		resolved = (md_dir / path).resolve()

		# Path traversal protection
		if not resolved.is_relative_to(md_dir.resolve()):
			raise ValueError("Invalid path: must be within the source's cache directory")

		if not resolved.is_file():
			raise FileNotFoundError(f"Page not found: {path}")

		async with aiofiles.open(resolved, encoding="utf-8") as f:
			content = await f.read()
		return content.strip()

	def clear_cache(self, app: str | None = None, source: str | None = None) -> list[str]:
		"""Delete cached data so it will be rebuilt on next access.

		Args:
		    app: Scope to a specific app, or None to clear all apps.
		    source: Scope to a specific source within an app. Requires app.

		Returns:
		    List of cleared cache paths (as strings).

		Raises:
		    ValueError: If source is given without app, or if app/source is unknown.
		"""
		if source and not app:
			raise ValueError("Cannot specify source without app.")

		targets: list[tuple[str, str]] = []
		if app and source:
			self._validate_source(app, source)
			targets = [(app, source)]
		elif app:
			self._validate_app(app)
			targets = [(app, s) for s in self._apps[app]]
		else:
			for a, sources in self._apps.items():
				targets.extend((a, s) for s in sources)

		cleared: list[str] = []
		for a, s in targets:
			cache = self._cache_path(a, s)
			if cache.exists():
				shutil.rmtree(cache)
				cleared.append(str(cache))
			self._ready.discard(self._cache_key(a, s))

		return cleared
