import { CONFIG } from "./config.js";

/** Shared session helpers for Tender Scrapper pages. */
export function getUsername() {
  const stored = localStorage.getItem("username");
  if (stored) return stored;
  const rawUser = localStorage.getItem("user");
  if (!rawUser) return "User";
  try {
    const parsed = JSON.parse(rawUser);
    if (typeof parsed === "string") return parsed;
    return parsed?.username || parsed?.name || parsed?.email || "User";
  } catch {
    return rawUser;
  }
}

export function clearSession() {
  [
    "access_token", "token_type", "username", "user", "last_tender",
    "session_timeout_hours", "last_activity_at"
  ].forEach(key => localStorage.removeItem(key));
  sessionStorage.clear();
}

export function redirectToLogin(loggedOut = false) {
  const loginUrl = new URL(CONFIG.services.loginFrontend, window.location.href);
  loginUrl.search = loggedOut ? "?logout=1" : "";
  loginUrl.hash = "";
  window.location.replace(loginUrl.href);
}
