# Tender Intelligence API

The project runs a FastAPI application with persistent tender records and a self-hosted [Ollama](https://ollama.com/) AI runtime. The application only calls the runtime over Docker's private service network; it does not require a cloud AI key.

See [API_CONTRACT.md](API_CONTRACT.md) for the frontend/backend endpoint contract, inputs, outputs, and integration notes.

## Start the stack

```powershell
docker compose up --build -d
docker compose exec ollama ollama pull llama3.2:3b
```

The first command starts the API at `http://localhost:8000`; the second downloads the configured language model into the persistent `ollama-data` volume. Model downloads are deliberately separate from container images so changing models does not rebuild the application.

## Tender workflow

Create a tender record:

```powershell
$tender = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/tenders" -ContentType "application/json" -Body '{"title":"Supply of office equipment","organisation":"Example Municipality","description":"Supply and deliver computers and office equipment. Submit a valid tax clearance certificate.","closing_date":"2026-10-31"}'
```

Analyse that tender with the configured model:

```powershell
Invoke-RestMethod -Method Post "http://localhost:8000/api/tenders/$($tender.id)/analyse"
```

The response contains a summary, requirements, risks, and recommended next steps. `GET /api/tenders` lists saved records, and `GET /api/tenders/{id}` retrieves a tender and its latest AI analysis.

## Business profiles and tender matching

Create a business profile containing the services, areas, and compliance information that the AI needs to assess opportunities:

```powershell
$business = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/business-profiles" -ContentType "application/json" -Body '{"business_name":"Example Supplies (Pty) Ltd","description":"Supplier of office technology and equipment to public-sector organisations.","industries":["Technology","Office Solutions"],"services":["Laptop supply","Printer supply","Office equipment delivery"],"service_areas":["Gauteng","National"],"certifications":["CSD registered","Valid tax clearance"]}'
```

Compare that business with a tender:

```powershell
Invoke-RestMethod -Method Post "http://localhost:8000/api/tenders/$($tender.id)/match/$($business.id)"
```

The matching response includes a suitability score, matching capabilities, gaps or risks, and next steps. Use `GET /api/business-profiles` to view the collected profiles.

### How the match score is calculated

| Area | Points | How it matches |
|---|---|---|
| Services | up to 40 | The profile's services (and synonyms) appear in the tender |
| Industries | up to 20 | The profile's industries (and synonyms) appear in the tender |
| Province | up to 20 | The tender is in one of the profile's service areas (10 for a national tender) |
| Category | up to 15 | The **tender-ml** model finds a category the company and the tender share |

The category step sends the company's industries, services and description, and the tenders being ranked, to the tender-ml service (`POST /match-categories`). tender-ml predicts the categories the company most likely works in and compares them with each tender's saved and predicted categories. A match adds 15 points with the reason *"Category matches your business (ML: …)"*.

When the model finds no shared category, or tender-ml cannot be reached, the earlier keyword rule applies (5 points when a service appears in the category name). The ML can therefore only add points, and matching never breaks because of the ML service. The setting is `TENDER_ML_URL` (default `http://tender-ml:9004`).

## Generic AI endpoint

```powershell
Invoke-RestMethod -Method Post http://localhost:8002/api/ai/generate `
  -ContentType 'application/json' `
  -Body '{"prompt":"Summarise this tender notice: ..."}'
```

`GET http://localhost:8002/health` reports whether the AI runtime is reachable. Set `AI_MODEL`, `OLLAMA_BASE_URL`, `AI_REQUEST_TIMEOUT_SECONDS`, and `DATABASE_PATH` in a local `.env` file when needed.

## Ask questions about a PDF

The AI service extracts selectable text from uploaded PDFs with pdfplumber. Uploads are limited to 15 MB and 200 pages, and the AI receives up to 80,000 extracted characters. Scanned/image-only PDFs need OCR before their text can be used.

Extract text without sending it to the model:

```powershell
curl.exe -F "file=@C:\path\to\tender.pdf" http://localhost:8002/api/ai/pdf/extract
```

Ask a question about the PDF:

```powershell
curl.exe -F "file=@C:\path\to\tender.pdf" `
  -F "question=What are the mandatory eligibility requirements?" `
  http://localhost:8002/api/ai/pdf/ask
```

Both endpoints are also available in the interactive API docs at `http://localhost:8002/docs`. Rebuild the AI service after adding the dependencies with `docker compose up --build -d ai`.

## Open tenders

`GET /tenders?status=Open` in the client API and the scraper API lists a tender only while it is still open by its dates:

- with a closing date: until that date and time (South African time);
- without one: for 36 days after it was published. 95% of tenders with a closing date close within 36 days. Tenders saved before the scraper read closing dates (most of those added before late October 2026) have none;
- with neither date: always, since nothing shows that it has closed.

The Smart Alerts API uses the same rule.

## Scraper

### Tender status

A tender is saved with the status of the eTenders list it was found on: `Open` (current), `Closed`, `Cancelled` or `Awarded`. When a tender is seen again, its status and any missing closing date are updated.

### Why each run reads 100 tenders

`ETENDERS_MAX_PAGES_DEFAULT` is `10` in `compose.yaml`, and eTenders shows 10 tenders per page, so each background run (every 30 minutes) reads the newest 100. That keeps runs short: with details, a page takes about 16 seconds, and the full open list (about 2,000 tenders) takes about an hour. Newer tenders always get their closing date this way, but a tender is never revisited once it moves past the first 10 pages.

### Refreshing older tenders (one-off backfill)

`app/backfill.py` walks a whole eTenders list once. Run it inside the scraper container at a quiet time:

```bash
python -m app.backfill --status current --pages 250    # about 1 hour: fills in closing dates of tenders still open
python -m app.backfill --status closed --pages 1000    # about 5 hours: marks stored tenders that eTenders has closed
```

To keep both runs going after you disconnect from the server, start them in the background and follow the log:

```bash
nohup sh -c "docker exec tender-scraper-api python -m app.backfill --status current --pages 250 && \
  docker exec tender-scraper-api python -m app.backfill --status closed --pages 1000" > backfill.log 2>&1 &
tail -f backfill.log | grep BACKFILL    # Ctrl+C stops watching, not the backfill
```

For `closed`, `cancelled` and `awarded`, only tenders already in the database are updated, so eTenders' history (over 100,000 closed tenders) is not imported. The closed list is ordered newest first; 1,000 pages cover roughly the last three to four months. Each run is recorded in `scraping_logs` with the source `backfill_<status>`.
