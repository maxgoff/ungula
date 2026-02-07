"""
Hybrid search combining vector similarity and keyword matching.

Merges results from ChromaDB vector search with keyword-based
scoring for better retrieval quality, especially for exact terms.
"""

import re
from typing import Any


DEFAULT_VECTOR_WEIGHT = 0.7
DEFAULT_KEYWORD_WEIGHT = 0.3


def hybrid_search(
    vector_results: list[dict[str, Any]],
    query: str,
    *,
    vector_weight: float = DEFAULT_VECTOR_WEIGHT,
    keyword_weight: float = DEFAULT_KEYWORD_WEIGHT,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    Re-rank vector search results using hybrid scoring.

    Combines vector similarity scores with keyword match scores
    to produce a final ranking. This helps surface results that
    contain exact query terms even if they're not the closest
    in embedding space.

    Args:
        vector_results: Results from vector search, each with
            'content', 'score', 'id', 'metadata'.
        query: The original search query.
        vector_weight: Weight for vector similarity (0-1).
        keyword_weight: Weight for keyword match (0-1).
        limit: Maximum results to return.

    Returns:
        Re-ranked results with added 'hybrid_score' and 'keyword_score'.
    """
    if not vector_results:
        return []

    # Normalize weights
    total_weight = vector_weight + keyword_weight
    v_weight = vector_weight / total_weight
    k_weight = keyword_weight / total_weight

    # Extract query terms (lowercase, deduplicated)
    query_terms = _extract_terms(query)

    # Score each result
    scored = []
    for result in vector_results:
        content = result.get("content", "")
        vector_score = result.get("score", 0.0)

        # Calculate keyword score
        k_score = _keyword_score(content, query_terms)

        # Hybrid score
        hybrid_score = (v_weight * vector_score) + (k_weight * k_score)

        scored.append({
            **result,
            "vector_score": vector_score,
            "keyword_score": k_score,
            "hybrid_score": hybrid_score,
        })

    # Sort by hybrid score descending
    scored.sort(key=lambda x: x["hybrid_score"], reverse=True)

    return scored[:limit]


def _extract_terms(text: str) -> list[str]:
    """Extract meaningful search terms from text."""
    # Lowercase and split on non-alphanumeric
    words = re.findall(r"[a-z0-9]+", text.lower())
    # Remove very short words and common stop words
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "has", "have", "had", "do", "does", "did", "will", "would",
        "could", "should", "may", "might", "can", "to", "of", "in",
        "for", "on", "with", "at", "by", "from", "it", "this", "that",
        "and", "or", "not", "but", "if", "as", "so", "no", "yes",
    }
    return [w for w in words if len(w) > 2 and w not in stop_words]


def _keyword_score(content: str, query_terms: list[str]) -> float:
    """
    Calculate keyword match score (0-1).

    Uses term frequency with diminishing returns.
    """
    if not query_terms or not content:
        return 0.0

    content_lower = content.lower()
    content_terms = set(re.findall(r"[a-z0-9]+", content_lower))

    # Count matching terms
    matches = sum(1 for term in query_terms if term in content_terms)

    if matches == 0:
        return 0.0

    # Base score: fraction of query terms found
    base_score = matches / len(query_terms)

    # Bonus for exact phrase match (partial)
    query_lower = " ".join(query_terms)
    phrase_bonus = 0.0
    if len(query_terms) > 1 and query_lower in content_lower:
        phrase_bonus = 0.2

    return min(1.0, base_score + phrase_bonus)
