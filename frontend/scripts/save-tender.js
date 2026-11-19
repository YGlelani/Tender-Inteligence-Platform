// "Save tender" buttons: save the tender and add it to the Application Tracker.
// Once saved, the button says "Track this bid" and opens the tender in the tracker.
//
// Markup: <button type="button" data-save-track="<database id, may be empty>"
//                 data-tender-number="<tender number>" data-closing-date="<closing date>">
// Call enableSaveTenderButtons() once per page; it handles every such button,
// including ones rendered later, and shows tenders already saved as "Saved".
// When a tender has no database id (the client and cache APIs leave it out),
// the id is looked up by tender number in the Search Tender API on click.
import { CONFIG } from "./config.js";
import { savedTendersApi, applicationTrackerApi, tenderSearchApi } from "./api.js";
import { esc } from "./utils.js";
import { icon } from "./icons.js";

const SELECTOR = "[data-save-track]";
const savedIds = new Set();
const savedNumbers = new Set();

const normalise = value => String(value ?? "").trim().toLowerCase();

function listFrom(result, keys) {
    if (Array.isArray(result)) return result;
    for (const key of keys) {
        if (Array.isArray(result?.[key])) return result[key];
    }
    return [];
}

function validId(value) {
    const id = Number(value);
    return value !== null && value !== undefined && value !== "" && Number.isInteger(id) && id > 0 ? id : null;
}

/** Find a tender's database id from its tender number. */
export async function findTenderId(number) {
    const reference = normalise(number);
    if (!reference) return null;
    const result = await tenderSearchApi.search({ q: String(number).trim(), include_closed: true, limit: 20 });
    const match = listFrom(result, ["tenders", "items", "results"])
        .find(item => normalise(item.tender_number) === reference);
    return validId(match?.id);
}

/** Save a tender, then track it. Returns "added", "already" or "failed" for the tracker step. */
export async function saveAndTrackTender({ id, number, closingDate }) {
    await savedTendersApi.save({ tender_id: id });
    savedIds.add(String(id));
    if (number) savedNumbers.add(normalise(number));

    const reference = String(number || "").trim();
    if (!reference) return "failed";

    try {
        const tracked = listFrom(await applicationTrackerApi.list({ limit: 100 }), ["applications", "items", "data"]);
        const already = tracked.some(item => {
            const candidate = normalise(
                item.tender_number ?? item.tender_reference ?? item.reference_number ?? item.tender_id
            );
            return candidate && (candidate === normalise(reference) || candidate === String(id));
        });
        if (already) return "already";

        const payload = { tender_number: reference };
        const deadline = closingDate ? new Date(String(closingDate).replace(" ", "T")) : null;
        if (deadline && !Number.isNaN(deadline.getTime())) {
            payload.application_deadline = deadline.toISOString().slice(0, 10);
        }
        await applicationTrackerApi.create(payload);
        return "added";
    } catch (error) {
        console.error("Tender saved, but it could not be added to the Application Tracker:", error);
        return "failed";
    }
}

/** Markup for a Save tender button, or "" when there is neither a database id nor a tender number. */
export function saveTenderButton({ id, number, closingDate }, className = "tender-save-btn", label = "Save tender") {
    const databaseId = validId(id);
    const reference = String(number ?? "").trim();
    const placeholders = ["", "—", "tender", "reference unavailable"];
    if (!databaseId && placeholders.includes(reference.toLowerCase())) return "";
    return `<button type="button" class="${esc(className)}" data-save-track="${esc(databaseId ?? "")}"
        data-tender-number="${esc(reference)}" data-closing-date="${esc(closingDate ?? "")}"
        title="Save this tender and add it to your Application Tracker">${icon("star")} ${esc(label)}</button>`;
}

/** Where "Track this bid" goes: the Application Tracker, opened at this tender. */
export function trackerLink(number) {
    const reference = String(number ?? "").trim();
    return reference
        ? `./application-tracker.html?tender=${encodeURIComponent(reference)}`
        : "./application-tracker.html";
}

// Once saved, the button becomes "Track this bid" and opens the tender in
// the Application Tracker.
function showSaved(button, message = "Saved") {
    button.innerHTML = `${icon("star")} Track this bid`;
    button.title = `${message}. Click to open it in your Application Tracker.`;
    button.setAttribute("aria-label", `Track this bid in your Application Tracker (${message})`);
    button.classList.add("is-saved");
}

function markSavedButtons(root = document) {
    if (!savedIds.size && !savedNumbers.size) return;
    root.querySelectorAll?.(SELECTOR).forEach(button => {
        if (button.classList.contains("is-saved")) return;
        if (savedIds.has(button.dataset.saveTrack) || savedNumbers.has(normalise(button.dataset.tenderNumber))) {
            showSaved(button, "Already in your Saved Tenders");
        }
    });
}

async function loadSavedTenders() {
    try {
        const saved = listFrom(await savedTendersApi.list(), ["saved_tenders", "items", "tenders", "data", "results"]);
        saved.forEach(item => {
            if (item.tender_id !== undefined && item.tender_id !== null) savedIds.add(String(item.tender_id));
            if (item.tender_number) savedNumbers.add(normalise(item.tender_number));
        });
        markSavedButtons();
    } catch (error) {
        console.warn("Could not load saved tenders to mark Save buttons:", error);
    }
}

let enabled = false;

export function enableSaveTenderButtons() {
    if (enabled) return;
    enabled = true;

    if (localStorage.getItem("access_token")) {
        loadSavedTenders();
        new MutationObserver(records => {
            for (const record of records) {
                record.addedNodes.forEach(node => {
                    if (node.nodeType !== 1) return;
                    if (node.matches(SELECTOR)) markSavedButtons(node.parentElement || document);
                    else markSavedButtons(node);
                });
            }
        }).observe(document.documentElement, { childList: true, subtree: true });
    }

    document.addEventListener("click", async event => {
        const button = event.target.closest(SELECTOR);
        if (!button) return;
        event.preventDefault();
        event.stopPropagation();
        if (button.disabled) return;

        if (button.classList.contains("is-saved")) {
            window.location.assign(trackerLink(button.dataset.tenderNumber));
            return;
        }

        if (!localStorage.getItem("access_token")) {
            window.location.replace(CONFIG.services.loginFrontend);
            return;
        }

        const previous = button.innerHTML;
        button.disabled = true;
        button.textContent = "Saving…";

        try {
            const number = button.dataset.tenderNumber;
            const id = validId(button.dataset.saveTrack) ?? await findTenderId(number);
            if (!id) throw new Error(`No database id found for tender ${number || "(no number)"}`);
            button.dataset.saveTrack = String(id);

            const tracker = await saveAndTrackTender({ id, number, closingDate: button.dataset.closingDate });
            showSaved(button, {
                added: "Saved and added to your Application Tracker",
                already: "Saved. It is already in your Application Tracker",
                failed: "Saved, but it could not be added to your Application Tracker"
            }[tracker]);
        } catch (error) {
            console.error("Could not save tender:", error);
            button.innerHTML = previous;
            window.alert("Could not save this tender. Please try again.");
        } finally {
            button.disabled = false;
        }
    });
}
