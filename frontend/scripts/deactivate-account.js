import { authApi } from "./api.js";
import { clearSession } from "./shared-utils.js";

// Profile page > User profile tab > "Deactivate account".
// The Signup API switches the account off; signing in again on the login
// page offers to reactivate it.
function longDate(isoDate) {
    const date = new Date(isoDate + "T12:00:00Z");
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleDateString("en-ZA", { day: "numeric", month: "long", year: "numeric" });
}

function setupDeactivateAccount() {
    const form = document.getElementById("deactivateAccountForm");
    if (!form || form.dataset.bound === "true") return;
    form.dataset.bound = "true";

    const status = document.getElementById("deactivateAccountStatus");
    const button = document.getElementById("deactivateAccountButton");
    const password = document.getElementById("deactivateAccountPassword");

    const show = (message, kind) => {
        status.hidden = false;
        status.textContent = message;
        status.classList.remove("success", "error", "info");
        status.classList.add(kind);
    };

    form.addEventListener("submit", async event => {
        event.preventDefault();
        button.disabled = true;
        show("Deactivating your account…", "info");
        try {
            const result = await authApi.deactivateAccount(password.value);
            form.reset();
            form.querySelectorAll("input, button").forEach(el => { el.disabled = true; });
            clearSession();
            const until = longDate(result?.delete_on || "");
            show(
                "Your account is deactivated. Sign in again any time"
                + (until ? ` before ${until}` : "")
                + " to reactivate it. Taking you to the home page…",
                "success"
            );
            setTimeout(() => window.location.replace("./"), 6000);
        } catch (error) {
            const detail = typeof error?.detail === "string" && error.detail
                ? error.detail
                : "Your account could not be deactivated. Please try again.";
            show(detail, "error");
            if (error?.status === 403) password.focus();
            button.disabled = false;
        }
    });
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", setupDeactivateAccount, { once: true });
} else {
    setupDeactivateAccount();
}
