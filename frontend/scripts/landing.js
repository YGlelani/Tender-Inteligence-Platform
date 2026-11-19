// Public landing page (index.html): live "closing soonest" tenders, live
// numbers and provinces, the sign-up links and the theme switch. A returning
// user who is still logged in never gets here; index.html sends them to the
// dashboard first.
import { CONFIG } from "./config.js";
import { tenderSearchApi, overviewApi } from "./api.js";
import { esc } from "./utils.js";
import { icon } from "./icons.js";

const $ = id => document.getElementById(id);

const DAY = 24 * 60 * 60 * 1000;

const number = value => Number(value).toLocaleString("en-ZA");

const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// Closing dates are stored as local times, for example "2026-11-14 11:00:00".
// A date with no time closes at the end of that day.
function closingTime(value) {
    if (!value) return null;
    let text = String(value).trim();
    if (/^\d{4}-\d{2}-\d{2}$/.test(text)) text += "T23:59:59";
    else if (/^\d{4}-\d{2}-\d{2} \d/.test(text)) text = text.replace(" ", "T");
    const date = new Date(text);
    return Number.isNaN(date.getTime()) ? null : date;
}

function startOfDay(date) {
    const copy = new Date(date);
    copy.setHours(0, 0, 0, 0);
    return copy;
}

function describeClosing(value) {
    const closes = closingTime(value);
    if (!closes) return { text: "Closing date not published", urgent: false };

    const days = Math.round((startOfDay(closes) - startOfDay(new Date())) / DAY);
    const hasTime = !/^\d{4}-\d{2}-\d{2}$/.test(String(value).trim());
    const time = hasTime
        ? closes.toLocaleTimeString("en-ZA", { hour: "2-digit", minute: "2-digit" })
        : "";

    if (days <= 0) return { text: time ? `Closes today at ${time}` : "Closes today", urgent: true };
    if (days === 1) return { text: time ? `Closes tomorrow at ${time}` : "Closes tomorrow", urgent: true };
    const date = closes.toLocaleDateString("en-ZA", { weekday: "short", day: "numeric", month: "short" });
    return { text: `Closes in ${days} days, ${date}`, urgent: false };
}

// The floating reminder in the hero uses the real next tender.
function showReminder(tender) {
    const closing = describeClosing(tender.closing_date);
    $("lpReminderIcon").innerHTML = icon("bell");
    $("lpReminderTitle").textContent = closing.text;
    $("lpReminderText").textContent = tender.title || tender.tender_number || "";
    $("lpReminder").hidden = false;
}

// Wrap the searched words in <mark>. The text is split on the matches first and
// every piece is escaped, so the highlight can never break the HTML.
function highlight(text, query) {
    const words = String(query || "").trim().split(/\s+/)
        .filter(word => word.length > 1)
        .map(word => word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    if (!words.length) return esc(text);
    const pattern = new RegExp(`(${words.join("|")})`, "gi");
    return String(text).split(pattern)
        .map((part, index) => (index % 2 ? `<mark>${esc(part)}</mark>` : esc(part)))
        .join("");
}

const COUNTDOWN_WINDOW = 48 * 60 * 60 * 1000;

function countdownText(closes) {
    const left = closes.getTime() - Date.now();
    if (left <= 0) return "Closed";
    const total = Math.floor(left / 1000);
    const hours = String(Math.floor(total / 3600)).padStart(2, "0");
    const minutes = String(Math.floor((total % 3600) / 60)).padStart(2, "0");
    const seconds = String(total % 60).padStart(2, "0");
    return `Closes in ${hours}:${minutes}:${seconds}`;
}

function tenderRow(tender, index, query = "") {
    const closing = describeClosing(tender.closing_date);
    const closes = closingTime(tender.closing_date);
    const ticking = closes && closes.getTime() - Date.now() < COUNTDOWN_WINDOW;
    const where = [tender.organisation, tender.province].filter(Boolean).join(", ");
    return `
        <li class="lp-board-item" style="--i: ${index}">
            <span class="lp-board-when${closing.urgent ? " is-urgent" : ""}"${ticking ? ` data-closes="${closes.getTime()}" title="${esc(closing.text)}"` : ""}>${esc(ticking ? countdownText(closes) : closing.text)}</span>
            <span class="lp-board-title">${highlight(tender.title || "Untitled tender", query)}</span>
            <span class="lp-board-meta">
                ${where ? `<span>${esc(where)}</span>` : ""}
                ${tender.tender_number ? `<span class="lp-board-number">${esc(tender.tender_number)}</span>` : ""}
            </span>
        </li>`;
}

async function loadBoard() {
    const list = $("lpBoardList");
    try {
        const result = await tenderSearchApi.search({ limit: 5 });
        const tenders = Array.isArray(result?.tenders) ? result.tenders : [];
        if (!tenders.length) {
            list.innerHTML = '<li class="lp-board-empty">No open tenders right now. New ones are added every day.</li>';
            return;
        }
        list.innerHTML = tenders.map((tender, index) => tenderRow(tender, index)).join("");
        startCountdowns();
        showReminder(tenders[0]);
    } catch (error) {
        console.warn("Could not load open tenders for the landing page:", error);
        $("landingBoard").classList.add("is-offline");
        list.innerHTML = '<li class="lp-board-empty">Open tenders could not be loaded just now. Log in to see them.</li>';
    }
}

// Nine tiles placed roughly where each province sits on the map.
const PROVINCE_TILES = {
    "Limpopo": "lim",
    "North West": "nw",
    "Gauteng": "gp",
    "Mpumalanga": "mp",
    "Northern Cape": "nc",
    "Free State": "fs",
    "KwaZulu-Natal": "kzn",
    "Western Cape": "wc",
    "Eastern Cape": "ec"
};

function renderProvinces(byProvince) {
    const map = $("lpProvinces");
    const counts = {};
    (Array.isArray(byProvince) ? byProvince : []).forEach(item => {
        const name = String(item.province ?? item.name ?? "").trim();
        const key = Object.keys(PROVINCE_TILES).find(province => province.toLowerCase() === name.toLowerCase());
        if (key) counts[key] = (counts[key] || 0) + (Number(item.count) || 0);
    });
    const max = Math.max(0, ...Object.values(counts));
    if (!max) {
        map.innerHTML = '<p class="lp-board-empty">Province numbers are not available just now.</p>';
        return;
    }
    map.innerHTML = Object.entries(PROVINCE_TILES).map(([name, area]) => {
        const count = counts[name] || 0;
        // 12% to 100% strength, so even quiet provinces stay visible.
        const strength = Math.round(12 + (count / max) * 88);
        return `
            <button type="button" class="lp-tile" role="listitem" style="grid-area: ${area}; --strength: ${strength}%"
                data-province="${esc(name)}" aria-label="${esc(name)}: ${esc(number(count))} tenders. Search this province.">
                <span class="lp-tile-name">${esc(name)}</span>
                <span class="lp-tile-count">${esc(number(count))}</span>
            </button>`;
    }).join("");
}

function fillCategories(byCategory) {
    const select = $("lpSearchCategory");
    const names = (Array.isArray(byCategory) ? byCategory : [])
        .filter(item => item && (item.category ?? item.name) && Number(item.count) > 0)
        .map(item => String(item.category ?? item.name));
    if (!names.length) {
        select.hidden = true;
        return;
    }
    select.insertAdjacentHTML("beforeend", names.map(name => `<option>${esc(name)}</option>`).join(""));
}

async function loadLiveNumbers() {
    try {
        const [stats, volume] = await Promise.all([overviewApi.stats(), overviewApi.volume(30)]);
        const open = Number(stats?.open_tenders);
        const week = Number(stats?.closing_this_week);
        const month = Number(volume?.total);

        if (Number.isFinite(open) && open > 0) {
            $("lpPulseText").textContent = `${number(open)} tenders open right now`;
            $("lpPulse").hidden = false;
        }
        setFigure("lpFigOpen", open);
        setFigure("lpFigWeek", week);
        setFigure("lpFigMonth", month);
        $("lpFigures").hidden = false;
        renderProvinces(stats?.by_province);
        fillCategories(stats?.by_category);
        revealDataWhenSeen();
    } catch (error) {
        // The numbers are a bonus; the page works without them.
        console.warn("Could not load live tender numbers:", error);
        $("provinces").hidden = true;
        $("lpSearchCategory").hidden = true;
    }
}

function setFigure(id, value) {
    const element = $(id);
    if (!Number.isFinite(value)) {
        element.textContent = "–";
        return;
    }
    element.dataset.target = String(value);
    element.textContent = reducedMotion ? number(value) : "0";
}

// One moment of motion: the figures count up and the province bars grow
// the first time the section comes into view.
function revealDataWhenSeen() {
    const section = $("provinces");
    let revealed = false;

    const showFinalNumbers = () => {
        section.querySelectorAll("[data-target]").forEach(element => {
            element.textContent = number(Number(element.dataset.target));
        });
    };

    const reveal = () => {
        if (revealed) return;
        revealed = true;
        window.removeEventListener("scroll", checkInView);
        section.classList.add("is-seen");
        if (reducedMotion) {
            showFinalNumbers();
            return;
        }
        const duration = 1100;
        const started = performance.now();
        const step = () => {
            const progress = Math.min(1, (performance.now() - started) / duration);
            const eased = 1 - Math.pow(1 - progress, 3);
            section.querySelectorAll("[data-target]").forEach(element => {
                element.textContent = number(Math.round(Number(element.dataset.target) * eased));
            });
            if (progress < 1) requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
        // Always end on the real numbers, even if animation frames are paused.
        setTimeout(showFinalNumbers, duration + 200);
    };

    function checkInView() {
        const box = section.getBoundingClientRect();
        if (box.top < window.innerHeight * 0.75 && box.bottom > 0) reveal();
    }

    if ("IntersectionObserver" in window) {
        const observer = new IntersectionObserver(entries => {
            if (entries.some(entry => entry.isIntersecting)) {
                observer.disconnect();
                reveal();
            }
        }, { threshold: 0.2 });
        observer.observe(section);
    }
    // Backup in case the observer does not fire.
    window.addEventListener("scroll", checkInView, { passive: true });
    checkInView();
}

/* ---------- Live search: no account needed ---------- */

let searchRequest = 0;

async function runSearch() {
    const results = $("lpResults");
    const q = $("lpSearchQ").value.trim();
    const province = $("lpSearchProvince").value;
    const category = $("lpSearchCategory").value;
    const requestId = ++searchRequest;

    results.innerHTML = '<p class="lp-results-hint">Searching open tenders…</p>';
    try {
        const params = { q, limit: 5 };
        if (province) params.province = province;
        if (category) params.category = category;
        const result = await tenderSearchApi.search(params);
        if (requestId !== searchRequest) return;

        const tenders = Array.isArray(result?.tenders) ? result.tenders : [];
        const total = Number(result?.total) || tenders.length;
        const what = [q && `"${q}"`, category && `in ${category}`, province && `in ${province}`].filter(Boolean).join(" ");

        if (!tenders.length) {
            results.innerHTML = `<p class="lp-results-hint">No open tenders ${esc(what || "found")} right now. Try another word, or create an account and Smart Alerts will tell you when one is published.</p>`;
            return;
        }
        results.innerHTML = `
            <p class="lp-results-count"><strong>${esc(number(total))}</strong> open tender${total === 1 ? "" : "s"}${what ? ` for ${esc(what)}` : ""}, closing soonest first</p>
            <ol class="lp-board-list lp-results-list">${tenders.map((tender, index) => tenderRow(tender, index, q)).join("")}</ol>
            <div class="lp-results-more">
                <span>${total > tenders.length ? `Showing ${tenders.length} of ${esc(number(total))}.` : ""} Create an account to see every match, get alerts and track your bids.</span>
                <a class="lp-button lp-button-signal lp-button-small" data-signup href="${esc(signupUrl())}">Create your account</a>
            </div>`;
        startCountdowns();
    } catch (error) {
        if (requestId !== searchRequest) return;
        console.warn("Landing page search failed:", error);
        results.innerHTML = '<p class="lp-results-hint">Search is not available just now. Please try again in a moment.</p>';
    }
}

function setUpSearch() {
    $("lpSearch").addEventListener("submit", event => {
        event.preventDefault();
        runSearch();
    });
    $("lpSearchProvince").addEventListener("change", runSearch);
    $("lpSearchCategory").addEventListener("change", runSearch);

    // Search as you type, after a short pause.
    let typing = null;
    $("lpSearchQ").addEventListener("input", () => {
        clearTimeout(typing);
        typing = setTimeout(runSearch, 450);
    });

    document.querySelectorAll("[data-try]").forEach(chip => {
        chip.addEventListener("click", () => {
            $("lpSearchQ").value = chip.dataset.try;
            runSearch();
        });
    });

    $("lpProvinces").addEventListener("click", event => {
        const button = event.target.closest("[data-province]");
        if (!button) return;
        $("lpSearchQ").value = "";
        $("lpSearchProvince").value = button.dataset.province;
        $("try").scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" });
        runSearch();
    });
}

/* ---------- Feature tabs ---------- */

function setUpTabs() {
    const tabs = [...document.querySelectorAll("#lpTabs [role=tab]")];
    const select = tab => {
        tabs.forEach(other => {
            const selected = other === tab;
            other.setAttribute("aria-selected", String(selected));
            other.tabIndex = selected ? 0 : -1;
            $(other.getAttribute("aria-controls")).hidden = !selected;
        });
    };
    tabs.forEach((tab, index) => {
        tab.addEventListener("click", () => select(tab));
        tab.addEventListener("keydown", event => {
            const keys = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 };
            let next = null;
            if (event.key in keys) next = tabs[(index + keys[event.key] + tabs.length) % tabs.length];
            if (event.key === "Home") next = tabs[0];
            if (event.key === "End") next = tabs[tabs.length - 1];
            if (!next) return;
            event.preventDefault();
            select(next);
            next.focus();
        });
    });
}

// Tick every countdown on the page once a second, only while there are any.
let countdownTimer = null;

function startCountdowns() {
    if (countdownTimer || !document.querySelector("[data-closes]")) return;
    countdownTimer = setInterval(() => {
        const clocks = document.querySelectorAll("[data-closes]");
        if (!clocks.length) {
            clearInterval(countdownTimer);
            countdownTimer = null;
            return;
        }
        clocks.forEach(element => {
            element.textContent = countdownText(new Date(Number(element.dataset.closes)));
        });
    }, 1000);
}

// Phones: show the sign-up bar once the hero is out of view, hide it at the closing section.
function setUpStickyBar() {
    const bar = $("lpStickyCta");
    const hero = document.querySelector(".lp-hero");
    const closing = document.querySelector(".lp-cta");
    const update = () => {
        const pastHero = hero.getBoundingClientRect().bottom < 0;
        const atEnd = closing.getBoundingClientRect().top < window.innerHeight;
        const show = pastHero && !atEnd;
        bar.classList.toggle("is-visible", show);
        bar.setAttribute("aria-hidden", String(!show));
        bar.querySelector("a").tabIndex = show ? 0 : -1;
    };
    window.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    update();
}

// The sign-up page is on another port, so its links carry the current theme.
function signupUrl() {
    return window.tsTheme ? window.tsTheme.link(CONFIG.services.signupFrontend) : CONFIG.services.signupFrontend;
}

function setUpSignupLinks() {
    document.querySelectorAll("[data-signup]").forEach(link => {
        link.href = signupUrl();
    });
}

function setUpThemeSwitch() {
    const button = $("lpTheme");
    const render = () => {
        const dark = document.documentElement.dataset.theme === "dark";
        button.innerHTML = icon(dark ? "sun" : "moon");
        button.setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");
        button.setAttribute("aria-pressed", String(dark));
    };
    button.addEventListener("click", () => {
        window.tsTheme.toggle();
        setUpSignupLinks();
    });
    // Also update when another tab or the device changes the theme.
    document.addEventListener("tstheme", () => {
        render();
        setUpSignupLinks();
    });
    render();
}

$("lpYear").textContent = String(new Date().getFullYear());
setUpSignupLinks();
setUpThemeSwitch();
setUpSearch();
setUpTabs();
setUpStickyBar();
loadBoard();
loadLiveNumbers();
