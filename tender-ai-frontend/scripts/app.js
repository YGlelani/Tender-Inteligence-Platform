// These values will be replaced by the GitHub Action during deployment
const AGENT_URL = "__AGENT_URL__";
const LOGIN_URL = "__LOGIN_URL__";

const app = {
    state: { profileId: null, profile: null, matches: [] },
    tasks: [],

    async init() {
        document.getElementById("back-to-site").href = mainSiteUrl(window.location);
        if (!this.checkAuth()) return;

        this.initTheme();
        this.initRouter();
        this.initCmdPalette();
        this.initChat();
        this.initModalA11y();
        this.checkHealth();
        
        // Auto-load existing profile!
        await this.loadExistingProfile();
    },

    checkAuth() {
        // The dashboard hands the sign-in over as index.html#token=... . The part
        // after # never reaches a server or its logs; it is removed straight away.
        const hash = new URLSearchParams(window.location.hash.slice(1));
        const handedOver = hash.get("token");
        if (handedOver) {
            localStorage.setItem("access_token", handedOver);
            window.history.replaceState({}, document.title, window.location.pathname);
        }
        const token = localStorage.getItem("access_token");
        if (!token) {
            window.location.href = LOGIN_URL;
            return false;
        }
        try {
            const payload = JSON.parse(atob(token.split('.')[1].replace(/-/g, "+").replace(/_/g, "/")));
            if (!payload.exp || payload.exp * 1000 <= Date.now()) {
                this.signInAgain();
                return false;
            }
            const email = payload.sub || payload.email || "User";
            document.getElementById("ui-avatar").textContent = email.substring(0, 2).toUpperCase();
            document.getElementById("ui-biz-name").textContent = email.split('@')[0];
            return true;
        } catch (e) {
            localStorage.removeItem("access_token");
            window.location.href = LOGIN_URL;
            return false;
        }
    },

    signInAgain() {
        localStorage.removeItem("access_token");
        window.location.href = LOGIN_URL;
    },

    // fetch() for the agent: a 401 means the sign-in has ended (expired, signed
    // out or password changed), so go back to sign in instead of failing quietly.
    async apiFetch(url, options) {
        const res = await fetch(url, options);
        if (res.status === 401) {
            this.signInAgain();
            throw new Error("Your session has ended. Please sign in again.");
        }
        return res;
    },

    getAuthHeaders() {
        const token = localStorage.getItem("access_token");
        return token ? { "Authorization": `Bearer ${token}` } : {};
    },

    async loadExistingProfile() {
        try {
            const res = await app.apiFetch(`${AGENT_URL}/agent/my-profile`, {
                headers: this.getAuthHeaders()
            });
            const data = await res.json();
            
            if (data.profile && data.profile_id) {
                this.state.profileId = data.profile_id;
                this.state.profile = data.profile;
                this.state.matches = data.top_matches || [];
                this.saveStateToSession();
                
                document.getElementById("stat-matches").textContent = this.state.matches.length;
                initRadarChart("echart-radar", this.state.matches);
                this.renderFullProfile();
                
                const chatBox = document.getElementById("chat-messages");
                chatBox.innerHTML = `<div class="msg agent">Welcome back! I've loaded your profile for <strong>${escapeHtml(data.profile.business_name)}</strong>. You have ${this.state.matches.length} matches. Click 'Tender Board' to view them.</div>`;
            } else {
                document.getElementById("chat-messages").innerHTML = `<div class="msg agent">Hello! I am ready to help. To see the tenders that suit your business, upload your business documents on <a href="${mainSiteUrl(window.location, "onboarding.html")}">Tender Scrapper → Business Documents</a>.</div>`;
            }
        } catch (e) {
            console.error("Failed to load profile", e);
            document.getElementById("chat-messages").innerHTML = `<div class="msg agent">Error connecting to the agent. Please try again.</div>`;
        }
    },

    /* ---------------- SIDEBAR (mobile drawer) ---------------- */

    toggleSidebar() {
        const sidebar = document.getElementById("sidebar");
        const backdrop = document.getElementById("sidebar-backdrop");
        if (!sidebar) return;
        const isOpen = sidebar.classList.toggle("open");
        if (backdrop) backdrop.classList.toggle("active", isOpen);
        document.body.classList.toggle("no-scroll", isOpen);
    },

    openSidebar() {
        document.getElementById("sidebar")?.classList.add("open");
        document.getElementById("sidebar-backdrop")?.classList.add("active");
        document.body.classList.add("no-scroll");
    },

    closeSidebar() {
        document.getElementById("sidebar")?.classList.remove("open");
        document.getElementById("sidebar-backdrop")?.classList.remove("active");
        document.body.classList.remove("no-scroll");
    },

    /* ---------------- THEME ---------------- */

    initTheme() {
        const saved = localStorage.getItem("theme") || "light";
        document.documentElement.setAttribute("data-theme", saved);
        this.updateThemeIcon(saved);
        document.getElementById("theme-toggle").addEventListener("click", () => {
            const isDark = document.documentElement.getAttribute("data-theme") === "dark";
            const newTheme = isDark ? "light" : "dark";
            document.documentElement.setAttribute("data-theme", newTheme);
            localStorage.setItem("theme", newTheme);
            this.updateThemeIcon(newTheme);
        });
    },

    updateThemeIcon(theme) {
        const icon = document.getElementById("theme-toggle").querySelector("img");
        icon.src = theme === "dark" ? "icons/sun.svg" : "icons/moon.svg";
    },

    /* ---------------- ROUTER ---------------- */

    initRouter() {
        document.querySelectorAll(".nav-item").forEach(btn => {
            btn.addEventListener("click", () => {
                document.querySelectorAll(".nav-item").forEach(b => b.classList.remove("active"));
                document.querySelectorAll(".view-section").forEach(v => v.classList.remove("active"));
                btn.classList.add("active");
                document.getElementById(btn.dataset.target).classList.add("active");

                if (window.matchMedia("(max-width: 768px)").matches) this.closeSidebar();

                if (btn.dataset.target === "view-tasks") this.loadTasks();
                if (btn.dataset.target === "view-tenders") this.loadTenders();
                if (btn.dataset.target === "view-profile") this.renderFullProfile();
            });
        });
    },

    /* ---------------- HEALTH ---------------- */

    // Updates the sidebar's system line and the Agent Assistant's status label together.
    async checkHealth() {
        let health = null;
        try {
            const res = await fetch(`${AGENT_URL}/health`);
            if (res.ok) health = await res.json();
        } catch {
            // Not reachable: shown as offline below.
        }
        const status = agentStatus(health);
        const badge = document.getElementById("agent-status");
        badge.textContent = status.label;
        badge.className = `badge badge-${status.kind}`;
        document.getElementById("health-dot").classList.toggle("online", Boolean(health));
        document.getElementById("health-text").textContent = health ? "System Online" : "System Offline";
    },

    /* ---------------- SESSION STATE ---------------- */

    loadStateFromSession() {
        const saved = localStorage.getItem("app_state");
        if (saved) {
            try {
                const parsed = JSON.parse(saved);
                if (parsed.profileId) {
                    this.state = parsed;
                    document.getElementById("stat-matches").textContent = this.state.matches.length;
                    initRadarChart("echart-radar", this.state.matches);
                    this.renderFullProfile();
                }
            } catch (e) {}
        }
    },

    saveStateToSession() {
        localStorage.setItem("app_state", JSON.stringify(this.state));
    },

    /* ---------------- PROFILE ---------------- */

    renderFullProfile() {
        const container = document.getElementById("profile-details");
        const p = this.state.profile;

        if (!p) {
            container.innerHTML = `<div class="empty-state">No business profile yet. Upload your business documents on <a href="${mainSiteUrl(window.location, "onboarding.html")}">Tender Scrapper → Business Documents</a>.</div>`;
            return;
        }

        const initials = (p.business_name || "??").slice(0, 2).toUpperCase();
        const certs = p.certifications && p.certifications.length > 0
            ? p.certifications.map(c => `<span style="background:#d1fae5; color:#10b981; padding:6px 12px; border-radius:8px; font-size:13px; font-weight:600; word-break:break-word;">✓ ${escapeHtml(c)}</span>`).join("")
            : `<span style="color:var(--text-muted); font-style:italic;">No certifications detected.</span>`;

        container.innerHTML = `
            <div class="profile-grid">
                <div class="profile-header-card">
                    <div class="profile-logo">${initials}</div>
                    <div class="profile-meta">
                        <h2>${escapeHtml(p.business_name)}</h2>
                        <p style="color:var(--text-muted); margin-top:4px; word-break:break-word;">Reg: ${escapeHtml(p.registration_number || 'N/A')} • ${escapeHtml(p.contact_email || 'No email')} • ${escapeHtml(p.website || 'No website')}</p>
                    </div>
                    <div class="profile-action">
                        <a class="btn-secondary" href="${mainSiteUrl(window.location, "onboarding.html")}">Update on Tender Scrapper</a>
                    </div>
                </div>

                <div class="profile-columns">
                    <div class="profile-card">
                        <h3>🏢 Core Industries</h3>
                        <div class="chip-grid">
                            ${(p.industries || []).map(i => `<span class="chip">${escapeHtml(i)}</span>`).join("")}
                        </div>
                    </div>

                    <div class="profile-card">
                        <h3>🛠️ Services</h3>
                        <div class="chip-grid">
                            ${(p.services || []).map(s => `<span class="chip">${escapeHtml(s)}</span>`).join("")}
                        </div>
                    </div>

                    <div class="profile-card">
                        <h3>📍 Service Areas</h3>
                        <div class="chip-grid">
                            ${(p.service_areas || []).length ? (p.service_areas || []).map(a => `<span class="chip">${escapeHtml(a)}</span>`).join("") : `<span style="color:var(--text-muted); font-size:14px;">National coverage</span>`}
                        </div>
                    </div>
                </div>

                <div class="profile-card" style="margin-top: 24px;">
                    <h3>📜 Certifications & Compliance</h3>
                    <div style="display:flex; gap:12px; flex-wrap:wrap; margin-top:16px;">
                        ${certs}
                    </div>
                </div>
            </div>
        `;
    },

    /* ---------------- CHAT ---------------- */

    initChat() {
        const input = document.getElementById("chat-input");
        const btn = document.getElementById("btn-send");

        const sendMsg = async () => {
            const text = input.value.trim();
            if (!text) return;
            input.value = "";

            const chatBox = document.getElementById("chat-messages");
            chatBox.innerHTML += `<div class="msg user">${escapeHtml(text)}</div>`;
            chatBox.scrollTop = chatBox.scrollHeight;

            const loadId = "loading-chat-" + Date.now();
            chatBox.innerHTML += `<div class="msg agent" id="${loadId}">Thinking (CPU is working, this may take 1-2 minutes)...</div>`;
            chatBox.scrollTop = chatBox.scrollHeight;

            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 180000);

            try {
                const res = await app.apiFetch(`${AGENT_URL}/agent/chat`, {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        ...this.getAuthHeaders()
                    },
                    body: JSON.stringify({ message: text, session_id: "dash-session" }),
                    signal: controller.signal
                });
                clearTimeout(timeoutId);

                const data = await res.json();
                document.getElementById(loadId).innerHTML = parseMarkdown(data.response);
                chatBox.scrollTop = chatBox.scrollHeight;
            } catch (err) {
                clearTimeout(timeoutId);
                if (err.name === 'AbortError') {
                    document.getElementById(loadId).innerHTML = "Request timed out. The AI is taking too long.";
                } else {
                    document.getElementById(loadId).innerHTML = "Network error. Could not reach the agent.";
                }
            }
        };

        btn.addEventListener("click", sendMsg);
        input.addEventListener("keypress", (e) => { if (e.key === "Enter") sendMsg(); });
    },

    /* ---------------- TENDERS ---------------- */

    // The board shows the user's matches themselves, best first: the same list as Smart Alerts.
    async loadTenders() {
        const grid = document.getElementById("tender-grid");
        grid.innerHTML = `<div class="empty-state">Loading your matches...</div>`;
        try {
            const res = await app.apiFetch(`${AGENT_URL}/agent/my-profile`, {
                headers: this.getAuthHeaders()
            });
            if (res.ok) {
                const data = await res.json();
                this.state.matches = data.top_matches || [];
                this.saveStateToSession();
                document.getElementById("stat-matches").textContent = this.state.matches.length;
            }
        } catch {
            // Keep showing the matches loaded with the profile.
        }

        const matches = boardMatches(this.state.matches);
        if (matches.length === 0) {
            grid.innerHTML = `<div class="empty-state">No matching tenders found for your profile yet.</div>`;
            return;
        }
        grid.innerHTML = matches.map(m => buildTenderCard({
            tender_number: m.tender_number,
            title: m.title,
            organisation: m.organisation,
            score: m.score
        })).join("");
    },

    /* ---------------- TASKS ---------------- */

    async loadTasks() {
        const board = document.getElementById("task-board");
        board.innerHTML = `<div class="empty-state">Agent is thinking...</div>`;
        try {
            const res = await app.apiFetch(`${AGENT_URL}/agent/tasks`, {
                headers: this.getAuthHeaders()
            });
            const data = await res.json();
            this.tasks = data.tasks || [];
            this.renderTasks();
        } catch {
            board.innerHTML = `<div class="empty-state">Failed to load tasks.</div>`;
        }
    },

    renderTasks() {
        const board = document.getElementById("task-board");
        const todo = this.tasks.filter(t => t.status === 'todo');
        const progress = this.tasks.filter(t => t.status === 'progress');
        const done = this.tasks.filter(t => t.status === 'done');

        const buildCard = (t) => `
            <div class="task-card ${t.status === 'done' ? 'done' : ''}">
                <div class="tc-badge ${t.priority.toLowerCase() === 'high' ? 'danger' : t.priority.toLowerCase() === 'review' ? 'warning' : ''}">${t.priority}</div>
                <h4>${escapeHtml(t.title)}</h4>
                <p>${escapeHtml(t.description)}</p>
                <div class="task-actions">
                    ${t.action_btn ? `<button type="button" class="btn-sm primary" onclick="app.handleTaskAction('${t.action_type}')">${t.action_btn}</button>` : "<div></div>"}
                    <select onchange="app.moveTask('${t.id}', this.value)" class="task-select">
                        <option value="" disabled selected>Move to...</option>
                        <option value="todo">To Do</option>
                        <option value="progress">In Progress</option>
                        <option value="done">Done</option>
                    </select>
                </div>
            </div>
        `;

        board.innerHTML = `
            <div class="task-column">
                <div class="task-col-header">To Do (${todo.length})</div>
                ${todo.map(buildCard).join("")}
            </div>
            <div class="task-column">
                <div class="task-col-header">In Progress (${progress.length})</div>
                ${progress.map(buildCard).join("")}
            </div>
            <div class="task-column">
                <div class="task-col-header">Done (${done.length})</div>
                ${done.map(buildCard).join("")}
            </div>
        `;
    },

    moveTask(taskId, newStatus) {
        const task = this.tasks.find(t => t.id === taskId);
        if (task) {
            task.status = newStatus;
            this.renderTasks();
        }
    },

    handleTaskAction(type) {
        if (type === 'proposal') this.openProposalBuilder();
        else if (type === 'strategy') document.querySelector('[data-target="view-tenders"]').click();
    },

    /* ---------------- DOCUMENTS / RAG ---------------- */

    async showDocuments(tenderNumber) {
        if (tenderNumber === "0/0") return;

        this.openModal("split-modal");
        document.getElementById("doc-title").textContent = tenderNumber;
        const docText = document.getElementById("doc-text");

        document.getElementById("doc-chat-messages").innerHTML = `<div class="msg agent">I have the tender details. Click 'Index for AI' on a PDF to let me read it, then you can ask questions.</div>`;
        document.getElementById("doc-chat-input").value = "";

        const safeTenderNumber = encodeURIComponent(tenderNumber);

        docText.innerHTML = "Fetching documents from API...";
        try {
            const res = await app.apiFetch(`${AGENT_URL}/agent/tenders/${safeTenderNumber}/documents`, {
                headers: this.getAuthHeaders()
            });
            if (!res.ok) throw new Error("Failed");
            const data = await res.json();

            if (!data.documents || data.documents.length === 0) {
                docText.innerHTML = `<div class="empty-state">No documents attached to this tender.</div>`;
                document.getElementById("doc-chat-input").disabled = true;
                document.getElementById("doc-chat-input").placeholder = "No documents to ask about.";
                document.getElementById("doc-btn-send").disabled = true;
                document.getElementById("doc-btn-send").style.opacity = "0.5";
            } else {
                docText.innerHTML = data.documents.map(d => `
                    <div style="margin-bottom:12px; padding:12px; border:1px solid var(--border); border-radius:8px; word-break:break-word;">
                        <div style="font-weight:600; font-size:14px; margin-bottom:8px;">${escapeHtml(d.name || d.document_name || 'Untitled')}</div>
                        <div style="display:flex; gap:8px; flex-wrap:wrap;">
                            <a href="${d.url || d.document_url}" target="_blank" rel="noopener" style="color:var(--primary); font-size:13px; text-decoration:none; padding:6px 12px; border:1px solid var(--primary); border-radius:6px;">Download</a>
                            <button type="button" onclick="app.indexDocument('${escapeHtml(tenderNumber)}', '${escapeHtml(d.url || d.document_url)}', this)" style="background:var(--success); color:white; border:none; padding:6px 12px; border-radius:6px; cursor:pointer; font-size:13px;">Index for AI</button>
                        </div>
                    </div>
                `).join("");

                document.getElementById("doc-chat-input").disabled = false;
                document.getElementById("doc-chat-input").placeholder = "e.g. What is the CIDB requirement?";
                document.getElementById("doc-btn-send").disabled = false;
                document.getElementById("doc-btn-send").style.opacity = "1";
            }
        } catch {
            docText.innerHTML = `<div class="empty-state">No documents found for this tender.</div>`;
            document.getElementById("doc-chat-input").disabled = true;
            document.getElementById("doc-btn-send").disabled = true;
            document.getElementById("doc-btn-send").style.opacity = "0.5";
        }

        const askBtn = document.getElementById("doc-btn-send");
        const askInput = document.getElementById("doc-chat-input");

        askBtn.onclick = async () => {
            const q = askInput.value.trim();
            if (!q) return;
            askInput.value = "";

            const msgs = document.getElementById("doc-chat-messages");
            msgs.innerHTML += `<div class="msg user">${escapeHtml(q)}</div>`;
            msgs.scrollTop = msgs.scrollHeight;

            const loadId = "loading-doc-" + Date.now();
            msgs.innerHTML += `<div class="msg agent" id="${loadId}">Searching vector database...</div>`;
            msgs.scrollTop = msgs.scrollHeight;

            try {
                const r = await app.apiFetch(`${AGENT_URL}/agent/query-indexed-document`, {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        ...this.getAuthHeaders()
                    },
                    body: JSON.stringify({ tender_number: tenderNumber, question: q })
                });
                const d = await r.json();
                document.getElementById(loadId).innerHTML = parseMarkdown(d.answer);
                msgs.scrollTop = msgs.scrollHeight;
            } catch {
                document.getElementById(loadId).innerHTML = "Error querying the document.";
            }
        };

        askInput.onkeypress = (e) => {
            if (e.key === "Enter") askBtn.click();
        };
    },

    async indexDocument(tenderNumber, docUrl, btn) {
        const originalText = btn.innerHTML;
        btn.innerHTML = "Indexing...";
        btn.disabled = true;
        btn.style.opacity = "0.7";

        try {
            const r = await app.apiFetch(`${AGENT_URL}/agent/index-document`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    ...this.getAuthHeaders()
                },
                body: JSON.stringify({ tender_number: tenderNumber, document_url: docUrl })
            });
            const d = await r.json();

            if (d.status === "success") {
                btn.innerHTML = "✓ Indexed";
                btn.style.background = "var(--primary)";

                const msgs = document.getElementById("doc-chat-messages");
                msgs.innerHTML += `<div class="msg agent">Document indexed successfully into the vector database (${d.chunks_indexed} chunks). You can now ask me specific questions.</div>`;
                msgs.scrollTop = msgs.scrollHeight;
            } else {
                throw new Error(d.detail || "Indexing failed");
            }
        } catch (err) {
            btn.innerHTML = "Failed";
            setTimeout(() => { btn.innerHTML = originalText; btn.disabled = false; btn.style.opacity = "1"; }, 2000);
            alert("Failed to index: " + err.message);
        }
    },

    /* ---------------- PROPOSAL ---------------- */

    openProposalBuilder() {
        this.openModal("proposal-modal");
        const editor = document.getElementById("proposal-text");
        editor.value = "Drafting with AI (Ollama)... This may take 30-60 seconds.";

        if (!this.state.matches || this.state.matches.length === 0) {
            editor.value = "Upload your business documents on Tender Scrapper (Business Documents) first, so the AI knows which tender to draft for.";
            return;
        }

        const tenderNumber = this.state.matches[0].tender_number;
        this.generateProposalText(tenderNumber);
    },

    async generateProposalText(tenderNumber) {
        const editor = document.getElementById("proposal-text");
        try {
            const res = await app.apiFetch(`${AGENT_URL}/agent/generate-proposal`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    ...this.getAuthHeaders()
                },
                body: JSON.stringify({ tender_number: tenderNumber, profile_id: this.state.profileId })
            });

            if (!res.ok) throw new Error("API Error");
            const data = await res.json();
            editor.value = data.proposal || "No proposal generated.";
        } catch {
            editor.value = "Error generating proposal. Make sure the backend is running and the tender exists.";
        }
    },

    copyProposal() {
        const editor = document.getElementById("proposal-text");
        editor.select();
        document.execCommand("copy");
        alert("Proposal copied to clipboard!");
    },

    /* ---------------- COMMAND PALETTE ---------------- */

    initCmdPalette() {
        const palette = document.getElementById("cmd-palette");
        const input = document.getElementById("cmd-input");

        document.addEventListener("keydown", (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === "k") {
                e.preventDefault();
                palette.classList.add("active");
                input.focus();
            }
            if (e.key === "Escape") palette.classList.remove("active");
        });

        document.querySelectorAll(".cmd-item").forEach(item => {
            item.addEventListener("click", () => {
                const action = item.dataset.action;
                palette.classList.remove("active");
                if (action === "documents") window.location.href = mainSiteUrl(window.location, "onboarding.html");
                if (action === "tenders") document.querySelector('[data-target="view-tenders"]').click();
                if (action === "profile") document.querySelector('[data-target="view-profile"]').click();
            });
        });
    },

    openCmdPalette() {
        document.getElementById("cmd-palette").classList.add("active");
        document.getElementById("cmd-input").focus();
    },

    /* ---------------- MODALS (a11y + scroll lock) ---------------- */

    initModalA11y() {
        const overlays = document.querySelectorAll(".modal-overlay");
        overlays.forEach(overlay => {
            overlay.addEventListener("click", (e) => {
                if (e.target === overlay) {
                    overlay.classList.remove("active");
                    document.body.classList.remove("no-scroll");
                }
            });
        });

        document.addEventListener("keydown", (e) => {
            if (e.key !== "Escape") return;
            let closed = false;
            overlays.forEach(o => {
                if (o.classList.contains("active")) {
                    o.classList.remove("active");
                    closed = true;
                }
            });
            if (closed) document.body.classList.remove("no-scroll");
        });
    },

    openModal(id) {
        document.getElementById(id).classList.add("active");
        document.body.classList.add("no-scroll");
    },

    closeModal(id) {
        document.getElementById(id).classList.remove("active");
        document.body.classList.remove("no-scroll");
    }
};

window.addEventListener("DOMContentLoaded", () => app.init());