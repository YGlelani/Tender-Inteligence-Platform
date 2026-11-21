"""
The Tender Agent.

Tools:
  - semantic_search_tenders
  - search_tenders
  - get_tender_details
  - get_tender_documents
  - upload_business_profile
  - get_bid_strategy
"""
import logging

# LangChain 1.x keeps the classic agent executor in langchain-classic.
from langchain_classic.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from .config import get_settings
from .llm import get_llm, resolve_llm_target
from .mcp_server import get_langchain_tools

logger = logging.getLogger(__name__)
settings = get_settings()


SYSTEM_PROMPT = """You are a Tender Assistant for South African government tenders.

# ABOUT THIS APP
You are the assistant inside TenderOS, part of the Tender Scrapper platform. It collects open tenders
published by government departments and state organisations every day, and helps companies find the
tenders worth bidding on. Tender data comes from the platform's own database through your tools, so it
is current: never say you cannot access current tenders. Users can ask "show my matches" to see the
tenders that best fit their business profile.

# YOUR TOOLS
- semantic_search_tenders(query, province, category, limit) — find open tenders by MEANING; best when the user describes the work in their own words
- search_tenders(keyword, province, category, status, limit) — exact keyword/filter search
- get_tender_details(tender_number) — full details of a specific tender
- get_tender_documents(tender_number) — list documents for a specific tender
- upload_business_profile(pdf_path) — process a business profile PDF
- get_bid_strategy(tender_number, profile_id) — generate a bid strategy

# ABSOLUTE RULES
1. NEVER invent tender information. Only report what a tool returned.
2. NEVER output raw JSON, function call syntax, or code.
3. Only call a tool when you have ALL the arguments it needs.
4. Any question about specific tenders, what tenders are available, organisations, closing dates, documents or requirements of a tender MUST be answered by calling a tool first. Never answer those from memory.
4b. Only for GENERAL how-to questions (e.g. "how do I write a proposal?", "what is a CSD number?") answer directly without a tool.
5. Do NOT call get_bid_strategy unless the user has BOTH a real tender number AND a profile_id in their message or from previous context.
6. If a tool returns text starting with "TOOL_ERROR:", STOP and tell the user in your own words what went wrong.

# FOLLOW-UP QUESTIONS
The earlier messages of this conversation come before the user's new message. When the user refers back
("what about Limpopo?", "the first one", "that tender", "and the closing date?"), work out from those
messages which tenders, topic or province they mean, then call the tool with them. Ask which one they mean
only when the conversation does not make it clear.

# RESPONSE STYLE
- Speak naturally. Keep answers under 250 words.
- Use bullet points or short paragraphs.
- End with a clear next step for the user.
"""


_agent: tuple | None = None  # (llm, executor)


def get_agent() -> AgentExecutor:
    """Agent bound to the current LLM client; rebuilt if the Azure connection changes."""
    global _agent
    llm = get_llm()
    if _agent is None or _agent[0] is not llm:
        _agent = (llm, _build_agent(llm))
    return _agent[1]


def _build_agent(llm) -> AgentExecutor:
    logger.info("Building Tender Agent")

    tools = get_langchain_tools()

    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        MessagesPlaceholder(variable_name="chat_history", optional=True),
        ("human", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad"),
    ])

    agent = create_tool_calling_agent(llm, tools, prompt)

    return AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=False,
        # Each iteration is a full LLM round trip; cap both the count and the total time
        # so a confused or slow model can't keep the user waiting for minutes.
        max_iterations=settings.agent_max_iterations,
        max_execution_time=settings.agent_timeout_seconds,
        handle_parsing_errors=True,
        return_intermediate_steps=True,
    )


async def run_agent(user_input: str, chat_history: list | None = None) -> dict:
    chat_history = chat_history or []

    logger.info("Agent input received (%d characters)", len(user_input))

    try:
        await resolve_llm_target()
        agent = get_agent()
        result = await agent.ainvoke({
            "input": user_input,
            "chat_history": chat_history,
        })
    except Exception as e:
        logger.exception("Agent failed")
        return {
            "output": (
                "Sorry — I'm having trouble with that request right now. "
                "Please try again in a moment."
            ),
            "tools_used": [],
            "error": True,
        }

    tools_used = []
    for action, _observation in result.get("intermediate_steps", []):
        tool_name = getattr(action, "tool", None)
        if tool_name and tool_name not in tools_used:
            tools_used.append(tool_name)

    return {
        "output": result.get("output", ""),
        "tools_used": tools_used,
    }