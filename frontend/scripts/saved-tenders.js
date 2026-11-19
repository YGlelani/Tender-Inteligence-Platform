import { CONFIG } from "./config.js";
import { escapeHtml } from "./utils.js";
import { savedTendersApi, applicationTrackerApi } from "./api.js";

import { icon } from "./icons.js";
const $ = id => document.getElementById(id);
const list = $("savedTenderList");
const count = $("savedTenderCount");
const message = $("savedTenderMessage");

// Saved Tenders and the Application Tracker work together: saving a tender
// tracks it, and removing it here also removes it from the tracker.
let trackerById = new Map();
let trackerByReference = new Map();
let trackerAvailable = false;
const savedById = new Map();

const normalise = value => String(value ?? "").trim().toLowerCase();

function trackedApplication(item) {
    const tenderId = item.tender_id ?? item.id;
    return trackerById.get(String(tenderId)) || trackerByReference.get(normalise(item.tender_number)) || null;
}

async function loadTrackerApplications() {
    trackerById = new Map();
    trackerByReference = new Map();
    try {
        const result = await applicationTrackerApi.list({ limit: 100 });
        const applications = Array.isArray(result?.applications) ? result.applications
            : Array.isArray(result?.items) ? result.items : [];
        applications.forEach(application => {
            if (application.tender_id !== undefined && application.tender_id !== null) {
                trackerById.set(String(application.tender_id), application);
            }
            const reference = normalise(application.tender_reference ?? application.tender_number);
            if (reference) trackerByReference.set(reference, application);
        });
        trackerAvailable = true;
    } catch (error) {
        trackerAvailable = false;
        console.warn("Could not load the Application Tracker:", error);
    }
}

function deadlineFrom(value) {
    if (!value) return null;
    const date = new Date(String(value).replace(" ", "T"));
    return Number.isNaN(date.getTime()) ? null : date.toISOString().slice(0, 10);
}

function trackingMarkup(item, tenderId) {
    if (!trackerAvailable) return "";
    const application = trackedApplication(item);
    if (application) {
        return `
            <div class="saved-tracking">
                <span>Application Tracker</span>
                <strong class="saved-tracking-status" data-status="${escapeHtml(application.status)}">${escapeHtml(application.status || "Tracked")}</strong>
                <a href="./application-tracker.html?tender=${encodeURIComponent(item.tender_number ?? "")}">Open tracker ${icon("arrow-right")}</a>
            </div>`;
    }
    return `
        <div class="saved-tracking">
            <span>Application Tracker</span>
            <strong>Not tracked yet</strong>
            <button type="button" data-track-saved="${escapeHtml(tenderId)}">Track application</button>
        </div>`;
}

function formatDate(value) {
    if (!value) return "Not provided";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat("en-ZA", { day: "2-digit", month: "short", year: "numeric" }).format(date);
}

function showMessage(text, isError = false) {
    message.textContent = text;
    message.hidden = false;
    message.classList.toggle("error", isError);
}

function showState(title, description, showBrowse = false) {
    list.innerHTML = `
        <div class="saved-state">
            <strong>${escapeHtml(title)}</strong>
            <p>${escapeHtml(description)}</p>
            ${showBrowse ? '<a href="./tender-search.html">Explore available tenders ' + icon("arrow-right") + '</a>' : ""}
            ${!showBrowse && title === "Could not load saved tenders" ? '<button type="button" id="retrySavedTenders">Try again</button>' : ""}
        </div>`;
    $("retrySavedTenders")?.addEventListener("click", loadSavedTenders);
}

function normalizeSavedResponse(payload) {
    if (Array.isArray(payload)) return payload;
    if (Array.isArray(payload?.saved_tenders)) return payload.saved_tenders;
    if (Array.isArray(payload?.items)) return payload.items;
    if (Array.isArray(payload?.data)) return payload.data;
    return [];
}

function renderSavedTender(item) {
    const tenderId = item.tender_id ?? item.id;
    const title = item.title ?? item.tender_title ?? "Untitled tender";
    const reference = item.tender_number ?? item.reference_number ?? tenderId ?? "Reference unavailable";
    const organisation = item.organisation ?? item.organization ?? item.organisation_name ?? "Organisation not provided";
    const category = item.category ?? item.category_name ?? "Not provided";
    const province = item.province ?? item.location ?? "Not provided";
    const status = item.status ?? "Not provided";
    const statusClass = /closed|expired|cancelled|awarded/i.test(status) ? "closed" : "";
    const closing = formatDate(item.closing_date);
    const published = formatDate(item.published_date);
    const notes = item.notes ?? "";
    const tenderUrl = /^https?:\/\//i.test(item.tender_url ?? item.url ?? "") ? (item.tender_url ?? item.url) : "";
    const detailUrl = `./tender.html?number=${encodeURIComponent(reference)}`;

    return `
        <article class="saved-tender-card" data-tender-id="${escapeHtml(tenderId)}">
            <div class="saved-card-top">
                <span class="saved-reference">${escapeHtml(reference)}</span>
                <span class="saved-status ${statusClass}">${escapeHtml(status)}</span>
            </div>
            <h2>${escapeHtml(title)}</h2>
            <p class="saved-organisation">${escapeHtml(organisation)}</p>
            <div class="saved-meta">
                <div><span>Category</span><strong>${escapeHtml(category)}</strong></div>
                <div><span>Province / Location</span><strong>${escapeHtml(province)}</strong></div>
                <div><span>Closing date</span><strong>${escapeHtml(closing)}</strong></div>
                <div><span>Published</span><strong>${escapeHtml(published)}</strong></div>
            </div>
            ${trackingMarkup(item, tenderId)}
            <div class="saved-notes">
                <label for="savedNotes-${escapeHtml(tenderId)}">Your notes</label>
                <textarea id="savedNotes-${escapeHtml(tenderId)}" maxlength="2000" placeholder="Add a reminder or note about this opportunity">${escapeHtml(notes)}</textarea>
            </div>
            <div class="saved-card-actions">
                <a href="${detailUrl}">Tender details</a>
                ${tenderUrl ? `<a href="${escapeHtml(tenderUrl)}" target="_blank" rel="noopener noreferrer">Source ${icon("external-link")}</a>` : ""}
                <button class="saved-save-notes" type="button" data-save-notes="${escapeHtml(tenderId)}">Save notes</button>
                <button class="saved-remove" type="button" data-remove-saved="${escapeHtml(tenderId)}">Remove</button>
            </div>
        </article>`;
}

async function loadSavedTenders() {
    list.innerHTML = '<div class="saved-state"><span class="saved-spinner"></span><p>Loading your saved tenders…</p></div>';
    message.hidden = true;

    if (!localStorage.getItem("access_token")) {
        window.location.replace(CONFIG.services.loginFrontend);
        return;
    }

    try {
        const [payload] = await Promise.all([savedTendersApi.list(), loadTrackerApplications()]);
        const saved = normalizeSavedResponse(payload);
        savedById.clear();
        saved.forEach(item => savedById.set(String(item.tender_id ?? item.id), item));
        count.textContent = String(payload?.count ?? saved.length);

        if (!saved.length) {
            showState("No saved tenders yet", "When you find a tender worth revisiting, save it and it will appear here.", true);
            return;
        }

        list.innerHTML = saved.map(renderSavedTender).join("");
    } catch (error) {
        console.error("Could not load saved tenders:", error);
        count.textContent = "—";
        const reason = error && error.message ? error.message : "Unknown network error";
        showState(
            "Could not load saved tenders",
            "Saved Tenders API (" + CONFIG.services.savedTenders + CONFIG.endpoints.savedTenders + ") failed: " + reason
        );
    }
}

list.addEventListener("click", async event => {
    const notesButton = event.target.closest("[data-save-notes]");
    const removeButton = event.target.closest("[data-remove-saved]");
    const trackButton = event.target.closest("[data-track-saved]");

    if (trackButton) {
        const item = savedById.get(trackButton.dataset.trackSaved);
        if (!item) return;
        trackButton.disabled = true;
        try {
            const payload = { tender_number: String(item.tender_number ?? "").trim() };
            const deadline = deadlineFrom(item.closing_date);
            if (deadline) payload.application_deadline = deadline;
            await applicationTrackerApi.create(payload);
        } catch (error) {
            console.error(error);
            // 409 means it is already tracked, which is fine.
            if (!String(error.message || "").includes("409")) {
                showMessage("Could not add this tender to your Application Tracker. Please try again.", true);
                trackButton.disabled = false;
                return;
            }
        }
        await loadSavedTenders();
        showMessage("Tender added to your Application Tracker.");
        return;
    }

    if (notesButton) {
        const tenderId = notesButton.dataset.saveNotes;
        const textarea = $("savedNotes-" + tenderId);
        notesButton.disabled = true;
        try {
            await savedTendersApi.updateNotes(tenderId, textarea.value.trim() || null);
            showMessage("Your notes have been saved.");
        } catch (error) {
            console.error(error);
            showMessage("Could not save notes. Please try again.", true);
        } finally {
            notesButton.disabled = false;
        }
    }

    if (removeButton) {
        const tenderId = removeButton.dataset.removeSaved;
        const item = savedById.get(tenderId);
        const application = item ? trackedApplication(item) : null;
        const question = application
            ? "Remove this tender from Saved Tenders? It will also be removed from your Application Tracker, including its status and notes."
            : "Remove this tender from your saved list?";
        if (!window.confirm(question)) return;
        removeButton.disabled = true;
        try {
            await savedTendersApi.remove(tenderId);
            let text = "Tender removed from your saved list.";
            if (application) {
                try {
                    await applicationTrackerApi.remove(application.id);
                    text = "Tender removed from Saved Tenders and your Application Tracker.";
                } catch (trackerError) {
                    console.error("Saved tender removed, but its tracker entry could not be removed:", trackerError);
                    text = "Tender removed from Saved Tenders, but it could not be removed from your Application Tracker. Remove it there manually.";
                }
            }
            await loadSavedTenders();
            showMessage(text, text.includes("could not"));
        } catch (error) {
            console.error(error);
            showMessage("Could not remove this tender. Please try again.", true);
            removeButton.disabled = false;
        }
    }
});

loadSavedTenders();
