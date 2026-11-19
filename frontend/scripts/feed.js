import { CONFIG } from "./config.js";
import { esc, closingAfterNow, hasClosingDatePassed } from "./utils.js";
import { getUsername } from "./shared-utils.js";

import { icon } from "./icons.js";
import {
    clientApi,
    cacheApi
} from "./api.js";
import { saveTenderButton, enableSaveTenderButtons } from "./save-tender.js";

enableSaveTenderButtons();


const $ = (id) =>
    document.getElementById(id);


const state = {

    query:
        new URLSearchParams(
            window.location.search
        ).get("q") || "",

    page: 1,

    pageSize: 10,

    total: 0,

    totalKnown: false,

    hasMore: false,

    items: []

};



function protectPage() {

    const token =
        localStorage.getItem(
            "access_token"
        );


    if (!token) {

        window.location.replace(
            CONFIG.services.loginFrontend
        );

        return false;
    }


    return true;
}






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


    return date.toLocaleDateString(
        undefined,
        {
            year: "numeric",
            month: "short",
            day: "2-digit"
        }
    );

}



function getTenderNumber(tender) {

    return (
        tender.tender_number ??
        tender.reference_number ??
        tender.reference ??
        tender.number ??
        tender.id ??
        "—"
    );

}



function getTenderTitle(tender) {

    return (
        tender.title ??
        tender.name ??
        tender.description ??
        "Untitled tender"
    );

}



function getTenderOrganisation(tender) {

    return (
        tender.organisation_name ??
        tender.organization_name ??
        tender.organisation ??
        tender.organization ??
        tender.department ??
        tender.entity_name ??
        ""
    );

}



function getTenderProvince(tender) {

    return (
        tender.province ??
        tender.province_name ??
        ""
    );

}



function getTenderCategory(tender) {

    return (
        tender.category_name ??
        tender.category ??
        tender.category_description ??
        ""
    );

}



function getTenderStatus(tender) {

    return (
        tender.status ??
        tender.tender_status ??
        ""
    );

}



function getPublishedDate(tender) {

    return (
        tender.published_date ??
        tender.published_at ??
        tender.publication_date ??
        tender.created_at ??
        ""
    );

}



function getClosingDate(tender) {

    return (
        tender.closing_date ??
        tender.closing_at ??
        tender.close_date ??
        tender.deadline ??
        ""
    );

}



/*
    Get the number of tenders from
    different API response formats.
*/

function getTotalFromResponse(data) {

    const possibleTotals = [

        data?.total,

        data?.count,

        data?.total_count,

        data?.totalCount,

        data?.pagination?.total,

        data?.meta?.total,

        data?.data?.total,

        data?.data?.pagination?.total,

        data?.data?.meta?.total

    ];

    for (
        const value of possibleTotals
    ) {

        if (
            value !== undefined &&
            value !== null &&
            Number.isFinite(
                Number(value)
            )
        ) {

            return Number(value);
        }

    }

    return null;
}



/*
    Extract tender list from
    different API response formats.
*/

function extractItems(data) {

    if (
        Array.isArray(data)
    ) {

        return data;
    }


    if (
        Array.isArray(
            data?.tenders
        )
    ) {

        return data.tenders;
    }


    if (
        Array.isArray(
            data?.items
        )
    ) {

        return data.items;
    }


    if (
        Array.isArray(
            data?.results
        )
    ) {

        return data.results;
    }


    if (
        Array.isArray(
            data?.data
        )
    ) {

        return data.data;
    }


    if (
        Array.isArray(
            data?.data?.tenders
        )
    ) {

        return data.data.tenders;
    }


    if (
        Array.isArray(
            data?.data?.items
        )
    ) {

        return data.data.items;
    }


    if (
        Array.isArray(
            data?.data?.results
        )
    ) {

        return data.data.results;
    }


    return [];
}



/*
    Load tenders from Cache API first.

    If Cache API fails, use Client API.
*/

async function fetchTenders() {

    const params = {

        limit:
            state.pageSize,

        offset:
            (
                state.page - 1
            ) *
            state.pageSize,

        // Only tenders that are still open for bids.
        closing_after:
            closingAfterNow()

    };


    if (state.query) {

        try {

            return await cacheApi.search(
                state.query,
                params
            );

        } catch (cacheError) {

            console.warn(
                "Cache search failed. Trying Client API.",
                cacheError
            );


            return await clientApi.search(
                state.query,
                params
            );

        }

    }


    try {

        return await cacheApi.tenders(
            params
        );

    } catch (cacheError) {

        console.warn(
            "Cache tender request failed. Trying Client API.",
            cacheError
        );


        return await clientApi.list(
            params
        );

    }

}



/*
    Save the selected tender so
    Tender Details can remember it.
*/

function saveSelectedTender(
    number
) {

    if (
        number &&
        number !== "—"
    ) {

        localStorage.setItem(
            "last_tender",
            String(number)
        );

    }

}



/*
    Open a tender.
*/

function openTender(
    number
) {

    saveSelectedTender(
        number
    );


    window.location.href =
        `./tender.html?number=${
            encodeURIComponent(
                String(number)
            )
        }`;

}



/*
    Make tender status readable.
*/

function getStatusClass(
    status
) {

    const value =
        String(
            status ?? ""
        )
        .toLowerCase()
        .trim();


    if (
        value.includes("open") ||
        value.includes("active") ||
        value.includes("published")
    ) {

        return "open";
    }


    if (
        value.includes("closed") ||
        value.includes("expired") ||
        value.includes("cancel")
    ) {

        return "closed";
    }


    return "";
}



/*
    Render one tender.
*/

function renderTender(tender) {
    const number = getTenderNumber(tender);
    const databaseId = tender.id ?? tender.tender_id ?? "";
    const title = getTenderTitle(tender);
    const organisation = getTenderOrganisation(tender);
    const province = getTenderProvince(tender);
    const category = getTenderCategory(tender);
    const status = getTenderStatus(tender) || "Open";
    const published = getPublishedDate(tender);
    const closing = getClosingDate(tender);
    const budget = tender.estimated_budget ?? tender.budget ?? tender.estimated_value ?? tender.contract_value ?? "";
    const description = tender.description || title || "Review the tender details and submission requirements before applying.";
    const organisationLine = [organisation, category, province].filter(Boolean).map(esc).join(" — ");

    return `
        <article class="feed-tender-card">
            <div class="feed-tender-topline">
                <span class="feed-tender-number">${esc(number)}</span>
                <span class="feed-tender-category">${esc(category || "Tender")}</span>
                <span class="feed-tender-status">${esc(status)}</span>
            </div>

            <h2 class="feed-tender-title">${esc(title)}</h2>
            <p class="feed-tender-organisation">${organisationLine}</p>

            <div class="feed-tender-details">
                <div><span class="feed-detail-label">Closing date</span><span class="feed-detail-value">${esc(formatDate(closing))}</span></div>
                <div><span class="feed-detail-label">Estimated budget</span><span class="feed-detail-value">${esc(budget === "" || budget === null ? "Not published" : budget)}</span></div>
                <div><span class="feed-detail-label">Published</span><span class="feed-detail-value">${esc(formatDate(published))}</span></div>
            </div>

            <p class="feed-tender-description">${esc(description)}</p>

            <div class="feed-tender-footer">
                <span class="feed-tender-footer-label">Tender details</span>
                <div class="tender-card-actions">
                    <button type="button" class="tender-open-btn" data-open-tender="${esc(number)}">Open ${icon("arrow-right")}</button>
                    ${saveTenderButton({ id: databaseId, number, closingDate: closing })}
                </div>
            </div>
        </article>
    `;
}


/*
    Render all tenders.
*/

function render() {

    const box =
        $("feedList");


    if (!box) {
        return;
    }


    if (
        !state.items.length
    ) {

        box.innerHTML = `

            <div
                class="state-msg">

                ${
                    state.query

                        ? `No tenders matched
                           "${esc(state.query)}".`

                        : "No tenders available."
                }

            </div>

        `;

    } else {

        box.innerHTML =
            state.items
                .map(
                    renderTender
                )
                .join("");

    }



    // Save tender buttons are handled by save-tender.js.

    /*
        Add click events to
        Open buttons.
    */



    document
        .querySelectorAll(
            "[data-open-tender]"
        )
        .forEach(
            button => {

                button.addEventListener(
                    "click",
                    () => {

                        const number =
                            button.dataset
                                .openTender;


                        openTender(
                            number
                        );

                    }
                );

            }
        );



    const totalPages =
        state.totalKnown
            ? Math.max(
                1,
                Math.ceil(
                    state.total /
                    state.pageSize
                )
            )
            : null;


    const start =
        state.items.length > 0

            ? (
                (
                    state.page - 1
                ) *
                state.pageSize
            ) + 1

            : 0;


    const end =
        state.totalKnown
            ? Math.min(
                state.page *
                state.pageSize,
                state.total
            )
            : (
                state.items.length > 0
                    ? (
                        (
                            state.page - 1
                        ) *
                        state.pageSize
                    ) + state.items.length
                    : 0
            );


    const feedCount =
        $("feedCount");


    if (feedCount) {

        feedCount.textContent =
            state.totalKnown

                ? (
                    state.total > 0
                        ? `Showing ${start}–${end}
                           of ${state.total.toLocaleString()}`
                        : "0 tenders"
                )

                : (
                    state.items.length > 0
                        ? `Showing ${start}–${end}`
                        : "0 tenders"
                );

    }


    const queryLabel =
        $("feedQueryLabel");


    if (queryLabel) {

        queryLabel.textContent =
            state.query

                ? `· filtered by "${state.query}"`

                : "";

    }


    const pageInfo =
        $("pageInfo");


    if (pageInfo) {

        pageInfo.textContent =
            state.totalKnown
                ? `Page ${state.page}
                   of ${totalPages}`
                : `Page ${state.page}`;

    }


    const prev =
        $("prevBtn");


    if (prev) {

        prev.disabled =
            state.page <= 1;

    }


    const next =
        $("nextBtn");


    if (next) {

        next.disabled =
            state.totalKnown
                ? state.page >= totalPages
                : !state.hasMore;

    }

}



/*
    Show loading message.
*/

function showLoading() {

    const box =
        $("feedList");


    if (!box) {
        return;
    }


    box.innerHTML = `

        <div
            class="state-msg">

            Loading tenders...

        </div>

    `;

}



/*
    Load data.
*/

async function load() {

    showLoading();


    try {

        const data =
            await fetchTenders();


        // Drop any closed tender an API returns despite closing_after.
        const items =
            extractItems(
                data
            ).filter(
                tender =>
                    !hasClosingDatePassed(
                        getClosingDate(tender)
                    )
            );


        state.items =
            items;


        const total =
            getTotalFromResponse(
                data
            );


        state.totalKnown =
            total !== null;


        state.total =
            state.totalKnown
                ? total
                : (
                    (
                        state.page - 1
                    ) *
                    state.pageSize +
                    items.length
                );


        state.hasMore =
            state.totalKnown
                ? (
                    state.page *
                    state.pageSize
                ) < state.total
                : items.length >= state.pageSize;


        render();


    } catch (error) {

        console.error(
            "Unable to load tenders:",
            error
        );


        state.items = [];

        state.total = 0;

        state.totalKnown = false;

        state.hasMore = false;


        const box =
            $("feedList");


        if (box) {

            box.innerHTML = `

                <div
                    class="state-msg error">

                    <strong>
                        Could not load tenders.
                    </strong>

                    <br>

                    ${esc(
                        error.message ||
                        "Unknown error"
                    )}

                </div>

            `;

        }


        render();

    }

}



/*
    Search.
*/

function performSearch() {

    const input =
        $("feedSearchInput");


    state.query =
        input
            ? input.value.trim()
            : "";


    state.page = 1;


    const url =
        new URL(
            window.location.href
        );


    if (state.query) {

        url.searchParams.set(
            "q",
            state.query
        );

    } else {

        url.searchParams.delete(
            "q"
        );

    }


    window.history.replaceState(
        {},
        "",
        url
    );


    load();

}



/*
    Clear search.
*/

function clearSearch() {

    state.query = "";

    state.page = 1;


    const input =
        $("feedSearchInput");


    if (input) {

        input.value = "";

    }


    const url =
        new URL(
            window.location.href
        );


    url.searchParams.delete(
        "q"
    );


    window.history.replaceState(
        {},
        "",
        url
    );


    load();

}



/*
    Logout.
*/





/*
    Set username.
*/

function setupUser() {

    const username =
        getUsername();


    const user =
        $("currentUser");


    const avatar =
        $("userAvatar");


    if (user) {

        user.textContent =
            username;

    }


    if (avatar) {

        avatar.textContent =
            username
                .trim()
                .charAt(0)
                .toUpperCase() || "U";

    }

}



/*
    Search input.
*/

function setupSearch() {

    const input =
        $("feedSearchInput");


    if (!input) {
        return;
    }


    input.value =
        state.query;


    const button =
        $("searchButton");


    if (button) {

        button.addEventListener(
            "click",
            performSearch
        );

    }


    let timeout;


    input.addEventListener(
        "input",
        () => {

            clearTimeout(
                timeout
            );


            timeout =
                setTimeout(
                    () => {

                        performSearch();

                    },
                    400
                );

        }
    );


    input.addEventListener(
        "keydown",
        event => {

            if (
                event.key === "Enter"
            ) {

                clearTimeout(
                    timeout
                );


                performSearch();

            }

        }
    );

}



/*
    Page size.
*/

function setupPageSize() {

    const select =
        $("feedPageSize");


    if (!select) {
        return;
    }


    select.value =
        String(
            state.pageSize
        );


    select.addEventListener(
        "change",
        event => {

            state.pageSize =
                Number(
                    event.target.value
                );


            state.page = 1;


            load();

        }
    );

}



/*
    Pagination.
*/

function setupPagination() {

    const previous =
        $("prevBtn");


    const next =
        $("nextBtn");


    if (previous) {

        previous.addEventListener(
            "click",
            () => {

                if (
                    state.page <= 1
                ) {

                    return;
                }


                state.page--;


                load();

            }
        );

    }


    if (next) {

        next.addEventListener(
            "click",
            () => {

                const totalPages =
                    Math.max(
                        1,
                        Math.ceil(
                            state.total /
                            state.pageSize
                        )
                    );


                if (
                    state.page >=
                    totalPages
                ) {

                    return;
                }


                state.page++;


                load();

            }
        );

    }

}



/*
    Refresh.
*/

function setupRefresh() {

    const button =
        $("feedRefreshBtn");


    if (!button) {
        return;
    }


    button.addEventListener(
        "click",
        async () => {

            button.disabled =
                true;


            button.textContent =
                "Refreshing...";


            try {

                await load();

            } finally {

                button.disabled =
                    false;

                button.innerHTML =
                    `${icon("refresh-cw")} Refresh`;

            }

        }
    );

}



/*
    Clear button.
*/

function setupClearButton() {

    const button =
        $("clearSearch");


    if (!button) {
        return;
    }


    button.addEventListener(
        "click",
        clearSearch
    );

}



/*
    Start.
*/

function start() {

    if (
        !protectPage()
    ) {

        return;
    }


    setupUser();


    setupSearch();

    setupPageSize();

    setupPagination();

    setupRefresh();

    setupClearButton();


    load();

}


start();