import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const dashboardPath = path.join(root, "dashboard.html");
const html = fs.readFileSync(dashboardPath, "utf8");

function fail(message) {
  console.error("Dashboard smoke test failed: " + message);
  process.exitCode = 1;
}
function assert(condition, message) {
  if (!condition) fail(message);
}
function checkCssBraces(file) {
  const source = fs.readFileSync(file, "utf8");
  let depth = 0;
  let inComment = false;
  let quote = "";
  let escaped = false;
  for (let i = 0; i < source.length; i += 1) {
    const char = source[i];
    const next = source[i + 1];
    if (inComment) {
      if (char === "*" && next === "/") { inComment = false; i += 1; }
      continue;
    }
    if (quote) {
      if (escaped) escaped = false;
      else if (char.charCodeAt(0) === 92) escaped = true;
      else if (char === quote) quote = "";
      continue;
    }
    if (char === "/" && next === "*") { inComment = true; i += 1; }
    else if (char === '"' || char === "'") quote = char;
    else if (char === "{") depth += 1;
    else if (char === "}") {
      depth -= 1;
      if (depth < 0) { fail(path.relative(root, file) + " has an unexpected closing brace"); return; }
    }
  }
  assert(!inComment, path.relative(root, file) + " contains an unclosed comment");
  assert(!quote, path.relative(root, file) + " contains an unclosed string");
  assert(depth === 0, path.relative(root, file) + " has unbalanced CSS braces");
}

assert(/<html\b/i.test(html), "dashboard.html must contain an HTML root");
assert(/<head\b/i.test(html) && /<\/head>/i.test(html), "dashboard.html must have a complete head");
assert(/<body\b/i.test(html) && /<\/body>/i.test(html), "dashboard.html must have a complete body");
assert(/<title>\s*Tender Scrapper\s*\|\s*Dashboard\s*<\/title>/i.test(html), "dashboard title is missing");
assert(!html.includes('class="overview-services"'), "dashboard must not render service status rows");
for (const id of ["scraperHealth", "clientHealth", "cacheHealth", "aiHealth"]) {
  assert(!html.includes('id="' + id + '"'), "dashboard must not render the removed service status #" + id);
}
const overviewScript = fs.readFileSync(path.join(root, "scripts/overview.js"), "utf8");
assert(!overviewScript.includes("function loadHealth()"), "removed service status checks must not run in the background");
assert(!overviewScript.includes("scraperApi.health") && !overviewScript.includes("clientApi.health") &&
  !overviewScript.includes("cacheApi.health") && !overviewScript.includes("ollamaApi.health"),
  "unused service health requests must be removed");

const requiredIds = [
  "appTopbar", "sidebarNavigation", "logoutButton", "dashboardMessage",
  "overviewGreetingName", "kpiTotalTenders", "kpiOpenTenders",
  "kpiClosingWeek", "kpiClosingMonth", "salesChart", "chartLine",
  "provinceList", "categoryList", "recentTenderList", "refreshOverview"
];
for (const id of requiredIds) {
  assert(html.includes('id="' + id + '"') || html.includes("id='" + id + "'"),
    "required dashboard hook #" + id + " is missing");
}

const cssRefs = [...html.matchAll(/<link\b[^>]*\bhref=["']([^"']+\.css(?:[?#][^"']*)?)["'][^>]*>/gi)]
  .map(match => match[1]);
const expectedCss = ["./css/styles.css", "./css/overview-dashboard.css", "./css/app-theme.css"];
for (const required of expectedCss) assert(cssRefs.includes(required), "dashboard must load " + required);
assert(!cssRefs.includes("./css/theme.css") && !cssRefs.includes("./css/modern-shell.css"),
  "dashboard must use the consolidated app-theme.css instead of duplicate shared layers");
assert(cssRefs.indexOf("./css/app-theme.css") > cssRefs.indexOf("./css/styles.css"),
  "app-theme.css must load after shared base styles");
assert(cssRefs.indexOf("./css/app-theme.css") > cssRefs.indexOf("./css/overview-dashboard.css"),
  "app-theme.css must load after dashboard styles");

const references = [...html.matchAll(/\b(?:href|src)=["']([^"']+)["']/gi)].map(match => match[1]);
for (const reference of references) {
  if (/^(?:[a-z]+:|\/\/|#|data:)/i.test(reference)) continue;
  const resolvedUrl = new URL(reference, "http://localhost/dashboard.html");
  const assetPath = path.join(root, decodeURIComponent(resolvedUrl.pathname).replace(/^\/+/, ""));
  assert(fs.existsSync(assetPath), "referenced local asset is missing: " + reference);
}

for (const relative of ["css/styles.css", "css/overview-dashboard.css", "css/app-theme.css"]) {
  checkCssBraces(path.join(root, relative));
}
const theme = fs.readFileSync(path.join(root, "css/app-theme.css"), "utf8");
const cookieScript = fs.readFileSync(path.join(root, "scripts/cookies.js"), "utf8");
assert(theme.includes("--app-bg"), "theme layer is missing shared design tokens");
assert(theme.includes('html[data-theme="dark"]'), "theme layer is missing dark-mode rules");
assert(theme.includes(".overview-page"), "dashboard-specific theme rules are missing");
const shell = theme;
assert(shell.includes("Canonical cookie launcher: bottom-right, aligned close to the viewport edge."),
  "shared shell must define the canonical cookie preferences pill");
assert(shell.includes("border-radius: 999px;") && shell.includes("height: 38px;"),
  "cookie preferences button must retain its compact pill shape");
assert(shell.includes("bottom: 8px;") && shell.includes("right: 28px;"),
  "cookie preferences button must sit close to the viewport bottom-right");
assert(shell.includes(".cookie-settings-launcher .cookie-settings-icon svg"),
  "cookie preferences icon must be visibly sized");
assert(shell.includes(".cookie-settings-launcher .cookie-settings-label"),
  "cookie preferences label must be visible");
assert(!shell.includes(".cookie-settings-launcher::before"),
  "cookie icon must render through its accessible button markup, not a pseudo-element");
assert((theme.match(/Canonical cookie launcher: bottom-right, aligned close to the viewport edge\./g) || []).length === 1,
  "cookie launcher styles must have exactly one canonical definition in app-theme.css");

const sharedUtils = fs.readFileSync(path.join(root, "scripts/shared-utils.js"), "utf8");
const escapeUtils = fs.readFileSync(path.join(root, "scripts/utils.js"), "utf8");
assert(sharedUtils.includes("export function getUsername"), "shared username helper is missing");
assert(sharedUtils.includes("export function clearSession"), "shared session cleanup helper is missing");
assert(escapeUtils.includes("export function esc"), "shared HTML escaping helper is missing");
assert(!fs.existsSync(path.join(root, "scripts/script.js")), "unused legacy demo chart script must be removed");
for (const pageFile of ["feed.html", "tender.html"]) {
  const pageHtml = fs.readFileSync(path.join(root, pageFile), "utf8");
  assert(!pageHtml.includes("floating-ai-assistant"), pageFile + " must not contain obsolete floating AI markup");
}
for (const scriptFile of ["scripts/feed.js", "scripts/tender.js", "scripts/alerts.js", "scripts/overview.js"]) {
  const source = fs.readFileSync(path.join(root, scriptFile), "utf8");
  assert(!/(?:const|function)\\s+esc\\b/.test(source), scriptFile + " must use shared HTML escaping");
}
const pageFiles = [
  "dashboard.html", "feed.html", "tender-search.html", "saved-tenders.html",
  "profile.html", "alerts.html", "application-tracker.html", "tender.html", "login.html", "index.html"
];
for (const pageFile of pageFiles) {
  const pageHtml = fs.readFileSync(path.join(root, pageFile), "utf8");
  assert(!/TenderScraping|Tender\s+Scraping/i.test(pageHtml),
    pageFile + " still contains the old Tender Scraping brand");
  if (pageFile !== "login.html") {
    assert(/<span>Tender Scrapper<\/span>/i.test(pageHtml),
      pageFile + " must display the canonical Tender Scrapper brand");
  }
}
const baseCss = fs.readFileSync(path.join(root, "css/styles.css"), "utf8");
assert(!/\.logo-area\s*\{|\.logo-icon\s*\{/i.test(baseCss),
  "legacy base CSS must not override shared logo styling");
assert(theme.includes(".sidebar .logo-area"),
  "app-theme.css must contain the shared logo styling");
for (const pageScript of ["scripts/feed.js", "scripts/profile.js", "scripts/alerts.js"]) {
  const source = fs.readFileSync(path.join(root, pageScript), "utf8");
  assert(!source.includes("setupLogout();"),
    pageScript + " must use the shared navigation logout handler only");
}
assert((shell.match(/Canonical cookie launcher: bottom-right, aligned close to the viewport edge\./g) || []).length === 1,
  "cookie launcher must have exactly one canonical style definition");


assert(cookieScript.includes('class="cookie-settings-label">Cookie preferences</span>'),
  "cookie settings button must include its visible label");
assert(cookieScript.includes('class="cookie-settings-icon" aria-hidden="true"'),
  "cookie settings button must include its icon");
const cookieInit = cookieScript.slice(cookieScript.indexOf("function initCookieConsent()"));
assert(cookieInit.indexOf("createSettingsButton();") >= 0 &&
  cookieInit.indexOf("createSettingsButton();") < cookieInit.indexOf("hasConsentDecision()"),
  "cookie button must be created even before a consent decision is saved");

// Browsers must check for new scripts after a deploy, and the security headers must still apply
// (an add_header inside a location would replace the server-level ones).
const nginxConf = fs.readFileSync(path.join(root, "nginx.conf"), "utf8");
const mainLocation = (nginxConf.match(/location \/ \{([^}]*)\}/) || ["", ""])[1].replace(/#.*$/gm, "");
assert(/\bexpires -1;/.test(mainLocation), "nginx must tell browsers to revalidate pages and scripts (expires -1)");
assert(!/\badd_header\b/.test(mainLocation), "location / must not use add_header, or the security headers are lost");

// Laptop widths (761-1024px with a mouse): the top bar starts beside the sidebar on every page. The rule must be
// as specific as app-theme.css's "html body:has(.app-topbar) .app-topbar { left: 0 }", or that one wins.
const responsiveFix = fs.readFileSync(path.join(root, "css/responsive-fix.css"), "utf8");
const laptopRules = responsiveFix.split("@media (min-width: 761px) and (max-width: 1024px) and (pointer: fine)")[1] || "";
assert(/html body:has\(\.app-topbar\) \.app-topbar[^{]*\{[^}]*left: var\(--sidebar-w\) !important/.test(laptopRules),
  "on laptop widths the top bar must start beside the sidebar, not behind it");
const savedCss = fs.readFileSync(path.join(root, "css/saved-tenders.css"), "utf8");
assert(!/\.saved-page\s*\{[^}]*max-width/.test(savedCss), "Saved Tenders must fill the space beside the sidebar like the other pages");
const stylesCss = fs.readFileSync(path.join(root, "css/styles.css"), "utf8");
assert(!/\.settings-content\s*\{[^}]*max-width/.test(stylesCss), "My profile must fill the space beside the sidebar like the other pages");
const profileRule = (theme.replace(/\r\n/g, "\n").match(/\n\.main-content\.settings-page \{[^}]*\}/) || [""])[0];
assert(profileRule.includes("var(--sidebar-w)") && !profileRule.includes("252px"),
  "My profile must leave the same room for the sidebar as the other pages (var(--sidebar-w))");

if (process.exitCode) process.exit(process.exitCode);
console.log("Dashboard smoke tests passed: page hooks, local assets, stylesheet order, CSS balance, shared theme coverage, and browser caching.");
