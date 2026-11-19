import { CONFIG } from "./config.js";
import { esc } from "./utils.js";
import { getUsername } from "./shared-utils.js";
import { alertsApi, aiAgentApi } from "./api.js";

import { icon } from "./icons.js";
import { saveTenderButton, enableSaveTenderButtons } from "./save-tender.js";

enableSaveTenderButtons();
const $ = id => document.getElementById(id);

const state = {
    profile: null,
    matches: [],
    notifications: [],
    unread: 0,
    aiAvailable: false
};

const matchesList = $("matchesList");
const notificationsList = $("notificationsList");

function protectPage() {
    const token = localStorage.getItem("access_token");

    if (token) {
        return true;
    }

    window.location.replace(CONFIG.services.loginFrontend);
    return false;
}

function setupUser() {
    const username = getUsername();
    const user = $("currentUser");
    const avatar = $("userAvatar");

    if (user) {
        user.textContent = username;
    }

    if (avatar) {
        avatar.textContent =
            username.trim().charAt(0).toUpperCase() || "U";
    }
}



function showMessage(message, type = "error") {
    const box = $("alertsMessage");

    if (!box) {
        return;
    }

    box.hidden = false;
    box.className = `state-msg ${type}`;
    box.textContent = message;

    window.clearTimeout(showMessage.timeout);

    showMessage.timeout = window.setTimeout(() => {
        box.hidden = true;
        box.textContent = "";
    }, 6000);
}

function listValue(values, emptyText = "Not specified") {
    const cleaned = (Array.isArray(values) ? values : [])
        .map(value => String(value || "").trim())
        .filter(Boolean);

    return cleaned.length
        ? cleaned.map(value => `<span>${esc(value)}</span>`).join("")
        : `<span class="profile-alert-muted">${esc(emptyText)}</span>`;
}

function formatAmount(value) {
    if (value === null || value === undefined || value === "") {
        return "Not specified";
    }

    const number = Number(value);

    if (!Number.isFinite(number)) {
        return String(value);
    }

    return number.toLocaleString(
        undefined,
        {
            minimumFractionDigits: 0,
            maximumFractionDigits: 2
        }
    );
}

function formatDate(value) {
    if (!value) {
        return "—";
    }

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
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

function formatDateTime(value) {
    if (!value) {
        return "—";
    }

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
        return String(value);
    }

    return date.toLocaleString(
        undefined,
        {
            year: "numeric",
            month: "short",
            day: "2-digit",
            hour: "2-digit",
            minute: "2-digit"
        }
    );
}

function renderAiAgentStatus() {
    const status = $("aiAgentStatus");
    if (!status) return;

    status.textContent = state.aiAvailable
        ? "AI Agent connected"
        : "AI Agent unavailable";
    status.className = state.aiAvailable
        ? "profile-alert-status active"
        : "profile-alert-status warning";
}

async function checkAiAgent() {
    try {
        await aiAgentApi.health();
        state.aiAvailable = true;
    } catch (error) {
        state.aiAvailable = false;
        console.warn("AI Agent health check failed:", error);
    }
    renderAiAgentStatus();
}

function renderProfile() {
    const status = $("profileStatus");
    const summary = $("profileSummary");

    if (!summary) {
        return;
    }

    if (!state.profile) {
        if (status) {
            status.textContent = "Profile required";
            status.className = "profile-alert-status warning";
        }

        summary.innerHTML = `
            <div class="alert-empty-state">
                <span class="alert-empty-icon">${icon("building-2")}</span>
                <strong>Add your company profile</strong>
                <span>Smart Alerts uses your company profile to find tenders that fit your business.</span>
                <a class="btn-secondary" href="./profile.html">Open company profile</a>
            </div>
        `;

        return;
    }

    if (status) {
        status.textContent = "Profile active";
        status.className = "profile-alert-status active";
    }

    const profile = state.profile;
    const documentKeywords = [
        ...(profile.document_industries || []),
        ...(profile.document_keywords || [])
    ];

    const budget =
        profile.min_tender_value !== null &&
        profile.max_tender_value !== null
            ? `R ${esc(formatAmount(profile.min_tender_value))} – R ${esc(formatAmount(profile.max_tender_value))}`
            : profile.min_tender_value !== null
                ? `From R ${esc(formatAmount(profile.min_tender_value))}`
                : profile.max_tender_value !== null
                    ? `Up to R ${esc(formatAmount(profile.max_tender_value))}`
                    : "Not specified";

    summary.innerHTML = `
        <div class="profile-alert-business">
            <span class="profile-alert-eyebrow">Business</span>
            <strong>${esc(profile.business_name)}</strong>
            <span>${esc(profile.industry || "Industry not specified")}</span>
        </div>

        <div class="profile-alert-grid">

            <div class="profile-alert-field">
                <span>Provinces</span>
                <div>${listValue(profile.provinces)}</div>
            </div>

            <div class="profile-alert-field">
                <span>Categories</span>
                <div>${listValue(profile.categories)}</div>
            </div>

            <div class="profile-alert-field">
                <span>Keywords</span>
                <div>${listValue(profile.keywords)}</div>
            </div>

            <div class="profile-alert-field">
                <span>From your business documents</span>
                <div>${documentKeywords.length
                    ? listValue(documentKeywords)
                    : `<a class="profile-alert-muted" href="./onboarding.html">Upload business documents to add more matches</a>`}</div>
            </div>

            <div class="profile-alert-field">
                <span>Tender value preference</span>
                <div>
                    <span class="profile-alert-budget">${budget}</span>
                </div>
            </div>

        </div>

        <div class="profile-alert-note">
            Smart Alerts uses your company profile and your business documents. Update either one and your matches update too.
        </div>
    `;
}

function matchCard(match, near = false) {
    return `
            <article class="alert-match-card${near ? " alert-match-near" : ""}">

                <div class="alert-match-top">
                    <div>
                        <span class="tender-number">
                            ${esc(match.tender_number)}
                        </span>
                        <h3>${esc(match.title)}</h3>
                    </div>

                    <span class="alert-score">
                        ${esc(match.score)}% match
                    </span>
                </div>

                <div class="alert-match-meta">
                    ${match.organisation
                        ? `<span><strong>Organisation:</strong> ${esc(match.organisation)}</span>`
                        : ""}
                    ${match.province
                        ? `<span><strong>Province:</strong> ${esc(match.province)}</span>`
                        : ""}
                    ${match.category
                        ? `<span><strong>Category:</strong> ${esc(match.category)}</span>`
                        : ""}
                    ${match.closing_date
                        ? `<span><strong>Closing:</strong> ${esc(formatDate(match.closing_date))}</span>`
                        : ""}
                </div>

                ${match.reasons?.length
                    ? `
                        <div class="alert-match-reasons">
                            ${match.reasons
                                .map(reason => `<span>${icon("check")} ${esc(reason)}</span>`)
                                .join("")}
                        </div>
                    `
                    : ""}

                <div class="alert-match-footer">
                    <span>${esc(match.status || "Open tender")}</span>
                    <div class="notification-actions">
                        ${near ? `<span class="profile-alert-muted">Worth a look</span>` : (() => {
                            const notification = state.notifications.find(item =>
                                Number(item.tender_id) === Number(match.id)
                            );
                            return notification && !notification.read_at
                                ? `<button type="button" class="text-button" data-read-notification="${esc(notification.id)}">Mark as read</button>`
                                : notification
                                    ? `<span class="notification-read-label">Read</span>`
                                    : `<span class="profile-alert-muted">New match</span>`;
                        })()}
                        ${saveTenderButton({
                            id: match.id,
                            number: match.tender_number,
                            closingDate: match.closing_date
                        }, "btn-secondary")}
                        <button
                            type="button"
                            class="btn-secondary"
                            data-open-tender="${esc(match.tender_number)}">
                            Open tender ${icon("arrow-right")}
                        </button>
                    </div>
                </div>

            </article>
    `;
}

function renderMatches() {
    const count = $("matchesCount");
    const strong = state.matches.filter(match => match.level !== "near");
    const near = state.matches.filter(match => match.level === "near").slice(0, 10);

    if (count) {
        count.textContent =
            `${strong.length} ${strong.length === 1 ? "match" : "matches"}`;
    }

    if (!matchesList) {
        return;
    }

    if (!state.profile) {
        matchesList.innerHTML = `
            <div class="alert-empty-state">
                <span class="alert-empty-icon">${icon("building-2")}</span>
                <strong>Company profile required</strong>
                <span>Fill in your company profile so Smart Alerts knows which tenders are relevant.</span>
                <a class="btn-secondary" href="./profile.html">Open company profile</a>
            </div>
        `;
        return;
    }

    const strongHtml = strong.length
        ? strong.map(match => matchCard(match)).join("")
        : `
            <div class="alert-empty-state">
                <span class="alert-empty-icon">${icon("search-x")}</span>
                <strong>No strong matches yet</strong>
                <span>${near.length
                    ? "None of the open tenders match 70% or more. The closest ones are below."
                    : "No open tenders match your company profile right now. Adding tender categories and keywords helps."}</span>
                <a class="btn-secondary" href="./profile.html">Review company profile</a>
            </div>
        `;

    const nearHtml = near.length
        ? `
            <div class="alert-near-heading">
                <h3>Worth a look</h3>
                <span>Partly match your profile (50–69%). These do not create alerts.</span>
            </div>
            ${near.map(match => matchCard(match, true)).join("")}
        `
        : "";

    matchesList.innerHTML = strongHtml + nearHtml;
}

function renderNotifications() {
    const unreadBadge = $("notificationUnreadCount");
    const navBadge = $("navUnreadCount");

    if (unreadBadge) {
        unreadBadge.textContent =
            `${state.unread} ${state.unread === 1 ? "unread" : "unread"}`;
    }

    if (navBadge) {
        navBadge.textContent = String(state.unread);
        navBadge.hidden = state.unread <= 0;
    }

    if (!notificationsList) {
        return;
    }

    if (!state.notifications.length) {
        notificationsList.innerHTML = `
            <div class="alert-empty-state">
                <span class="alert-empty-icon">${icon("check")}</span>
                <strong>No notifications</strong>
                <span>New tenders matching your company profile will appear here automatically.</span>
            </div>
        `;
        return;
    }

    notificationsList.innerHTML = state.notifications
        .map(notification => {
            const unread = !notification.read_at;

            return `
                <article class="notification-card ${unread ? "unread" : ""}">

                    <div class="notification-icon">
                        ${unread ? "!" : icon("check")}
                    </div>

                    <div class="notification-content">

                        <div class="notification-title-row">
                            <div>
                                <span class="tender-number">
                                    ${esc(notification.tender_number)}
                                </span>
                                <h3>${esc(notification.title)}</h3>
                            </div>

                            <span class="alert-score">
                                ${esc(notification.score)}%
                            </span>
                        </div>

                        <p>
                            This tender matched your company profile.
                        </p>

                        ${notification.reasons?.length
                            ? `
                                <div class="notification-reasons">
                                    ${notification.reasons
                                        .map(reason => `<span>${icon("check")} ${esc(reason)}</span>`)
                                        .join("")}
                                </div>
                            `
                            : ""}

                        <div class="notification-footer">
                            <span>${esc(formatDateTime(notification.matched_at))}</span>

                            <div class="notification-actions">

                                ${saveTenderButton({
                                    id: notification.tender_id,
                                    number: notification.tender_number,
                                    closingDate: notification.closing_date
                                }, "btn-secondary")}

                                <button
                                    type="button"
                                    class="btn-secondary"
                                    data-open-tender="${esc(notification.tender_number)}">
                                    Open tender ${icon("arrow-right")}
                                </button>

                                ${unread
                                    ? `
                                        <button
                                            type="button"
                                            class="text-button"
                                            data-read-notification="${esc(notification.id)}">
                                            Mark as read
                                        </button>
                                    `
                                    : "<span class='notification-read-label'>Read</span>"}

                            </div>
                        </div>

                    </div>

                </article>
            `;
        })
        .join("");
}

async function loadProfileAndMatches() {
    try {
        state.profile = await alertsApi.profile();
    } catch (error) {
        state.profile = null;
        state.matches = [];
        renderProfile();
        renderMatches();
        if (error.status !== 404) {
            console.error("Unable to load company profile:", error);
            showMessage("Could not load your company profile. Please try again.", "error");
        }
        return;
    }

    renderProfile();

    if (matchesList && !state.matches.length) {
        matchesList.innerHTML =
            '<div class="state-msg">Loading profile matches...</div>';
    }

    try {
        const matches = await alertsApi.matches();
        state.matches = Array.isArray(matches) ? matches : [];
        renderMatches();
    } catch (error) {
        console.error("Unable to load Smart Alert matches:", error);
        if (matchesList) {
            matchesList.innerHTML = `
                <div class="state-msg error">
                    Could not load matching tenders. Your company profile is saved; try Refresh in a moment.
                </div>
            `;
        }
    }
}

async function loadNotifications() {
    try {
        const [notifications, unread] = await Promise.all([
            alertsApi.notifications(100, false),
            alertsApi.unreadCount()
        ]);

        state.notifications =
            Array.isArray(notifications)
                ? notifications
                : [];

        state.unread =
            Number(unread?.unread || 0);

        renderNotifications();
    } catch (error) {
        console.error("Unable to load notifications:", error);

        if (notificationsList) {
            notificationsList.innerHTML = `
                <div class="state-msg error">
                    Could not load notifications.
                    <br>
                    ${esc(error.message || "Unknown error")}
                </div>
            `;
        }
    }
}

async function markNotificationRead(notificationId) {
    try {
        await alertsApi.markNotificationRead(notificationId);

        const notification =
            state.notifications.find(
                item => Number(item.id) === Number(notificationId)
            );

        if (notification) {
            notification.read_at = new Date().toISOString();
        }

        state.unread = Math.max(0, state.unread - 1);
        renderNotifications();
    } catch (error) {
        console.error(
            "Unable to mark notification as read:",
            error
        );

        showMessage(
            error.message || "Could not mark notification as read.",
            "error"
        );
    }
}

function openTender(tenderNumber) {
    if (!tenderNumber) {
        return;
    }

    localStorage.setItem(
        "last_tender",
        String(tenderNumber)
    );

    window.location.href =
        `./tender.html?number=${encodeURIComponent(
            String(tenderNumber)
        )}`;
}

function setupEvents() {
    $("alertsRefreshBtn")?.addEventListener(
        "click",
        async event => {
            const button = event.currentTarget;

            button.disabled = true;
            button.textContent = "Refreshing...";

            try {
                await Promise.all([
                    loadProfileAndMatches(),
                    loadNotifications()
                ]);
            } finally {
                button.disabled = false;
                button.innerHTML = `${icon("refresh-cw")} Refresh`;
            }
        }
    );

    matchesList?.addEventListener(
        "click",
        async event => {
            const readButton = event.target.closest("[data-read-notification]");
            if (readButton) {
                await markNotificationRead(readButton.dataset.readNotification);
                return;
            }

            const button = event.target.closest("[data-open-tender]");
            if (button) openTender(button.dataset.openTender);
        }
    );

    notificationsList?.addEventListener(
        "click",
        async event => {
            const openButton =
                event.target.closest("[data-open-tender]");

            if (openButton) {
                openTender(openButton.dataset.openTender);
                return;
            }

            const readButton =
                event.target.closest("[data-read-notification]");

            if (readButton) {
                await markNotificationRead(
                    readButton.dataset.readNotification
                );
            }
        }
    );
}

async function start() {
    if (!protectPage()) {
        return;
    }

    setupUser();
    setupEvents();

    await Promise.all([
        checkAiAgent(),
        loadProfileAndMatches(),
        loadNotifications()
    ]);

    window.setInterval(
        loadNotifications,
        30000
    );

    window.setInterval(
        loadProfileAndMatches,
        60000
    );
}

start();
