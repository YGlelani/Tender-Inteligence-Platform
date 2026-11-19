// Shared by the landing page (index.html) and the login page (login.html):
// is this browser still logged in? True when a login is saved, its token has
// not expired, and there has been activity within the session length.
function hasValidSession() {
    const token = localStorage.getItem("access_token");
    if (!token) return false;

    try {
        const part = token.split(".")[1];
        const base64 = part.replace(/-/g, "+").replace(/_/g, "/")
            .padEnd(Math.ceil(part.length / 4) * 4, "=");
        const payload = JSON.parse(atob(base64));
        if (payload.exp && payload.exp * 1000 <= Date.now()) return false;
    } catch {
        return false;
    }

    const hours = Number(localStorage.getItem("session_timeout_hours")) || 2;
    const lastActivity = Number(localStorage.getItem("last_activity_at")) || 0;
    return Date.now() - lastActivity < hours * 60 * 60 * 1000;
}
