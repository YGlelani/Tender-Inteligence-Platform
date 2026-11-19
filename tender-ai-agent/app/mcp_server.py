"""
MCP (Model Context Protocol) server exposing tender tools.

Uses the official mcp Python SDK with SSE transport so external
MCP clients (Claude Desktop, Cursor, custom agents) can discover
and invoke tools over HTTP.

Mounted onto the FastAPI app at /mcp/sse and /mcp/messages.
"""
import logging
from typing import Any

import httpx
from mcp.server import Server
from mcp.types import Tool, TextContent
from mcp.server.sse import SseServerTransport
from starlette.requests import Request
from starlette.responses import Response

from .config import ai_service_headers, get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# -------- MCP Server --------
mcp = Server("tender-ai-agent")


# -------- Tool definitions --------
@mcp.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search_tenders",
            description="Search open South African government tenders by keyword, province, or category.",
            inputSchema={
                "type": "object",
                "properties": {
                    "keyword": {"type": "string"},
                    "province": {"type": "string"},
                    "category": {"type": "string"},
                    "status": {"type": "string", "default": "Open"},
                    "limit": {"type": "integer", "default": 5},
                },
            },
        ),
        Tool(
            name="semantic_search_tenders",
            description="Find open tenders by meaning (vector search), e.g. 'fixing potholes' finds road rehabilitation tenders.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "province": {"type": "string"},
                    "category": {"type": "string"},
                    "limit": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="get_tender_details",
            description="Fetch full details of a single tender by tender_number.",
            inputSchema={
                "type": "object",
                "properties": {"tender_number": {"type": "string"}},
                "required": ["tender_number"],
            },
        ),
        Tool(
            name="get_tender_documents",
            description="List documents attached to a tender.",
            inputSchema={
                "type": "object",
                "properties": {"tender_number": {"type": "string"}},
                "required": ["tender_number"],
            },
        ),
        Tool(
            name="get_bid_strategy",
            description="Generate a rule-based bid strategy for a tender and business profile.",
            inputSchema={
                "type": "object",
                "properties": {
                    "tender_number": {"type": "string"},
                    "profile_id": {"type": "integer"},
                },
                "required": ["tender_number", "profile_id"],
            },
        ),
    ]


@mcp.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    logger.info("MCP call_tool: %s %s", name, arguments)

    async with httpx.AsyncClient(timeout=60) as client:
        try:
            if name == "search_tenders":
                params = {k: v for k, v in arguments.items() if v}
                params.setdefault("status", "Open")
                params.setdefault("limit", 5)
                r = await client.get(f"{settings.client_api_url}/tenders", params=params)
                r.raise_for_status()
                data = r.json()
                tenders = data.get("tenders", [])[: params.get("limit", 5)]
                text = "\n".join(
                    f"- [{t.get('tender_number')}] {t.get('title')} ({t.get('province')})"
                    for t in tenders
                ) or "No tenders found."
                return [TextContent(type="text", text=text)]

            if name == "semantic_search_tenders":
                from .tools.semantic_search import semantic_search_tenders
                text = await semantic_search_tenders.ainvoke(arguments)
                return [TextContent(type="text", text=text)]

            if name == "get_tender_details":
                tn = arguments.get("tender_number")
                r = await client.get(f"{settings.client_api_url}/tenders/{tn}")
                if r.status_code == 404:
                    return [TextContent(type="text", text=f"Tender '{tn}' not found.")]
                r.raise_for_status()
                import json
                return [TextContent(type="text", text=json.dumps(r.json(), indent=2))]

            if name == "get_tender_documents":
                tn = arguments.get("tender_number")
                r = await client.get(f"{settings.client_api_url}/tenders/{tn}")
                if r.status_code == 404:
                    return [TextContent(type="text", text=f"Tender '{tn}' not found.")]
                r.raise_for_status()
                docs = r.json().get("documents") or []
                if not docs:
                    return [TextContent(type="text", text=f"No documents for '{tn}'.")]
                lines = [
                    f"{i}. {d.get('name')} — {d.get('url', '')}"
                    for i, d in enumerate(docs, 1)
                ]
                return [TextContent(type="text", text="\n".join(lines))]

            if name == "get_bid_strategy":
                tn = arguments.get("tender_number")
                pid = arguments.get("profile_id")
                # create tender in AI service
                r = await client.get(f"{settings.client_api_url}/tenders/{tn}")
                r.raise_for_status()
                t = r.json()
                cr = await client.post(
                    f"{settings.ai_service_url}/api/tenders",
                    headers=ai_service_headers(),
                    json={
                        "title": t.get("title", "Untitled"),
                        "organisation": t.get("organisation_name") or t.get("organisation"),
                        "description": t.get("description") or t.get("title", ""),
                        "source_url": t.get("tender_url"),
                        "closing_date": str(t.get("closing_date")) if t.get("closing_date") else None,
                    },
                )
                cr.raise_for_status()
                tid = cr.json()["id"]
                sr = await client.post(
                    f"{settings.ai_service_url}/api/tenders/{tid}/bid-strategy/{pid}",
                    headers=ai_service_headers(),
                )
                sr.raise_for_status()
                import json
                return [TextContent(type="text", text=json.dumps(sr.json(), indent=2))]

            return [TextContent(type="text", text=f"Unknown tool: {name}")]

        except Exception as e:
            logger.exception("MCP tool error")
            return [TextContent(type="text", text=f"Error: {e}")]


# -------- SSE transport (mounted onto FastAPI) --------
_sse_transport = SseServerTransport("/mcp/messages/")


async def handle_sse(request: Request) -> Response:
    """SSE endpoint — MCP clients connect here."""
    async with _sse_transport.connect_sse(
        request.scope, request.receive, request._send
    ) as (read_stream, write_stream):
        await mcp.run(
            read_stream,
            write_stream,
            mcp.create_initialization_options(),
        )
    return Response()


async def handle_messages(request: Request) -> Response:
    """POST endpoint — MCP clients send messages here."""
    await _sse_transport.handle_post_message(request.scope, request.receive, request._send)
    return Response()


# -------- Legacy manifest (kept for backward compat) --------
def get_mcp_manifest() -> dict:
    """Old JSON manifest — kept so existing /mcp/tools callers don't break."""
    from .tools.search_tenders import search_tenders
    from .tools.get_tender import get_tender_details
    from .tools.get_documents import get_tender_documents
    from .tools.upload_business_profile import upload_business_profile
    from .tools.bid_strategy import get_bid_strategy
    from .tools.semantic_search import semantic_search_tenders

    tools = [
        search_tenders,
        get_tender_details,
        get_tender_documents,
        upload_business_profile,
        get_bid_strategy,
        semantic_search_tenders,
    ]
    manifest = []
    for t in tools:
        schema = t.args_schema.model_json_schema() if t.args_schema else {"type": "object", "properties": {}}
        manifest.append({
            "name": t.name,
            "description": t.description,
            "inputSchema": schema,
        })
    return {"tools": manifest}


def get_langchain_tools() -> list:
    """Return the tools as LangChain objects for the ReAct agent."""
    from .tools.search_tenders import search_tenders
    from .tools.get_tender import get_tender_details
    from .tools.get_documents import get_tender_documents
    from .tools.upload_business_profile import upload_business_profile
    from .tools.bid_strategy import get_bid_strategy
    from .tools.semantic_search import semantic_search_tenders
    return [
        search_tenders,
        get_tender_details,
        get_tender_documents,
        upload_business_profile,
        get_bid_strategy,
        semantic_search_tenders,
    ]