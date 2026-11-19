// window.APP_CONFIG comes from scripts/runtime-config.js, which the container writes at
// start-up (docker-entrypoint.d/40-runtime-config.sh). Production sets nothing there,
// so the visitor's host name and the production ports below stay in force.
const RUNTIME_CONFIG = window.APP_CONFIG || {};
const USER_SERVER_IP = RUNTIME_CONFIG.USER_SERVER_IP || window.location.hostname;
const SERVER_ORIGIN = `http://${USER_SERVER_IP}`;

export const CONFIG = {
    serverIp: USER_SERVER_IP,
    services: {
        scraper: `${SERVER_ORIGIN}:8000`,
        client: `${SERVER_ORIGIN}:8001`,
        cache: `${SERVER_ORIGIN}:8003`,
        login: `${SERVER_ORIGIN}:8006`,
        signup: `${SERVER_ORIGIN}:8007`,
        businessProfile: `${SERVER_ORIGIN}:9005`,
        loginFrontend: `${SERVER_ORIGIN}:8009/login.html`,
        signupFrontend: `${SERVER_ORIGIN}:8008/`,
        dashboard: `${window.location.origin}/dashboard.html`,
        alerts: `${SERVER_ORIGIN}:9005`,
        savedTenders: `${SERVER_ORIGIN}:9007`,
        applicationTracker: `${SERVER_ORIGIN}:9007`,
        notifications: `${SERVER_ORIGIN}:9007`,
        tenderSearch: `${SERVER_ORIGIN}:8001`,
        overview: `${SERVER_ORIGIN}:8001`,
        aiAssistant: `${SERVER_ORIGIN}:9001/index.html`,
        aiAgent: `${SERVER_ORIGIN}:9000`,
        tenderAgent: `${SERVER_ORIGIN}:9000`
    },
    endpoints: {
        scraperHealth: "/health",
        scraperDeepHealth: "/health/deep",
        scraperStats: "/stats",
        scrape: "/scrape",
        scrapeAndSave: "/scrape-and-save",
        scrapingLogs: "/scraping-logs",
        scrapingLog: id => `/scraping-logs/${encodeURIComponent(id)}`,
        tenders: "/tenders",
        tenderSearch: "/tenders/search",
        tender: number => `/tenders/${encodeURIComponent(number)}`,
        tenderDetail: number => `/tenders/${encodeURIComponent(number)}`,
        clientStats: "/stats",
        clientHealth: "/health",
        cachedTenders: "/cache/tenders",
        cachedSearch: "/cache/tenders/search",
        cachedTender: number => `/cache/tenders/${encodeURIComponent(number)}`,
        cachedStats: "/cache/stats",
        cacheStats: "/cache/stats-cache",
        cacheClear: "/cache/clear",
        cacheHealth: "/health",
        aiAgentHealth: "/health",
        aiAgentChat: "/agent/chat",
        aiAgentUploadProfile: "/agent/upload-profile-direct",
        aiAgentBidStrategy: "/agent/bid-strategy-direct",
        agentOverview: "/agent/overview",
        agentOverviewRefresh: "/agent/overview/refresh",
        onboardingCatalogue: "/agent/onboarding/catalogue",
        onboardingProfile: "/agent/onboarding/profile",
        onboardingDocuments: "/agent/onboarding/documents",
        onboardingDocument: id => `/agent/onboarding/documents/${encodeURIComponent(id)}`,
        onboardingDocumentReprocess: id => `/agent/onboarding/documents/${encodeURIComponent(id)}/reprocess`,
        onboardingDocumentFile: id => `/agent/onboarding/documents/${encodeURIComponent(id)}/file`,
        signup: "/signup",
        signupHealth: "/health",
        userProfile: "/user/profile",
        userAccount: "/user/account",
        userDeactivate: "/user/deactivate",
        changePassword: "/change-password",
        businessProfileHealth: "/health",
        businessProfile: "/profile",
        businessProfileRefresh: "/profile/refresh",
        alertProfile: "/profile",
        alertMatches: "/matches",
        notifications: "/notifications",
        unreadNotifications: "/notifications/unread-count",
        notificationRead: id => `/notifications/${encodeURIComponent(id)}/read`,
        savedTenders: "/api/saved-tenders",
        savedTenderNotes: id => `/api/saved-tenders/${encodeURIComponent(id)}`,
        applications: "/api/applications",
        application: id => `/api/applications/${encodeURIComponent(id)}`,
        applicationStats: "/api/applications/stats",
        applicationHealth: "/health",
        bellNotifications: "/notifications",
        bellUnreadCount: "/notifications/unread-count",
        bellNotificationRead: id => `/notifications/${encodeURIComponent(id)}/read`,
        bellReadAll: "/notifications/read-all",
        notificationPreferences: "/notification-preferences"
    },
    refreshIntervals: { kpis: 30000, scrapeStatus: 15000 },
    requestTimeout: 15000
};

// Staging publishes the same services on other ports (for example 18001 instead of 8001).
// RUNTIME_CONFIG.PORTS maps a service name above to its port; only the port changes.
for (const [name, port] of Object.entries(RUNTIME_CONFIG.PORTS || {})) {
    if (name !== "dashboard" && typeof CONFIG.services[name] === "string" && /^\d{1,5}$/.test(String(port))) {
        CONFIG.services[name] = CONFIG.services[name].replace(/^(https?:\/\/[^/]+?):\d+/, `$1:${port}`);
    }
}
