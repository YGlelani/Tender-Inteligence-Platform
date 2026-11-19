// window.APP_CONFIG comes from scripts/runtime-config.js (written at container start-up);
// it is empty in production, so the production ports below apply.
const LOGIN_PAGE_CONFIG = window.APP_CONFIG || {};
const LOGIN_PAGE_PORTS = LOGIN_PAGE_CONFIG.PORTS || {};
const USER_SERVER_IP = LOGIN_PAGE_CONFIG.USER_SERVER_IP || window.location.hostname;
const SERVER_ORIGIN = `http://${USER_SERVER_IP}`;
const API_URL = `${SERVER_ORIGIN}:${LOGIN_PAGE_PORTS.login || 8006}`;
const SIGNUP_URL = `${SERVER_ORIGIN}:${LOGIN_PAGE_PORTS.signupFrontend || 8008}/`;
// This script runs the login page (login.html). index.html is the public landing page.
const DASHBOARD_URL = `${window.location.origin}/dashboard.html`;

function clearSession() {
    localStorage.removeItem("access_token");
    localStorage.removeItem("token_type");
    localStorage.removeItem("username");
    localStorage.removeItem("user");
    localStorage.removeItem("last_tender");
    localStorage.removeItem("session_timeout_hours");
    localStorage.removeItem("last_activity_at");
    sessionStorage.clear();
}

function handleLogoutRequest() {
    const params = new URLSearchParams(window.location.search);

    if (params.get("logout") !== "1") {
        return false;
    }

    clearSession();

    params.delete("logout");

    const query = params.toString();

    const cleanUrl =
        window.location.pathname +
        (query ? "?" + query : "") +
        window.location.hash;

    window.history.replaceState(
        {},
        document.title,
        cleanUrl
    );

    return true;
}

function setStatus(message, type = "") {
    const statusEl = document.getElementById("loginStatus");

    if (!statusEl) {
        return;
    }

    statusEl.textContent = message;
    statusEl.className = `status ${type}`.trim();
}

function setLoading(isLoading) {
    const button = document.getElementById("loginButton");
    const buttonText = document.getElementById("loginButtonText");

    if (!button) {
        return;
    }

    button.disabled = isLoading;

    if (buttonText) {
        buttonText.textContent = isLoading
            ? "SIGNING IN..."
            : "SIGN IN";
    }
}

function setupPasswordToggle() {
    const passwordInput = document.getElementById("password");
    const toggleButton = document.getElementById("togglePassword");
    const eyeIcon = document.getElementById("eyeIcon");

    if (!passwordInput || !toggleButton || !eyeIcon) {
        return;
    }

    toggleButton.addEventListener("click", () => {
        const isHidden = passwordInput.type === "password";

        passwordInput.type = isHidden
            ? "text"
            : "password";

        toggleButton.setAttribute(
            "aria-label",
            isHidden
                ? "Hide password"
                : "Show password"
        );

        toggleButton.setAttribute(
            "title",
            isHidden
                ? "Hide password"
                : "Show password"
        );

        eyeIcon.innerHTML = isHidden
            ? `
                <path d="M3 3l18 18"
                      stroke="currentColor"
                      stroke-width="1.8"
                      stroke-linecap="round"/>

                <path d="M10.58 10.58a2 2 0 002.84 2.84"
                      stroke="currentColor"
                      stroke-width="1.8"
                      stroke-linecap="round"/>

                <path d="M9.88 5.3A10.5 10.5 0 0112 5c4.48 0 8.27 2.94 9.54 7a10.9 10.9 0 01-3.17 4.72M6.61 6.61A10.9 10.9 0 002.46 12c1.27 4.06 5.06 7 9.54 7a10.5 10.5 0 003.1-.47"
                      stroke="currentColor"
                      stroke-width="1.8"
                      stroke-linejoin="round"
                      stroke-linecap="round"/>
            `
            : `
                <path d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"
                      stroke="currentColor"
                      stroke-width="1.8"
                      stroke-linejoin="round"
                      stroke-linecap="round"/>

                <path d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
                      stroke="currentColor"
                      stroke-width="1.8"
                      stroke-linejoin="round"
                      stroke-linecap="round"/>
            `;
    });
}

const MOON_ICON = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20.985 12.486a9 9 0 1 1-9.473-9.472c.405-.022.617.46.402.803a6 6 0 0 0 8.268 8.268c.344-.215.825-.004.803.401"/></svg>';
const SUN_ICON = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/></svg>';

// Light / dark switch on the login page, using the same theme as the rest of the app.
function setupThemeSwitch() {
    const button = document.getElementById("loginTheme");
    if (!button || !window.tsTheme) return;
    const render = () => {
        const dark = document.documentElement.dataset.theme === "dark";
        button.innerHTML = dark ? SUN_ICON : MOON_ICON;
        button.setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");
        button.setAttribute("aria-pressed", String(dark));
    };
    button.addEventListener("click", () => window.tsTheme.toggle());
    document.addEventListener("tstheme", render);
    render();
}

function setupSignupLink() {
    const signupLink = document.getElementById("signupLink");

    if (!signupLink) {
        return;
    }

    signupLink.addEventListener("click", event => {
        event.preventDefault();
        // The sign-up page is on another port; pass the current theme along.
        window.location.assign(window.tsTheme ? window.tsTheme.link(SIGNUP_URL) : SIGNUP_URL);
    });
}

function readCredentials() {
    return {
        username: document.getElementById("username")?.value.trim() || "",
        password: document.getElementById("password")?.value || ""
    };
}

// POST the username and password (and any extra fields) as a form to the Login API.
async function postCredentials(path, username, password, extra = {}) {
    const formData = new URLSearchParams();

    formData.append("username", username);
    formData.append("password", password);

    Object.entries(extra).forEach(([name, value]) => formData.append(name, value));

    const response = await fetch(
        API_URL + path,
        {
            method: "POST",
            headers: {
                "Content-Type":
                    "application/x-www-form-urlencoded"
            },
            body: formData
        }
    );

    let data = {};

    try {
        data = await response.json();
    } catch {
        data = {};
    }

    return { response, data };
}

function finishLogin(data, username, message, show = setStatus) {
    localStorage.setItem(
        "access_token",
        data.access_token
    );

    localStorage.setItem(
        "token_type",
        data.token_type || "bearer"
    );

    localStorage.setItem(
        "username",
        username
    );

    if (data.session_timeout_hours) {
        localStorage.setItem(
            "session_timeout_hours",
            String(data.session_timeout_hours)
        );
    }

    // A fresh login starts a fresh inactivity window.
    localStorage.setItem(
        "last_activity_at",
        String(Date.now())
    );

    show(message, "success");

    // The dashboard reads the token from localStorage (same site). Never put it
    // in the URL: addresses end up in server logs and browser history.
    window.location.replace(DASHBOARD_URL);
}

function showLoginError(response, data, show = setStatus) {
    if (response.status === 401) {
        const detail = String(data.detail || "");
        show(
            !detail || /^incorrect username or password/i.test(detail)
                ? "Incorrect email or password."
                : detail,
            "error"
        );
        return;
    }

    if (response.status >= 500) {
        show(
            data.detail ||
            "The login server is unavailable. Please try again.",
            "error"
        );
        return;
    }

    show(
        data.detail ||
        "Unable to sign in. Please try again.",
        "error"
    );
}

function showConnectionError(error, show = setStatus) {
    console.error("Login request failed:", error);

    show(
        "Unable to connect to the login server. Please check that the Login API is running.",
        "error"
    );
}

// After the correct password for an account its owner deactivated, the
// Login API answers 403. The page then switches to the reactivate form
// (window.showLoginView comes from scripts/forgot-password.js), asks the
// Login API to email a 6-digit code, and posts the details plus the code
// to /reactivate.
let reactivation = null;

function setReactivateStatus(message, type = "") {
    const statusEl = document.getElementById("reactivateStatus");

    if (!statusEl) {
        return;
    }

    statusEl.textContent = message;
    statusEl.className = `status ${type}`.trim();
}

async function sendReactivationCode() {
    if (!reactivation) {
        return;
    }

    setReactivateStatus("Sending a code to your email...", "loading");

    try {
        const { response, data } = await postCredentials(
            "/reactivate/send-code", reactivation.username, reactivation.password
        );

        if (response.ok) {
            setReactivateStatus(data.message || "We've emailed you a 6-digit code.", "success");
            return;
        }

        showLoginError(response, data, setReactivateStatus);

    } catch (error) {
        showConnectionError(error, setReactivateStatus);
    }
}

function startReactivation(username, password) {
    reactivation = { username, password };
    document.getElementById("reactivateForm")?.reset();
    setReactivateStatus("");
    window.showLoginView?.("reactivate");
    sendReactivationCode();
}

async function reactivate() {
    if (!reactivation) {
        window.showLoginView?.("login");
        return;
    }

    const code = document.getElementById("reactivateCode")?.value.trim() || "";

    if (!/^\d{6}$/.test(code)) {
        setReactivateStatus("Enter the 6-digit code from the email.", "error");
        return;
    }

    const button = document.getElementById("reactivateButton");

    if (button) {
        button.disabled = true;
    }
    setReactivateStatus("Reactivating your account...", "loading");

    try {
        const { response, data } = await postCredentials(
            "/reactivate", reactivation.username, reactivation.password, { code }
        );

        if (response.ok && data.access_token) {
            const { username } = reactivation;
            reactivation = null;
            finishLogin(data, username, "Your account is active again. Redirecting...", setReactivateStatus);
            return;
        }

        showLoginError(response, data, setReactivateStatus);

    } catch (error) {
        showConnectionError(error, setReactivateStatus);

    } finally {
        if (button) {
            button.disabled = false;
        }
    }
}

async function login() {
    const { username, password } = readCredentials();

    if (!username || !password) {
        setStatus(
            "Please enter your email and password.",
            "error"
        );
        return;
    }

    setLoading(true);
    setStatus("Authenticating...", "loading");

    try {
        const { response, data } = await postCredentials("/login", username, password);

        if (response.ok && data.access_token) {
            finishLogin(data, username, "Login successful. Redirecting...");
            return;
        }

        if (response.status === 403) {
            setStatus("");
            startReactivation(username, password);
            return;
        }

        showLoginError(response, data);

    } catch (error) {
        showConnectionError(error);

    } finally {
        setLoading(false);
    }
}

// hasValidSession() comes from scripts/session-check.js, loaded before this file.

// Still logged in and not logging out: go straight to the dashboard
// instead of showing the sign-in form again.
function forwardExistingSession() {
    const params = new URLSearchParams(window.location.search);
    if (params.get("logout") === "1") return false;
    if (!hasValidSession()) return false;
    window.location.replace(DASHBOARD_URL);
    return true;
}

const handingOff = forwardExistingSession();

window.addEventListener("DOMContentLoaded", () => {
    if (handingOff) {
        return;
    }

    const loggedOut = handleLogoutRequest();

    setupPasswordToggle();
    setupSignupLink();
    setupThemeSwitch();

    const loginForm = document.getElementById("loginForm");

    if (!loginForm) {
        return;
    }

    loginForm.addEventListener("submit", event => {
        event.preventDefault();
        login();
    });

    document.getElementById("reactivateForm")?.addEventListener("submit", event => {
        event.preventDefault();
        reactivate();
    });

    document.getElementById("reactivateResendLink")?.addEventListener("click", event => {
        event.preventDefault();
        sendReactivationCode();
    });

    if (loggedOut) {
        document.getElementById("username")?.focus();
    }
});
