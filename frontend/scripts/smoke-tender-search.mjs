import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const source = fs.readFileSync(path.join(root, "scripts/tender-search.js"), "utf8");
const api = fs.readFileSync(path.join(root, "scripts/api.js"), "utf8");
const config = fs.readFileSync(path.join(root, "scripts/config.js"), "utf8");

function assert(condition, message) {
  if (!condition) {
    console.error("Tender search smoke test failed: " + message);
    process.exitCode = 1;
  }
}

assert(source.includes('import { tenderSearchApi } from "./api.js";'),
  "tender search must use the shared API module");
assert(source.includes("saveTenderButton(") && source.includes("enableSaveTenderButtons()"),
  "tender cards must use the shared save-and-track button");
assert(source.includes("tenderSearchApi.search(params)"),
  "tender search must call the Search Tender API through the shared wrapper");
assert(source.includes("q: el.search.value.trim()"),
  "search term must use the Search Tender API's q query parameter");
assert(source.includes("offset: state.page * PAGE_SIZE"),
  "pagination offset must be sent to the Search Tender API");
assert(source.includes("params.include_closed = true"),
  "closed tenders must only be requested when the user asks for them");
assert(/tenderSearchApi[\s\S]*CONFIG\.services\.tenderSearch[\s\S]*CONFIG\.endpoints\.tenderSearch/.test(api),
  "tenderSearchApi must use the configured Search Tender service and /tenders/search endpoint");
assert(config.includes('tenderSearch: `${SERVER_ORIGIN}:8001`'),
  "Search Tender API must use the configured client API port 8001");
assert(!source.includes(":9009") && !source.includes("API_BASE_URL"),
  "tender search must not hard-code the Search Tender API address");
if (!process.exitCode) console.log("Tender search API wiring checks passed.");
