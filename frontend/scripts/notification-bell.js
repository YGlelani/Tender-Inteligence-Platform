import { notificationsApi } from "./api.js";
import { icon } from "./icons.js";

const POLL_MS = 60000;

const STYLES = `
.nav-alerts-dot { width: 8px; height: 8px; margin-left: auto; border-radius: 50%; background: #ef4444; flex: 0 0 8px; }
.nav-alerts-dot[hidden] { display: none; }
.nb-wrap { position: relative; display: inline-flex; }
.nb-button { position: relative; display: inline-flex; align-items: center; justify-content: center;
  width: 40px; height: 40px; padding: 0; border: 0; border-radius: 50%; background: transparent;
  color: inherit; cursor: pointer; font-size: 20px; }
.nb-button:hover, .nb-button[aria-expanded="true"] { background: var(--shell-bg, #f3f7fc); }
.nb-button:focus-visible { outline: 2px solid var(--shell-accent, #206e98); outline-offset: 2px; }
.nb-badge { position: absolute; top: 3px; right: 1px; min-width: 18px; height: 18px; padding: 0 5px;
  border: 2px solid var(--shell-surface, #fff); border-radius: 9px; background: #dc2626; color: #fff;
  font-size: 10px; font-weight: 750; line-height: 14px; text-align: center; box-sizing: border-box; }
.nb-panel { position: absolute; top: calc(100% + 8px); right: 0; z-index: 1000; width: min(380px, calc(100vw - 24px));
  max-height: min(520px, calc(100vh - 100px)); display: flex; flex-direction: column; overflow: hidden;
  border: 1px solid var(--shell-border, #e2eaf4); border-radius: 14px; background: var(--shell-surface, #fff);
  color: var(--shell-ink, #14243b); box-shadow: 0 18px 40px rgba(15, 30, 55, .16); font-size: 13px; }
.nb-panel[hidden] { display: none; }
.nb-head { display: flex; align-items: center; gap: 8px; padding: 14px 16px; border-bottom: 1px solid var(--shell-border, #e2eaf4); }
.nb-head h2 { flex: 1; margin: 0; font-size: 15px; }
.nb-link { padding: 4px 6px; border: 0; border-radius: 6px; background: none; color: var(--shell-accent, #206e98);
  font: inherit; font-weight: 650; cursor: pointer; }
.nb-link:hover { background: var(--shell-bg, #f3f7fc); }
.nb-icon-btn { display: inline-flex; padding: 6px; border: 0; border-radius: 6px; background: none;
  color: var(--shell-muted, #5a697f); font-size: 16px; cursor: pointer; }
.nb-icon-btn:hover { background: var(--shell-bg, #f3f7fc); color: var(--shell-ink, #14243b); }
.nb-body { overflow-y: auto; }
.nb-list { margin: 0; padding: 0; list-style: none; }
.nb-item { display: flex; gap: 10px; width: 100%; padding: 12px 16px; border: 0; border-bottom: 1px solid var(--shell-border, #e2eaf4);
  background: none; color: inherit; font: inherit; text-align: left; cursor: pointer; }
.nb-item:hover { background: var(--shell-bg, #f3f7fc); }
.nb-item.unread { background: color-mix(in srgb, var(--shell-accent, #206e98) 7%, transparent); }
.nb-dot { flex: 0 0 8px; height: 8px; margin-top: 5px; border-radius: 50%; background: transparent; }
.nb-item.unread .nb-dot { background: var(--shell-accent, #206e98); }
.nb-text { flex: 1; min-width: 0; }
.nb-title { display: block; font-weight: 700; }
.nb-msg { display: block; margin-top: 2px; color: var(--shell-muted, #5a697f); overflow-wrap: anywhere; }
.nb-time { display: block; margin-top: 4px; color: var(--shell-muted, #5a697f); font-size: 11px; }
.nb-empty { padding: 32px 16px; color: var(--shell-muted, #5a697f); text-align: center; }
`;

function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, c => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[c]);
}

function timeAgo(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    const seconds = Math.max(0, (Date.now() - date.getTime()) / 1000);
    if (seconds < 60) return "Just now";
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    if (days < 7) return `${days}d ago`;
    return date.toLocaleDateString();
}

function injectStyles() {
    if (document.getElementById("notificationBellStyles")) return;
    const style = document.createElement("style");
    style.id = "notificationBellStyles";
    style.textContent = STYLES;
    document.head.appendChild(style);
}

export function setupNotificationBell() {
    injectStyles();
    const existing = document.querySelector(".topbar-actions .topbar-icon-link");
    if (!existing || document.getElementById("notificationBell")) return;
    if (!localStorage.getItem("access_token")) return;

    const wrap = document.createElement("div");
    wrap.className = "nb-wrap";
    wrap.id = "notificationBell";
    wrap.innerHTML = `
        <button type="button" class="topbar-icon-link nb-button" aria-haspopup="dialog" aria-expanded="false"
                aria-controls="notificationPanel" aria-label="Notifications" title="Notifications">
            ${icon("bell", "topbar-bell-icon")}
            <span class="nb-badge" hidden></span>
        </button>
        <div class="nb-panel" id="notificationPanel" role="dialog" aria-label="Notifications" hidden>
            <div class="nb-head">
                <h2>Notifications</h2>
                <button type="button" class="nb-link" data-nb-read-all>Mark all as read</button>
                <a class="nb-icon-btn" href="./profile.html#notifications" aria-label="Notification settings" title="Notification settings">${icon("sliders-horizontal")}</a>
            </div>
            <div class="nb-body" data-nb-body></div>
        </div>
    `;
    existing.replaceWith(wrap);

    const button = wrap.querySelector(".nb-button");
    const badge = wrap.querySelector(".nb-badge");
    const panel = wrap.querySelector(".nb-panel");
    const body = wrap.querySelector("[data-nb-body]");
    const readAllButton = wrap.querySelector("[data-nb-read-all]");

    const setBadge = count => {
        const n = Number(count) || 0;
        badge.hidden = n <= 0;
        badge.textContent = n > 99 ? "99+" : String(n);
        button.setAttribute("aria-label", n > 0 ? `Notifications, ${n} unread` : "Notifications");
    };

    const refreshCount = async () => {
        try {
            const result = await notificationsApi.unreadCount();
            setBadge(result?.unread);
        } catch (error) {
            console.warn("Could not refresh notifications:", error);
        }
    };

    const showMessage = text => {
        body.innerHTML = `<p class="nb-empty">${escapeHtml(text)}</p>`;
    };

    const renderList = async () => {
        showMessage("Loading...");
        try {
            const items = await notificationsApi.list(30);
            if (!Array.isArray(items) || !items.length) {
                showMessage("You're all caught up. No notifications yet.");
                return;
            }
            body.innerHTML = `<ul class="nb-list">${items.map(item => `
                <li><button type="button" class="nb-item${item.is_read ? "" : " unread"}"
                        data-id="${escapeHtml(item.id)}" data-link="${escapeHtml(item.link || "")}">
                    <span class="nb-dot" aria-hidden="true"></span>
                    <span class="nb-text">
                        <span class="nb-title">${escapeHtml(item.title)}</span>
                        <span class="nb-msg">${escapeHtml(item.message)}</span>
                        <span class="nb-time">${escapeHtml(timeAgo(item.created_at))}</span>
                    </span>
                </button></li>`).join("")}</ul>`;
        } catch (error) {
            showMessage("Notifications are unavailable right now.");
        }
    };

    const open = () => {
        panel.hidden = false;
        button.setAttribute("aria-expanded", "true");
        renderList();
    };

    const close = () => {
        panel.hidden = true;
        button.setAttribute("aria-expanded", "false");
    };

    button.addEventListener("click", event => {
        event.stopPropagation();
        if (panel.hidden) open();
        else close();
    });

    readAllButton.addEventListener("click", async () => {
        try {
            await notificationsApi.markAllRead();
            setBadge(0);
            body.querySelectorAll(".nb-item.unread").forEach(el => el.classList.remove("unread"));
        } catch (error) {
            console.warn("Could not mark notifications as read:", error);
        }
    });

    body.addEventListener("click", async event => {
        const item = event.target.closest(".nb-item");
        if (!item) return;
        const link = item.dataset.link;
        if (item.classList.contains("unread")) {
            item.classList.remove("unread");
            try {
                await notificationsApi.markRead(item.dataset.id);
            } catch (error) {
                console.warn("Could not mark notification as read:", error);
            }
            refreshCount();
        }
        if (link && /^[a-z0-9-]+\.html(?:[?#].*)?$/i.test(link)) {
            window.location.assign(new URL("./" + link, window.location.href).href);
        }
    });

    document.addEventListener("click", event => {
        if (!panel.hidden && !wrap.contains(event.target)) close();
    });

    document.addEventListener("keydown", event => {
        if (event.key === "Escape" && !panel.hidden) {
            close();
            button.focus();
        }
    });

    refreshCount();
    window.setInterval(() => {
        if (!document.hidden) refreshCount();
    }, POLL_MS);
}
