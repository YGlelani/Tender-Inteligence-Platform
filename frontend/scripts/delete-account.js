import { authApi } from "./api.js";
import { clearSession } from "./shared-utils.js";

// Profile page > User profile tab > "Delete account".
// The Signup API deletes the account and every service's data about it.
function setupDeleteAccount() {
    const form = document.getElementById("deleteAccountForm");
    if (!form || form.dataset.bound === "true") return;
    form.dataset.bound = "true";

    const status = document.getElementById("deleteAccountStatus");
    const button = document.getElementById("deleteAccountButton");
    const password = document.getElementById("deleteAccountPassword");
    const confirmBox = document.getElementById("deleteAccountConfirm");

    const show = (message, kind) => {
        status.hidden = false;
        status.textContent = message;
        status.classList.remove("success", "error", "info");
        status.classList.add(kind);
    };

    form.addEventListener("submit", async event => {
        event.preventDefault();
        if (!confirmBox.checked) {
            show("Tick the box to confirm you want to delete your account.", "error");
            confirmBox.focus();
            return;
        }

        button.disabled = true;
        show("Deleting your account…", "info");
        try {
            await authApi.deleteAccount(password.value);
            form.reset();
            form.querySelectorAll("input, button").forEach(el => { el.disabled = true; });
            clearSession();
            show("Your account has been deleted. Taking you to the home page…", "success");
            setTimeout(() => window.location.replace("./"), 4000);
        } catch (error) {
            const detail = typeof error?.detail === "string" && error.detail
                ? error.detail
                : "Your account could not be deleted. Please try again.";
            show(detail, "error");
            if (error?.status === 403) password.focus();
            button.disabled = false;
        }
    });
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", setupDeleteAccount, { once: true });
} else {
    setupDeleteAccount();
}
