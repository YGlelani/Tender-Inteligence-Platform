/** Shared HTML escaping helpers used by page modules. */
export function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, character => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  })[character]);
}

export const escapeHtml = esc;

/*
  Tenders keep their scraped status (for example "Open") after they close, so
  pages ask the API for tenders closing from now on and drop any stale ones
  that still come back.
*/
const pad = number => String(number).padStart(2, "0");

/** The current local time as "YYYY-MM-DD HH:MM:SS", the format the API stores. */
export function closingAfterNow() {
  const now = new Date();
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ` +
    `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
}

/** True only when the closing date is readable and already in the past. */
export function hasClosingDatePassed(value) {
  if (!value) return false;
  let text = String(value).trim();
  // A date with no time closes at the end of that day.
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) text += "T23:59:59";
  else if (/^\d{4}-\d{2}-\d{2} \d/.test(text)) text = text.replace(" ", "T");
  const date = new Date(text);
  return !Number.isNaN(date.getTime()) && date.getTime() < Date.now();
}
