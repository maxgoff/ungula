"""
Memory Manager for the vector memory system.

Orchestrates ChromaDB for vector search, embedding providers for
generating embeddings, and the chunker for document processing.
Provides a unified interface for indexing, searching, and managing
the agent's long-term memory.
"""

import hashlib
import logging
from pathlib import Path
from typing import Any
from uuid import UUID

from ..storage.base import MemoryEntry, MemoryEntryCreate, StorageBackend
from .chunker import chunk_text
from .embeddings import EmbeddingProvider

logger = logging.getLogger(__name__)

# ChromaDB collection name
COLLECTION_NAME = "ungula_memory"


class MemoryManager:
    """
    Manages the vector memory system.

    Uses ChromaDB for vector storage/search and delegates embedding
    generation to pluggable providers (local or OpenAI).
    """

    def __init__(
        self,
        storage: StorageBackend,
        embedding_provider: EmbeddingProvider,
        persist_dir: Path | None = None,
    ):
        self.storage = storage
        self.embedding_provider = embedding_provider
        self.persist_dir = persist_dir
        self._collection = None
        self._client = None

    async def initialize(self) -> None:
        """Initialize ChromaDB client and collection."""
        try:
            import chromadb

            if self.persist_dir:
                self.persist_dir.mkdir(parents=True, exist_ok=True)
                self._client = chromadb.PersistentClient(
                    path=str(self.persist_dir),
                )
            else:
                self._client = chromadb.Client()

            self._collection = self._client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )

            logger.info(
                "Initialized ChromaDB (persist=%s, docs=%d)",
                self.persist_dir,
                self._collection.count(),
            )
        except ImportError:
            logger.error("chromadb not installed. Install with: pip install chromadb")
            raise
        except Exception as e:
            logger.error("Failed to initialize ChromaDB: %s", e)
            raise

    async def add_memory(
        self,
        content: str,
        memory_type: str = "fact",
        level: str = "global",
        project_id: str | None = None,
        agent_id: str | None = None,
        source: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryEntry:
        """
        Add a memory entry with vector embedding.

        Args:
            content: The memory content text.
            memory_type: Type (fact, decision, preference, pattern, etc.).
            level: Scope (global, project, agent).
            project_id: Optional project scope.
            agent_id: Optional agent scope.
            source: Where this memory came from.
            metadata: Additional metadata.

        Returns:
            The created MemoryEntry.
        """
        # Generate embedding
        embeddings = await self.embedding_provider.embed([content])
        embedding = embeddings[0]

        # Store in SQLite
        entry = await self.storage.create_memory(
            MemoryEntryCreate(
                content=content,
                memory_type=memory_type,
                level=level,
                project_id=project_id,
                agent_id=agent_id,
                source=source,
                embedding=embedding,
                metadata=metadata or {},
            )
        )

        # Index in ChromaDB
        if self._collection is not None:
            chroma_metadata = {
                "memory_type": memory_type,
                "level": level,
            }
            if project_id:
                chroma_metadata["project_id"] = project_id
            if agent_id:
                chroma_metadata["agent_id"] = agent_id
            if source:
                chroma_metadata["source"] = source

            self._collection.add(
                ids=[str(entry.id)],
                embeddings=[embedding],
                documents=[content],
                metadatas=[chroma_metadata],
            )

        logger.info("Added memory entry %s (type=%s, level=%s)", entry.id, memory_type, level)
        return entry

    async def search(
        self,
        query: str,
        *,
        memory_type: str | None = None,
        level: str | None = None,
        project_id: str | None = None,
        agent_id: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Search memory using vector similarity.

        Args:
            query: Search query text.
            memory_type: Filter by memory type.
            level: Filter by scope level.
            project_id: Filter by project.
            agent_id: Filter by agent.
            limit: Maximum results.

        Returns:
            List of dicts with 'entry', 'score', and 'content'.
        """
        if self._collection is None or self._collection.count() == 0:
            return []

        # Generate query embedding
        query_embeddings = await self.embedding_provider.embed([query])
        query_embedding = query_embeddings[0]

        # Build ChromaDB where filter
        where_filter = self._build_where_filter(
            memory_type=memory_type,
            level=level,
            project_id=project_id,
            agent_id=agent_id,
        )

        # Query ChromaDB
        try:
            results = self._collection.query(
                query_embeddings=[query_embedding],
                n_results=min(limit, self._collection.count()),
                where=where_filter if where_filter else None,
                include=["documents", "distances", "metadatas"],
            )
        except Exception as e:
            logger.error("ChromaDB query failed: %s", e)
            return []

        if not results or not results["ids"] or not results["ids"][0]:
            return []

        # Build response
        search_results = []
        for i, doc_id in enumerate(results["ids"][0]):
            distance = results["distances"][0][i] if results["distances"] else 0
            score = 1.0 - distance  # Convert cosine distance to similarity
            document = results["documents"][0][i] if results["documents"] else ""
            chroma_meta = results["metadatas"][0][i] if results["metadatas"] else {}

            search_results.append({
                "id": doc_id,
                "content": document,
                "score": score,
                "metadata": chroma_meta,
            })

        return search_results

    async def index_document(
        self,
        content: str,
        source: str,
        memory_type: str = "fact",
        level: str = "project",
        project_id: str | None = None,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
    ) -> int:
        """
        Index a document by chunking, deduplicating, and batch-embedding.

        Generates all chunks up front, deduplicates by SHA-256 content hash,
        batch-embeds in a single call, and batch-inserts into storage + ChromaDB.

        Args:
            content: Full document text.
            source: Source identifier (e.g., file path).
            memory_type: Memory type for all chunks.
            level: Scope level.
            project_id: Optional project.
            chunk_size: Target chunk size in words.
            chunk_overlap: Overlap between chunks.

        Returns:
            Number of new chunks indexed (after dedup).
        """
        chunks = chunk_text(
            content,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            source=source,
        )

        if not chunks:
            return 0

        # 1. Compute content hashes and deduplicate within batch
        seen_hashes: set[str] = set()
        unique_chunks: list[dict[str, Any]] = []
        chunk_hashes: list[str] = []

        for chunk in chunks:
            content_hash = hashlib.sha256(chunk["content"].encode()).hexdigest()
            if content_hash in seen_hashes:
                continue
            seen_hashes.add(content_hash)
            unique_chunks.append(chunk)
            chunk_hashes.append(content_hash)

        # 2. Check existing memories by source + content_hash to skip re-indexing
        existing_hashes: set[str] = set()
        try:
            existing = await self.storage.search_memory(
                memory_type=memory_type,
                level=level,
                project_id=project_id,
                limit=10000,
            )
            for entry in existing:
                if entry.source == source:
                    stored_hash = (entry.metadata or {}).get("content_hash")
                    if stored_hash:
                        existing_hashes.add(stored_hash)
        except Exception as e:
            logger.warning("Could not check existing memories for dedup: %s", e)

        # Filter to only new chunks
        new_chunks = []
        new_hashes = []
        for chunk, h in zip(unique_chunks, chunk_hashes):
            if h not in existing_hashes:
                new_chunks.append(chunk)
                new_hashes.append(h)

        if not new_chunks:
            logger.info("Document '%s': all %d chunks already indexed", source, len(chunks))
            return 0

        # 3. Batch embed all new chunks in a single call
        texts = [c["content"] for c in new_chunks]
        embeddings = await self.embedding_provider.embed(texts)

        # 4. Batch insert into storage + ChromaDB
        ids_list = []
        for i, (chunk, embedding, content_hash) in enumerate(
            zip(new_chunks, embeddings, new_hashes)
        ):
            metadata = dict(chunk.get("metadata", {}))
            metadata["content_hash"] = content_hash

            entry = await self.storage.create_memory(
                MemoryEntryCreate(
                    content=chunk["content"],
                    memory_type=memory_type,
                    level=level,
                    project_id=project_id,
                    source=source,
                    embedding=embedding,
                    metadata=metadata,
                )
            )
            ids_list.append((str(entry.id), chunk["content"], embedding, metadata))

        if self._collection is not None and ids_list:
            chroma_ids = [item[0] for item in ids_list]
            chroma_docs = [item[1] for item in ids_list]
            chroma_embeddings = [item[2] for item in ids_list]
            chroma_metadatas = []
            for item in ids_list:
                cm = {
                    "memory_type": memory_type,
                    "level": level,
                }
                if project_id:
                    cm["project_id"] = project_id
                if source:
                    cm["source"] = source
                chroma_metadatas.append(cm)

            self._collection.add(
                ids=chroma_ids,
                embeddings=chroma_embeddings,
                documents=chroma_docs,
                metadatas=chroma_metadatas,
            )

        logger.info(
            "Indexed document '%s': %d new chunks (of %d total, %d deduped)",
            source, len(new_chunks), len(chunks), len(chunks) - len(unique_chunks),
        )
        return len(new_chunks)

    async def delete_memory(self, memory_id: UUID) -> bool:
        """Delete a memory entry from both SQLite and ChromaDB."""
        # Delete from ChromaDB
        if self._collection is not None:
            try:
                self._collection.delete(ids=[str(memory_id)])
            except Exception as e:
                logger.warning("Failed to delete from ChromaDB: %s", e)

        # Delete from SQLite
        return await self.storage.delete_memory(memory_id)

    async def sync_from_storage(self) -> int:
        """
        Sync ChromaDB from SQLite storage.

        Re-indexes all memory entries that have embeddings stored.
        Useful for rebuilding the vector index.

        Returns:
            Number of entries synced.
        """
        if self._collection is None:
            return 0

        # Get all entries from storage
        entries = await self.storage.search_memory(limit=10000)
        synced = 0

        for entry in entries:
            if entry.embedding:
                chroma_meta = {
                    "memory_type": entry.memory_type,
                    "level": entry.level,
                }
                if entry.project_id:
                    chroma_meta["project_id"] = entry.project_id
                if entry.agent_id:
                    chroma_meta["agent_id"] = entry.agent_id
                if entry.source:
                    chroma_meta["source"] = entry.source

                self._collection.upsert(
                    ids=[str(entry.id)],
                    embeddings=[entry.embedding],
                    documents=[entry.content],
                    metadatas=[chroma_meta],
                )
                synced += 1

        logger.info("Synced %d entries to ChromaDB", synced)
        return synced

    async def get_status(self) -> dict[str, Any]:
        """Get memory system status."""
        collection_count = self._collection.count() if self._collection else 0
        return {
            "initialized": self._collection is not None,
            "collection_count": collection_count,
            "embedding_provider": type(self.embedding_provider).__name__,
            "embedding_dimension": self.embedding_provider.dimension(),
            "persist_dir": str(self.persist_dir) if self.persist_dir else None,
        }

    @staticmethod
    def _build_where_filter(
        memory_type: str | None = None,
        level: str | None = None,
        project_id: str | None = None,
        agent_id: str | None = None,
    ) -> dict | None:
        """Build a ChromaDB where filter from parameters."""
        conditions = []
        if memory_type:
            conditions.append({"memory_type": memory_type})
        if level:
            conditions.append({"level": level})
        if project_id:
            conditions.append({"project_id": project_id})
        if agent_id:
            conditions.append({"agent_id": agent_id})

        if not conditions:
            return None
        if len(conditions) == 1:
            return conditions[0]
        return {"$and": conditions}
