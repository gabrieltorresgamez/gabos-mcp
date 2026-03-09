import pytest
import pytest_asyncio

from gabos_mcp.utils.search import SearchIndex


@pytest.fixture
def index_dir(tmp_path):
	return tmp_path / "index"


@pytest.fixture
def sample_docs():
	return [
		("page1.md", "Getting Started", "Welcome to the application. This is the intro."),
		("page2.md", "API Reference", "Function signatures and parameter details."),
		("subdir/nested.md", "Nested Page", "Some deeply nested content about configuration."),
	]


@pytest_asyncio.fixture
async def built_index(index_dir, sample_docs):
	idx = SearchIndex(index_dir)
	await idx.build(iter(sample_docs))
	return idx


@pytest.mark.asyncio
class TestBuild:
	async def test_creates_marker(self, built_index, index_dir):
		assert (index_dir / ".indexed").exists()

	async def test_marker_prevents_rebuild(self, index_dir, sample_docs):
		idx = SearchIndex(index_dir)
		await idx.build(iter(sample_docs))

		# Build again with different docs — marker should prevent rebuild
		await idx.build(iter([("other.md", "Other", "completely different content xyz")]))

		# Original docs still searchable, new one is not
		results = await idx.search("xyz")
		assert results == []

	async def test_empty_documents(self, index_dir):
		idx = SearchIndex(index_dir)
		await idx.build(iter([]))
		assert (index_dir / ".indexed").exists()
		assert await idx.search("anything") == []


@pytest.mark.asyncio
class TestSearch:
	async def test_returns_results(self, built_index):
		results = await built_index.search("API Reference")
		assert len(results) > 0
		assert any(r["title"] == "API Reference" for r in results)

	async def test_no_results(self, built_index):
		results = await built_index.search("qqqzzznomatch")
		assert results == []

	async def test_result_keys(self, built_index):
		results = await built_index.search("welcome")
		assert len(results) > 0
		assert set(results[0].keys()) == {"title", "path", "score"}

	async def test_scores_sorted_descending(self, built_index):
		results = await built_index.search("content")
		scores = [r["score"] for r in results]
		assert scores == sorted(scores, reverse=True)

	async def test_limit_respected(self, built_index):
		results = await built_index.search("the", limit=1)
		assert len(results) <= 1

	async def test_no_index_returns_empty(self, index_dir):
		idx = SearchIndex(index_dir)
		assert await idx.search("anything") == []

	async def test_partial_match(self, built_index):
		# "configur" should match the doc containing "configuration"
		results = await built_index.search("configur")
		assert len(results) > 0
		assert any(r["path"] == "subdir/nested.md" for r in results)

	async def test_case_insensitive(self, built_index):
		# lowercase "api" should match "API Reference"
		results = await built_index.search("api")
		assert len(results) > 0
		assert any(r["title"] == "API Reference" for r in results)

	async def test_substring_match(self, built_index):
		# "param" should match the doc containing "parameter"
		results = await built_index.search("param")
		assert len(results) > 0
		assert any(r["title"] == "API Reference" for r in results)
