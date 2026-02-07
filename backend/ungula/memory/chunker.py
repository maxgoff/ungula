"""
Markdown-aware text chunking for the memory system.

Splits documents into overlapping chunks that respect markdown structure
(headings, code blocks, paragraphs) for better retrieval quality.
"""

import re


DEFAULT_CHUNK_SIZE = 500  # tokens (approximated as words)
DEFAULT_CHUNK_OVERLAP = 50  # tokens overlap between chunks
MIN_CHUNK_SIZE = 50


def chunk_text(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    source: str | None = None,
) -> list[dict]:
    """
    Split text into overlapping chunks, respecting markdown structure.

    Args:
        text: The text to chunk.
        chunk_size: Target chunk size in approximate words.
        chunk_overlap: Number of words to overlap between chunks.
        source: Optional source identifier for metadata.

    Returns:
        List of chunk dicts with 'content', 'index', and 'metadata'.
    """
    if not text or not text.strip():
        return []

    # Split into structural sections first
    sections = _split_by_structure(text)

    # Now merge sections into chunks of appropriate size
    chunks = []
    current_chunk_parts: list[str] = []
    current_word_count = 0

    for section in sections:
        section_words = len(section.split())

        if section_words == 0:
            continue

        # If a single section is larger than chunk_size, split it further
        if section_words > chunk_size:
            # Flush current chunk first
            if current_chunk_parts:
                chunks.append("\n\n".join(current_chunk_parts))
                current_chunk_parts = []
                current_word_count = 0

            # Split large section by paragraphs/sentences
            sub_chunks = _split_large_section(section, chunk_size, chunk_overlap)
            chunks.extend(sub_chunks)
            continue

        # Would adding this section exceed chunk_size?
        if current_word_count + section_words > chunk_size and current_chunk_parts:
            chunks.append("\n\n".join(current_chunk_parts))
            # Keep overlap from end of previous chunk
            if chunk_overlap > 0 and current_chunk_parts:
                overlap_text = current_chunk_parts[-1]
                overlap_words = overlap_text.split()
                if len(overlap_words) > chunk_overlap:
                    overlap_text = " ".join(overlap_words[-chunk_overlap:])
                current_chunk_parts = [overlap_text]
                current_word_count = len(overlap_text.split())
            else:
                current_chunk_parts = []
                current_word_count = 0

        current_chunk_parts.append(section)
        current_word_count += section_words

    # Flush remaining
    if current_chunk_parts:
        chunks.append("\n\n".join(current_chunk_parts))

    # Build result dicts
    results = []
    for i, chunk_text_content in enumerate(chunks):
        chunk_text_content = chunk_text_content.strip()
        if len(chunk_text_content.split()) < MIN_CHUNK_SIZE // 5:
            continue  # Skip very tiny chunks
        meta = {"index": i, "word_count": len(chunk_text_content.split())}
        if source:
            meta["source"] = source
        results.append({
            "content": chunk_text_content,
            "index": i,
            "metadata": meta,
        })

    return results


def _split_by_structure(text: str) -> list[str]:
    """Split text by markdown headings and code blocks."""
    # Split on markdown headings (##, ###, etc.)
    # Keep the heading with its content
    sections = []
    current = []

    for line in text.split("\n"):
        # Check if this is a heading
        if re.match(r"^#{1,6}\s", line) and current:
            sections.append("\n".join(current))
            current = []
        current.append(line)

    if current:
        sections.append("\n".join(current))

    return [s for s in sections if s.strip()]


def _split_large_section(
    text: str,
    chunk_size: int,
    chunk_overlap: int,
) -> list[str]:
    """Split a large section into smaller chunks by paragraphs."""
    paragraphs = re.split(r"\n\s*\n", text)
    chunks = []
    current_parts: list[str] = []
    current_words = 0

    for para in paragraphs:
        para_words = len(para.split())
        if para_words == 0:
            continue

        if current_words + para_words > chunk_size and current_parts:
            chunks.append("\n\n".join(current_parts))
            # Overlap
            if chunk_overlap > 0 and current_parts:
                overlap = current_parts[-1]
                words = overlap.split()
                if len(words) > chunk_overlap:
                    overlap = " ".join(words[-chunk_overlap:])
                current_parts = [overlap]
                current_words = len(overlap.split())
            else:
                current_parts = []
                current_words = 0

        current_parts.append(para)
        current_words += para_words

    if current_parts:
        chunks.append("\n\n".join(current_parts))

    return chunks
