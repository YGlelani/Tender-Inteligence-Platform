import { CONFIG } from "./config.js";


function queryString(params = {}) {
    const entries =
        Object.entries(params)
            .filter(
                ([, value]) =>
                    value !== undefined &&
                    value !== null &&
                    value !== ""
            );

    if (!entries.length) {
        return "";
    }

    return "?" +
        entries
            .map(
                ([key, value]) =>
                    `${encodeURIComponent(key)}=${encodeURIComponent(value)}`
            )
            .join("&");
}


function authHeaders() {
    const token =
        localStorage.getItem("access_token");

    if (!token) {
        return {};
    }

    return {
        Authorization: `Bearer ${token}`
    };
}


function clearAuthentication() {
    localStorage.removeItem("access_token");
    localStorage.removeItem("token_type");
    localStorage.removeItem("username");
    localStorage.removeItem("user");
    localStorage.removeItem("last_tender");
    // Without these, the next login would inherit a stale inactivity clock.
    localStorage.removeItem("session_timeout_hours");
    localStorage.removeItem("last_activity_at");
    sessionStorage.clear();
}


function redirectToLogin(clearLoginSession = false) {
    const loginUrl =
        CONFIG.services.loginFrontend +
        (clearLoginSession ? "?logout=1" : "");

    window.location.replace(
        loginUrl
    );
}


export async function request(
    baseUrl,
    path,
    options = {}
) {
    if (!baseUrl) {
        throw new Error("API base URL is not configured.");
    }

    if (!path) {
        throw new Error("API endpoint is not configured.");
    }

    const controller =
        new AbortController();

    const timeout =
        setTimeout(
            () => controller.abort(),
            CONFIG.requestTimeout
        );

    // authRedirect: false keeps the user signed in when a secondary service
    // (e.g. the AI agent) rejects the token; the caller handles the error.
    const { authRedirect = true, ...fetchOptions } = options;

    try {
        const headers = {
            Accept: "application/json",
            ...authHeaders(),
            ...(fetchOptions.headers || {})
        };

        let requestOptions = {
            ...fetchOptions,
            headers,
            signal:
                options.signal ||
                controller.signal
        };

        if (
            requestOptions.body &&
            typeof requestOptions.body !== "string" &&
            !(requestOptions.body instanceof FormData)
        ) {
            headers["Content-Type"] =
                "application/json";

            requestOptions = {
                ...requestOptions,
                body:
                    JSON.stringify(
                        requestOptions.body
                    )
            };
        }

        const response =
            await fetch(
                `${baseUrl}${path}`,
                requestOptions
            );

        if (response.status === 401 && authRedirect) {
            const hasSession = Boolean(localStorage.getItem("access_token"));
            if (hasSession) {
                clearAuthentication();
                redirectToLogin(true);
                throw new Error("Session expired. Please log in again.");
            }
        }

        if (!response.ok) {
            let detail = "";
            try {
                const body = await response.clone().json();
                detail = body?.detail || body?.message || body?.error || "";
            } catch {
                try { detail = (await response.clone().text()).slice(0, 300); } catch {}
            }
            const detailText = Array.isArray(detail)
                ? detail.map(item => item?.msg || String(item)).join("; ")
                : String(detail || "");
            const suffix = detailText ? ": " + detailText : "";
            const error = new Error(response.status + " " + response.statusText + " @ " + path + suffix);
            error.status = response.status;
            error.detail = detail;
            throw error;
        }

        if (response.status === 204) {
            return null;
        }

        const text =
            await response.text();

        if (!text) {
            return null;
        }

        try {
            return JSON.parse(text);
        } catch {
            return text;
        }

    } catch (error) {
        if (error.name === "AbortError") {
            throw new Error(
                "The request timed out. Please try again."
            );
        }

        throw error;

    } finally {
        clearTimeout(timeout);
    }
}


/* SCRAPER API */

export const scraperApi = {
    health:
        () =>
            request(
                CONFIG.services.scraper,
                CONFIG.endpoints.scraperHealth
            ),

    deepHealth:
        () =>
            request(
                CONFIG.services.scraper,
                CONFIG.endpoints.scraperDeepHealth
            ),

    stats:
        () =>
            request(
                CONFIG.services.scraper,
                CONFIG.endpoints.scraperStats
            ),

    scrape:
        payload =>
            request(
                CONFIG.services.scraper,
                CONFIG.endpoints.scrape,
                {
                    method: "POST",
                    body: payload
                }
            ),

    scrapeAndSave:
        () =>
            request(
                CONFIG.services.scraper,
                CONFIG.endpoints.scrapeAndSave
            ),

    logs:
        params =>
            request(
                CONFIG.services.scraper,
                CONFIG.endpoints.scrapingLogs +
                queryString(params)
            ),

    log:
        id =>
            request(
                CONFIG.services.scraper,
                CONFIG.endpoints.scrapingLog(id)
            )
};


/* CLIENT API */

export const clientApi = {
    health:
        () =>
            request(
                CONFIG.services.client,
                CONFIG.endpoints.clientHealth
            ),

    stats:
        () =>
            request(
                CONFIG.services.client,
                CONFIG.endpoints.clientStats
            ),

    list:
        params =>
            request(
                CONFIG.services.client,
                CONFIG.endpoints.tenders +
                queryString(params)
            ),

    search:
        (q, params = {}) =>
            request(
                CONFIG.services.client,
                CONFIG.endpoints.tenderSearch +
                queryString({
                    q,
                    ...params
                })
            ),

    detail:
        number =>
            request(
                CONFIG.services.client,
                CONFIG.endpoints.tender(number)
            )
};


/* SEARCH TENDER API (client API, port 8001) */

// Hides tenders whose closing date has passed unless include_closed is true.
// Each tender includes its database id, which Saved Tenders needs.
export const tenderSearchApi = {
    search:
        params =>
            request(
                CONFIG.services.tenderSearch,
                CONFIG.endpoints.tenderSearch +
                queryString(params)
            )
};


/* OVERVIEW API (client API, port 8001) */

// The dashboard's numbers. Open and closing counts use each tender's closing
// time, and volume counts every tender published per day.
export const overviewApi = {
    stats:
        () =>
            request(
                CONFIG.services.overview,
                "/overview/stats",
                { authRedirect: false }
            ),

    volume:
        days =>
            request(
                CONFIG.services.overview,
                "/overview/volume" +
                queryString({ days }),
                { authRedirect: false }
            )
};


/* CACHE API */

export const cacheApi = {
    health:
        () =>
            request(
                CONFIG.services.cache,
                CONFIG.endpoints.cacheHealth
            ),

    stats:
        () =>
            request(
                CONFIG.services.cache,
                CONFIG.endpoints.cachedStats
            ),

    cacheStats:
        () =>
            request(
                CONFIG.services.cache,
                CONFIG.endpoints.cacheStats
            ),

    tenders:
        params =>
            request(
                CONFIG.services.cache,
                CONFIG.endpoints.cachedTenders +
                queryString(params)
            ),

    search:
        (q, params = {}) =>
            request(
                CONFIG.services.cache,
                CONFIG.endpoints.cachedSearch +
                queryString({
                    q,
                    ...params
                })
            ),

    tender:
        number =>
            request(
                CONFIG.services.cache,
                CONFIG.endpoints.cachedTender(number)
            ),

    clear:
        () =>
            request(
                CONFIG.services.cache,
                CONFIG.endpoints.cacheClear,
                {
                    method: "POST"
                }
            )
};


/* SIGNUP API */

export const authApi = {
    health:
        () =>
            request(
                CONFIG.services.signup,
                CONFIG.endpoints.signupHealth
            ),

    signup:
        payload =>
            request(
                CONFIG.services.signup,
                CONFIG.endpoints.signup,
                {
                    method: "POST",
                    body: payload
                }
            ),

    userProfile: () => request(CONFIG.services.signup, CONFIG.endpoints.userProfile),

    updateUserProfile: payload => request(CONFIG.services.signup, CONFIG.endpoints.userProfile, {
        method: "PUT",
        body: payload
    }),

    // Permanently deletes the signed-in account (Signup API). A wrong password answers 403.
    deleteAccount: password => request(CONFIG.services.signup, CONFIG.endpoints.userAccount, {
        method: "DELETE",
        body: { password }
    }),

    // Switches the signed-in account off until the user signs in again (Signup API).
    // Answers { deactivated, delete_on }. A wrong password answers 403.
    deactivateAccount: password => request(CONFIG.services.signup, CONFIG.endpoints.userDeactivate, {
        method: "POST",
        body: { password }
    }),

    changePassword: (currentPassword, newPassword) => request(CONFIG.services.login, CONFIG.endpoints.changePassword, {
        method: "POST",
        body: { current_password: currentPassword, new_password: newPassword }
    })
};

/* BUSINESS PROFILE API */

export const businessProfileApi = {
    health:
        () =>
            request(
                CONFIG.services.businessProfile,
                CONFIG.endpoints.businessProfileHealth
            ),

    get:
        () =>
            request(
                CONFIG.services.businessProfile,
                CONFIG.endpoints.businessProfile
            ),

    // The company profile is built from the user's business documents; it cannot be typed.
    refresh:
        () =>
            request(
                CONFIG.services.businessProfile,
                CONFIG.endpoints.businessProfileRefresh,
                { method: "POST" }
            )
};


/* SMART TENDER ALERTS API */

export const alertsApi = {
    profile:
        () =>
            request(
                CONFIG.services.alerts,
                CONFIG.endpoints.alertProfile
            ),

    matches:
        () =>
            request(
                CONFIG.services.alerts,
                CONFIG.endpoints.alertMatches
            ),

    notifications:
        (limit = 50, unreadOnly = false) =>
            request(
                CONFIG.services.alerts,
                CONFIG.endpoints.notifications +
                queryString({
                    limit,
                    unread_only: unreadOnly
                })
            ),

    unreadCount:
        () =>
            request(
                CONFIG.services.alerts,
                CONFIG.endpoints.unreadNotifications
            ),

    markNotificationRead:
        id =>
            request(
                CONFIG.services.alerts,
                CONFIG.endpoints.notificationRead(id),
                {
                    method: "POST"
                }
            )
};


export const aiAgentApi = {
    health: () =>
        request(CONFIG.services.aiAgent, CONFIG.endpoints.aiAgentHealth),

    chat: payload =>
        request(CONFIG.services.aiAgent, CONFIG.endpoints.aiAgentChat, {
            method: "POST",
            body: payload
        }),

    uploadProfile: payload =>
        request(CONFIG.services.aiAgent, CONFIG.endpoints.aiAgentUploadProfile, {
            method: "POST",
            body: payload
        }),

    bidStrategy: payload =>
        request(CONFIG.services.aiAgent, CONFIG.endpoints.aiAgentBidStrategy, {
            method: "POST",
            body: payload
        })
};


/* ONBOARDING + READINESS (tender AI agent) */

// The agent is a secondary service: if it rejects a token (e.g. a JWT_SECRET
// mismatch) that must not sign the user out of the whole app.
const agentRequest = (path, options = {}) =>
    request(CONFIG.services.tenderAgent, path, { ...options, authRedirect: false });

export const onboardingApi = {
    overview: () =>
        agentRequest(CONFIG.endpoints.agentOverview),

    refresh: () =>
        agentRequest(CONFIG.endpoints.agentOverviewRefresh, { method: "POST" }),

    uploadProfile: ({ file, website }) => {
        const form = new FormData();
        if (file) form.append("file", file);
        if (website) form.append("website", website);
        return agentRequest(CONFIG.endpoints.onboardingProfile, {
            method: "POST",
            body: form
        });
    },

    uploadDocument: (docType, file) => {
        const form = new FormData();
        form.append("doc_type", docType);
        form.append("file", file);
        return agentRequest(CONFIG.endpoints.onboardingDocuments, {
            method: "POST",
            body: form
        });
    },

    deleteDocument: id =>
        agentRequest(CONFIG.endpoints.onboardingDocument(id), { method: "DELETE" }),

    reprocessDocument: id =>
        agentRequest(CONFIG.endpoints.onboardingDocumentReprocess(id), { method: "POST" }),

    documentFileUrl: id =>
        CONFIG.services.tenderAgent + CONFIG.endpoints.onboardingDocumentFile(id)
};


/* SAVED TENDERS API */

export const savedTendersApi = {
    list: () => request(CONFIG.services.savedTenders, CONFIG.endpoints.savedTenders),
    save: payload => request(CONFIG.services.savedTenders, CONFIG.endpoints.savedTenders, {
        method: "POST",
        body: payload
    }),
    updateNotes: (tenderId, notes) => request(
        CONFIG.services.savedTenders,
        CONFIG.endpoints.savedTenderNotes(tenderId),
        { method: "PATCH", body: { notes } }
    ),
    remove: tenderId => request(
        CONFIG.services.savedTenders,
        CONFIG.endpoints.savedTenderNotes(tenderId),
        { method: "DELETE" }
    )
};


/* NOTIFICATIONS API (top-bar bell) */

// Secondary service: a failure here must not sign the user out.
const bellRequest = (path, options = {}) =>
    request(CONFIG.services.notifications, path, { ...options, authRedirect: false });

export const notificationsApi = {
    list: (limit = 20, unreadOnly = false) =>
        bellRequest(CONFIG.endpoints.bellNotifications + queryString({ limit, unread_only: unreadOnly })),
    unreadCount: () => bellRequest(CONFIG.endpoints.bellUnreadCount),
    markRead: id => bellRequest(CONFIG.endpoints.bellNotificationRead(id), { method: "POST" }),
    markAllRead: () => bellRequest(CONFIG.endpoints.bellReadAll, { method: "POST" }),
    preferences: () => bellRequest(CONFIG.endpoints.notificationPreferences),
    updatePreferences: preferences => bellRequest(CONFIG.endpoints.notificationPreferences, {
        method: "PUT",
        body: { preferences }
    })
};


/* TENDER APPLICATION TRACKER API */

export const applicationTrackerApi = {
    health: () => request(CONFIG.services.applicationTracker, CONFIG.endpoints.applicationHealth),
    list: params => request(CONFIG.services.applicationTracker, CONFIG.endpoints.applications + queryString(params)),
    stats: () => request(CONFIG.services.applicationTracker, CONFIG.endpoints.applicationStats),
    create: payload => request(CONFIG.services.applicationTracker, CONFIG.endpoints.applications, { method: "POST", body: payload }),
    update: (id, payload) => request(CONFIG.services.applicationTracker, CONFIG.endpoints.application(id), { method: "PATCH", body: payload }),
    remove: id => request(CONFIG.services.applicationTracker, CONFIG.endpoints.application(id), { method: "DELETE" })
};
