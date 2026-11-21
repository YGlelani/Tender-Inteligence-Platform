# Tender AI Agent

A LangChain ReAct agent that helps users find, understand, and evaluate
South African government tenders.

## What it does

You send a natural-language message:

> "Find IT tenders in the Western Cape that close next month."

The agent:

1. **Thinks** about what to do
2. **Calls tools** to search, fetch details, analyze, or match tenders
3. **Returns** a natural-language answer with the results

Under the hood it uses:

- **Mistral** on Azure AI — the LLM that makes decisions
- **client-api** — a tool for searching and fetching tenders
- **ai service** — a tool for analyzing tenders and matching business profiles
- **tender-ml** — the team's machine learning model, which predicts tender categories
- **LangChain** — the framework that ties tools + LLM into an agent

## Matches and chat routing

- **One set of matches.** The dashboard (`/agent/my-profile`), the chat greeting and "show my matches" all take the user's matches from Smart Alerts (alerts-api `GET /matches`, called with the user's own sign-in), so they always show the same tenders as the Smart Alerts page. Smart Alerts scores every open tender against the company profile and the uploaded business documents, matches whole phrases rather than single words, and leaves out tenders outside the company's provinces or above its CIDB grade. If Smart Alerts has nothing for the user or cannot be reached, the AI service's matcher is used instead; `match_source` in the `/agent/my-profile` response says which one answered. Set `ALERTS_API_URL` when Smart Alerts is not at its default address on the shared network.
- **"Show my matches"**, "5 tenders that match my business profile" and similar messages return the signed-in user's best-matching open tenders, with scores and reasons. The user is only asked to upload a profile when they have none. Profiles are found by the signed-in email regardless of letter case. If the AI service fails, `/agent/my-profile` now answers `502` instead of reporting that the user has no profile.
- **Routing** compares whole words, so "profile" is no longer mistaken for "file", and tolerates small typos in key words ("bussiness", "march my profile"). Questions about the app itself ("what is Tender Scrapper?") go to the assistant instead of a search.
- **Personal questions** ("what is my company called?") get the user's own profile as context, and their answers are never stored in the shared answer cache.
- **Searches stay in the user's provinces.** A search that names no province ("find laptop tenders") only shows tenders from the provinces the user's matches use, plus national tenders: the provinces on their Business Profile in Smart Alerts or, without a Business Profile, the service areas of their uploaded profile. The reply says which provinces it searched. A province the user names ("...in KwaZulu-Natal") is searched instead. The assistant is told the same provinces for the searches it runs itself. A user with no provinces set is searched everywhere.
- **Follow-up questions** ("what about Limpopo?", "show the documents for the first one", "tell me more about that tender", "and the closing date?") go to the assistant together with the last three exchanges of the conversation, so it can tell which tenders, topic or province the user means. Follow-ups are never answered from, or stored in, the shared answer cache. Each message starts without the previous message's tender number, so an earlier tender is never reused by mistake. The conversation is kept in Redis for 24 hours (the last 20 messages); if Redis cannot be reached, the service logs `Chat memory unavailable` and answers each message on its own.

## Account deletion

When a user deletes their account, Signup-api calls
`POST /internal/accounts/delete` with `{"email": ...}` and the header
`X-Internal-Key: <ACCOUNT_DELETION_KEY>`. The key must be set to the same value
in both repositories' GitHub Actions secrets; without it the endpoint answers 503.

The agent first asks the AI service to delete its copies of the business profile.
If that fails it answers 502 and deletes nothing, so the user can try again.
Otherwise it deletes the user's uploaded files and vault records, their insights,
their cached overview, matches and document extractions, cached profile
extractions (a cache shared by all users), their chat history in Redis and their
conversation state in memory. See `app/account_deletion.py`.

## Search with the ML category model

A search first asks tender-ml, the team's category model, for the request's category. When the model is at least 70% sure (for example "laptops" → *Supplies: Computer Equipment*), the search looks inside that category first and says so in the reply. Otherwise, or when that finds nothing, the normal search runs.

Settings: `TENDER_ML_URL` (default `http://tender-ml:9004`) and `TENDER_ML_TIMEOUT` in seconds (default `2`). When tender-ml cannot be reached, search works exactly as before.

<!-- trigger -->

<!-- deploy trigger -->
