import { authApi } from "./api.js";

function setupChangePassword() {
    const form = document.getElementById("changePasswordForm");
    if (!form || form.dataset.bound === "true") return;
    form.dataset.bound = "true";

    const status = document.getElementById("changePasswordStatus");
    const button = document.getElementById("changePasswordButton");
    const current = document.getElementById("currentPassword");
    const next = document.getElementById("newPassword");
    const confirm = document.getElementById("confirmPassword");

    const show = (message, ok) => {
        status.hidden = false;
        status.textContent = message;
        status.classList.toggle("success", ok);
        status.classList.toggle("error", !ok);
    };

    form.addEventListener("submit", async event => {
        event.preventDefault();
        if (next.value !== confirm.value) {
            show("The new passwords do not match.", false);
            confirm.focus();
            return;
        }
        button.disabled = true;
        try {
            const result = await authApi.changePassword(current.value, next.value);
            // Changing the password signs out every other device; this browser
            // gets a new token so it stays signed in.
            if (result?.access_token) {
                localStorage.setItem("access_token", result.access_token);
                localStorage.setItem("token_type", result.token_type || "bearer");
                localStorage.setItem("last_activity_at", String(Date.now()));
                if (result.session_timeout_hours) {
                    localStorage.setItem("session_timeout_hours", String(result.session_timeout_hours));
                }
            }
            form.reset();
            show(result?.message || "Your password has been changed.", true);
        } catch (error) {
            const detail = typeof error?.detail === "string" && error.detail
                ? error.detail
                : "Could not change your password. Please try again.";
            show(detail, false);
        } finally {
            button.disabled = false;
        }
    });
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", setupChangePassword, { once: true });
} else {
    setupChangePassword();
}
