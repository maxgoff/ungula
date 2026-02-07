"""
Embedding providers for the vector memory system.

Supports local (sentence-transformers) and OpenAI embeddings.
Falls back gracefully if dependencies are unavailable.
"""

import hashlib
import logging
from abc import ABC, abstractmethod
from collections import OrderedDict

logger = logging.getLogger(__name__)


class EmbeddingProvider(ABC):
    """Abstract embedding provider."""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts."""
        pass

    @abstractmethod
    def dimension(self) -> int:
        """Return the embedding dimension."""
        pass


class LocalEmbeddingProvider(EmbeddingProvider):
    """
    Local embedding provider using sentence-transformers.

    Uses all-MiniLM-L6-v2 by default (384 dimensions, fast).
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self._model = None
        self._dimension: int | None = None

    def _load_model(self):
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
            # Get dimension from a test embedding
            test = self._model.encode(["test"])
            self._dimension = len(test[0])
            logger.info(
                "Loaded sentence-transformers model '%s' (dim=%d)",
                self.model_name,
                self._dimension,
            )
        except ImportError:
            raise RuntimeError(
                "sentence-transformers not installed. "
                "Install with: pip install sentence-transformers"
            )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings using sentence-transformers."""
        self._load_model()
        embeddings = self._model.encode(texts, normalize_embeddings=True)
        return [emb.tolist() for emb in embeddings]

    def dimension(self) -> int:
        self._load_model()
        return self._dimension or 384


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """
    OpenAI embedding provider using text-embedding-3-small.

    Requires an OpenAI API key.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
    ):
        self.api_key = api_key
        self.model = model
        self._client = None
        # text-embedding-3-small = 1536 dimensions
        self._dimension = 1536

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(api_key=self.api_key)
            return self._client
        except ImportError:
            raise RuntimeError("openai not installed. Install with: pip install openai")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings using OpenAI API."""
        client = self._get_client()
        response = await client.embeddings.create(
            input=texts,
            model=self.model,
        )
        return [item.embedding for item in response.data]

    def dimension(self) -> int:
        return self._dimension


class CachedEmbeddingProvider(EmbeddingProvider):
    """
    Caching wrapper around an EmbeddingProvider.

    Caches embeddings by SHA-256 of text content. Only uncached texts
    are sent to the underlying provider. Uses FIFO eviction when the
    cache exceeds max_cache_size.
    """

    def __init__(self, provider: EmbeddingProvider, max_cache_size: int = 10000):
        self._provider = provider
        self._max_cache_size = max_cache_size
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._hits = 0
        self._misses = 0

    @staticmethod
    def _hash_text(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts, returning cached results where possible."""
        results: list[list[float] | None] = [None] * len(texts)
        uncached_indices: list[int] = []
        uncached_texts: list[str] = []

        for i, text in enumerate(texts):
            key = self._hash_text(text)
            if key in self._cache:
                results[i] = self._cache[key]
                # Move to end for LRU-like behavior within FIFO
                self._cache.move_to_end(key)
                self._hits += 1
            else:
                uncached_indices.append(i)
                uncached_texts.append(text)
                self._misses += 1

        # Batch embed only uncached texts
        if uncached_texts:
            new_embeddings = await self._provider.embed(uncached_texts)
            for idx, text, embedding in zip(uncached_indices, uncached_texts, new_embeddings):
                results[idx] = embedding
                key = self._hash_text(text)
                self._cache[key] = embedding
                # FIFO eviction
                while len(self._cache) > self._max_cache_size:
                    self._cache.popitem(last=False)

        return results  # type: ignore[return-value]

    def dimension(self) -> int:
        return self._provider.dimension()

    @property
    def cache_stats(self) -> dict[str, int]:
        return {
            "size": len(self._cache),
            "hits": self._hits,
            "misses": self._misses,
            "max_size": self._max_cache_size,
        }


def create_embedding_provider(
    provider: str = "local",
    model: str | None = None,
    api_key: str | None = None,
) -> EmbeddingProvider:
    """Factory for creating embedding providers from config."""
    if provider == "openai":
        if not api_key:
            raise ValueError("OpenAI embedding provider requires an API key")
        return OpenAIEmbeddingProvider(
            api_key=api_key,
            model=model or "text-embedding-3-small",
        )
    else:
        return LocalEmbeddingProvider(
            model_name=model or "all-MiniLM-L6-v2",
        )
