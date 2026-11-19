import { tenderSearchApi } from "./api.js";
import { saveTenderButton, enableSaveTenderButtons } from "./save-tender.js";
import { escapeHtml, hasClosingDatePassed } from "./utils.js";


import { icon } from "./icons.js";
const PAGE_SIZE = 20;

const state = {
    page: 0,
    total: 0,
    tenders: [],
    closingSoon: false,
    overOneMillion: false,
    loading: false,
    requestId: 0,
    hasNextPage: false
};

const initialSearchQuery = new URLSearchParams(window.location.search).get("q") || "";

const el = {
    form: document.getElementById("tenderSearchForm"),
    search: document.getElementById("tenderSearchInput"),
    province: document.getElementById("tenderProvinceFilter"),
    category: document.getElementById("tenderCategoryFilter"),
    organisation: document.getElementById("tenderOrganisationFilter"),
    status: document.getElementById("tenderStatusFilter"),
    closing: document.getElementById("closingSoonFilter"),
    budget: document.getElementById("overBudgetFilter"),
    more: document.getElementById("toggleAdvancedFilters"),
    advanced: document.getElementById("advancedTenderFilters"),
    clear: document.getElementById("clearTenderFilters"),
    grid: document.getElementById("tenderResultsGrid"),
    count: document.getElementById("tenderResultsCount"),
    apiStatus: document.getElementById("tenderApiStatus"),
    previous: document.getElementById("tenderPreviousPage"),
    next: document.getElementById("tenderNextPage"),
    pageInfo: document.getElementById("tenderPageInformation")
};

if (el.search) {
    el.search.value = initialSearchQuery;
}

function getValue(object, keys, fallback = "") {
    for (const key of keys) {
        const value = object?.[key];

        if (value !== undefined && value !== null && value !== "") {
            return value;
        }
    }

    return fallback;
}

function normalizeTender(raw) {
    const organisation = getValue(raw, [
        "organisation",
        "organization",
        "organisation_name",
        "organization_name",
        "procuring_entity"
    ]);

    const category = getValue(raw, [
        "category",
        "category_name",
        "industry",
        "sector"
    ]);

    return {
        id: getValue(raw, ["id", "tender_id"], null),
        number: getValue(raw, [
            "tender_number",
            "reference_number",
            "reference",
            "bid_number",
            "number"
        ], "Reference unavailable"),
        title: getValue(raw, [
            "title",
            "tender_title",
            "name"
        ], "Untitled tender"),
        description: getValue(raw, [
            "description",
            "summary",
            "scope"
        ]),
        organisation: typeof organisation === "object"
            ? getValue(organisation, ["name", "organisation_name", "title"])
            : organisation,
        category: typeof category === "object"
            ? getValue(category, ["name", "category_name", "title"])
            : category,
        province: getValue(raw, [
            "province",
            "province_name",
            "location"
        ]),
        closingDate: getValue(raw, [
            "closing_date",
            "closing_at",
            "submission_deadline",
            "deadline",
            "due_date"
        ]),
        budget: getValue(raw, [
            "estimated_budget",
            "budget",
            "estimated_value",
            "contract_value",
            "value"
        ], null),
        status: getValue(raw, ["status", "tender_status"]),
        url: getValue(raw, [
            "url",
            "tender_url",
            "source_url",
            "link"
        ]),
        match: getValue(raw, [
            "match_percentage",
            "match_score",
            "match"
        ], null)
    };
}

function getTenderArray(payload) {
    if (Array.isArray(payload)) return payload;

    for (const key of ["tenders", "items", "results"]) {
        if (Array.isArray(payload?.[key])) {
            return payload[key];
        }
    }

    return [];
}

function parseDate(value) {
    if (!value) return null;

    const date = new Date(value);

    return Number.isNaN(date.getTime()) ? null : date;
}

function daysUntilClosing(value) {
    const date = parseDate(value);

    if (!date) return null;

    const today = new Date();
    today.setHours(0, 0, 0, 0);
    date.setHours(0, 0, 0, 0);

    return Math.ceil((date.getTime() - today.getTime()) / 86400000);
}

function formatDate(value) {
    const date = parseDate(value);

    if (!date) return "Not published";

    return new Intl.DateTimeFormat("en-ZA", {
        day: "2-digit",
        month: "short",
        year: "numeric"
    }).format(date);
}

function parseMoney(value) {
    if (value === null || value === undefined || value === "") {
        return null;
    }

    if (typeof value === "number") {
        return Number.isFinite(value) ? value : null;
    }

    const cleaned = String(value)
        .replace(/ZAR/gi, "")
        .replace(/R/gi, "")
        .replace(/,/g, "")
        .replace(/\s/g, "")
        .trim();

    const number = Number(cleaned);

    return Number.isFinite(number) ? number : null;
}

function formatMoney(value) {
    const amount = parseMoney(value);

    if (amount === null) return "Not published";

    return new Intl.NumberFormat("en-ZA", {
        style: "currency",
        currency: "ZAR",
        maximumFractionDigits: 0
    }).format(amount);
}

function getClosingStatus(tender) {
    const days = daysUntilClosing(tender.closingDate);
    const status = String(tender.status || "").toLowerCase();

    if (["closed", "expired", "cancelled", "awarded"].includes(status)) {
        return { text: tender.status, className: "" };
    }

    if (days === null) {
        return {
            text: tender.status || "Closing date unavailable",
            className: ""
        };
    }

    if (days < 0) {
        return { text: "Closing date passed", className: "" };
    }

    if (days === 0) {
        return { text: "Closes today", className: "urgent" };
    }

    if (days <= 3) {
        return {
            text: `Closes in ${days} ${days === 1 ? "day" : "days"}`,
            className: "urgent"
        };
    }

    if (days <= 14) {
        return {
            text: `Closes in ${days} days`,
            className: "soon"
        };
    }

    return { text: `Closes in ${days} days`, className: "" };
}

function calculateMatch(tender) {
    if (tender.match === null || tender.match === "") {
        return null;
    }

    const score = Number(tender.match);

    if (!Number.isFinite(score)) return null;

    const percentage = score > 0 && score <= 1 ? score * 100 : score;

    return Math.max(0, Math.min(100, Math.round(percentage)));
}

function setApiStatus(online, message) {
    el.apiStatus.textContent = message;
    el.apiStatus.classList.toggle("online", online);
    el.apiStatus.classList.toggle("offline", !online);
}

function showState(message, isError = false) {
    el.grid.innerHTML = `
        <div class="ts-state-card ${isError ? "error" : ""}">
            <p>${escapeHtml(message)}</p>
            ${isError ? '<button type="button" id="retryTenderSearch">Try again</button>' : ""}
        </div>
    `;

    const retry = document.getElementById("retryTenderSearch");

    if (retry) {
        retry.addEventListener("click", loadTenders);
    }
}

function updateCategories(tenders) {
    const selected = el.category.value;

    const categories = [
        ...new Set(tenders.map(tender => tender.category).filter(Boolean))
    ].sort((a, b) => a.localeCompare(b));

    el.category.innerHTML = '<option value="">Any industry</option>';

    for (const category of categories) {
        const option = document.createElement("option");
        option.value = category;
        option.textContent = category;
        el.category.appendChild(option);
    }

    if (categories.includes(selected)) {
        el.category.value = selected;
    }
}

function createTenderCard(tender) {
    const closing = getClosingStatus(tender);
    const match = calculateMatch(tender);

    const organisation = [
        tender.organisation || "Organisation not published",
        tender.category || "",
        tender.province || ""
    ].filter(Boolean).join(" — ");

    const matchMarkup = match === null
        ? ""
        : `<span class="ts-match-score">${match}% match</span>`;

    const description = tender.description
        ? escapeHtml(tender.description)
        : "Review the tender details and submission requirements before applying.";

    const linkMarkup = /^https?:\/\//i.test(tender.url)
        ? `<a class="ts-tender-action" href="${escapeHtml(tender.url)}" target="_blank" rel="noopener noreferrer">View tender ${icon("external-link")}</a>`
        : "";

    return `
        <article class="ts-tender-card">
            <div class="ts-tender-topline">
                <span class="ts-tender-number">${escapeHtml(tender.number)}</span>
                <span class="ts-tender-type">${escapeHtml(tender.category || "Tender")}</span>
                ${matchMarkup}
            </div>

            <h2 class="ts-tender-title">${escapeHtml(tender.title)}</h2>

            <p class="ts-tender-organisation">${escapeHtml(organisation)}</p>

            <div class="ts-tender-details">
                <div>
                    <span class="ts-detail-label">Closing date</span>
                    <span class="ts-detail-value">${escapeHtml(formatDate(tender.closingDate))}</span>
                </div>

                <div>
                    <span class="ts-detail-label">Estimated budget</span>
                    <span class="ts-detail-value">${escapeHtml(formatMoney(tender.budget))}</span>
                </div>
            </div>

            <div class="ts-tender-badges">
                <span class="ts-status-badge ${closing.className}">
                    ${escapeHtml(closing.text)}
                </span>
            </div>

            <p class="ts-tender-description">${description}</p>

            <div class="ts-card-actions">
                ${linkMarkup}
                ${saveTenderButton({ id: tender.id, number: tender.number, closingDate: tender.closingDate }, "ts-save-tender")}
            </div>
        </article>
    `;
}

function updatePagination() {
    el.previous.disabled = state.loading || state.page === 0;
    el.next.disabled = state.loading || !state.hasNextPage;
    el.pageInfo.textContent = `Page ${state.page + 1}`;
}

// Closed and awarded tenders are only shown when that status is picked.
function wantsClosedTenders() {
    return ["closed", "awarded"].includes(el.status.value);
}

function applyQuickFilters(tenders) {
    const hideClosed = !wantsClosedTenders();

    return tenders.filter(tender => {
        if (hideClosed && hasClosingDatePassed(tender.closingDate)) {
            return false;
        }

        if (state.closingSoon) {
            const days = daysUntilClosing(tender.closingDate);

            if (days === null || days < 0 || days > 14) {
                return false;
            }
        }

        if (state.overOneMillion) {
            const budget = parseMoney(tender.budget);

            if (budget === null || budget <= 1000000) {
                return false;
            }
        }

        return true;
    });
}

function renderTenders() {
    const visibleTenders = applyQuickFilters(state.tenders);

    if (!visibleTenders.length) {
        showState("No tenders match these filters. Try changing your search or filters.");
    } else {
        el.grid.innerHTML = visibleTenders.map(createTenderCard).join("");
    }

    el.count.textContent =
        `Showing ${visibleTenders.length} results on this page`;

    updatePagination();
}

async function loadTenders() {
    const requestId = ++state.requestId;

    state.loading = true;
    updatePagination();

    if (!state.tenders.length) {
        showState("Loading tender opportunities...");
    }

    setApiStatus(false, "Connecting to API");

    const params = {
        q: el.search.value.trim(),
        limit: PAGE_SIZE,
        offset: state.page * PAGE_SIZE
    };

    if (el.province.value) {
        params.province = el.province.value;
    }

    if (el.category.value) {
        params.category = el.category.value;
    }

    if (el.organisation.value.trim()) {
        params.organisation = el.organisation.value.trim();
    }

    if (el.status.value) {
        params.status = el.status.value;
    }

    // The Search Tender API hides tenders whose closing date has passed.
    if (wantsClosedTenders()) {
        params.include_closed = true;
    }

    try {
        // The Search Tender API (client API, port 8001) reads the shared
        // SQLite database and returns each tender's database id for saving.
        const payload = await tenderSearchApi.search(params);
        if (requestId !== state.requestId) return;

        state.tenders = getTenderArray(payload).map(normalizeTender);

        const total = Number(payload.total ?? payload.total_count ?? payload.count);

        state.total = Number.isFinite(total) && total >= 0
            ? total
            : state.tenders.length;

        state.hasNextPage = Number.isFinite(Number(payload.total))
            ? (state.page + 1) * PAGE_SIZE < Number(payload.total)
            : state.tenders.length === PAGE_SIZE;

        updateCategories(state.tenders);
        setApiStatus(true, "API connected");
        renderTenders();
    } catch (error) {
        if (requestId !== state.requestId) return;

        console.error("Tender search request failed:", error);

        state.tenders = [];
        state.total = 0;
        state.hasNextPage = false;

        setApiStatus(false, "API unavailable");
        el.count.textContent = "Unable to load tenders";

        showState(
            "Could not load tenders. Check the API address, server availability and CORS settings.",
            true
        );
    } finally {
        if (requestId === state.requestId) {
            state.loading = false;
            updatePagination();
        }
    }
}

let searchTimer;

function resetAndLoad() {
    state.page = 0;
    loadTenders();
}

el.form.addEventListener("submit", event => {
    event.preventDefault();
    clearTimeout(searchTimer);
    resetAndLoad();
});

el.search.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(resetAndLoad, 400);
});

el.province.addEventListener("change", resetAndLoad);
el.category.addEventListener("change", resetAndLoad);
el.status.addEventListener("change", resetAndLoad);

el.organisation.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(resetAndLoad, 400);
});

el.closing.addEventListener("click", () => {
    state.closingSoon = !state.closingSoon;

    el.closing.classList.toggle("active", state.closingSoon);
    el.closing.setAttribute("aria-pressed", String(state.closingSoon));

    renderTenders();
});

el.budget.addEventListener("click", () => {
    state.overOneMillion = !state.overOneMillion;

    el.budget.classList.toggle("active", state.overOneMillion);
    el.budget.setAttribute("aria-pressed", String(state.overOneMillion));

    renderTenders();
});

el.more.addEventListener("click", () => {
    const opening = el.advanced.hidden;

    el.advanced.hidden = !opening;
    el.more.setAttribute("aria-expanded", String(opening));
    el.more.textContent = opening ? "Fewer filters" : "More filters";
});

el.clear.addEventListener("click", () => {
    el.search.value = "";
    el.province.value = "";
    el.category.value = "";
    el.organisation.value = "";
    el.status.value = "";

    state.closingSoon = false;
    state.overOneMillion = false;
    state.page = 0;

    el.closing.classList.remove("active");
    el.budget.classList.remove("active");

    el.closing.setAttribute("aria-pressed", "false");
    el.budget.setAttribute("aria-pressed", "false");

    resetAndLoad();
});

el.previous.addEventListener("click", () => {
    if (state.page > 0 && !state.loading) {
        state.page--;
        loadTenders();
    }
});

el.next.addEventListener("click", () => {
    if (state.hasNextPage && !state.loading) {
        state.page++;
        loadTenders();
    }
});

loadTenders();


// Save tender buttons are handled by save-tender.js.
enableSaveTenderButtons();
