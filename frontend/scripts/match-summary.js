/**
 * Which tender matches the overview page shows.
 *
 * Smart Alerts (alerts-api) matches every user who has a Business Profile or uploaded
 * business documents, and the AI workspace shows the same list. When Smart Alerts has
 * no answer for the user, the AI agent's own matches are shown instead.
 */
import { esc } from "./utils.js";

export function pickMatches(smartAlerts, agentOverview) {
    if (Array.isArray(smartAlerts)) return { matches: smartAlerts, scanned: null };
    return { matches: agentOverview?.matches || [], scanned: agentOverview?.tenders_scanned || null };
}

export function matchLine({ matches, scanned }) {
    if (!matches.length) return "";
    const best = matches[0];
    return `<p class="ready-matches"><strong>${matches.length}</strong> open tender${matches.length === 1 ? "" : "s"} match your profile` +
        (scanned ? ` (from ${Number(scanned).toLocaleString()} scanned)` : "") +
        ` — best: <a href="./tender.html?number=${encodeURIComponent(best.tender_number)}">${esc(best.title)}</a> · ${esc(best.score)}% fit</p>`;
}
