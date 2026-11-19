function buildTenderCard(tender) {
    const isZero = tender.score === 0;
    const scClass = tender.score >= 60 ? 'high' : tender.score >= 30 ? 'mid' : '';

    return `
        <div class="tender-card">
            <div class="tc-header">
                <span class="tc-number">${escapeHtml(tender.tender_number)}</span>
                <span class="tc-score ${scClass}">${tender.score}/100</span>
            </div>
            <div class="tc-title">${escapeHtml(tender.title)}</div>
            <div class="tc-org">${escapeHtml(tender.organisation || 'Unknown')}</div>
            <div class="tc-actions">
                <button type="button" onclick="app.showDocuments('${escapeHtml(tender.tender_number)}')" ${isZero ? 'disabled style="opacity:0.5; cursor:not-allowed;"' : ''}>Read Docs</button>
                <button type="button" class="primary" onclick="app.openProposalBuilder()" ${isZero ? 'disabled style="opacity:0.5; cursor:not-allowed;"' : ''}>Strategy</button>
            </div>
        </div>
    `;
}

// The Tender Board's cards: every match with a real tender number and a score, best first.
function boardMatches(matches) {
    return (matches || [])
        .filter(m => m.tender_number && m.tender_number !== "0/0" && Number(m.score) > 0)
        .sort((a, b) => Number(b.score) - Number(a.score));
}

// The Agent Assistant's status label, from the agent's /health answer (null when it could not be reached).
// The chat needs the AI model; other parts (such as meaning-based search) have fallbacks.
function agentStatus(health) {
    if (!health) return { label: "Offline", kind: "offline" };
    if (health.llm && health.llm.ok === false) return { label: "AI unavailable", kind: "warning" };
    return { label: "Online", kind: "online" };
}

function buildProfileView(profile) {
    if (!profile) return `<div class="empty-state">No profile uploaded yet.</div>`;
    const initials = (profile.business_name || "??").slice(0, 2).toUpperCase();
    return `
        <div style="display:flex; gap:24px; align-items:center; background:var(--bg-surface); padding:32px; border-radius:var(--radius-lg); border:1px solid var(--border); flex-wrap:wrap;">
            <div style="width:80px; height:80px; border-radius:16px; background:var(--primary); color:white; display:flex; align-items:center; justify-content:center; font-size:28px; font-weight:700; flex-shrink:0;">${initials}</div>
            <div style="min-width:0;">
                <h2 style="font-size:24px; margin-bottom:8px; word-break:break-word;">${escapeHtml(profile.business_name)}</h2>
                <p style="color:var(--text-muted); margin-bottom:12px; word-break:break-word;">Reg: ${escapeHtml(profile.registration_number || 'N/A')} • ${escapeHtml(profile.contact_email || 'No email')}</p>
                <div style="display:flex; gap:8px; flex-wrap:wrap;">
                    ${(profile.industries || []).map(i => `<span style="background:var(--bg-base); padding:4px 12px; border-radius:99px; font-size:12px; border:1px solid var(--border);">${escapeHtml(i)}</span>`).join("")}
                    ${(profile.service_areas || []).map(a => `<span style="background:var(--bg-base); padding:4px 12px; border-radius:99px; font-size:12px; border:1px solid var(--border);">${escapeHtml(a)}</span>`).join("")}
                </div>
            </div>
        </div>
    `;
}

// Radar axis (0 Services, 1 Province, 2 Industry, 3 Category) and points for each match reason.
// Matches come from Smart Alerts, or from the AI service when Smart Alerts has none; both wordings are listed.
const RADAR_REASONS = [
    ["Service match", 0, 15], ["Profile keyword match", 0, 15], ["Matches your business documents", 0, 15],
    ["Related to your keywords", 0, 10], ["Tender wording overlaps", 0, 10],
    ["Province match", 1, 20], ["In your head office province", 1, 20],
    ["Industry match", 2, 15], ["Industry from your business documents", 2, 15],
    ["Category matches", 3, 20], ["Category aligned", 3, 10],
];
const RADAR_MAX = [40, 20, 20, 20];

function radarValues(match) {
    const values = [0, 0, 0, 0];
    (match.reasons || []).forEach(reason => {
        const rule = RADAR_REASONS.find(([prefix]) => reason.startsWith(prefix));
        if (rule) values[rule[1]] += rule[2];
    });
    return values.map((value, axis) => Math.min(RADAR_MAX[axis], value));
}

// Keeps a single instance and a single debounced resize handler.
let _radarChart = null;
let _radarResizeTimer = null;

function initRadarChart(domId, matches) {
    const chartDom = document.getElementById(domId);
    if (!chartDom || !matches || matches.length === 0) return;

    if (chartDom.querySelector('.empty-state')) chartDom.innerHTML = '';

    if (_radarChart) {
        _radarChart.dispose();
        _radarChart = null;
    }
    _radarChart = echarts.init(chartDom);

    const indicators = [
        { name: 'Services', max: 40 },
        { name: 'Province', max: 20 },
        { name: 'Industry', max: 20 },
        { name: 'Category', max: 20 }
    ];

    const data = matches.slice(0, 3).map((m) => ({ value: radarValues(m), name: m.tender_number }));

    const option = {
        color: ['#206e98', '#10b981', '#f59e0b'],
        tooltip: {},
        radar: {
            indicator: indicators,
            radius: '65%',
            axisName: { color: 'var(--text-muted)', fontSize: 10 },
            splitLine: { lineStyle: { color: 'var(--border)' } },
            splitArea: { show: false },
            axisLine: { lineStyle: { color: 'var(--border)' } }
        },
        series: [{ type: 'radar', data: data }]
    };

    _radarChart.setOption(option);

    if (!initRadarChart._bound) {
        initRadarChart._bound = true;
        window.addEventListener('resize', () => {
            clearTimeout(_radarResizeTimer);
            _radarResizeTimer = setTimeout(() => { if (_radarChart) _radarChart.resize(); }, 150);
        });
    }
}