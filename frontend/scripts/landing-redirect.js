// A returning user who is still signed in goes straight to the dashboard.
// hasValidSession() comes from session-check.js, loaded just before this file.
if (hasValidSession()) {
    window.location.replace("./dashboard.html");
}
