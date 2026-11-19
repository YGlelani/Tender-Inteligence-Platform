import { alertsApi } from "./api.js";
import { setupNotificationBell } from "./notification-bell.js";

import { icon } from "./icons.js";
function getPageKey() {
    const file = window.location.pathname
        .split("/")
        .pop() || "index.html";

    const pageMap = {
        "dashboard.html": "overview",
        "index.html": "overview",
        "": "overview",
        "feed.html": "feed",
        "tender.html": "feed",
        "tender-search.html": "tender-search",
        "saved-tenders.html": "saved-tenders",
        "application-tracker.html": "application-tracker",
        "alerts.html": "alerts",
        "profile.html": "profile",
        "onboarding.html": "onboarding"
    };

    return pageMap[file] || "overview";
}

function setupServerPortLinks() {
    document.querySelectorAll("a[data-server-port]").forEach(link => {
        const port = link.dataset.serverPort;
        const path = link.dataset.serverPath || "/";
        link.href = `http://${window.location.hostname}:${port}${path}`;
        if (port === "9001" && link.dataset.signInHandover !== "true") {
            // The AI workspace is another site, so it cannot read this site's
            // sign-in. Hand the token over after # when the link is used: that
            // part of an address is never sent to a server or written to its logs.
            link.dataset.signInHandover = "true";
            link.addEventListener("click", () => {
                const token = localStorage.getItem("access_token");
                const base = link.href.split("#")[0];
                link.href = token ? `${base}#token=${encodeURIComponent(token)}` : base;
            });
        }
    });
}

function setupActiveNavigation() {
    const currentPage = getPageKey();

    document
        .querySelectorAll(".sidebar-nav .nav-item, .profile-link")
        .forEach(link => {
            const active = link.dataset.page === currentPage;

            link.classList.toggle("active", active);

            if (active) {
                link.setAttribute("aria-current", "page");
            } else {
                link.removeAttribute("aria-current");
            }
        });
}

function closeMobileNavigation() {
    document.body.classList.remove("sidebar-open");

    const toggle = document.getElementById("mobileSidebarToggle");

    if (toggle) {
        toggle.setAttribute("aria-expanded", "false");
    }
}

function openMobileNavigation() {
    document.body.classList.add("sidebar-open");

    const toggle = document.getElementById("mobileSidebarToggle");

    if (toggle) {
        toggle.setAttribute("aria-expanded", "true");
    }

    const closeButton = document.getElementById("mobileSidebarClose");

    if (closeButton) {
        closeButton.focus();
    }
}

function setupMobileNavigation() {
    const toggle = document.getElementById("mobileSidebarToggle");
    const close = document.getElementById("mobileSidebarClose");
    const backdrop = document.getElementById("sidebarBackdrop");
    const sidebarLinks = document.querySelectorAll(
        ".sidebar-nav .nav-item, .profile-link"
    );

    if (toggle) {
        toggle.setAttribute("aria-expanded", "false");

        toggle.addEventListener("click", () => {
            if (document.body.classList.contains("sidebar-open")) {
                closeMobileNavigation();
            } else {
                openMobileNavigation();
            }
        });
    }

    if (close) {
        close.addEventListener("click", closeMobileNavigation);
    }

    if (backdrop) {
        backdrop.addEventListener("click", closeMobileNavigation);
    }

    sidebarLinks.forEach(link => {
        link.addEventListener("click", closeMobileNavigation);
    });

    document.addEventListener("keydown", event => {
        if (event.key === "Escape") {
            const wasOpen = document.body.classList.contains("sidebar-open");
            closeMobileNavigation();

            if (wasOpen && toggle && window.innerWidth <= 650) {
                toggle.focus();
            }
        }
    });

    window.addEventListener("resize", () => {
        if (window.innerWidth > 650) {
            closeMobileNavigation();
        }
    });
}


function setupPersistentTopbar() {
    const existingTopbar = document.getElementById("appTopbar");

    if (existingTopbar) {
        const existingUsername =
            localStorage.getItem("username") ||
            localStorage.getItem("user") ||
            "User";
        const existingInitial = existingUsername.trim().charAt(0).toUpperCase() || "U";
        const usernameElement = existingTopbar.querySelector("#topbarUsername");
        const avatarElement = existingTopbar.querySelector("#topbarAvatar");

        if (usernameElement) usernameElement.textContent = existingUsername;
        if (avatarElement) avatarElement.textContent = existingInitial;

        const menuToggle = existingTopbar.querySelector("#topbarMenuToggle");
        menuToggle?.addEventListener("click", () => {
            const mobileToggle = document.getElementById("mobileSidebarToggle");
            if (mobileToggle) mobileToggle.click();
        });

        return;
    }

    const username =
        localStorage.getItem("username") ||
        localStorage.getItem("user") ||
        "User";

    const initial = username.trim().charAt(0).toUpperCase() || "U";

    const topbar = document.createElement("header");
    topbar.id = "appTopbar";
    topbar.className = "app-topbar";
    topbar.innerHTML = `
        <form class="topbar-search" id="globalTenderSearch" role="search">
            <label class="topbar-search-icon" for="globalSearchInput" aria-hidden="true">${icon("search")}</label>
            <input id="globalSearchInput" name="q" type="search" placeholder="Search tenders, proposals, documents..." autocomplete="off" aria-label="Search tenders, proposals, and documents">
        </form>
        <div class="topbar-actions">
            <a class="topbar-icon-link" href="./alerts.html" aria-label="Open Smart Alerts" title="Smart Alerts">
                ${icon("bell", "topbar-bell-icon")}
                <span class="topbar-notification-dot" aria-hidden="true" hidden></span>
            </a>
            <a class="topbar-user" href="./profile.html">
                <span class="topbar-avatar" id="topbarAvatar" aria-hidden="true">${initial}</span>
                <span class="topbar-username" id="topbarUsername">${escapeTopbarText(username)}</span>
            </a>
        </div>
    `;

    document.body.prepend(topbar);

}

function escapeTopbarText(value) {
    return String(value ?? "").replace(/[&<>"']/g, character => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
    })[character]);
}

function setupThemeToggle() {
    const topbarActions = document.querySelector(".topbar-actions");
    if (!topbarActions) return;

    let button = document.getElementById("themeToggleButton");
    if (!button) {
        button = document.createElement("button");
        button.id = "themeToggleButton";
        button.className = "topbar-theme-toggle";
        button.type = "button";
        const notification = topbarActions.querySelector(".topbar-icon-link");
        if (notification) topbarActions.insertBefore(button, notification);
        else topbarActions.prepend(button);
    }

    const moonIcon = icon("moon", "theme-toggle-icon");
    const sunIcon = icon("sun", "theme-toggle-icon");

    // scripts/theme.js owns the theme for every page; this only draws the button.
    const renderButton = () => {
        const dark = document.documentElement.dataset.theme === "dark";
        button.innerHTML = dark ? sunIcon : moonIcon;
        button.setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");
        button.title = dark ? "Switch to light mode" : "Switch to dark mode";
        button.setAttribute("aria-pressed", String(dark));
    };

    renderButton();

    if (button.dataset.themeBound !== "true") {
        button.dataset.themeBound = "true";
        button.addEventListener("click", () => {
            if (window.tsTheme) {
                window.tsTheme.toggle();
            } else {
                const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
                localStorage.setItem("tenderScrapperTheme", next);
                document.documentElement.dataset.theme = next;
            }
            renderButton();
        });
        // Another tab or the device changed the theme.
        document.addEventListener("tstheme", renderButton);
    }
}
// Tells the Login API this sign-in is over, so the token stops working even if
// it was copied. Other devices stay signed in. The browser forgets the token
// either way, so a slow or unreachable server only delays sign-out by 2 seconds.
function endSignInOnServer() {
    const token = localStorage.getItem("access_token");
    if (!token) return Promise.resolve();
    const request = fetch(`${window.location.protocol}//${window.location.hostname}:8006/logout`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        keepalive: true
    }).catch(() => {});
    return Promise.race([request, new Promise(resolve => window.setTimeout(resolve, 2000))]);
}

function setupSharedLogout() {
    document.querySelectorAll("#logoutButton, .logout-button").forEach(button => {
        if (button.dataset.sharedLogoutBound === "true") {
            return;
        }

        button.dataset.sharedLogoutBound = "true";
        button.addEventListener("click", async event => {
            event.preventDefault();
            event.stopImmediatePropagation();
            if (button.disabled) return;
            button.disabled = true;

            await endSignInOnServer();

            [
                "access_token",
                "token_type",
                "username",
                "user",
                "last_tender",
                "session_timeout_hours",
                "last_activity_at"
            ].forEach(key => localStorage.removeItem(key));

            sessionStorage.clear();
            const loginUrl = new URL(window.location.href);
            loginUrl.protocol = window.location.protocol;
            loginUrl.pathname = "/login.html";
            loginUrl.search = "?logout=1";
            loginUrl.hash = "";
            window.location.replace(loginUrl.href);
        }, true);
    });
}



function setupInactivityTimeout() {
    if (!localStorage.getItem("access_token")) return;

    const configuredHours = Number(localStorage.getItem("session_timeout_hours"));
    const timeoutHours = Number.isFinite(configuredHours) && configuredHours > 0
        ? configuredHours
        : 2;
    const timeoutMs = Math.max(1_000, timeoutHours * 60 * 60 * 1000);
    const persistenceIntervalMs = 5_000;
    let timer = null;
    let lastActivityAt = Number(localStorage.getItem("last_activity_at")) || Date.now();
    let lastPersistedAt = lastActivityAt;

    if (!localStorage.getItem("last_activity_at")) {
        localStorage.setItem("last_activity_at", String(lastActivityAt));
    }

    const clearSession = () => {
        [
            "access_token",
            "token_type",
            "username",
            "user",
            "last_tender",
            "session_timeout_hours",
            "last_activity_at"
        ].forEach(key => localStorage.removeItem(key));
        sessionStorage.clear();
    };

    const redirectToLogin = async () => {
        await endSignInOnServer();
        clearSession();
        const loginUrl = new URL(window.location.href);
        loginUrl.pathname = "/login.html";
        loginUrl.search = "?logout=1&reason=inactive";
        loginUrl.hash = "";
        window.location.replace(loginUrl.href);
    };

    const scheduleCheck = () => {
        if (timer !== null) window.clearTimeout(timer);
        const remaining = timeoutMs - (Date.now() - lastActivityAt);
        if (remaining <= 0) {
            redirectToLogin();
            return;
        }
        timer = window.setTimeout(scheduleCheck, Math.min(remaining, 30_000));
    };

    const recordActivity = () => {
        const now = Date.now();
        lastActivityAt = now;
        if (now - lastPersistedAt >= persistenceIntervalMs) {
            localStorage.setItem("last_activity_at", String(now));
            lastPersistedAt = now;
        }
        scheduleCheck();
    };

    const activityEvents = ["pointerdown", "keydown", "mousemove", "touchstart", "wheel", "scroll", "click"];
    activityEvents.forEach(eventName => {
        document.addEventListener(eventName, recordActivity, { passive: true });
    });

    window.addEventListener("storage", event => {
        if (event.key === "last_activity_at" && event.newValue) {
            const sharedActivityAt = Number(event.newValue);
            if (Number.isFinite(sharedActivityAt) && sharedActivityAt > lastActivityAt) {
                lastActivityAt = sharedActivityAt;
                lastPersistedAt = sharedActivityAt;
                scheduleCheck();
            }
        }

        if (event.key === "access_token" && !event.newValue) {
            if (timer !== null) window.clearTimeout(timer);
        }
    });

    document.addEventListener("visibilitychange", () => {
        if (!document.hidden) scheduleCheck();
    });

    scheduleCheck();
}

function setupAlertsNavigation() {
    const sidebarNav = document.querySelector(".sidebar-nav");
    if (!sidebarNav || sidebarNav.querySelector('[data-page="alerts"]')) return;

    const link = document.createElement("a");
    link.href = "./alerts.html";
    link.className = "nav-item";
    link.dataset.page = "alerts";
    link.innerHTML = '<span class="nav-icon" aria-hidden="true">' + icon("bell-ring") + '</span><span>Smart Alerts</span>'
        + '<span class="nav-alerts-dot" aria-hidden="true" hidden></span>';

    const savedLink = sidebarNav.querySelector('[data-page="saved-tenders"]');
    if (savedLink?.nextSibling) sidebarNav.insertBefore(link, savedLink.nextSibling);
    else sidebarNav.appendChild(link);
}

// Unread tender matches (alerts-api) show as a dot on the sidebar Smart Alerts link.
function setupNotificationIndicator() {
    const indicators = document.querySelectorAll(".nav-alerts-dot");

    if (!indicators.length) {
        return;
    }

    const token = localStorage.getItem("access_token");

    if (!token) {
        indicators.forEach(indicator => {
            indicator.hidden = true;
        });
        return;
    }

    const refreshUnreadIndicator = async () => {
        try {
            const result = await alertsApi.unreadCount();
            const unread = Number(result?.unread ?? result?.unread_count ?? result?.count ?? 0);
            const hasUnread = Number.isFinite(unread) && unread > 0;

            indicators.forEach(indicator => {
                indicator.hidden = !hasUnread;
                indicator.setAttribute(
                    "aria-label",
                    hasUnread ? "You have unread notifications" : "No unread notifications"
                );
            });
        } catch (error) {
            console.warn("Could not refresh notification indicator:", error);
        }
    };

    refreshUnreadIndicator();
    window.setInterval(refreshUnreadIndicator, 60000);
}


function setupApplicationTrackerNavigation() {
    const sidebarNav = document.querySelector(".sidebar-nav");
    if (!sidebarNav || sidebarNav.querySelector('[data-page="application-tracker"]')) return;

    const link = document.createElement("a");
    link.href = "./application-tracker.html";
    link.className = "nav-item";
    link.dataset.page = "application-tracker";
    link.innerHTML = '<span class="nav-icon" aria-hidden="true">' + icon("clipboard-list") + '</span><span>Application Tracker</span>';

    const savedLink = sidebarNav.querySelector('[data-page="saved-tenders"]');
    if (savedLink?.nextSibling) sidebarNav.insertBefore(link, savedLink.nextSibling);
    else sidebarNav.appendChild(link);
}

function setupDocumentsNavigation() {
    const sidebarNav = document.querySelector(".sidebar-nav");
    if (!sidebarNav || sidebarNav.querySelector('[data-page="onboarding"]')) return;

    const link = document.createElement("a");
    link.href = "./onboarding.html";
    link.className = "nav-item";
    link.dataset.page = "onboarding";
    link.innerHTML = '<span class="nav-icon" aria-hidden="true">' + icon("file-text") + '</span><span>Business Documents</span>';

    const overviewLink = sidebarNav.querySelector('[data-page="overview"]');
    if (overviewLink?.nextSibling) sidebarNav.insertBefore(link, overviewLink.nextSibling);
    else sidebarNav.appendChild(link);
}

function setupAiAssistantNavigation() {
    // Keep the AI Assistant in one shared location on every page with a sidebar.
    document.querySelectorAll(".floating-ai-assistant").forEach(button => button.remove());

    const sidebarNav = document.querySelector(".sidebar-nav");
    if (!sidebarNav || sidebarNav.querySelector(".ai-nav-item")) {
        return;
    }

    const link = document.createElement("a");
    link.href = "#";
    link.className = "nav-item ai-nav-item";
    link.dataset.serverPort = "9001";
    link.dataset.serverPath = "/index.html";
    link.setAttribute("aria-label", "Open AI Assistant");
    link.innerHTML = '<span class="nav-icon" aria-hidden="true">' + icon("sparkles") + '</span><span>AI Assistant</span>';
    sidebarNav.appendChild(link);
}


function setupGlobalTenderSearch() {
    const form = document.getElementById("globalTenderSearch");
    const input = document.getElementById("globalSearchInput");
    if (!form || !input || form.dataset.searchBound === "true") return;
    form.dataset.searchBound = "true";
    form.addEventListener("submit", event => {
        event.preventDefault();
        const query = input.value.trim();
        if (!query) {
            input.focus();
            return;
        }
        const target = new URL("./tender-search.html", window.location.href);
        target.searchParams.set("q", query);
        window.location.assign(target.href);
    });
}

function startNavigation() {
    setupPersistentTopbar();
    setupGlobalTenderSearch();
    setupAiAssistantNavigation();
    setupApplicationTrackerNavigation();
    setupAlertsNavigation();
    setupDocumentsNavigation();
    setupThemeToggle();
    setupSharedLogout();
    setupInactivityTimeout();
    setupNotificationBell();
    setupNotificationIndicator();
    setupServerPortLinks();
    setupActiveNavigation();
    setupMobileNavigation();
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", startNavigation, {
        once: true
    });
} else {
    startNavigation();
}


