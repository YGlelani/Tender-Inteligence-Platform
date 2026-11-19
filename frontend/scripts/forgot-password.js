// Forgot password on the login page: email a 6-digit code, then reset with it.
// Loaded after script.js, which defines API_URL (the login API on port 8006).
(function () {
    const LOGIN_API = typeof API_URL === "string"
        ? API_URL
        : `http://${window.location.hostname}:8006`;

    let resetEmail = "";

    const $ = id => document.getElementById(id);

    function setText(id, message, type = "") {
        const el = $(id);
        if (!el) return;
        el.textContent = message;
        el.className = `status ${type}`.trim();
    }

    // Views: login, forgot, reset, and reactivate (used by script.js after
    // signing in to a deactivated account, through window.showLoginView).
    function showView(view) {
        const heading = document.querySelector(".login-card h1");
        const intro = document.querySelector("#loginForm")?.previousElementSibling;
        $("loginForm").hidden = view !== "login";
        $("forgotForm").hidden = view !== "forgot";
        $("resetForm").hidden = view !== "reset";
        if ($("reactivateForm")) $("reactivateForm").hidden = view !== "reactivate";
        $("signupLine").hidden = view !== "login";
        if (intro && intro.classList.contains("welcome-text")) intro.hidden = view !== "login";
        if (heading) {
            heading.textContent = {
                login: "Sign in to your account",
                reactivate: "Reactivate your account"
            }[view] || "Reset your password";
        }
        const focusId = { login: "username", forgot: "forgotEmail", reset: "resetCode", reactivate: "reactivateCode" }[view];
        $(focusId)?.focus();
    }

    window.showLoginView = showView;

    async function post(path, body) {
        const response = await fetch(LOGIN_API + path, {
            method: "POST",
            headers: { "Content-Type": "application/json", Accept: "application/json" },
            body: JSON.stringify(body)
        });
        let data = {};
        try { data = await response.json(); } catch { data = {}; }
        let detail = data.detail || data.message || "";
        if (Array.isArray(detail)) detail = detail.map(item => item?.msg || String(item)).join("; ");
        return { ok: response.ok, status: response.status, message: String(detail || "") };
    }

    async function sendCode(email, statusId, button) {
        if (button) button.disabled = true;
        setText(statusId, "Sending code...", "loading");
        try {
            const result = await post("/forgot-password", { email });
            if (!result.ok) {
                setText(statusId, result.message || "Could not send the code. Please try again.", "error");
                return false;
            }
            resetEmail = email;
            return result.message;
        } catch (error) {
            console.error("Forgot password request failed:", error);
            setText(statusId, "Unable to connect to the login server. Please try again.", "error");
            return false;
        } finally {
            if (button) button.disabled = false;
        }
    }

    function setup() {
        if (!$("forgotForm") || !$("resetForm")) return;

        $("forgotPasswordLink")?.addEventListener("click", event => {
            event.preventDefault();
            const typed = $("username")?.value.trim() || "";
            if (typed.includes("@")) $("forgotEmail").value = typed;
            setText("forgotStatus", "");
            showView("forgot");
        });

        document.querySelectorAll("[data-back-to-login]").forEach(link => {
            link.addEventListener("click", event => {
                event.preventDefault();
                showView("login");
            });
        });

        $("forgotForm").addEventListener("submit", async event => {
            event.preventDefault();
            const email = $("forgotEmail").value.trim();
            if (!email) return;
            const message = await sendCode(email, "forgotStatus", $("forgotButton"));
            if (message) {
                $("resetForm").reset();
                setText("resetStatus", message, "success");
                showView("reset");
            }
        });

        $("resendCodeLink")?.addEventListener("click", async event => {
            event.preventDefault();
            if (!resetEmail) {
                showView("forgot");
                return;
            }
            const message = await sendCode(resetEmail, "resetStatus", null);
            if (message) setText("resetStatus", "A new code is on its way. Use the newest code.", "success");
        });

        $("resetForm").addEventListener("submit", async event => {
            event.preventDefault();
            const code = $("resetCode").value.trim();
            const password = $("resetPassword").value;
            if (!/^\d{6}$/.test(code)) {
                setText("resetStatus", "Enter the 6-digit code from the email.", "error");
                return;
            }
            if (password !== $("resetConfirm").value) {
                setText("resetStatus", "The new passwords do not match.", "error");
                return;
            }
            const button = $("resetButton");
            button.disabled = true;
            setText("resetStatus", "Resetting password...", "loading");
            try {
                const result = await post("/reset-password", { email: resetEmail, code, new_password: password });
                if (!result.ok) {
                    setText("resetStatus", result.message || "Could not reset your password. Please try again.", "error");
                    return;
                }
                $("resetForm").reset();
                showView("login");
                if ($("username")) $("username").value = resetEmail;
                $("password")?.focus();
                setText("loginStatus", result.message || "Your password has been reset. You can now sign in.", "success");
            } catch (error) {
                console.error("Reset password request failed:", error);
                setText("resetStatus", "Unable to connect to the login server. Please try again.", "error");
            } finally {
                button.disabled = false;
            }
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", setup, { once: true });
    } else {
        setup();
    }
})();
