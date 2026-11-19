import { esc, closingAfterNow, hasClosingDatePassed } from "./utils.js";
import { saveTenderButton, enableSaveTenderButtons } from "./save-tender.js";

enableSaveTenderButtons();

import { icon } from "./icons.js";
import { pickMatches } from "./match-summary.js";
import {
    clientApi,
    cacheApi,
    scraperApi,
    businessProfileApi,
    alertsApi,
    onboardingApi,
    overviewApi
} from "./api.js";

import {
    renderChart,
    renderChartError
} from "./chart.js";

import {
    state
} from "./state.js";


const $ =
    id =>
        document.getElementById(id);


const fmt =
    value => {

        const number =
            Number(value);

        return Number.isFinite(number)
            ? number.toLocaleString()
            : (value ?? "—");
    };



const firstValue =
    (
        object,
        keys,
        fallback = null
    ) => {

        for (const key of keys) {

            if (
                object?.[key] !== undefined &&
                object?.[key] !== null
            ) {

                return object[key];

            }

        }

        return fallback;
    };



async function tryFetch(
    ...functions
) {

    let lastError;


    for (const fn of functions) {

        try {

            return await fn();

        } catch (error) {

            lastError = error;

        }

    }


    if (lastError) {
        throw lastError;
    }


    return null;
}



/* KPIs */

async function loadKpis() {

    const stats =
        await tryFetch(
            () => overviewApi.stats(),
            () => cacheApi.stats(),
            () => clientApi.stats()
        );


    state.stats =
        stats;


    if (!stats) {
        return;
    }


    $("kpiTotalTenders").textContent =
        fmt(
            firstValue(
                stats,
                [
                    "total_tenders",
                    "totalTenders",
                    "total"
                ],
                0
            )
        );


    $("kpiOpenTenders").textContent =
        fmt(
            firstValue(
                stats,
                [
                    "open_tenders",
                    "openTenders",
                    "open"
                ],
                0
            )
        );


    $("kpiClosingWeek").textContent =
        fmt(
            firstValue(
                stats,
                [
                    "closing_this_week",
                    "closingThisWeek",
                    "closing_week"
                ],
                0
            )
        );


    $("kpiClosingMonth").textContent =
        fmt(
            firstValue(
                stats,
                [
                    "closing_this_month",
                    "closingThisMonth",
                    "closing_month"
                ],
                0
            )
        );
}



/* CHART */

// Tenders published per day, counted by the Overview API across all
// tenders (not a sample), grouped into a few points for the chart.
async function loadVolume() {

    try {

        const days = state.range;

        const data = await overviewApi.volume(days);

        const daily = Array.isArray(data?.daily) ? data.daily : [];

        if (!daily.length) {
            renderChartError();
            return;
        }

        // 7D: one point per day. 30D: every 5 days. 90D: every 10 days.
        const size = days <= 7 ? 1 : days <= 30 ? 5 : 10;

        const dayOf = value => new Date(`${value}T12:00:00`);
        const dayMonth = date => date.toLocaleDateString("en-ZA", { day: "numeric", month: "short" });

        const values = [];
        const labels = [];
        const details = [];

        for (let i = 0; i < daily.length; i += size) {
            const group = daily.slice(i, i + size);
            values.push(group.reduce((sum, item) => sum + (Number(item.count) || 0), 0));

            const first = dayOf(group[0].date);
            const last = dayOf(group[group.length - 1].date);

            if (size === 1) {
                labels.push(first.toLocaleDateString("en-ZA", { weekday: "short" }));
                details.push(first.toLocaleDateString("en-ZA", { weekday: "short", day: "numeric", month: "short" }));
            } else {
                labels.push(dayMonth(first));
                // "11–15 Oct", or "29 Oct – 2 Nov" across two months.
                details.push(
                    group.length === 1
                        ? dayMonth(first)
                        : first.getMonth() === last.getMonth()
                            ? `${first.getDate()}–${dayMonth(last)}`
                            : `${dayMonth(first)} – ${dayMonth(last)}`
                );
            }
        }

        const total = Number(data.total) || 0;
        const previous = Number(data.previous_total) || 0;

        // Compare with the same number of days before this period. Changes
        // under 2% either way are shown as flat, in grey.
        let change;
        let trend;
        if (previous > 0) {
            const percent = ((total - previous) / previous) * 100;
            change = `${percent >= 0 ? "+" : ""}${percent.toFixed(1)}%`;
            trend = Math.abs(percent) < 2 ? "flat" : percent > 0 ? "up" : "down";
        } else {
            change = total > 0 ? "New" : "0%";
            trend = "flat";
        }

        renderChart({
            total: `${total.toLocaleString()} tender${total === 1 ? "" : "s"}`,
            change,
            trend,
            compare: `vs previous ${days} days`,
            compareTitle: `${previous.toLocaleString()} tender${previous === 1 ? " was" : "s were"} published in the ${days} days before`,
            values,
            labels,
            details
        });

    } catch (error) {

        console.error("Unable to load tender volume:", error);
        renderChartError();

    }
}



/* PROVINCES */

async function loadProvinces() {

    const box =
        $("provinceList");


    const stats =
        state.stats ||
        await tryFetch(
            () => overviewApi.stats(),
            () => cacheApi.stats(),
            () => clientApi.stats()
        );


    const values =
        stats?.by_province ??
        stats?.byProvince ??
        stats?.provinces;


    if (
        !Array.isArray(values) ||
        !values.length
    ) {

        box.innerHTML =
            `<p class="state-msg">
                Province data unavailable.
            </p>`;

        return;
    }


    const sorted =
        [...values]
            .sort(
                (a, b) =>
                    Number(
                        b.count ??
                        b.value ??
                        0
                    ) -
                    Number(
                        a.count ??
                        a.value ??
                        0
                    )
            )
            .slice(0, 6);


    const max =
        Math.max(
            ...sorted.map(
                item =>
                    Number(
                        item.count ??
                        item.value ??
                        0
                    )
            ),
            1
        );


    box.innerHTML =
        sorted
            .map(
                item => {

                    const name =
                        item.province ??
                        item.name ??
                        "Unknown";


                    const count =
                        Number(
                            item.count ??
                            item.value ??
                            0
                        );


                    const width =
                        Math.max(
                            3,
                            Math.round(
                                (
                                    count /
                                    max
                                ) * 100
                            )
                        );


                    return `
                        <div class="province-label-group">

                            <div class="province-stats">

                                <span>
                                    ${esc(name)}
                                </span>

                                <strong>
                                    ${fmt(count)}
                                </strong>

                            </div>

                            <div class="progress-track">

                                <div
                                    class="progress-fill"
                                    style="width:${width}%">
                                </div>

                            </div>

                        </div>
                    `;

                }
            )
            .join("");
}



/* CATEGORIES */

async function loadCategories() {

    const box =
        $("categoryList");


    const stats =
        state.stats ||
        await tryFetch(
            () => overviewApi.stats(),
            () => cacheApi.stats(),
            () => clientApi.stats()
        );


    const values =
        stats?.by_category ??
        stats?.byCategory ??
        stats?.categories;


    if (
        !Array.isArray(values) ||
        !values.length
    ) {

        box.innerHTML =
            `<p class="state-msg">
                Category data unavailable.
            </p>`;

        return;
    }


    box.innerHTML =
        [...values]

            .sort(
                (a, b) =>
                    Number(
                        b.count ??
                        b.value ??
                        0
                    ) -
                    Number(
                        a.count ??
                        a.value ??
                        0
                    )
            )

            .slice(0, 7)

            .map(
                item => `

                    <div class="category-item">

                        <span>
                            ${esc(
                                item.category ??
                                item.name ??
                                "Unknown"
                            )}
                        </span>

                        <span class="category-count">

                            ${fmt(
                                item.count ??
                                item.value ??
                                0
                            )}

                        </span>

                    </div>

                `
            )
            .join("");
}



/* SCRAPE */

function formatDate(value) {

    if (!value) {
        return "—";
    }


    const date =
        new Date(value);


    if (
        Number.isNaN(
            date.getTime()
        )
    ) {

        return String(value);

    }


    return date.toLocaleString(
        undefined,
        {
            month: "short",
            day: "2-digit",
            hour: "2-digit",
            minute: "2-digit"
        }
    );
}



async function loadScrapeStatus() {

    const stats =
        state.stats ||
        await tryFetch(
            () => overviewApi.stats(),
            () => cacheApi.stats(),
            () => clientApi.stats()
        );


    let last =
        stats?.last_scrape ??
        stats?.lastScrape;


    if (!last) {

        try {

            const logs =
                await scraperApi.logs({
                    limit: 1
                });


            last =
                Array.isArray(logs)
                    ? logs[0]
                    : logs?.items?.[0] ??
                      logs?.results?.[0] ??
                      logs?.logs?.[0];

        } catch {}

    }


    const badge =
        $("scrapeStatus");


    const text =
        $("scrapeStatusText");


    if (!last) {

        badge.className =
            "status-badge idle";

        text.textContent =
            "No data";

        return;
    }


    const status =
        String(
            last.status ??
            "unknown"
        ).toLowerCase();


    badge.className =
        "status-badge";


    if (
        [
            "success",
            "completed",
            "complete",
            "running",
            "ok"
        ].includes(status)
    ) {

        badge.classList.add(
            "success"
        );

    } else if (
        [
            "failed",
            "error"
        ].includes(status)
    ) {

        badge.classList.add(
            "error"
        );

    } else {

        badge.classList.add(
            "idle"
        );

    }


    text.textContent =
        status.charAt(0).toUpperCase() +
        status.slice(1);


    $("scrapeStarted").textContent =
        formatDate(
            last.started_at ??
            last.startedAt ??
            last.start_time
        );


    $("scrapeCompleted").textContent =
        status === "running"
            ? "In Progress"
            : formatDate(
                last.completed_at ??
                last.completedAt ??
                last.end_time
            );


    $("scrapeFound").textContent =
        fmt(
            last.tenders_found ??
            last.found ??
            last.items_found
        );


    $("scrapeAdded").textContent =
        fmt(
            last.tenders_added ??
            last.added ??
            last.items_added
        );
}




/* RECENT TENDERS */

async function loadRecentTenders() {

    const box =
        $("recentTenderList");

    if (!box) {
        return;
    }

    try {

        const data =
            await tryFetch(
                () =>
                    clientApi.list({
                        limit: 5,
                        offset: 0,
                        closing_after: closingAfterNow()
                    }),

                () =>
                    cacheApi.tenders({
                        limit: 5,
                        offset: 0,
                        closing_after: closingAfterNow()
                    })
            );

        // Only tenders that are still open for bids.
        const items =
            (
                Array.isArray(data)
                    ? data
                    : data?.tenders ??
                      data?.items ??
                      data?.results ??
                      []
            ).filter(
                item =>
                    !hasClosingDatePassed(
                        item.closing_date ?? item.closing_at ?? item.deadline
                    )
            );

        if (!items.length) {
            box.innerHTML =
                `<p class="state-msg">
                    No recent tenders available.
                </p>`;

            return;
        }

        box.innerHTML =
            items
                .map(item => {

                    const number =
                        firstValue(
                            item,
                            [
                                "tender_number",
                                "reference_number",
                                "reference",
                                "number",
                                "id"
                            ],
                            "—"
                        );

                    const title =
                        firstValue(
                            item,
                            [
                                "title",
                                "name",
                                "description"
                            ],
                            "Untitled tender"
                        );

                    const organisation =
                        firstValue(
                            item,
                            [
                                "organisation_name",
                                "organization_name",
                                "organisation",
                                "organization",
                                "department",
                                "entity_name"
                            ],
                            "—"
                        );

                    const status =
                        firstValue(
                            item,
                            [
                                "status",
                                "tender_status"
                            ],
                            ""
                        );

                    const statusText =
                        String(status || "Unknown");

                    const statusClass =
                        statusText
                            .toLowerCase()
                            .includes("open")
                            ? "open"
                            : statusText
                                .toLowerCase()
                                .includes("closed")
                                ? "closed"
                                : "";

                    return `
                        <article class="recent-tender">

                            <div class="recent-tender-main">

                                <span class="recent-tender-number">
                                    ${esc(number)}
                                </span>

                                <h3 class="recent-tender-title">
                                    ${esc(title)}
                                </h3>

                                <p class="recent-tender-org">
                                    ${esc(organisation)}
                                </p>

                            </div>

                            <div class="recent-tender-side">

                                <span class="tender-status ${statusClass}">
                                    ${esc(statusText)}
                                </span>

                                ${saveTenderButton({
                                    id: item.id ?? item.tender_id,
                                    number: item.tender_number ?? item.reference_number ?? item.reference,
                                    closingDate: item.closing_date ?? item.closing_at ?? item.deadline
                                }, "recent-open-btn", "Save")}

                                <button
                                    type="button"
                                    class="recent-open-btn"
                                    data-recent-tender="${esc(number)}">

                                    Open ${icon("arrow-right")}

                                </button>

                            </div>

                        </article>
                    `;

                })
                .join("");

        const topMatches = $("topMatchCards");
        if (topMatches) {
            let profile = null;
            try {
                profile = await businessProfileApi.get();
            } catch {}

            const hasProfile = Boolean(
                profile && (
                    profile.business_name ||
                    profile.company_name ||
                    profile.name ||
                    profile.industry ||
                    profile.services
                )
            );

            // Profiles created during onboarding live in the tender AI agent. Smart Alerts matches
            // them on their uploaded documents; the agent's own matches are the fallback.
            let agentMatches = [];
            if (!hasProfile) {
                let smartAlerts = null;
                let agentOverview = null;
                try { smartAlerts = await alertsApi.matches(); } catch {}
                if (!Array.isArray(smartAlerts)) {
                    try { agentOverview = await onboardingApi.overview(); } catch {}
                }
                agentMatches = pickMatches(smartAlerts, agentOverview).matches;
            }

            if (!hasProfile && agentMatches.length) {
                topMatches.innerHTML = agentMatches.slice(0, 3).map(match => {
                    const number = match.tender_number || "Tender";
                    const closing = match.closing_date ? `Closes ${formatDate(match.closing_date)}` : "Closing date not supplied";
                    // The agent's ids belong to its own store, so save by tender number.
                    const trackButton =
                        saveTenderButton({ number: match.tender_number, closingDate: match.closing_date }, "") ||
                        `<button type="button" data-recent-tender="${esc(number)}">Track this bid</button>`;
                    return `<article class="db-match-card"><div><span class="db-bid-tag">Bid</span><span class="db-fit-tag">${esc(`${Number(match.score) || 0}% match`)}</span></div><h3>${esc(match.title || "Untitled tender")}</h3><p>${esc(match.organisation || "Organisation not listed")}</p><small>${esc(closing)}</small>${trackButton}<a href="./tender.html?number=${encodeURIComponent(number)}">Details</a></article>`;
                }).join("");
            } else if (!hasProfile) {
                topMatches.innerHTML = `<div class="db-no-profile"><strong>Complete your business profile to unlock top matches</strong><span>Tell us about your business so we can find tenders that fit.</span><a href="./onboarding.html">Complete profile ${icon("arrow-right")}</a></div>`;
            } else {
                const matches = await alertsApi.matches();
                const actualMatches = Array.isArray(matches) ? matches : [];
                if (!actualMatches.length) {
                    topMatches.innerHTML = `<div class="db-no-profile"><strong>No current profile matches</strong><span>No active tenders currently match your business profile.</span><a href="./profile.html">Review profile ${icon("arrow-right")}</a></div>`;
                } else {
                    topMatches.innerHTML = actualMatches.slice(0, 3).map(match => {
                        const number = match.tender_number || match.reference_number || match.id || "Tender";
                        const title = match.title || "Untitled tender";
                        const organisation = match.organisation || match.organization || "Organisation not listed";
                        const score = Number.isFinite(Number(match.score)) ? `${Number(match.score)}% match` : "Profile match";
                        const closing = match.closing_date ? `Closes ${formatDate(match.closing_date)}` : "Closing date not supplied";
                        // Save and track in one click; open the details if the match has no database id.
                        const trackButton =
                            saveTenderButton({ id: match.id, number: match.tender_number ?? match.reference_number, closingDate: match.closing_date }, "") ||
                            `<button type="button" data-recent-tender="${esc(number)}">Track this bid</button>`;
                        return `<article class="db-match-card"><div><span class="db-bid-tag">Bid</span><span class="db-fit-tag">${esc(score)}</span></div><h3>${esc(title)}</h3><p>${esc(organisation)}</p><small>${esc(closing)}</small>${trackButton}<a href="./tender.html?number=${encodeURIComponent(number)}">Details</a></article>`;
                    }).join("");
                }
            }
        }

        document
            .querySelectorAll(
                "[data-recent-tender]"
            )
            .forEach(button => {

                button.addEventListener(
                    "click",
                    () => {

                        const number =
                            button.dataset
                                .recentTender;

                        if (!number || number === "—") {
                            return;
                        }

                        localStorage.setItem(
                            "last_tender",
                            number
                        );

                        window.location.assign(
                            "./tender.html?number=" +
                            encodeURIComponent(number)
                        );

                    }
                );

            });

    } catch (error) {

        console.error(
            "Unable to load recent tenders:",
            error
        );

        box.innerHTML =
            `<p class="state-msg error">
                Unable to load recent tenders.
            </p>`;

    }
}


export async function refreshOverview() {

    await Promise.allSettled([

        loadKpis(),

        loadVolume(),

        loadProvinces(),

        loadCategories(),

        loadRecentTenders(),

        loadScrapeStatus()

    ]);

}



document
    .querySelectorAll(".range-btn")
    .forEach(
        button => {

            button.addEventListener(
                "click",
                () => {

                    document
                        .querySelectorAll(
                            ".range-btn"
                        )
                        .forEach(
                            item =>
                                item.classList.remove(
                                    "active"
                                )
                        );

                    button.classList.add(
                        "active"
                    );

                    state.range =
                        Number(
                            button.dataset.range
                        );

                    loadVolume();
                }
            );

        }
    );
