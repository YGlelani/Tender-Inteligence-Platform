import { notificationsApi } from "./api.js";

// Notification settings on the profile page (Notifications tab). Saved on the
// notifications API, so they apply to the bell and to emails on every device.

const DESCRIPTIONS = {
    password_changed: "When your password is changed. Always on, for your security.",
    profile_updated: "When your profile details are updated.",
    tender_closing_soon: "3 days and 1 day before a tender you saved closes.",
    tender_updated: "When the closing date of a tender you saved changes.",
    tender_cancelled: "When a tender you saved is cancelled.",
    new_matches: "When new tenders match your business profile."
};

function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, c => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[c]);
}

function switchHtml(pref, field, label) {
    const id = `pref-${pref.type}-${field}`;
    return `<label class="notification-channel" for="${id}">
        <span>${label}</span>
        <input class="notification-switch" type="checkbox" id="${id}" data-field="${field}"
            aria-label="${escapeHtml(pref.label)}: ${label.toLowerCase()}"
            ${pref[field] ? "checked" : ""} ${pref.locked ? "disabled" : ""}>
    </label>`;
}

async function setupNotificationPreferences() {
    const list = document.getElementById("notificationPreferenceList");
    const status = document.getElementById("notificationPreferencesStatus");
    if (!list) return;

    if (!document.getElementById("notificationChannelStyles")) {
        const style = document.createElement("style");
        style.id = "notificationChannelStyles";
        style.textContent = `
            .notification-channels { display: flex; gap: 18px; align-items: center; flex: 0 0 auto; }
            .notification-channel { display: inline-flex; align-items: center; gap: 8px; font-size: 12px;
                color: var(--shell-muted, #7285a4); cursor: pointer; }
            .notification-switch:disabled { opacity: .55; cursor: not-allowed; }
            @media (max-width: 600px) { .notification-channels { flex-direction: column; align-items: flex-end; gap: 8px; } }
        `;
        document.head.appendChild(style);
    }

    try {
        const result = await notificationsApi.preferences();
        const prefs = result?.preferences || [];
        list.innerHTML = prefs.map(pref => `
            <div class="notification-preference-row" data-type="${escapeHtml(pref.type)}">
                <span class="notification-preference-copy">
                    <strong>${escapeHtml(pref.label)}</strong>
                    <span>${escapeHtml(DESCRIPTIONS[pref.type] || "")}</span>
                </span>
                <span class="notification-channels">
                    ${switchHtml(pref, "in_app", "Bell")}
                    ${switchHtml(pref, "email", "Email")}
                </span>
            </div>`).join("");
        list.setAttribute("aria-busy", "false");
        if (status) status.textContent = "Changes save automatically.";
    } catch (error) {
        console.warn("Could not load notification settings:", error);
        list.setAttribute("aria-busy", "false");
        list.innerHTML = '<p class="settings-muted">Notification settings are unavailable right now. Please try again later.</p>';
        return;
    }

    list.addEventListener("change", async event => {
        const input = event.target.closest("input[data-field]");
        const row = input?.closest("[data-type]");
        if (!row) return;
        const inApp = row.querySelector('[data-field="in_app"]');
        const email = row.querySelector('[data-field="email"]');
        try {
            await notificationsApi.updatePreferences([
                { type: row.dataset.type, in_app: inApp.checked, email: email.checked }
            ]);
            if (status) status.textContent = "Saved.";
        } catch (error) {
            input.checked = !input.checked;
            if (status) status.textContent = "Could not save. Please try again.";
        }
    });
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", setupNotificationPreferences, { once: true });
} else {
    setupNotificationPreferences();
}
