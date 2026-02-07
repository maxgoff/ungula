"""
Comprehensive tests for the Ungula memory module.

Covers:
- chunker.py: chunk_text() with various inputs
- hybrid.py: hybrid_search() with vector/keyword results
- embeddings.py: create_embedding_provider() factory and provider classes
- manager.py: MemoryManager operations with mocked ChromaDB and storage
"""

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from ungula.memory.chunker import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    MIN_CHUNK_SIZE,
    chunk_text,
)
from ungula.memory.embeddings import (
    EmbeddingProvider,
    LocalEmbeddingProvider,
    OpenAIEmbeddingProvider,
    create_embedding_provider,
)
from ungula.memory.hybrid import (
    DEFAULT_KEYWORD_WEIGHT,
    DEFAULT_VECTOR_WEIGHT,
    hybrid_search,
)
from ungula.memory.manager import COLLECTION_NAME, MemoryManager
from ungula.storage.base import MemoryEntry, MemoryEntryCreate, StorageBackend


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_memory_entry(
    content: str = "test content",
    memory_type: str = "fact",
    level: str = "global",
    **kwargs: Any,
) -> MemoryEntry:
    """Create a MemoryEntry for testing."""
    now = datetime.now(timezone.utc)
    return MemoryEntry(
        id=kwargs.get("id", uuid.uuid4()),
        content=content,
        memory_type=memory_type,
        level=level,
        project_id=kwargs.get("project_id"),
        agent_id=kwargs.get("agent_id"),
        source=kwargs.get("source"),
        embedding=kwargs.get("embedding"),
        created_at=kwargs.get("created_at", now),
        accessed_at=kwargs.get("accessed_at", now),
        access_count=kwargs.get("access_count", 0),
        metadata=kwargs.get("metadata", {}),
    )


def _words(n: int) -> str:
    """Generate a string with approximately n words."""
    return " ".join(f"word{i}" for i in range(n))


# ===========================================================================
# Tests for chunker.py
# ===========================================================================


class TestChunkTextEmpty:
    """Tests for empty / trivial input to chunk_text."""

    def test_empty_string_returns_empty_list(self):
        assert chunk_text("") == []

    def test_none_input_returns_empty_list(self):
        # The function explicitly checks `not text`, so None would error
        # but empty-string and whitespace-only should return [].
        assert chunk_text("   ") == []
        assert chunk_text("\n\n") == []
        assert chunk_text("\t  \n") == []


class TestChunkTextShort:
    """Tests for short text that fits in a single chunk."""

    def test_single_short_paragraph(self):
        text = "This is a short paragraph with enough words to not be skipped."
        result = chunk_text(text)
        assert len(result) >= 1
        assert result[0]["content"].strip() == text
        assert result[0]["index"] == 0
        assert "word_count" in result[0]["metadata"]

    def test_metadata_includes_source_when_provided(self):
        text = _words(20)  # 20 words, above the MIN_CHUNK_SIZE // 5 threshold
        result = chunk_text(text, source="test_doc.md")
        assert len(result) >= 1
        assert result[0]["metadata"]["source"] == "test_doc.md"

    def test_metadata_omits_source_when_not_provided(self):
        text = _words(20)
        result = chunk_text(text)
        assert len(result) >= 1
        assert "source" not in result[0]["metadata"]


class TestChunkTextMarkdownHeaders:
    """Tests for markdown heading-aware splitting."""

    def test_splits_on_markdown_headings(self):
        text = (
            "# Introduction\n"
            + _words(30)
            + "\n\n"
            + "## Details\n"
            + _words(30)
            + "\n\n"
            + "## Conclusion\n"
            + _words(30)
        )
        result = chunk_text(text, chunk_size=100)
        # With small content, all sections may be merged into one chunk;
        # but the structural split should still work.
        assert len(result) >= 1
        # All content should be present across chunks
        all_content = " ".join(r["content"] for r in result)
        assert "Introduction" in all_content
        assert "Details" in all_content
        assert "Conclusion" in all_content

    def test_heading_levels_1_through_6(self):
        sections = []
        for i in range(1, 7):
            hashes = "#" * i
            sections.append(f"{hashes} Heading Level {i}\n" + _words(20))
        text = "\n\n".join(sections)
        result = chunk_text(text, chunk_size=500)
        assert len(result) >= 1
        all_content = " ".join(r["content"] for r in result)
        for i in range(1, 7):
            assert f"Heading Level {i}" in all_content


class TestChunkTextCodeBlocks:
    """Tests for text containing code blocks."""

    def test_code_block_content_preserved(self):
        text = (
            "# Setup\n"
            "Here is some setup code:\n"
            "```python\n"
            "def hello():\n"
            "    print('hello world')\n"
            "```\n"
            "\n"
            "And some more explanation text to pad things out a bit."
        )
        result = chunk_text(text, chunk_size=500)
        assert len(result) >= 1
        all_content = " ".join(r["content"] for r in result)
        assert "def hello():" in all_content
        assert "print('hello world')" in all_content


class TestChunkTextOverlap:
    """Tests for overlap behavior between chunks."""

    def test_overlap_creates_shared_content(self):
        # Create text that must be split into multiple chunks
        # Use small chunk_size to force splitting
        sections = []
        for i in range(5):
            sections.append(f"## Section {i}\n" + _words(60))
        text = "\n\n".join(sections)

        result = chunk_text(text, chunk_size=80, chunk_overlap=20)
        if len(result) > 1:
            # With overlap, later chunks should contain some words
            # from the tail end of the previous chunk
            first_words = set(result[0]["content"].split())
            second_words = set(result[1]["content"].split())
            # There should be some overlap (shared words)
            overlap = first_words & second_words
            assert len(overlap) > 0, "Expected overlapping words between chunks"

    def test_zero_overlap(self):
        sections = []
        for i in range(5):
            sections.append(f"## Section {i}\n" + _words(60))
        text = "\n\n".join(sections)

        result = chunk_text(text, chunk_size=80, chunk_overlap=0)
        # Should still produce chunks, just without overlap
        assert len(result) >= 1


class TestChunkTextLargeSections:
    """Tests for sections that exceed chunk_size and need sub-splitting."""

    def test_large_section_is_sub_split(self):
        # A single section (no headings) with multiple paragraphs so
        # _split_large_section can split on paragraph boundaries (\n\n).
        paragraphs = [_words(40) for _ in range(5)]
        text = "\n\n".join(paragraphs)  # 200 words across 5 paragraphs
        result = chunk_text(text, chunk_size=50, chunk_overlap=10)
        assert len(result) > 1, "A 200-word text with paragraphs and chunk_size=50 should produce multiple chunks"

    def test_large_section_with_paragraphs(self):
        paragraphs = [_words(40) for _ in range(6)]
        text = "\n\n".join(paragraphs)
        result = chunk_text(text, chunk_size=50, chunk_overlap=5)
        assert len(result) >= 2
        # Every chunk should have reasonable word count
        for r in result:
            assert r["metadata"]["word_count"] > 0


class TestChunkTextEdgeCases:
    """Edge cases for chunk_text."""

    def test_very_tiny_chunks_are_filtered(self):
        # A single word is fewer than MIN_CHUNK_SIZE // 5 = 10 words
        text = "hello"
        result = chunk_text(text)
        # "hello" is 1 word, MIN_CHUNK_SIZE // 5 = 10, so it should be skipped
        assert len(result) == 0

    def test_custom_chunk_size(self):
        # Use multiple paragraphs so the chunker can split on boundaries
        paragraphs = [_words(30) for _ in range(4)]
        text = "\n\n".join(paragraphs)
        result = chunk_text(text, chunk_size=30, chunk_overlap=5)
        assert len(result) >= 2

    def test_index_values_are_sequential(self):
        sections = [f"## Part {i}\n" + _words(40) for i in range(4)]
        text = "\n\n".join(sections)
        result = chunk_text(text, chunk_size=50, chunk_overlap=5)
        if len(result) > 1:
            for i, r in enumerate(result):
                assert r["index"] == i


# ===========================================================================
# Tests for hybrid.py
# ===========================================================================


def _make_vector_result(
    doc_id: str,
    content: str,
    score: float,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a vector search result dict."""
    return {
        "id": doc_id,
        "content": content,
        "score": score,
        "metadata": metadata or {},
    }


class TestHybridSearchEmpty:
    """Tests for empty inputs to hybrid_search."""

    def test_empty_vector_results(self):
        result = hybrid_search([], "some query")
        assert result == []

    def test_empty_query_with_results(self):
        results = [_make_vector_result("1", "some content here for testing", 0.9)]
        # An empty query yields no query terms, so keyword_score will be 0
        ranked = hybrid_search(results, "")
        assert len(ranked) == 1
        assert ranked[0]["keyword_score"] == 0.0


class TestHybridSearchScoring:
    """Tests for hybrid scoring logic."""

    def test_default_weights(self):
        results = [
            _make_vector_result("1", "python programming language tutorial", 0.8),
            _make_vector_result("2", "java programming language basics", 0.9),
        ]
        ranked = hybrid_search(results, "python programming")
        assert len(ranked) == 2
        # All results should have hybrid_score, vector_score, keyword_score
        for r in ranked:
            assert "hybrid_score" in r
            assert "vector_score" in r
            assert "keyword_score" in r

    def test_keyword_match_boosts_lower_vector_score(self):
        # Result 1: low vector score but exact keyword match
        # Result 2: high vector score but no keyword match
        results = [
            _make_vector_result("1", "chromadb vector database for embeddings", 0.5),
            _make_vector_result("2", "unrelated content about cooking recipes", 0.95),
        ]
        ranked = hybrid_search(
            results,
            "chromadb vector database",
            keyword_weight=0.6,
            vector_weight=0.4,
        )
        # With heavy keyword weight, result 1 should rank higher
        assert ranked[0]["id"] == "1"

    def test_vector_weight_dominance(self):
        results = [
            _make_vector_result("1", "matching query terms exactly here", 0.3),
            _make_vector_result("2", "totally different words and phrases", 0.99),
        ]
        ranked = hybrid_search(
            results,
            "matching query terms",
            vector_weight=0.99,
            keyword_weight=0.01,
        )
        # With nearly all weight on vector score, result 2 should win
        assert ranked[0]["id"] == "2"

    def test_hybrid_score_is_weighted_combination(self):
        results = [
            _make_vector_result("1", "python programming tutorial basics", 0.8),
        ]
        ranked = hybrid_search(
            results,
            "python programming",
            vector_weight=0.7,
            keyword_weight=0.3,
        )
        r = ranked[0]
        total = 0.7 + 0.3
        expected = (0.7 / total) * 0.8 + (0.3 / total) * r["keyword_score"]
        assert abs(r["hybrid_score"] - expected) < 1e-9

    def test_phrase_bonus_for_exact_match(self):
        results = [
            _make_vector_result("1", "content about python programming in depth", 0.8),
            _make_vector_result("2", "python is great and programming is fun", 0.8),
        ]
        # "python programming" as adjacent phrase in result 1
        ranked = hybrid_search(results, "python programming")
        # Result 1 should get a phrase bonus, giving it a higher keyword_score
        r1 = next(r for r in ranked if r["id"] == "1")
        r2 = next(r for r in ranked if r["id"] == "2")
        assert r1["keyword_score"] >= r2["keyword_score"]


class TestHybridSearchLimit:
    """Tests for result limiting."""

    def test_limit_respected(self):
        results = [
            _make_vector_result(str(i), f"content number {i} with test words", 0.5 + i * 0.01)
            for i in range(20)
        ]
        ranked = hybrid_search(results, "content test", limit=5)
        assert len(ranked) == 5

    def test_limit_larger_than_results(self):
        results = [
            _make_vector_result("1", "some test content here", 0.8),
            _make_vector_result("2", "more test content there", 0.7),
        ]
        ranked = hybrid_search(results, "test content", limit=100)
        assert len(ranked) == 2


class TestHybridSearchWeightNormalization:
    """Tests for weight normalization."""

    def test_weights_summing_to_more_than_one(self):
        results = [_make_vector_result("1", "test content for scoring", 0.8)]
        ranked = hybrid_search(results, "test", vector_weight=2.0, keyword_weight=1.0)
        assert len(ranked) == 1
        # Weights should be normalized: 2/3 and 1/3
        r = ranked[0]
        expected = (2.0 / 3.0) * 0.8 + (1.0 / 3.0) * r["keyword_score"]
        assert abs(r["hybrid_score"] - expected) < 1e-9

    def test_weights_summing_to_less_than_one(self):
        results = [_make_vector_result("1", "test content for scoring", 0.8)]
        ranked = hybrid_search(results, "test", vector_weight=0.1, keyword_weight=0.1)
        assert len(ranked) == 1
        # Normalized to 0.5 / 0.5
        r = ranked[0]
        expected = 0.5 * 0.8 + 0.5 * r["keyword_score"]
        assert abs(r["hybrid_score"] - expected) < 1e-9


class TestHybridSearchStopWords:
    """Tests for stop word filtering in keyword extraction."""

    def test_stop_words_are_excluded(self):
        results = [_make_vector_result("1", "the cat sat on the mat", 0.5)]
        # "the" and "on" are stop words; only "cat", "sat", "mat" should count
        ranked = hybrid_search(results, "the cat on the mat")
        r = ranked[0]
        # Should still get keyword matches for "cat" and "mat"
        assert r["keyword_score"] > 0.0

    def test_short_words_excluded(self):
        results = [_make_vector_result("1", "we go to it by ox", 0.5)]
        # "we", "go", "to", "it", "by", "ox" are all 2 chars, excluded
        ranked = hybrid_search(results, "we go to it by ox")
        r = ranked[0]
        assert r["keyword_score"] == 0.0


class TestHybridSearchNoOverlap:
    """Tests where query terms don't appear in results."""

    def test_no_keyword_overlap(self):
        results = [
            _make_vector_result("1", "alpha beta gamma delta", 0.8),
        ]
        ranked = hybrid_search(results, "epsilon zeta theta")
        assert len(ranked) == 1
        assert ranked[0]["keyword_score"] == 0.0
        # hybrid_score should be purely from vector score
        total_w = DEFAULT_VECTOR_WEIGHT + DEFAULT_KEYWORD_WEIGHT
        expected = (DEFAULT_VECTOR_WEIGHT / total_w) * 0.8
        assert abs(ranked[0]["hybrid_score"] - expected) < 1e-9


# ===========================================================================
# Tests for embeddings.py
# ===========================================================================


class TestCreateEmbeddingProviderFactory:
    """Tests for the create_embedding_provider factory function."""

    def test_default_creates_local_provider(self):
        provider = create_embedding_provider()
        assert isinstance(provider, LocalEmbeddingProvider)
        assert provider.model_name == "all-MiniLM-L6-v2"

    def test_local_with_custom_model(self):
        provider = create_embedding_provider(provider="local", model="custom-model")
        assert isinstance(provider, LocalEmbeddingProvider)
        assert provider.model_name == "custom-model"

    def test_openai_provider_created(self):
        provider = create_embedding_provider(
            provider="openai",
            api_key="sk-test-key-123",
        )
        assert isinstance(provider, OpenAIEmbeddingProvider)
        assert provider.api_key == "sk-test-key-123"
        assert provider.model == "text-embedding-3-small"

    def test_openai_with_custom_model(self):
        provider = create_embedding_provider(
            provider="openai",
            api_key="sk-test-key",
            model="text-embedding-3-large",
        )
        assert isinstance(provider, OpenAIEmbeddingProvider)
        assert provider.model == "text-embedding-3-large"

    def test_openai_without_api_key_raises(self):
        with pytest.raises(ValueError, match="API key"):
            create_embedding_provider(provider="openai")

    def test_openai_with_none_api_key_raises(self):
        with pytest.raises(ValueError, match="API key"):
            create_embedding_provider(provider="openai", api_key=None)

    def test_unknown_provider_defaults_to_local(self):
        # The factory uses an else branch, so any non-"openai" string -> local
        provider = create_embedding_provider(provider="unknown_provider")
        assert isinstance(provider, LocalEmbeddingProvider)


class TestLocalEmbeddingProvider:
    """Tests for LocalEmbeddingProvider."""

    def test_initialization_defaults(self):
        provider = LocalEmbeddingProvider()
        assert provider.model_name == "all-MiniLM-L6-v2"
        assert provider._model is None
        assert provider._dimension is None

    def test_initialization_custom_model(self):
        provider = LocalEmbeddingProvider(model_name="paraphrase-MiniLM-L3-v2")
        assert provider.model_name == "paraphrase-MiniLM-L3-v2"

    @patch("ungula.memory.embeddings.LocalEmbeddingProvider._load_model")
    async def test_embed_calls_load_model(self, mock_load):
        provider = LocalEmbeddingProvider()
        mock_model = MagicMock()
        mock_model.encode.return_value = [MagicMock(tolist=lambda: [0.1, 0.2, 0.3])]
        provider._model = mock_model

        result = await provider.embed(["test text"])
        mock_load.assert_called_once()
        assert result == [[0.1, 0.2, 0.3]]

    @patch("ungula.memory.embeddings.LocalEmbeddingProvider._load_model")
    async def test_embed_multiple_texts(self, mock_load):
        provider = LocalEmbeddingProvider()
        mock_emb1 = MagicMock()
        mock_emb1.tolist.return_value = [0.1, 0.2]
        mock_emb2 = MagicMock()
        mock_emb2.tolist.return_value = [0.3, 0.4]
        mock_model = MagicMock()
        mock_model.encode.return_value = [mock_emb1, mock_emb2]
        provider._model = mock_model

        result = await provider.embed(["text1", "text2"])
        assert len(result) == 2
        assert result[0] == [0.1, 0.2]
        assert result[1] == [0.3, 0.4]
        mock_model.encode.assert_called_once_with(
            ["text1", "text2"], normalize_embeddings=True
        )

    def test_dimension_default_when_model_not_loaded(self):
        provider = LocalEmbeddingProvider()
        # Patch _load_model so it doesn't actually load
        with patch.object(provider, "_load_model"):
            # _dimension is None, so it returns default 384
            dim = provider.dimension()
            assert dim == 384

    def test_dimension_from_loaded_model(self):
        provider = LocalEmbeddingProvider()
        provider._dimension = 768
        with patch.object(provider, "_load_model"):
            dim = provider.dimension()
            assert dim == 768

    def test_load_model_raises_without_sentence_transformers(self):
        provider = LocalEmbeddingProvider()
        with patch.dict("sys.modules", {"sentence_transformers": None}):
            with pytest.raises(RuntimeError, match="sentence-transformers not installed"):
                provider._load_model()

    def test_load_model_only_once(self):
        provider = LocalEmbeddingProvider()
        mock_st = MagicMock()
        mock_model_instance = MagicMock()
        mock_model_instance.encode.return_value = [[0.1] * 384]
        mock_st.SentenceTransformer.return_value = mock_model_instance

        with patch.dict("sys.modules", {"sentence_transformers": mock_st}):
            provider._load_model()
            provider._load_model()  # Second call should be a no-op
            mock_st.SentenceTransformer.assert_called_once()


class TestOpenAIEmbeddingProvider:
    """Tests for OpenAIEmbeddingProvider."""

    def test_initialization(self):
        provider = OpenAIEmbeddingProvider(api_key="sk-test")
        assert provider.api_key == "sk-test"
        assert provider.model == "text-embedding-3-small"
        assert provider._client is None
        assert provider._dimension == 1536

    def test_initialization_custom_model(self):
        provider = OpenAIEmbeddingProvider(
            api_key="sk-test",
            model="text-embedding-3-large",
        )
        assert provider.model == "text-embedding-3-large"

    def test_dimension_returns_1536(self):
        provider = OpenAIEmbeddingProvider(api_key="sk-test")
        assert provider.dimension() == 1536

    async def test_embed_calls_openai_api(self):
        provider = OpenAIEmbeddingProvider(api_key="sk-test")

        mock_item1 = MagicMock()
        mock_item1.embedding = [0.1, 0.2, 0.3]
        mock_item2 = MagicMock()
        mock_item2.embedding = [0.4, 0.5, 0.6]

        mock_response = MagicMock()
        mock_response.data = [mock_item1, mock_item2]

        mock_client = AsyncMock()
        mock_client.embeddings.create = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        result = await provider.embed(["text1", "text2"])
        assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        mock_client.embeddings.create.assert_called_once_with(
            input=["text1", "text2"],
            model="text-embedding-3-small",
        )

    def test_get_client_raises_without_openai(self):
        provider = OpenAIEmbeddingProvider(api_key="sk-test")
        with patch.dict("sys.modules", {"openai": None}):
            with pytest.raises(RuntimeError, match="openai not installed"):
                provider._get_client()

    def test_get_client_caches_instance(self):
        provider = OpenAIEmbeddingProvider(api_key="sk-test")
        mock_openai = MagicMock()
        mock_async_client = MagicMock()
        mock_openai.AsyncOpenAI.return_value = mock_async_client

        with patch.dict("sys.modules", {"openai": mock_openai}):
            client1 = provider._get_client()
            client2 = provider._get_client()
            assert client1 is client2
            mock_openai.AsyncOpenAI.assert_called_once()


class TestEmbeddingProviderABC:
    """Tests for the abstract base class."""

    def test_cannot_instantiate_abstract_class(self):
        with pytest.raises(TypeError):
            EmbeddingProvider()

    def test_subclass_must_implement_embed_and_dimension(self):
        # A subclass that doesn't implement abstract methods can't be instantiated
        class IncompleteProvider(EmbeddingProvider):
            pass

        with pytest.raises(TypeError):
            IncompleteProvider()


# ===========================================================================
# Tests for manager.py
# ===========================================================================


def _create_mock_storage() -> MagicMock:
    """Create a mock StorageBackend."""
    storage = MagicMock(spec=StorageBackend)
    storage.create_memory = AsyncMock()
    storage.delete_memory = AsyncMock()
    storage.search_memory = AsyncMock()
    return storage


def _create_mock_embedding_provider(
    dim: int = 384,
    embedding: list[float] | None = None,
) -> MagicMock:
    """Create a mock EmbeddingProvider."""
    provider = MagicMock(spec=EmbeddingProvider)
    default_embedding = embedding or [0.1] * dim
    provider.embed = AsyncMock(return_value=[default_embedding])
    provider.dimension.return_value = dim
    return provider


def _create_mock_collection() -> MagicMock:
    """Create a mock ChromaDB collection."""
    collection = MagicMock()
    collection.count.return_value = 0
    collection.add = MagicMock()
    collection.query = MagicMock()
    collection.delete = MagicMock()
    collection.upsert = MagicMock()
    return collection


class TestMemoryManagerInit:
    """Tests for MemoryManager initialization."""

    def test_basic_initialization(self):
        storage = _create_mock_storage()
        provider = _create_mock_embedding_provider()
        manager = MemoryManager(storage=storage, embedding_provider=provider)

        assert manager.storage is storage
        assert manager.embedding_provider is provider
        assert manager.persist_dir is None
        assert manager._collection is None
        assert manager._client is None

    def test_initialization_with_persist_dir(self):
        storage = _create_mock_storage()
        provider = _create_mock_embedding_provider()
        persist = Path("/tmp/test_chroma")
        manager = MemoryManager(
            storage=storage,
            embedding_provider=provider,
            persist_dir=persist,
        )
        assert manager.persist_dir == persist

    async def test_initialize_ephemeral_client(self):
        storage = _create_mock_storage()
        provider = _create_mock_embedding_provider()
        manager = MemoryManager(storage=storage, embedding_provider=provider)

        mock_client = MagicMock()
        mock_collection = _create_mock_collection()
        mock_client.get_or_create_collection.return_value = mock_collection

        mock_chromadb = MagicMock()
        mock_chromadb.Client.return_value = mock_client

        with patch.dict("sys.modules", {"chromadb": mock_chromadb}):
            await manager.initialize()

        assert manager._client is mock_client
        assert manager._collection is mock_collection
        mock_client.get_or_create_collection.assert_called_once_with(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    async def test_initialize_persistent_client(self, tmp_path):
        storage = _create_mock_storage()
        provider = _create_mock_embedding_provider()
        persist_dir = tmp_path / "chroma_data"
        manager = MemoryManager(
            storage=storage,
            embedding_provider=provider,
            persist_dir=persist_dir,
        )

        mock_client = MagicMock()
        mock_collection = _create_mock_collection()
        mock_client.get_or_create_collection.return_value = mock_collection

        mock_chromadb = MagicMock()
        mock_chromadb.PersistentClient.return_value = mock_client

        with patch.dict("sys.modules", {"chromadb": mock_chromadb}):
            await manager.initialize()

        mock_chromadb.PersistentClient.assert_called_once_with(
            path=str(persist_dir),
        )
        assert persist_dir.exists()

    async def test_initialize_raises_on_import_error(self):
        storage = _create_mock_storage()
        provider = _create_mock_embedding_provider()
        manager = MemoryManager(storage=storage, embedding_provider=provider)

        with patch.dict("sys.modules", {"chromadb": None}):
            with pytest.raises((ImportError, ModuleNotFoundError)):
                await manager.initialize()


class TestMemoryManagerAddMemory:
    """Tests for MemoryManager.add_memory."""

    async def test_add_memory_basic(self):
        storage = _create_mock_storage()
        provider = _create_mock_embedding_provider()
        manager = MemoryManager(storage=storage, embedding_provider=provider)

        expected_entry = _make_memory_entry(content="test fact")
        storage.create_memory.return_value = expected_entry

        collection = _create_mock_collection()
        manager._collection = collection

        result = await manager.add_memory(content="test fact", memory_type="fact")

        assert result is expected_entry
        provider.embed.assert_called_once_with(["test fact"])
        storage.create_memory.assert_called_once()

        # Verify the MemoryEntryCreate passed to storage
        call_args = storage.create_memory.call_args[0][0]
        assert isinstance(call_args, MemoryEntryCreate)
        assert call_args.content == "test fact"
        assert call_args.memory_type == "fact"
        assert call_args.embedding == [0.1] * 384

    async def test_add_memory_indexes_in_chromadb(self):
        storage = _create_mock_storage()
        provider = _create_mock_embedding_provider()
        manager = MemoryManager(storage=storage, embedding_provider=provider)

        entry_id = uuid.uuid4()
        expected_entry = _make_memory_entry(
            id=entry_id,
            content="important decision",
            memory_type="decision",
            level="project",
            project_id="proj-1",
            agent_id="agent-1",
            source="meeting.md",
        )
        storage.create_memory.return_value = expected_entry

        collection = _create_mock_collection()
        manager._collection = collection

        await manager.add_memory(
            content="important decision",
            memory_type="decision",
            level="project",
            project_id="proj-1",
            agent_id="agent-1",
            source="meeting.md",
        )

        collection.add.assert_called_once()
        add_kwargs = collection.add.call_args[1]
        assert add_kwargs["ids"] == [str(entry_id)]
        assert add_kwargs["documents"] == ["important decision"]
        assert add_kwargs["metadatas"][0]["memory_type"] == "decision"
        assert add_kwargs["metadatas"][0]["level"] == "project"
        assert add_kwargs["metadatas"][0]["project_id"] == "proj-1"
        assert add_kwargs["metadatas"][0]["agent_id"] == "agent-1"
        assert add_kwargs["metadatas"][0]["source"] == "meeting.md"

    async def test_add_memory_without_collection(self):
        """When collection is None, should still store in SQLite."""
        storage = _create_mock_storage()
        provider = _create_mock_embedding_provider()
        manager = MemoryManager(storage=storage, embedding_provider=provider)

        expected_entry = _make_memory_entry(content="orphan memory")
        storage.create_memory.return_value = expected_entry

        # _collection is None (not initialized)
        result = await manager.add_memory(content="orphan memory")

        assert result is expected_entry
        storage.create_memory.assert_called_once()

    async def test_add_memory_with_metadata(self):
        storage = _create_mock_storage()
        provider = _create_mock_embedding_provider()
        manager = MemoryManager(storage=storage, embedding_provider=provider)
        manager._collection = _create_mock_collection()

        expected_entry = _make_memory_entry(content="meta memory")
        storage.create_memory.return_value = expected_entry

        await manager.add_memory(
            content="meta memory",
            metadata={"importance": "high", "tags": ["test"]},
        )

        call_args = storage.create_memory.call_args[0][0]
        assert call_args.metadata == {"importance": "high", "tags": ["test"]}

    async def test_add_memory_default_metadata_is_empty_dict(self):
        storage = _create_mock_storage()
        provider = _create_mock_embedding_provider()
        manager = MemoryManager(storage=storage, embedding_provider=provider)
        manager._collection = _create_mock_collection()

        expected_entry = _make_memory_entry(content="no meta")
        storage.create_memory.return_value = expected_entry

        await manager.add_memory(content="no meta")

        call_args = storage.create_memory.call_args[0][0]
        assert call_args.metadata == {}


class TestMemoryManagerSearch:
    """Tests for MemoryManager.search."""

    async def test_search_returns_empty_when_no_collection(self):
        storage = _create_mock_storage()
        provider = _create_mock_embedding_provider()
        manager = MemoryManager(storage=storage, embedding_provider=provider)
        # _collection is None
        results = await manager.search("test query")
        assert results == []

    async def test_search_returns_empty_when_collection_empty(self):
        storage = _create_mock_storage()
        provider = _create_mock_embedding_provider()
        manager = MemoryManager(storage=storage, embedding_provider=provider)

        collection = _create_mock_collection()
        collection.count.return_value = 0
        manager._collection = collection

        results = await manager.search("test query")
        assert results == []

    async def test_search_basic(self):
        storage = _create_mock_storage()
        provider = _create_mock_embedding_provider()
        manager = MemoryManager(storage=storage, embedding_provider=provider)

        collection = _create_mock_collection()
        collection.count.return_value = 5
        collection.query.return_value = {
            "ids": [["id-1", "id-2"]],
            "documents": [["first document content", "second document content"]],
            "distances": [[0.1, 0.3]],
            "metadatas": [[
                {"memory_type": "fact", "level": "global"},
                {"memory_type": "decision", "level": "project"},
            ]],
        }
        manager._collection = collection

        results = await manager.search("test query")

        assert len(results) == 2
        assert results[0]["id"] == "id-1"
        assert results[0]["content"] == "first document content"
        assert results[0]["score"] == pytest.approx(0.9)  # 1.0 - 0.1
        assert results[0]["metadata"]["memory_type"] == "fact"

        assert results[1]["id"] == "id-2"
        assert results[1]["score"] == pytest.approx(0.7)  # 1.0 - 0.3

    async def test_search_with_type_filter(self):
        storage = _create_mock_storage()
        provider = _create_mock_embedding_provider()
        manager = MemoryManager(storage=storage, embedding_provider=provider)

        collection = _create_mock_collection()
        collection.count.return_value = 10
        collection.query.return_value = {
            "ids": [["id-1"]],
            "documents": [["filtered result"]],
            "distances": [[0.2]],
            "metadatas": [[{"memory_type": "fact", "level": "global"}]],
        }
        manager._collection = collection

        await manager.search("query", memory_type="fact")

        query_call = collection.query.call_args
        assert query_call[1]["where"] == {"memory_type": "fact"}

    async def test_search_with_multiple_filters(self):
        storage = _create_mock_storage()
        provider = _create_mock_embedding_provider()
        manager = MemoryManager(storage=storage, embedding_provider=provider)

        collection = _create_mock_collection()
        collection.count.return_value = 10
        collection.query.return_value = {
            "ids": [[]],
            "documents": [[]],
            "distances": [[]],
            "metadatas": [[]],
        }
        manager._collection = collection

        await manager.search(
            "query",
            memory_type="decision",
            level="project",
            project_id="proj-1",
        )

        query_call = collection.query.call_args
        where = query_call[1]["where"]
        assert "$and" in where
        conditions = where["$and"]
        assert {"memory_type": "decision"} in conditions
        assert {"level": "project"} in conditions
        assert {"project_id": "proj-1"} in conditions

    async def test_search_with_no_filters_passes_none(self):
        storage = _create_mock_storage()
        provider = _create_mock_embedding_provider()
        manager = MemoryManager(storage=storage, embedding_provider=provider)

        collection = _create_mock_collection()
        collection.count.return_value = 5
        collection.query.return_value = {
            "ids": [["id-1"]],
            "documents": [["content"]],
            "distances": [[0.1]],
            "metadatas": [[{}]],
        }
        manager._collection = collection

        await manager.search("query")

        query_call = collection.query.call_args
        assert query_call[1]["where"] is None

    async def test_search_handles_empty_chromadb_response(self):
        storage = _create_mock_storage()
        provider = _create_mock_embedding_provider()
        manager = MemoryManager(storage=storage, embedding_provider=provider)

        collection = _create_mock_collection()
        collection.count.return_value = 5
        collection.query.return_value = {
            "ids": [[]],
            "documents": [[]],
            "distances": [[]],
            "metadatas": [[]],
        }
        manager._collection = collection

        results = await manager.search("query")
        assert results == []

    async def test_search_handles_chromadb_exception(self):
        storage = _create_mock_storage()
        provider = _create_mock_embedding_provider()
        manager = MemoryManager(storage=storage, embedding_provider=provider)

        collection = _create_mock_collection()
        collection.count.return_value = 5
        collection.query.side_effect = RuntimeError("ChromaDB error")
        manager._collection = collection

        results = await manager.search("query")
        assert results == []

    async def test_search_respects_limit(self):
        storage = _create_mock_storage()
        provider = _create_mock_embedding_provider()
        manager = MemoryManager(storage=storage, embedding_provider=provider)

        collection = _create_mock_collection()
        collection.count.return_value = 100
        collection.query.return_value = {
            "ids": [["id-1"]],
            "documents": [["content"]],
            "distances": [[0.1]],
            "metadatas": [[{}]],
        }
        manager._collection = collection

        await manager.search("query", limit=5)

        query_call = collection.query.call_args
        assert query_call[1]["n_results"] == 5


class TestMemoryManagerDeleteMemory:
    """Tests for MemoryManager.delete_memory."""

    async def test_delete_memory_from_both_stores(self):
        storage = _create_mock_storage()
        provider = _create_mock_embedding_provider()
        manager = MemoryManager(storage=storage, embedding_provider=provider)

        collection = _create_mock_collection()
        manager._collection = collection

        memory_id = uuid.uuid4()
        storage.delete_memory.return_value = True

        result = await manager.delete_memory(memory_id)

        assert result is True
        collection.delete.assert_called_once_with(ids=[str(memory_id)])
        storage.delete_memory.assert_called_once_with(memory_id)

    async def test_delete_memory_without_collection(self):
        storage = _create_mock_storage()
        provider = _create_mock_embedding_provider()
        manager = MemoryManager(storage=storage, embedding_provider=provider)
        # _collection is None

        memory_id = uuid.uuid4()
        storage.delete_memory.return_value = True

        result = await manager.delete_memory(memory_id)

        assert result is True
        storage.delete_memory.assert_called_once_with(memory_id)

    async def test_delete_memory_chromadb_failure_still_deletes_from_storage(self):
        storage = _create_mock_storage()
        provider = _create_mock_embedding_provider()
        manager = MemoryManager(storage=storage, embedding_provider=provider)

        collection = _create_mock_collection()
        collection.delete.side_effect = RuntimeError("ChromaDB delete failed")
        manager._collection = collection

        memory_id = uuid.uuid4()
        storage.delete_memory.return_value = True

        # Should not raise; ChromaDB failure is caught
        result = await manager.delete_memory(memory_id)

        assert result is True
        storage.delete_memory.assert_called_once_with(memory_id)

    async def test_delete_memory_not_found(self):
        storage = _create_mock_storage()
        provider = _create_mock_embedding_provider()
        manager = MemoryManager(storage=storage, embedding_provider=provider)
        manager._collection = _create_mock_collection()

        memory_id = uuid.uuid4()
        storage.delete_memory.return_value = False

        result = await manager.delete_memory(memory_id)
        assert result is False


class TestMemoryManagerIndexDocument:
    """Tests for MemoryManager.index_document."""

    async def test_index_document_chunks_and_adds(self):
        storage = _create_mock_storage()
        provider = _create_mock_embedding_provider()
        # Make embed return correct number of embeddings for batch calls
        default_emb = [0.1] * 384
        provider.embed = AsyncMock(side_effect=lambda texts: [default_emb] * len(texts))
        manager = MemoryManager(storage=storage, embedding_provider=provider)
        manager._collection = _create_mock_collection()

        # search_memory returns empty (no existing docs)
        storage.search_memory.return_value = []

        # Create a document large enough to produce multiple chunks
        doc_content = "\n\n".join([_words(60) for _ in range(5)])

        entry = _make_memory_entry(content="chunk")
        storage.create_memory.return_value = entry

        count = await manager.index_document(
            content=doc_content,
            source="test_doc.md",
            chunk_size=80,
            chunk_overlap=10,
        )

        assert count >= 1
        assert storage.create_memory.call_count == count
        # Batch embedding: single embed call for all chunks
        assert provider.embed.call_count == 1

    async def test_index_document_short_content(self):
        storage = _create_mock_storage()
        provider = _create_mock_embedding_provider()
        default_emb = [0.1] * 384
        provider.embed = AsyncMock(side_effect=lambda texts: [default_emb] * len(texts))
        manager = MemoryManager(storage=storage, embedding_provider=provider)
        manager._collection = _create_mock_collection()

        storage.search_memory.return_value = []

        entry = _make_memory_entry(content="short doc")
        storage.create_memory.return_value = entry

        count = await manager.index_document(
            content="This is a reasonably sized piece of text with enough words to avoid being filtered.",
            source="short.md",
        )

        assert count >= 1

    async def test_index_document_empty_content(self):
        storage = _create_mock_storage()
        provider = _create_mock_embedding_provider()
        manager = MemoryManager(storage=storage, embedding_provider=provider)
        manager._collection = _create_mock_collection()

        count = await manager.index_document(content="", source="empty.md")
        assert count == 0
        storage.create_memory.assert_not_called()


class TestMemoryManagerSyncFromStorage:
    """Tests for MemoryManager.sync_from_storage."""

    async def test_sync_from_storage(self):
        storage = _create_mock_storage()
        provider = _create_mock_embedding_provider()
        manager = MemoryManager(storage=storage, embedding_provider=provider)

        collection = _create_mock_collection()
        manager._collection = collection

        entries = [
            _make_memory_entry(
                id=uuid.uuid4(),
                content=f"entry {i}",
                memory_type="fact",
                embedding=[0.1] * 384,
                source="sync_test.md",
            )
            for i in range(3)
        ]
        storage.search_memory.return_value = entries

        synced = await manager.sync_from_storage()

        assert synced == 3
        assert collection.upsert.call_count == 3

    async def test_sync_skips_entries_without_embeddings(self):
        storage = _create_mock_storage()
        provider = _create_mock_embedding_provider()
        manager = MemoryManager(storage=storage, embedding_provider=provider)

        collection = _create_mock_collection()
        manager._collection = collection

        entries = [
            _make_memory_entry(content="with embedding", embedding=[0.1] * 384),
            _make_memory_entry(content="without embedding", embedding=None),
            _make_memory_entry(content="also with embedding", embedding=[0.2] * 384),
        ]
        storage.search_memory.return_value = entries

        synced = await manager.sync_from_storage()

        assert synced == 2
        assert collection.upsert.call_count == 2

    async def test_sync_returns_zero_without_collection(self):
        storage = _create_mock_storage()
        provider = _create_mock_embedding_provider()
        manager = MemoryManager(storage=storage, embedding_provider=provider)
        # _collection is None

        synced = await manager.sync_from_storage()
        assert synced == 0


class TestMemoryManagerGetStatus:
    """Tests for MemoryManager.get_status."""

    async def test_get_status_initialized(self):
        storage = _create_mock_storage()
        provider = _create_mock_embedding_provider(dim=384)
        manager = MemoryManager(
            storage=storage,
            embedding_provider=provider,
            persist_dir=Path("/tmp/test"),
        )

        collection = _create_mock_collection()
        collection.count.return_value = 42
        manager._collection = collection

        status = await manager.get_status()

        assert status["initialized"] is True
        assert status["collection_count"] == 42
        assert status["embedding_dimension"] == 384
        assert status["persist_dir"] == "/tmp/test"

    async def test_get_status_not_initialized(self):
        storage = _create_mock_storage()
        provider = _create_mock_embedding_provider()
        manager = MemoryManager(storage=storage, embedding_provider=provider)

        status = await manager.get_status()

        assert status["initialized"] is False
        assert status["collection_count"] == 0
        assert status["persist_dir"] is None


class TestMemoryManagerBuildWhereFilter:
    """Tests for the static _build_where_filter method."""

    def test_no_filters(self):
        result = MemoryManager._build_where_filter()
        assert result is None

    def test_single_filter(self):
        result = MemoryManager._build_where_filter(memory_type="fact")
        assert result == {"memory_type": "fact"}

    def test_two_filters(self):
        result = MemoryManager._build_where_filter(memory_type="fact", level="project")
        assert "$and" in result
        assert {"memory_type": "fact"} in result["$and"]
        assert {"level": "project"} in result["$and"]

    def test_all_filters(self):
        result = MemoryManager._build_where_filter(
            memory_type="decision",
            level="agent",
            project_id="proj-1",
            agent_id="agent-1",
        )
        assert "$and" in result
        conditions = result["$and"]
        assert len(conditions) == 4
        assert {"memory_type": "decision"} in conditions
        assert {"level": "agent"} in conditions
        assert {"project_id": "proj-1"} in conditions
        assert {"agent_id": "agent-1"} in conditions

    def test_none_values_are_excluded(self):
        result = MemoryManager._build_where_filter(
            memory_type="fact",
            level=None,
            project_id=None,
        )
        assert result == {"memory_type": "fact"}

    def test_empty_string_values_are_excluded(self):
        result = MemoryManager._build_where_filter(
            memory_type="",
            level="global",
        )
        # Empty string is falsy, so memory_type should be excluded
        assert result == {"level": "global"}
