"""
Tool: semantic_search_tenders

Finds open tenders by meaning (vector search over tender embeddings), not by
exact keywords. Optional province / category filters are applied inside the
vector query.
"""
import logging

from langchain_core.tools import tool

from ..embeddings import embeddings_ready
from ..tender_index import semantic_search

logger = logging.getLogger(__name__)


@tool
async def semantic_search_tenders(query: str, province: str = "", category: str = "",
                                  limit: int = 5) -> str:
    """
    Find open tenders whose description MEANS the same as the query, even when
    they use different words (e.g. "fixing potholes" finds "road rehabilitation").

    Prefer this over search_tenders when the user describes the kind of work
    in their own words. Use search_tenders for exact filters only.

    Args:
        query: What the user is looking for, in plain words.
        province: Optional South African province, e.g. "Western Cape".
        category: Optional tender category.
        limit: How many results (default 5, max 10).

    Returns:
        A plain-text list of matching tenders with a relevance score.
    """
    if not query or not query.strip():
        return "TOOL_ERROR: No query given. Ask the user what kind of work they are looking for."
    if not embeddings_ready():
        # Answer instantly instead of waiting on a broken embedding endpoint.
        return ("TOOL_ERROR: Semantic search is unavailable right now. "
                "Call search_tenders with a short keyword instead.")
    try:
        results = await semantic_search(query, province=province or None,
                                        category=category or None, limit=min(int(limit or 5), 10))
    except Exception as e:
        logger.error("semantic_search_tenders failed: %s", e)
        return ("TOOL_ERROR: Semantic search is unavailable right now. "
                "Use search_tenders instead, or tell the user to try again.")

    if not results:
        return "No open tenders matched that description. Suggest the user broadens the search."

    lines = [f"Top {len(results)} tenders by meaning (score 1.0 = perfect match):"]
    for t in results:
        lines.append(
            f"- [{t.get('tender_number')}] {t.get('title', '')[:100]} — {t.get('organisation', '')} "
            f"({t.get('province') or 'N/A'}), closes: {t.get('closing_date') or 'not specified'}, "
            f"score {t['score']:.2f}"
        )
    return "\n".join(lines)
