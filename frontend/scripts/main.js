import { CONFIG } from "./config.js";
import { refreshOverview } from "./overview.js";
import { getUsername, clearSession, redirectToLogin } from "./shared-utils.js";


function getAccessToken() {
    return localStorage.getItem("access_token");
}


function setupUser() {
    const username =
        getUsername();

    const userElements =
        document.querySelectorAll(
            "#currentUser, .current-user, [data-current-user]"
        );

    userElements.forEach(
        element => {
            element.textContent =
                username;
        }
    );

    const avatarElements =
        document.querySelectorAll(
            "#userAvatar, .user-avatar, [data-user-avatar]"
        );

    avatarElements.forEach(
        element => {
            element.textContent =
                username
                    .trim()
                    .charAt(0)
                    .toUpperCase() ||
                "U";
        }
    );
}





function setupRefresh() {
    const button =
        document.getElementById(
            "refreshOverview"
        );

    if (!button) {
        return;
    }

    button.addEventListener(
        "click",
        async () => {
            const originalText =
                button.innerHTML;

            button.disabled = true;

            button.textContent =
                "Refreshing...";

            try {
                await refreshOverview();
            } catch (error) {
                console.error(
                    "Dashboard refresh failed:",
                    error
                );
            } finally {
                button.disabled = false;

                button.innerHTML =
                    originalText;
            }
        }
    );
}


function setupTenderDetailsLink() {
    const link =
        document.getElementById(
            "tenderDetailsLink"
        );

    if (!link) {
        return;
    }

    const tenderNumber =
        localStorage.getItem(
            "last_tender"
        );

    link.href =
        tenderNumber
            ? "./tender.html?number=" +
              encodeURIComponent(tenderNumber)
            : "./feed.html";
}


function protectDashboard() {
    if (getAccessToken()) {
        return true;
    }

    redirectToLogin();

    return false;
}


function setupNavigationProtection() {
    document.addEventListener(
        "click",
        event => {
            const link =
                event.target.closest("a");

            if (!link) {
                return;
            }

            const href =
                link.getAttribute("href");

            if (!href) {
                return;
            }

            if (
                href.startsWith("#") ||
                href.startsWith("http://") ||
                href.startsWith("https://") ||
                href.startsWith("mailto:")
            ) {
                return;
            }

            if (!getAccessToken()) {
                event.preventDefault();

                redirectToLogin();
            }
        }
    );
}


function setupSessionProtection() {
    window.addEventListener(
        "pageshow",
        () => {
            if (!getAccessToken()) {
                redirectToLogin();
            }
        }
    );

    window.addEventListener(
        "storage",
        event => {
            if (
                event.key ===
                    "access_token" &&
                !event.newValue
            ) {
                redirectToLogin();
            }
        }
    );
}


async function startDashboard() {
    /*
     * Never load dashboard data before
     * authentication has been established.
     */
    if (!protectDashboard()) {
        return;
    }

    setupUser();

    setupRefresh();
    setupTenderDetailsLink();
    setupNavigationProtection();
    setupSessionProtection();

    try {
        await refreshOverview();
    } catch (error) {
        console.error(
            "Unable to load dashboard:",
            error
        );
    }

    window.refreshOverview =
        refreshOverview;
}


startDashboard();
