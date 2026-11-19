// AI tender-readiness panel on the overview. Additive, like overview-layout.js:
// it inserts its own section and never touches the dashboard's existing markup.
import { alertsApi, onboardingApi } from "./api.js";
import { matchLine, pickMatches } from "./match-summary.js";
import { esc } from "./utils.js";

import { icon } from "./icons.js";
const DISMISS_KEY = "onboarding_dismissed";
const POLL_MS = 5000;

const $ = id => document.getElementById(id);
let pollTimer = null;
let insightRetries = 0;
// Smart Alerts' matches, asked once per page load (the card polls while documents process).
// undefined: not asked yet; null: Smart Alerts had no answer, so the agent's matches are shown.
let smartMatches;

function dismissed() {
    try { return localStorage.getItem(DISMISS_KEY) === "1"; } catch { return false; }
}

function ensurePanel() {
    const page = document.querySelector(".overview-page");
    if (!page) return null;
    let panel = $("readinessPanel");
    if (panel) return panel;

    panel = document.createElement("section");
    panel.id = "readinessPanel";
    panel.className = "overview-panel ready-panel";
    panel.setAttribute("aria-label", "AI tender readiness");
    panel.innerHTML = `
        <div class="overview-panel-heading">
            <div>
                <span class="overview-section-kicker">AI TENDER AGENT</span>
                <h2>Your tender readiness</h2>
                <p id="readySummary">The agent is reviewing your business documents…</p>
                <p class="ready-ai-note">Checked by AI, which can make mistakes. Confirm important details against your documents.</p>
            </div>
            <a class="overview-text-link" href="./onboarding.html">Manage documents <span>${icon("arrow-right")}</span></a>
        </div>
        <div class="ready-body" id="readyBody"><p class="state-msg">Loading your readiness…</p></div>`;

    const anchor = page.querySelector(".overview-kpi-grid") || page.querySelector(".overview-footer");
    page.insertBefore(panel, anchor);
    return panel;
}

function priorityLabel(priority) {
    return { high: "Do now", medium: "Soon", low: "Nice to have" }[priority] || priority;
}

function formatDate(value) {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

function render(data) {
    const r = data.readiness;
    const band = r.score >= 85 ? "good" : r.score >= 60 ? "mid" : "low";

    $("readySummary").textContent = data.ai_summary ||
        (data.processing ? "The agent is reading your documents — this updates automatically."
            : `${r.label}: ${r.verified} of ${r.required_total} key documents verified.`);

    const actions = (data.actions || []).slice(0, 6).map(action => `
        <li data-priority="${esc(action.priority)}">
            <a href="./onboarding.html${action.doc_type ? "#" + encodeURIComponent(action.doc_type) : ""}">
                <span class="ready-priority">${esc(priorityLabel(action.priority))}</span>
                <strong>${esc(action.title)}</strong>
                ${action.detail ? `<small>${esc(action.detail)}</small>` : ""}
            </a>
        </li>`).join("");

    const advice = (data.ai_advice || []).map(item => `
        <li><strong>${esc(item.title)}</strong><small>${esc(item.detail)}</small></li>`).join("");

    const expiring = (data.expiring || []).slice(0, 4).map(item => `
        <li data-expired="${item.days_left < 0}">
            <strong>${esc(item.label)}</strong>
            <small>${item.days_left < 0 ? "Expired" : "Expires"} ${esc(formatDate(item.expiry_date))}
            ${item.days_left >= 0 ? `· ${item.days_left} day${item.days_left === 1 ? "" : "s"} left` : ""}</small>
        </li>`).join("");

    $("readyBody").innerHTML = `
        <div class="ready-score">
            <div class="onb-ring" data-band="${band}" style="--score:${r.score}"><strong>${r.score}%</strong></div>
            <div class="ready-score-text">
                <strong>${esc(r.label)}</strong>
                <ul class="ready-counts">
                    <li data-kind="ok"><b>${r.verified}</b> verified</li>
                    <li data-kind="warn"><b>${r.attention}</b> need attention</li>
                    <li data-kind="missing"><b>${r.missing}</b> missing</li>
                </ul>
                ${data.processing ? '<small class="onb-muted"><span class="onb-spinner" aria-hidden="true"></span> Processing new uploads…</small>' : ""}
            </div>
        </div>
        <div class="ready-col">
            <h3>What to do next</h3>
            ${actions ? `<ol class="ready-actions">${actions}</ol>` : '<p class="ready-empty">Nothing outstanding — your documents are tender-ready. ' + icon("check") + '</p>'}
        </div>
        <div class="ready-col">
            <h3>Agent insights</h3>
            ${advice ? `<ul class="ready-advice">${advice}</ul>` : `<p class="ready-empty">${data.processing ? "Insights appear once your documents are processed." : "Preparing tailored advice…"}</p>`}
            ${expiring ? `<h3 class="ready-sub">Expiring soon</h3><ul class="ready-expiring">${expiring}</ul>` : ""}
        </div>
        ${matchLine(pickMatches(smartMatches, data))}`;
}

async function loadSmartMatches() {
    try {
        return await alertsApi.matches();
    } catch (error) {
        console.warn("Smart Alerts matches unavailable:", error);
        return null;
    }
}

function renderUnavailable() {
    $("readySummary").textContent = "The AI agent is not reachable right now.";
    $("readyBody").innerHTML = '<p class="state-msg">Readiness will appear here once the tender agent service is back online.</p>';
}

async function loadReadiness() {
    clearTimeout(pollTimer);
    if (!localStorage.getItem("access_token")) return;

    let data;
    try {
        data = await onboardingApi.overview();
    } catch (error) {
        console.warn("Readiness unavailable:", error);
        if (ensurePanel()) renderUnavailable();
        return;
    }

    // First visit after signup: send the user to the document step.
    if (data.onboarding_needed && !dismissed()) {
        window.location.replace("./onboarding.html?welcome=1");
        return;
    }

    if (!ensurePanel()) return;
    if (smartMatches === undefined) smartMatches = await loadSmartMatches();
    render(data);

    // Keep polling while documents process, and briefly while background insights are computed.
    const waitingForInsights = !data.insights_updated_at && !data.onboarding_needed && insightRetries++ < 6;
    if (data.processing || waitingForInsights) {
        pollTimer = setTimeout(loadReadiness, POLL_MS);
    }
}

document.getElementById("refreshOverview")?.addEventListener("click", async () => {
    insightRetries = 0;
    smartMatches = undefined;
    try { await onboardingApi.refresh(); } catch {}
    setTimeout(loadReadiness, 2500);
});

loadReadiness();
