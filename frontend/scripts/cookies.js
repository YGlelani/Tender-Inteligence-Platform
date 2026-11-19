import { icon } from "./icons.js";
const CONSENT_COOKIE = "tender_scrapper_cookie_consent_v5";
const LEGACY_CONSENT_COOKIE = "tender_scrapper_cookie_consent";
const CONSENT_VERSION = 5;
const CONSENT_MAX_AGE = 60 * 60 * 24 * 180;

const COOKIE_POLICY_URL = "./cookies.html";

const CATEGORY_DEFINITIONS = {
    necessary: {
        label: "Necessary",
        description: "Keep you signed in, sign you out after a period of inactivity and remember your cookie choice.",
        required: true
    },
    functional: {
        label: "Functional",
        description: "Remember settings you choose yourself, such as light or dark mode. Saved only when you make the choice and never sent to us.",
        required: true
    },
    analytics: {
        label: "Analytics",
        description: "Not used. Tender Scrapper has no analytics or advertising service. If that changes, we will ask you first.",
        required: false
    }
};

// Everything this site stores in your browser. Keep in step with cookies.html.
const STORAGE_INVENTORY = [
    { name: CONSENT_COOKIE, type: "Cookie", category: "Necessary", purpose: "Your cookie choice.", duration: "180 days" },
    { name: "access_token, token_type", type: "Local storage", category: "Necessary", purpose: "Keeps you signed in.", duration: "Until you log out or the session ends" },
    { name: "session_timeout_hours, last_activity_at", type: "Local storage", category: "Necessary", purpose: "Signs you out after a period of inactivity.", duration: "Until you log out or the session ends" },
    { name: "username, user", type: "Local storage", category: "Necessary", purpose: "Shows your name in the app.", duration: "Until you log out or the session ends" },
    { name: "last_tender", type: "Local storage", category: "Functional", purpose: "Reopens the tender you last viewed.", duration: "Until you log out or the session ends" },
    { name: "onboarding_dismissed", type: "Local storage", category: "Functional", purpose: "Keeps the setup checklist hidden after you close it.", duration: "Until you clear your browser data" },
    { name: "tenderScrapperTheme", type: "Local storage", category: "Functional", purpose: "Light or dark mode, if you pick one.", duration: "Until you clear your browser data" }
];

const DEFAULT_CONSENT = {
    version: CONSENT_VERSION,
    accepted: false,
    categories: {
        necessary: true,
        functional: true,
        analytics: false
    },
    consentedAt: null,
    updatedAt: null,
    expiresAt: null
};

const listeners = new Set();

function readRawCookie(name) {
    if (typeof document === "undefined") {
        return null;
    }

    const prefix = name + "=";

    const match = document.cookie
        .split("; ")
        .find(cookie => cookie.startsWith(prefix));

    if (!match) {
        return null;
    }

    return decodeURIComponent(
        match.slice(prefix.length)
    );
}

function parseConsent(raw) {
    if (!raw) {
        return null;
    }

    try {
        const parsed = JSON.parse(raw);

        return {
            version: Number(parsed.version) || CONSENT_VERSION,
            accepted: parsed.accepted === true,
            categories: {
                necessary: true,
                functional: true,
                analytics: parsed.categories?.analytics === true
            },
            consentedAt: parsed.consentedAt || null,
            updatedAt: parsed.updatedAt || null,
            expiresAt: parsed.expiresAt || null
        };
    } catch {
        return null;
    }
}

function migrateLegacyConsent() {
    const legacy = parseConsent(
        readRawCookie(LEGACY_CONSENT_COOKIE)
    );

    if (!legacy || !legacy.accepted) {
        return null;
    }

    return saveConsentState(
        legacy.categories,
        {
            preserveTimestamps: true
        }
    );
}

function getConsentState() {
    const current = parseConsent(
        readRawCookie(CONSENT_COOKIE)
    );

    if (current) {
        if (
            current.expiresAt &&
            new Date(current.expiresAt).getTime() <= Date.now()
        ) {
            clearConsentCookie();
            return {
                ...DEFAULT_CONSENT,
                categories: {
                    ...DEFAULT_CONSENT.categories
                }
            };
        }

        return current;
    }

    const migrated = migrateLegacyConsent();

    if (migrated) {
        return migrated;
    }

    return {
        ...DEFAULT_CONSENT,
        categories: {
            ...DEFAULT_CONSENT.categories
        }
    };
}

function writeConsentCookie(state) {
    if (typeof document === "undefined") {
        return;
    }

    const encoded = encodeURIComponent(
        JSON.stringify(state)
    );

    const secure = window.location.protocol === "https:"
        ? "; Secure"
        : "";

    document.cookie =
        CONSENT_COOKIE +
        "=" +
        encoded +
        "; Max-Age=" +
        CONSENT_MAX_AGE +
        "; Path=/; SameSite=Lax" +
        secure;
}

function clearConsentCookie() {
    if (typeof document === "undefined") {
        return;
    }

    document.cookie =
        CONSENT_COOKIE +
        "=; Max-Age=0; Path=/; SameSite=Lax";

    document.cookie =
        LEGACY_CONSENT_COOKIE +
        "=; Max-Age=0; Path=/; SameSite=Lax";
}

function notifyListeners(state) {
    listeners.forEach(listener => {
        try {
            listener(state);
        } catch (error) {
            console.error(
                "Cookie consent listener failed:",
                error
            );
        }
    });

    window.dispatchEvent(
        new CustomEvent(
            "tenderScrapperCookieConsent",
            {
                detail: state
            }
        )
    );
}

function saveConsentState(
    categories = DEFAULT_CONSENT.categories,
    options = {}
) {
    const now = new Date();
    const existing = getConsentState();

    const consentedAt =
        options.preserveTimestamps &&
        existing.consentedAt
            ? existing.consentedAt
            : now.toISOString();

    const state = {
        version: CONSENT_VERSION,
        accepted: true,
        categories: {
            necessary: true,
            functional: true,
            analytics: Boolean(
                categories.analytics
            )
        },
        consentedAt,
        updatedAt: now.toISOString(),
        expiresAt: new Date(
            now.getTime() +
            CONSENT_MAX_AGE * 1000
        ).toISOString()
    };

    writeConsentCookie(state);
    notifyListeners(state);

    return state;
}

// No analytics service exists, so accepting turns nothing extra on.
function acceptAllCookies() {
    return saveConsentState({
        analytics: false
    });
}

function rejectOptionalCookies() {
    return saveConsentState({
        analytics: false
    });
}

function saveSelectedCookies() {
    const analytics =
        document.getElementById(
            "cookieAnalyticsCheckbox"
        );

    return saveConsentState({
        analytics: analytics?.checked === true
    });
}

function hasConsentDecision() {
    return getConsentState().accepted === true;
}

function hasCategoryConsent(category) {
    const state = getConsentState();

    return (
        category in CATEGORY_DEFINITIONS &&
        state.categories[category] === true
    );
}

function onConsentChange(listener) {
    listeners.add(listener);

    return () => {
        listeners.delete(listener);
    };
}

function formatConsentDate(value) {
    if (!value) {
        return "Not recorded";
    }

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
        return "Not recorded";
    }

    return new Intl.DateTimeFormat(
        undefined,
        {
            dateStyle: "medium",
            timeStyle: "short"
        }
    ).format(date);
}

function createElement(tag, className, text) {
    const element =
        document.createElement(tag);

    if (className) {
        element.className = className;
    }

    if (text !== undefined) {
        element.textContent = text;
    }

    return element;
}

function removeConsentUI() {
    [
        "tenderCookieConsent",
        "tenderCookieSettings",
        "tenderCookieSettingsButton"
    ].forEach(id => {
        const element =
            document.getElementById(id);

        if (element) {
            element.remove();
        }
    });
}

function createSettingsButton() {
    if (
        document.getElementById(
            "tenderCookieSettingsButton"
        )
    ) {
        return;
    }

    const button =
        createElement(
            "button",
            "cookie-settings-launcher"
        );

    button.id =
        "tenderCookieSettingsButton";

    button.type = "button";

    button.innerHTML = '<span class="cookie-settings-icon" aria-hidden="true">' + icon("cookie") + '</span><span class="cookie-settings-label">Cookie preferences</span>';

    button.addEventListener(
        "click",
        openCookieSettings
    );

    document.body.appendChild(button);
}

function createBanner() {
    if (
        document.getElementById(
            "tenderCookieConsent"
        )
    ) {
        return;
    }

    const wrapper =
        createElement(
            "div",
            "cookie-consent-banner"
        );

    wrapper.id =
        "tenderCookieConsent";

    wrapper.innerHTML = `
        <div
            class="cookie-consent-content"
            role="dialog"
            aria-modal="false"
            aria-labelledby="cookieConsentTitle">

            <div class="cookie-consent-copy">

                <div
                    class="cookie-consent-icon"
                    aria-hidden="true">
                    ${icon("cookie")}
                </div>

                <div class="cookie-consent-text">

                    <p class="cookie-consent-eyebrow">
                        Privacy centre
                    </p>

                    <h2 id="cookieConsentTitle">
                        Your cookie choices matter
                    </h2>

                    <p class="cookie-consent-description">
                        Tender Scrapper only stores what the site needs to work:
                        one cookie for your cookie choice, and browser storage that
                        keeps you signed in and remembers settings you pick, such
                        as light or dark mode. We use no analytics or advertising
                        cookies. <a href="${COOKIE_POLICY_URL}">Cookie Policy</a>
                    </p>

                    <button
                        type="button"
                        class="cookie-consent-details"
                        id="cookieConsentDetailsButton"
                        aria-expanded="false"
                        aria-controls="cookieConsentDetails">
                        View cookie details
                    </button>

                    <div
                        class="cookie-consent-details-panel"
                        id="cookieConsentDetails"
                        hidden>

                        <div class="cookie-consent-detail-row">
                            <div>
                                <strong>Necessary</strong>
                                <span>Always active</span>
                            </div>
                            <em>Required</em>
                        </div>

                        <div class="cookie-consent-detail-row">
                            <div>
                                <strong>Functional</strong>
                                <span>Saved only when you choose a setting</span>
                            </div>
                            <em>Required</em>
                        </div>

                        <div class="cookie-consent-detail-row">
                            <div>
                                <strong>Analytics</strong>
                                <span>Optional</span>
                            </div>
                            <em>Not used</em>
                        </div>

                        <p class="cookie-consent-note">
                            Your consent record is stored in this browser
                            for 180 days and can be changed later.
                        </p>

                    </div>

                </div>

            </div>

            <div class="cookie-consent-actions">

                <button
                    type="button"
                    class="cookie-consent-button cookie-consent-button-secondary"
                    id="cookieManageButton">
                    Manage
                </button>

                <button
                    type="button"
                    class="cookie-consent-button cookie-consent-button-secondary"
                    id="cookieRejectButton">
                    Reject optional
                </button>

                <button
                    type="button"
                    class="cookie-consent-button cookie-consent-button-primary"
                    id="cookieAcceptButton">
                    Accept
                </button>

            </div>

        </div>
    `;

    document.body.appendChild(wrapper);

    const detailsButton =
        document.getElementById(
            "cookieConsentDetailsButton"
        );

    const details =
        document.getElementById(
            "cookieConsentDetails"
        );

    detailsButton.addEventListener(
        "click",
        () => {
            const opening =
                details.hidden;

            details.hidden =
                !opening;

            detailsButton.setAttribute(
                "aria-expanded",
                String(opening)
            );

            detailsButton.textContent =
                opening
                    ? "Hide cookie details"
                    : "View cookie details";
        }
    );

    document.getElementById(
        "cookieAcceptButton"
    ).addEventListener(
        "click",
        () => {
            acceptAllCookies();
            removeConsentUI();
            createSettingsButton();
        }
    );

    document.getElementById(
        "cookieRejectButton"
    ).addEventListener(
        "click",
        () => {
            rejectOptionalCookies();
            removeConsentUI();
            createSettingsButton();
        }
    );

    document.getElementById(
        "cookieManageButton"
    ).addEventListener(
        "click",
        openCookieSettings
    );
}

function renderCategoryRow(
    category,
    state
) {
    const definition =
        CATEGORY_DEFINITIONS[category];

    const enabled =
        state.categories[category];

    const row =
        createElement(
            "div",
            "cookie-settings-category"
        );

    const copy =
        createElement(
            "div",
            "cookie-settings-category-copy"
        );

    const title =
        createElement(
            "div",
            "cookie-settings-category-title"
        );

    const name =
        createElement(
            "strong",
            null,
            definition.label
        );

    const description =
        createElement(
            "p",
            null,
            definition.description
        );

    title.appendChild(name);

    copy.appendChild(title);
    copy.appendChild(description);

    const control =
        createElement(
            "label",
            "cookie-switch"
        );

    const checkbox =
        document.createElement(
            "input"
        );

    checkbox.type = "checkbox";
    checkbox.id =
        "cookie" +
        category.charAt(0).toUpperCase() +
        category.slice(1) +
        "Checkbox";

    checkbox.checked =
        enabled;

    checkbox.disabled =
        definition.required;

    const slider =
        createElement(
            "span",
            "cookie-switch-slider"
        );

    control.appendChild(checkbox);
    control.appendChild(slider);

    const stateLabel =
        createElement(
            "span",
            "cookie-category-state",
            definition.required
                ? "Always on"
                : enabled
                    ? "Enabled"
                    : "Disabled"
        );

    if (!definition.required) {
        checkbox.addEventListener(
            "change",
            () => {
                stateLabel.textContent =
                    checkbox.checked
                        ? "Enabled"
                        : "Disabled";
            }
        );
    }

    row.appendChild(copy);
    row.appendChild(stateLabel);
    row.appendChild(control);

    return row;
}

function createSettingsModal() {
    const state =
        getConsentState();

    const returnFocusTo =
        document.activeElement;

    const overlay =
        createElement(
            "div",
            "cookie-settings-overlay"
        );

    overlay.id =
        "tenderCookieSettings";

    overlay.innerHTML = `
        <section
            class="cookie-settings-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="cookieSettingsTitle">

            <div class="cookie-settings-header">

                <div>
                    <p class="cookie-consent-eyebrow">
                        Privacy centre
                    </p>

                    <h2 id="cookieSettingsTitle">
                        Cookie settings
                    </h2>

                    <p>
                        See what Tender Scrapper stores in your browser and
                        choose which optional categories it may use.
                        <a href="${COOKIE_POLICY_URL}">Read the Cookie Policy</a>
                    </p>
                </div>

                <button
                    type="button"
                    class="cookie-settings-close"
                    id="cookieSettingsClose"
                    aria-label="Close cookie settings">
                    ${icon("x")}
                </button>

            </div>

            <div class="cookie-settings-status">

                <div>
                    <span>Consent status</span>
                    <strong id="cookieSettingsStatus">
                        ${state.accepted ? "Recorded" : "Not recorded"}
                    </strong>
                </div>

                <div>
                    <span>Last updated</span>
                    <strong id="cookieSettingsUpdated">
                        ${formatConsentDate(state.updatedAt)}
                    </strong>
                </div>

                <div>
                    <span>Expires</span>
                    <strong id="cookieSettingsExpires">
                        ${formatConsentDate(state.expiresAt)}
                    </strong>
                </div>

                <div>
                    <span>Policy version</span>
                    <strong>
                        v${CONSENT_VERSION}
                    </strong>
                </div>

            </div>

            <div
                class="cookie-settings-categories"
                id="cookieSettingsCategories">
            </div>

            <div class="cookie-settings-inventory">

                <div class="cookie-settings-inventory-header">
                    <div>
                        <h3>What this site stores</h3>
                        <p>
                            All of it is first-party: it stays in this browser
                            and is never shared with other companies.
                        </p>
                    </div>

                    <span>
                        1 cookie, ${STORAGE_INVENTORY.length - 1} storage items
                    </span>
                </div>

                <div id="cookieInventoryList"></div>

            </div>

            <div class="cookie-settings-warning">
                Tender Scrapper has no analytics service. Turning the
                Analytics switch on does not start any tracking.
            </div>

            <div class="cookie-settings-actions">

                <button
                    type="button"
                    class="cookie-consent-button cookie-consent-button-secondary"
                    id="cookieSettingsReject">
                    Reject optional
                </button>

                <button
                    type="button"
                    class="cookie-consent-button cookie-consent-button-secondary"
                    id="cookieSettingsSave">
                    Save choices
                </button>

                <button
                    type="button"
                    class="cookie-consent-button cookie-consent-button-primary"
                    id="cookieSettingsAcceptAll">
                    Accept
                </button>

            </div>

            <button
                type="button"
                class="cookie-settings-reset"
                id="cookieSettingsReset">
                Reset cookie consent
            </button>

        </section>
    `;

    document.body.appendChild(overlay);

    const categories =
        document.getElementById(
            "cookieSettingsCategories"
        );

    categories.appendChild(
        renderCategoryRow(
            "necessary",
            state
        )
    );

    categories.appendChild(
        renderCategoryRow(
            "functional",
            state
        )
    );

    categories.appendChild(
        renderCategoryRow(
            "analytics",
            state
        )
    );

    const inventory =
        document.getElementById(
            "cookieInventoryList"
        );

    STORAGE_INVENTORY.forEach(item => {
        const row =
            createElement(
                "div",
                "cookie-inventory-item"
            );

        const copy =
            createElement("div");

        copy.appendChild(
            createElement(
                "strong",
                null,
                item.name
            )
        );

        copy.appendChild(
            createElement(
                "span",
                null,
                item.type + " · " + item.category + ". " + item.purpose
            )
        );

        row.appendChild(copy);
        row.appendChild(
            createElement(
                "em",
                null,
                item.duration
            )
        );

        inventory.appendChild(row);
    });

    const modal =
        overlay.querySelector(
            ".cookie-settings-modal"
        );

    // Keep keyboard focus inside the dialog while it is open.
    function handleKeydown(event) {
        if (event.key === "Escape") {
            close();
            return;
        }

        if (event.key !== "Tab") {
            return;
        }

        const focusable = Array.from(
            modal.querySelectorAll(
                "a[href], button:not([disabled]), input:not([disabled])"
            )
        );

        if (!focusable.length) {
            return;
        }

        const first = focusable[0];
        const last = focusable[focusable.length - 1];

        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        }
    }

    function close() {
        document.removeEventListener(
            "keydown",
            handleKeydown
        );

        overlay.remove();

        // Return focus to whatever opened the dialog, if it is still on the page.
        const target =
            returnFocusTo && document.contains(returnFocusTo)
                ? returnFocusTo
                : document.getElementById("tenderCookieSettingsButton");

        if (target) {
            target.focus();
        }
    }

    document.getElementById(
        "cookieSettingsClose"
    ).addEventListener(
        "click",
        close
    );

    overlay.addEventListener(
        "click",
        event => {
            if (event.target === overlay) {
                close();
            }
        }
    );

    document.addEventListener(
        "keydown",
        handleKeydown
    );

    // A choice made here also answers the banner, so remove it too.
    function finish(saveChoice) {
        saveChoice();

        const banner =
            document.getElementById(
                "tenderCookieConsent"
            );

        if (banner) {
            banner.remove();
        }

        createSettingsButton();
        close();
    }

    document.getElementById(
        "cookieSettingsReject"
    ).addEventListener(
        "click",
        () => finish(rejectOptionalCookies)
    );

    document.getElementById(
        "cookieSettingsSave"
    ).addEventListener(
        "click",
        () => finish(saveSelectedCookies)
    );

    document.getElementById(
        "cookieSettingsAcceptAll"
    ).addEventListener(
        "click",
        () => finish(acceptAllCookies)
    );

    document.getElementById(
        "cookieSettingsReset"
    ).addEventListener(
        "click",
        () => {
            clearConsentCookie();

            window.dispatchEvent(
                new CustomEvent(
                    "tenderScrapperCookieConsent",
                    {
                        detail:
                            getConsentState()
                    }
                )
            );

            close();
            removeConsentUI();
            createBanner();

            const manage =
                document.getElementById(
                    "cookieManageButton"
                );

            if (manage) {
                manage.focus();
            }
        }
    );

    const firstChoice =
        document.getElementById(
            "cookieAnalyticsCheckbox"
        );

    if (firstChoice) {
        firstChoice.focus();
    }
}

function openCookieSettings() {
    if (
        document.getElementById(
            "tenderCookieSettings"
        )
    ) {
        return;
    }

    createSettingsModal();
}

function initCookieConsent() {
    const start =
        () => {
            createSettingsButton();

            if (
                hasConsentDecision()
            ) {
                return;
            }

            createBanner();
        };

    if (
        document.readyState ===
        "loading"
    ) {
        document.addEventListener(
            "DOMContentLoaded",
            start,
            {
                once: true
            }
        );
    } else {
        start();
    }
}

export {
    CONSENT_COOKIE,
    CONSENT_VERSION,
    DEFAULT_CONSENT,
    CATEGORY_DEFINITIONS,
    getConsentState,
    hasConsentDecision,
    hasCategoryConsent,
    saveConsentState,
    acceptAllCookies,
    rejectOptionalCookies,
    onConsentChange,
    openCookieSettings
};

initCookieConsent();
