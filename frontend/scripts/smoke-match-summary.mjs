// Checks the overview page's match helpers: Smart Alerts' matches first, the AI agent's as a fallback.
import assert from "node:assert";

import { matchLine, pickMatches } from "./match-summary.js";

const smart = [
  { tender_number: "09/2026", title: "Office <cleaning>", score: 92 },
  { tender_number: "10/2026", title: "Hygiene services", score: 75 }
];
const overview = { matches: [{ tender_number: "01/2026", title: "Laptops", score: 40 }], tenders_scanned: 200 };

assert.deepStrictEqual(pickMatches(smart, overview), { matches: smart, scanned: null }, "Smart Alerts matches come first");
assert.deepStrictEqual(pickMatches([], overview), { matches: [], scanned: null }, "Smart Alerts finding nothing is shown as nothing");
assert.deepStrictEqual(pickMatches(null, overview), { matches: overview.matches, scanned: 200 }, "the agent's matches are the fallback");
assert.deepStrictEqual(pickMatches(null, null), { matches: [], scanned: null }, "no answer from either service");

const line = matchLine(pickMatches(smart, overview));
assert.ok(line.includes("<strong>2</strong> open tenders match your profile"), "the count is shown");
assert.ok(line.includes("Office &lt;cleaning&gt;"), "titles are escaped");
assert.ok(line.includes("92% fit") && !line.includes("scanned"), "Smart Alerts has no scanned count");
assert.ok(matchLine(pickMatches(null, overview)).includes("(from 200 scanned)"), "the agent's scanned count is kept");
assert.strictEqual(matchLine({ matches: [], scanned: null }), "", "no matches, no line");

console.log("Match summary smoke test passed");
