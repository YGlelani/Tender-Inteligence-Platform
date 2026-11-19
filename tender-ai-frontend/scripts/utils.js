function escapeHtml(s) {
    if (!s) return "";
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
}

function parseMarkdown(text) {
    if (!text) return "";
    let html = escapeHtml(text);
    html = html.replace(/^### (.*$)/gim, '<h4>$1</h4>');
    html = html.replace(/^## (.*$)/gim, '<h3>$1</h3>');
    html = html.replace(/^# (.*$)/gim, '<h2>$1</h2>');
    html = html.replace(/\*\*(.*?)\*\*/gim, '<strong>$1</strong>');
    html = html.replace(/^\s*-\s(.*$)/gim, '<li>$1</li>');
    html = html.replace(/<\/li>\n<li>/g, '</li><li>');
    html = html.replace(/<li>(.*)<\/li>/g, '<ul><li>$1</li></ul>');
    return html.replace(/\n$/gim, '<br />');
}
// The main Tender Scrapper site runs on the same server as this AI workspace, on port 8009
// (staging sets another port in scripts/runtime-config.js as window.APP_CONFIG.MAIN_SITE_PORT).
// Business documents are uploaded there only, on its Business Documents page (onboarding.html).
function mainSiteUrl(location, page = "dashboard.html") {
    const port = (window.APP_CONFIG && window.APP_CONFIG.MAIN_SITE_PORT) || 8009;
    return `${location.protocol}//${location.hostname}:${port}/${page}`;
}
