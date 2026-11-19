import { businessProfileApi, onboardingApi } from "./api.js";
import { finishedProcessing } from "./profile-sources.js";
import { esc } from "./utils.js";
import { redirectToLogin } from "./shared-utils.js";

import { icon } from "./icons.js";
const $ = id => document.getElementById(id);

const LEVEL_LABELS = {
    missing: "Missing",
    uploading: "Uploading…",
    processing: "AI is reading…",
    verified: "Verified",
    attention: "Check",
    invalid: "Fix needed",
    failed: "Couldn't read"
};

const DISMISS_KEY = "onboarding_dismissed";
const POLL_MS = 3000;

let overview = null;
let pollTimer = null;
let scrolledToHash = false;
const uploading = new Set();


/* ---------- helpers ---------- */

function showMessage(text, kind = "error") {
    const box = $("onbMessage");
    if (!text) {
        box.hidden = true;
        return;
    }
    box.textContent = text;
    box.dataset.kind = kind;
    box.hidden = false;
}

function cleanError(error) {
    // request() errors look like "400 Bad Request @ /path: detail"
    const message = String(error?.message || error || "Something went wrong.");
    const detail = message.split(": ").slice(1).join(": ");
    return detail || message;
}

function chip(level, extraClass = "") {
    return `<span class="onb-chip ${extraClass}" data-level="${esc(level)}">${esc(LEVEL_LABELS[level] || level)}</span>`;
}

function prettyKey(key) {
    return key.replaceAll("_", " ").replace(/\b\w/g, c => c.toUpperCase())
        .replace("Id ", "ID ").replace("Bbbee", "B-BBEE").replace("Tcs", "TCS").replace("Csd", "CSD").replace("Crs", "CRS");
}

function prettyValue(value) {
    if (value === true) return "Yes";
    if (value === false) return "No";
    if (Array.isArray(value)) {
        return value.map(item => (item && typeof item === "object") ? (item.name || Object.values(item).join(" ")) : item)
            .filter(Boolean).join(", ");
    }
    if (value && typeof value === "object") return Object.values(value).filter(Boolean).join(", ");
    return value;
}

function formatDate(value) {
    if (!value) return "";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}


/* ---------- rendering ---------- */

function renderScore() {
    const readiness = overview?.readiness;
    if (!readiness) return;
    const ring = document.querySelector("#onbScore .onb-ring");
    ring.style.setProperty("--score", readiness.score);
    ring.dataset.band = readiness.score >= 85 ? "good" : readiness.score >= 60 ? "mid" : "low";
    $("onbScoreValue").textContent = `${readiness.score}%`;
    $("onbScoreLabel").textContent = readiness.label;
    $("onbScoreDetail").textContent =
        `${readiness.verified} of ${readiness.required_total} key documents verified` +
        (readiness.attention ? ` · ${readiness.attention} need attention` : "");
}

function renderProfile() {
    const profile = overview?.profile;
    const chipEl = $("profileChip");
    const result = $("profileResult");

    if (!profile) {
        chipEl.dataset.level = uploading.has("profile") ? "uploading" : "missing";
        chipEl.textContent = uploading.has("profile") ? LEVEL_LABELS.uploading : "Not added";
        result.hidden = true;
        return;
    }

    const level = { ready: "verified", processing: "processing", failed: "failed" }[profile.status] || "processing";
    chipEl.dataset.level = level;
    chipEl.textContent = level === "verified" ? "Profile ready" : LEVEL_LABELS[level];

    const source = profile.source_kind === "website"
        ? `From your website <a href="${esc(profile.source_ref)}" target="_blank" rel="noopener noreferrer">${esc(profile.source_ref)}</a>`
        : `From ${esc(profile.source_ref || "your PDF")}`;

    if (profile.status === "failed") {
        result.innerHTML = `<p class="onb-error">${esc(profile.error)}</p><p class="onb-muted">${source}</p>`;
        result.hidden = false;
        return;
    }
    if (!profile.business_name) {
        result.innerHTML = `<p class="onb-muted"><span class="onb-spinner" aria-hidden="true"></span> The agent is reading your profile… ${source}</p>`;
        result.hidden = false;
        return;
    }

    const tags = (items, cls = "") => (items || []).slice(0, 12).map(item => `<span class="onb-tag ${cls}">${esc(item)}</span>`).join("");
    const facts = [
        ["Registration", profile.registration_number],
        ["B-BBEE level", profile.bbbee_level],
        ["CSD number", profile.csd_number],
        ["CIDB", profile.cidb_grading],
        ["Established", profile.year_established],
        ["Email", profile.contact_email],
        ["Phone", profile.contact_phone]
    ].filter(([, value]) => value);

    result.innerHTML = `
        <div class="onb-profile-head">
            <div>
                <h3>${esc(profile.business_name)}</h3>
                <p class="onb-muted">${source}${profile.status === "processing" ? ' · <span class="onb-spinner" aria-hidden="true"></span> updating…' : ""}</p>
            </div>
        </div>
        ${profile.description ? `<p>${esc(profile.description)}</p>` : ""}
        ${profile.industries?.length ? `<div class="onb-tag-row"><span class="onb-tag-label">Industries</span>${tags(profile.industries, "strong")}</div>` : ""}
        ${profile.services?.length ? `<div class="onb-tag-row"><span class="onb-tag-label">Services</span>${tags(profile.services)}</div>` : ""}
        ${profile.service_areas?.length ? `<div class="onb-tag-row"><span class="onb-tag-label">Areas</span>${tags(profile.service_areas)}</div>` : ""}
        ${facts.length ? `<dl class="onb-fields">${facts.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl>` : ""}
        <div class="onb-profile-link">
            <p class="onb-muted">Your company profile is built from these details, so Smart Alerts can match tenders to your business.</p>
            <a class="onb-btn primary" href="./profile.html">See them in My profile</a>
        </div>
    `;
    result.hidden = false;
}

function renderDocument(doc) {
    const fields = Object.entries(doc.fields || {})
        .map(([key, value]) => [key, prettyValue(value)])
        .filter(([, value]) => value !== null && value !== undefined && value !== "")
        .slice(0, 8);

    const checks = (doc.checks || []).map(check =>
        `<li data-level="${esc(check.level)}">${esc(check.message)}</li>`).join("");

    const busy = doc.level === "processing";
    return `
        <li class="onb-file" data-level="${esc(doc.level)}">
            <div class="onb-file-top">
                <strong title="${esc(doc.filename)}">${esc(doc.filename)}</strong>
                ${chip(doc.level, "small")}
            </div>
            ${busy ? '<p class="onb-muted"><span class="onb-spinner" aria-hidden="true"></span> Reading and checking this document…</p>' : ""}
            ${doc.error ? `<p class="onb-error">${esc(doc.error)}</p>` : ""}
            ${doc.summary ? `<p class="onb-summary">${esc(doc.summary)}</p>` : ""}
            ${fields.length ? `<dl class="onb-fields">${fields.map(([k, v]) => `<div><dt>${esc(prettyKey(k))}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl>` : ""}
            ${checks ? `<ul class="onb-checks">${checks}</ul>` : ""}
            <div class="onb-file-actions">
                <button type="button" data-view="${esc(doc.id)}" data-name="${esc(doc.filename)}">View</button>
                ${busy ? "" : `<button type="button" data-retry="${esc(doc.id)}">Re-check</button>`}
                <button type="button" data-remove="${esc(doc.id)}" class="danger">Remove</button>
            </div>
        </li>`;
}

function renderCard(item) {
    const level = uploading.has(item.key) ? "uploading" : item.level;
    const hasDocs = item.documents.length > 0;
    const uploadLabel = !hasDocs ? "Upload" : item.multiple ? "Add another" : "Replace";
    const badge = item.requirement === "sector" ? '<span class="onb-req">For your industry</span>'
        : item.requirement === "recommended" ? '<span class="onb-req">Recommended</span>' : "";

    return `
        <article class="onb-doc" id="${esc(item.key)}" data-level="${esc(level)}" data-drop="${esc(item.key)}">
            <header>
                <div>
                    <h4>${esc(item.label)} ${badge}</h4>
                    <p>${esc(item.hint)}</p>
                </div>
                ${chip(level)}
            </header>
            ${hasDocs ? `<ul class="onb-files">${item.documents.map(renderDocument).join("")}</ul>` : ""}
            <label class="onb-upload">
                <input type="file" hidden accept="application/pdf,.pdf,image/png,image/jpeg,image/webp" data-upload="${esc(item.key)}" ${item.multiple ? "multiple" : ""}>
                <span aria-hidden="true">${icon("upload")}</span> ${uploadLabel}
                <small>or drop a file here</small>
            </label>
        </article>`;
}

function renderChecklist() {
    const list = overview?.checklist || [];
    const groups = { docsRequired: [], docsRecommended: [], docsOther: [] };
    list.forEach(item => {
        if (item.requirement === "required") groups.docsRequired.push(item);
        else if (item.requirement === "recommended" || (item.requirement === "sector" && item.applies)) groups.docsRecommended.push(item);
        else groups.docsOther.push(item);
    });
    Object.entries(groups).forEach(([id, items]) => {
        $(id).innerHTML = items.length ? items.map(renderCard).join("")
            : '<p class="state-msg">Nothing here for your business yet.</p>';
    });
}

function render() {
    renderScore();
    renderProfile();
    renderChecklist();
}


function scrollToHash() {
    if (scrolledToHash || !window.location.hash) return;
    scrolledToHash = true;
    const target = document.getElementById(decodeURIComponent(window.location.hash.slice(1)));
    if (!target) return;
    const card = target.closest(".onb-more");
    if (card) card.open = true;
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    target.classList.add("onb-highlight");
}


/* ---------- data ---------- */

async function load() {
    const previous = overview;
    try {
        overview = await onboardingApi.overview();
        // The company profile is built from these documents: rebuild it once they are processed.
        if (finishedProcessing(previous, overview)) {
            businessProfileApi.refresh().catch(error => console.warn("Company profile refresh failed:", error));
        }
        showMessage("");
        render();
        scrollToHash();
    } catch (error) {
        console.error("Unable to load onboarding state:", error);
        showMessage(`The AI agent couldn't load your documents (${cleanError(error)}). Please refresh in a moment.`);
    }
    schedulePoll();
}

function schedulePoll() {
    clearTimeout(pollTimer);
    if (overview?.processing || uploading.size) {
        pollTimer = setTimeout(load, POLL_MS);
    }
}

async function uploadDocuments(docType, files) {
    if (!files?.length) return;
    uploading.add(docType);
    render();
    try {
        for (const file of files) {
            await onboardingApi.uploadDocument(docType, file);
        }
        showMessage("");
    } catch (error) {
        showMessage(cleanError(error));
    } finally {
        uploading.delete(docType);
        await load();
    }
}

async function uploadProfile(payload) {
    uploading.add("profile");
    renderProfile();
    try {
        await onboardingApi.uploadProfile(payload);
        showMessage("");
    } catch (error) {
        showMessage(cleanError(error));
    } finally {
        uploading.delete("profile");
        await load();
    }
}

async function viewDocument(id, name) {
    // The file endpoint needs the Authorization header, so fetch it as a blob.
    try {
        const response = await fetch(onboardingApi.documentFileUrl(id), {
            headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` }
        });
        if (!response.ok) throw new Error(`Could not open ${name}.`);
        const url = URL.createObjectURL(await response.blob());
        window.open(url, "_blank", "noopener");
        setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (error) {
        showMessage(cleanError(error));
    }
}


/* ---------- events ---------- */

function bindEvents() {
    document.querySelectorAll("[data-profile-tab]").forEach(tab => {
        tab.addEventListener("click", () => {
            const which = tab.dataset.profileTab;
            document.querySelectorAll("[data-profile-tab]").forEach(t => {
                t.classList.toggle("active", t === tab);
                t.setAttribute("aria-selected", String(t === tab));
            });
            document.querySelectorAll("[data-profile-pane]").forEach(pane => {
                pane.hidden = pane.dataset.profilePane !== which;
            });
        });
    });

    $("profileFile").addEventListener("change", event => {
        const file = event.target.files?.[0];
        event.target.value = "";
        if (file) uploadProfile({ file });
    });

    const profileDrop = $("profileDrop");
    ["dragover", "dragenter"].forEach(type => profileDrop.addEventListener(type, event => {
        event.preventDefault();
        profileDrop.classList.add("dragging");
    }));
    ["dragleave", "drop"].forEach(type => profileDrop.addEventListener(type, () => profileDrop.classList.remove("dragging")));
    profileDrop.addEventListener("drop", event => {
        event.preventDefault();
        const file = event.dataTransfer?.files?.[0];
        if (file) uploadProfile({ file });
    });

    $("profileWebsiteForm").addEventListener("submit", event => {
        event.preventDefault();
        const website = $("profileWebsite").value.trim();
        if (!website) {
            $("profileWebsite").focus();
            return;
        }
        uploadProfile({ website });
    });

    const main = document.querySelector(".onb-page");

    main.addEventListener("change", event => {
        const input = event.target.closest("[data-upload]");
        if (!input) return;
        const files = Array.from(input.files || []);
        input.value = "";
        uploadDocuments(input.dataset.upload, files);
    });

    main.addEventListener("click", async event => {
        const view = event.target.closest("[data-view]");
        const retry = event.target.closest("[data-retry]");
        const remove = event.target.closest("[data-remove]");
        if (view) {
            viewDocument(view.dataset.view, view.dataset.name);
        } else if (retry) {
            retry.disabled = true;
            try {
                await onboardingApi.reprocessDocument(retry.dataset.retry);
            } catch (error) {
                showMessage(cleanError(error));
            }
            load();
        } else if (remove) {
            if (!window.confirm("Remove this document from your vault?")) return;
            remove.disabled = true;
            try {
                await onboardingApi.deleteDocument(remove.dataset.remove);
            } catch (error) {
                showMessage(cleanError(error));
            }
            load();
        }
    });

    main.addEventListener("dragover", event => {
        const card = event.target.closest("[data-drop]");
        if (!card) return;
        event.preventDefault();
        card.classList.add("dragging");
    });
    main.addEventListener("dragleave", event => {
        event.target.closest("[data-drop]")?.classList.remove("dragging");
    });
    main.addEventListener("drop", event => {
        const card = event.target.closest("[data-drop]");
        if (!card) return;
        event.preventDefault();
        card.classList.remove("dragging");
        uploadDocuments(card.dataset.drop, Array.from(event.dataTransfer?.files || []));
    });

    const dismiss = () => {
        try { localStorage.setItem(DISMISS_KEY, "1"); } catch {}
    };
    $("onbSkip").addEventListener("click", () => {
        dismiss();
        window.location.assign("./dashboard.html");
    });
    $("onbDone").addEventListener("click", dismiss);
}


/* ---------- start ---------- */

if (!localStorage.getItem("access_token")) {
    redirectToLogin();
} else {
    if (new URLSearchParams(window.location.search).has("welcome")) {
        $("onbEyebrow").textContent = "WELCOME — ONE LAST STEP";
        $("onbTitle").textContent = "Let's get your business tender-ready";
    }
    bindEvents();
    load();
}
