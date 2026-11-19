function renderStrategyModal(strategy, tenderNumber) {
    const prob = Math.min(85, Math.max(5, strategy.suitability_score || 0));
    const r = 50, circ = 2 * Math.PI * r;
    const off = circ * (1 - prob / 100);
    const color = prob >= 60 ? 'var(--success)' : prob >= 30 ? 'var(--warning)' : 'var(--danger)';

    const hero = `
        <div style="display:flex; gap:32px; align-items:center; margin-bottom:32px; padding-bottom:32px; border-bottom:1px solid var(--border);">
            <div style="position:relative; width:120px; height:120px; display:flex; align-items:center; justify-content:center;">
                <svg width="120" height="120" style="transform:rotate(-90deg);">
                    <circle cx="60" cy="60" r="${r}" stroke="var(--border)" stroke-width="10" fill="none" />
                    <circle cx="60" cy="60" r="${r}" stroke="${color}" stroke-width="10" fill="none" stroke-dasharray="${circ}" stroke-dashoffset="${off}" stroke-linecap="round" />
                </svg>
                <div style="position:absolute; font-size:28px; font-weight:700;">${prob}%</div>
            </div>
            <div>
                <div style="font-size:12px; color:var(--text-muted); font-weight:700; text-transform:uppercase;">Bid Strategy</div>
                <h2 style="font-size:24px; margin:4px 0 8px 0;">${escapeHtml(tenderNumber)}</h2>
                <span style="background:var(--primary-light); color:var(--primary); padding:4px 12px; border-radius:99px; font-size:12px; font-weight:600;">${escapeHtml(strategy.industry_detected || "General")}</span>
            </div>
        </div>
    `;

    const grid = `
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:24px;">
            <div>
                <h4 style="margin-bottom:12px;">Requirements</h4>
                <ul style="font-size:13px; color:var(--text-muted); padding-left:16px; display:flex; flex-direction:column; gap:8px;">
                    ${(strategy.key_requirements || []).map(r => `<li>${escapeHtml(r)}</li>`).join("")}
                </ul>
            </div>
            <div>
                <h4 style="margin-bottom:12px;">Winning Strategy</h4>
                <ul style="font-size:13px; color:var(--text-muted); padding-left:16px; display:flex; flex-direction:column; gap:8px;">
                    ${(strategy.winning_strategy || []).map(r => `<li>${escapeHtml(r)}</li>`).join("")}
                </ul>
            </div>
        </div>
    `;

    return `${hero}${grid}`;
}