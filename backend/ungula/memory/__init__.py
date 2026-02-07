"""
Vector memory system for Ungula.

Provides semantic search over agent memories using ChromaDB
for vector storage and sentence-transformers or OpenAI for embeddings.
"""

from .embeddings import (
    EmbeddingProvider,
    LocalEmbeddingProvider,
    OpenAIEmbeddingProvider,
    create_embedding_provider,
)
from .hybrid import hybrid_search
from .manager import MemoryManager

__all__ = [
    "EmbeddingProvider",
    "LocalEmbeddingProvider",
    "MemoryManager",
    "OpenAIEmbeddingProvider",
    "create_embedding_provider",
    "hybrid_search",
]
