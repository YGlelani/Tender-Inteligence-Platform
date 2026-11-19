import { CONFIG } from "./config.js";
import { escapeHtml } from "./utils.js";
import { applicationTrackerApi, savedTendersApi } from "./api.js";

const $ = id => document.getElementById(id);
const list = $("trackerApplications");
const notice = $("trackerNotice");
const form = $("trackerCreateForm");
const createButton = $("trackerCreateButton");
const statusFilter = $("trackerStatusFilter");
const searchInput = $("trackerSearch");
const statusOptions = ["Interested", "Preparing", "Submitted", "Won", "Lost"];
let applications = [];
let stats = {};
let pendingDeleteId = null;
let deleteTrigger = null;

function formatDate(value) {
    if (!value) return "Not set";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat("en-ZA", { day: "2-digit", month: "short", year: "numeric" }).format(date);
}

function showNotice(message, isError = false) {
    notice.textContent = message;
    notice.classList.toggle("error", isError);
    notice.hidden = !message;
}

function requireLogin() {
    if (localStorage.getItem("access_token")) return true;
    window.location.replace(CONFIG.services.loginFrontend);
    return false;
}

function updateStats(data) {
    stats = data?.counts || {};
    $("statTotal").textContent = String(data?.total ?? applications.length);
    $("statPreparing").textContent = String(stats.Preparing ?? 0);
    $("statSubmitted").textContent = String(stats.Submitted ?? 0);
    $("statWon").textContent = String(stats.Won ?? 0);
}

function visibleApplications() {
    const status = statusFilter.value;
    const term = searchInput.value.trim().toLowerCase();
    return applications.filter(item => {
        const statusMatches = !status || item.status === status;
        const text = [item.tender_title, item.tender_reference, item.notes].join(" ").toLowerCase();
        return statusMatches && (!term || text.includes(term));
    });
}

function renderApplication(item) {
    const deadline = item.application_deadline;
    const overdue = Boolean(item.is_overdue);
    const statusSelect = statusOptions.map(status =>
        `<option value="${status}" ${item.status === status ? "selected" : ""}>${status}</option>`
    ).join("");
    return `
        <article class="tracker-application-card" data-application-id="${escapeHtml(item.id)}">
            <div class="tracker-card-top">
                <div><h3>${escapeHtml(item.tender_title || "Tender application")}</h3><span class="tracker-reference">Reference: ${escapeHtml(item.tender_reference || item.tender_id || "Not available")}</span></div>
                <span class="tracker-status-pill" data-status="${escapeHtml(item.status)}">${escapeHtml(item.status)}</span>
            </div>
            <div class="tracker-card-meta">
                <div class="${overdue ? "overdue" : ""}">Application deadline<strong>${escapeHtml(formatDate(deadline))}${overdue ? " · Overdue" : ""}</strong></div>
                <div>Added<strong>${escapeHtml(formatDate(item.created_at))}</strong></div>
                <div>Submitted<strong>${escapeHtml(formatDate(item.submission_date))}</strong></div>
            </div>
            <div class="tracker-card-controls">
                <label>Status<select data-field="status">${statusSelect}</select></label>
                <label class="full-width">Notes<textarea data-field="notes" rows="2" maxlength="10000" placeholder="Add notes or next steps…">${escapeHtml(item.notes || "")}</textarea></label>
            </div>
            <div class="tracker-card-actions"><button class="tracker-save-button" type="button" data-action="save">Save changes</button><button class="tracker-delete-button" type="button" data-action="delete">Remove</button></div>
        </article>`;
}

function renderList() {
    const filtered = visibleApplications();
    $("trackerListDescription").textContent = `${filtered.length} of ${applications.length} application${applications.length === 1 ? "" : "s"} shown`;
    if (!filtered.length) {
        list.innerHTML = `<div class="tracker-empty"><strong>${applications.length ? "No matching applications" : "Your tracker is empty"}</strong>${applications.length ? "Try a different status or search term." : "Save a tender from Tender Feed or Search Tender to start tracking your application progress."}</div>`;
        return;
    }
    list.innerHTML = filtered.map(renderApplication).join("");
}

async function loadSavedTenders() {
    const savedPayload = await savedTendersApi.list();
    return Array.isArray(savedPayload) ? savedPayload
        : Array.isArray(savedPayload?.saved_tenders) ? savedPayload.saved_tenders
        : Array.isArray(savedPayload?.items) ? savedPayload.items
        : Array.isArray(savedPayload?.data) ? savedPayload.data : [];
}

// Every tracked tender is also a saved tender: save any that are missing,
// for example ones added here by tender number.
async function syncTrackerIntoSavedTenders(existingApplications, saved) {
    const savedIds = new Set(saved.map(item => String(item.tender_id ?? item.id ?? "")).filter(Boolean));
    let added = 0;
    for (const application of existingApplications) {
        const tenderId = Number(application.tender_id);
        if (!Number.isInteger(tenderId) || tenderId <= 0 || savedIds.has(String(tenderId))) continue;
        try {
            await savedTendersApi.save({ tender_id: tenderId });
            savedIds.add(String(tenderId));
            added++;
        } catch (error) {
            console.error("Could not save tracked tender:", application.tender_reference, error);
        }
    }
    return added;
}

// Every saved tender is also tracked: add any that are missing.
async function syncSavedTendersIntoTracker(existingApplications, saved) {
    const known = new Set(existingApplications.map(item =>
        String(item.tender_reference ?? item.tender_number ?? item.tender_id ?? "").trim().toLowerCase()
    ).filter(Boolean));
    let added = 0;
    for (const item of saved) {
        const id = item.tender_id ?? item.id;
        const reference = String(item.tender_number ?? item.reference_number ?? item.reference ?? id ?? "").trim();
        if (!reference) continue;
        const keys = [reference, String(id ?? "")].map(v => v.trim().toLowerCase()).filter(Boolean);
        if (keys.some(key => known.has(key))) continue;
        const rawDeadline = item.closing_date ?? item.closing_at ?? item.deadline;
        const parsed = rawDeadline ? new Date(rawDeadline) : null;
        const validDeadline = parsed && !Number.isNaN(parsed.getTime());
        try {
            const payload = {
                tender_number: reference
            };
            if (validDeadline) payload.application_deadline = parsed.toISOString().slice(0, 10);
            await applicationTrackerApi.create(payload);
            keys.forEach(key => known.add(key));
            added++;
        } catch (error) {
            // Continue so one malformed saved record does not block the rest.
            console.error("Could not sync saved tender into tracker:", reference, error);
        }
    }
    return added;
}

// "Track this bid" links here as application-tracker.html?tender=<tender number>.
// Show that tender: clear filters that would hide it, scroll to it and highlight it.
let requestedTender = new URLSearchParams(window.location.search).get("tender");

function showRequestedTender() {
    if (!requestedTender) return;
    const wanted = requestedTender.trim().toLowerCase();
    requestedTender = null;

    const application = applications.find(item =>
        String(item.tender_reference ?? item.tender_number ?? "").trim().toLowerCase() === wanted
    );
    if (!application) {
        showNotice("That tender is not in your Application Tracker yet. Try Refresh in a moment.", true);
        return;
    }

    if (statusFilter.value || searchInput.value) {
        statusFilter.value = "";
        searchInput.value = "";
        renderList();
    }

    const card = list.querySelector(`[data-application-id="${CSS.escape(String(application.id))}"]`);
    if (!card) return;
    card.classList.add("is-highlighted");
    card.setAttribute("tabindex", "-1");
    card.scrollIntoView({ behavior: "smooth", block: "center" });
    card.focus({ preventScroll: true });
    setTimeout(() => card.classList.remove("is-highlighted"), 4000);
}

async function loadTracker() {
    if (!requireLogin()) return;
    list.innerHTML = '<div class="tracker-empty">Loading your applications…</div>';
    showNotice("");
    try {
        let listResult = await applicationTrackerApi.list({ limit: 100, sort_by: "deadline", sort_order: "asc" });
        let initialApplications = Array.isArray(listResult?.applications) ? listResult.applications : [];
        let synced = 0;
        try {
            const saved = await loadSavedTenders();
            synced = await syncSavedTendersIntoTracker(initialApplications, saved);
            await syncTrackerIntoSavedTenders(initialApplications, saved);
        } catch (syncError) {
            // The tracker still works when the Saved Tenders API is down.
            console.error("Could not sync with Saved Tenders:", syncError);
        }
        if (synced) {
            showNotice(`Added ${synced} saved tender${synced === 1 ? "" : "s"} to your Application Tracker.`);
            listResult = await applicationTrackerApi.list({ limit: 100, sort_by: "deadline", sort_order: "asc" });
        }
        const statsResult = await applicationTrackerApi.stats();
        applications = Array.isArray(listResult?.applications) ? listResult.applications : [];
        updateStats(statsResult);
        renderList();
        showRequestedTender();
    } catch (error) {
        console.error("Unable to load tracker:", error);
        list.innerHTML = '<div class="tracker-empty"><strong>Could not load your applications</strong>Check that the Application Tracker API is reachable and your login session is valid. Then try Refresh.</div>';
        showNotice(error.message || "Could not connect to the Application Tracker API.", true);
    }
}

if (form) form.addEventListener("submit", async event => {
    event.preventDefault();
    if (!requireLogin()) return;
    const tenderNumber = $("newTenderNumber").value.trim();
    if (!tenderNumber) {
        showNotice("Enter the tender number shown on the notice.", true);
        return;
    }
    createButton.disabled = true;
    showNotice("");
    try {
        const created = await applicationTrackerApi.create({
            tender_number: tenderNumber,
            notes: $("newNotes").value.trim() || null
        });
        // A tracked tender is also saved, so it shows in Saved Tenders.
        let savedToo = true;
        const tenderId = Number(created?.tender_id);
        if (Number.isInteger(tenderId) && tenderId > 0) {
            try {
                await savedTendersApi.save({ tender_id: tenderId });
            } catch (savedError) {
                savedToo = false;
                console.error("Tender tracked, but it could not be saved:", savedError);
            }
        }
        form.reset();
        await loadTracker();
        showNotice(savedToo
            ? "Tender added to your Application Tracker and Saved Tenders."
            : "Tender added to your Application Tracker, but it could not be added to Saved Tenders.", !savedToo);
    } catch (error) {
        console.error("Unable to create tracker entry:", error);
        showNotice(error.message.includes("409") ? "This tender is already in your tracker." : error.message.includes("404") ? "Tender number not found. Check the number and try again." : error.message || "Could not add this tender.", true);
    } finally {
        createButton.disabled = false;
    }
});

list.addEventListener("click", async event => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    const card = button.closest("[data-application-id]");
    if (!card) return;
    const id = card.dataset.applicationId;
    if (button.dataset.action === "delete") {
        openDeleteConfirmation(id, button);
        return;
    }
    if (button.dataset.action === "save") {
        const payload = {};
        card.querySelectorAll("[data-field]").forEach(field => {
            if (field.dataset.field === "notes") payload.notes = field.value.trim() || null;
            else if (field.dataset.field === "status") payload.status = field.value;
        });
        button.disabled = true;
        try {
            await applicationTrackerApi.update(id, payload);
            showNotice("Application changes saved.");
            await loadTracker();
        } catch (error) {
            showNotice(error.message || "Could not save application changes.", true);
        } finally {
            button.disabled = false;
        }
    }
});

const confirmOverlay = $("trackerConfirmOverlay");
const confirmDialog = confirmOverlay.querySelector(".tracker-confirm-dialog");
const confirmCancel = $("trackerConfirmCancel");
const confirmRemove = $("trackerConfirmRemove");

function openDeleteConfirmation(applicationId, trigger) {
    pendingDeleteId = applicationId;
    deleteTrigger = trigger;
    confirmOverlay.hidden = false;
    document.body.classList.add("tracker-confirm-open");
    confirmRemove.disabled = false;
    confirmCancel.disabled = false;
    confirmRemove.textContent = "Remove application";
    confirmDialog.focus();
    confirmCancel.focus();
}

function closeDeleteConfirmation() {
    confirmOverlay.hidden = true;
    document.body.classList.remove("tracker-confirm-open");
    pendingDeleteId = null;
    const trigger = deleteTrigger;
    deleteTrigger = null;
    if (trigger?.isConnected) trigger.focus();
}

confirmCancel.addEventListener("click", closeDeleteConfirmation);
confirmOverlay.addEventListener("click", event => {
    if (event.target === confirmOverlay) closeDeleteConfirmation();
});
document.addEventListener("keydown", event => {
    if (confirmOverlay.hidden) return;
    if (event.key === "Escape") {
        event.preventDefault();
        closeDeleteConfirmation();
    } else if (event.key === "Tab") {
        const focusable = [confirmCancel, confirmRemove].filter(button => !button.disabled);
        if (event.shiftKey && document.activeElement === focusable[0]) {
            event.preventDefault();
            focusable[focusable.length - 1].focus();
        } else if (!event.shiftKey && document.activeElement === focusable[focusable.length - 1]) {
            event.preventDefault();
            focusable[0].focus();
        }
    }
});

confirmRemove.addEventListener("click", async () => {
    if (!pendingDeleteId) return;
    const applicationId = pendingDeleteId;
    confirmRemove.disabled = true;
    confirmCancel.disabled = true;
    confirmRemove.textContent = "Removing…";
    try {
        const application = applications.find(item => String(item.id) === String(applicationId));
        await applicationTrackerApi.remove(applicationId);
        // Keep Saved Tenders and Application Tracker in sync: removing a tracked
        // application also removes its linked saved tender, when the ID is available.
        if (application?.tender_id !== undefined && application?.tender_id !== null) {
            try {
                await savedTendersApi.remove(application.tender_id);
            } catch (savedError) {
                console.error("Application removed, but the linked saved tender could not be removed:", savedError);
                closeDeleteConfirmation();
                confirmCancel.disabled = false;
                showNotice("Application removed, but its saved tender could not be removed. Please remove it from Saved Tenders manually.", true);
                await loadTracker();
                return;
            }
        }
        closeDeleteConfirmation();
        confirmCancel.disabled = false;
        showNotice("Application and its saved tender removed.");
        await loadTracker();
    } catch (error) {
        confirmCancel.disabled = false;
        confirmRemove.disabled = false;
        confirmRemove.textContent = "Remove application";
        showNotice(error.message || "Could not remove this application.", true);
    }
});

statusFilter.addEventListener("change", renderList);
searchInput.addEventListener("input", renderList);
$("trackerRefresh").addEventListener("click", loadTracker);

if (requireLogin()) loadTracker();
