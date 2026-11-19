// Tender volume line chart on the Overview page.
//
// renderChart({
//     total: "2,666 tenders",
//     change: "-1.4%",          // shown in the pill
//     trend: "up" | "down" | "flat",
//     compare: "vs previous 30 days",
//     compareTitle: "2,703 tenders were published in the 30 days before",
//     values: [452, 398, ...],
//     labels: ["11 Oct", ...],  // under the chart
//     details: ["11–15 Oct", ...] // in the hover tooltip
// })

const SVG_W = 640;

const SVG_H = 260;

// Room on the left for the axis values, and a little on the right for the last point.
const PADDING_LEFT = 46;

const PADDING_RIGHT = 18;

// The plot runs from the top grid line (y=40) to the bottom one (y=220),
// matching the grid lines in dashboard.html.
const PLOT_TOP = 40;

const PLOT_BOTTOM = 220;

const GRID_STEPS = 3;


/** A round step for the axis, so the grid lines read 0, 150, 300, 450… */
function niceStep(max) {
    const raw = Math.max(1, max) / GRID_STEPS;
    const power = 10 ** Math.floor(Math.log10(raw));
    const scaled = raw / power;
    const nice = scaled <= 1 ? 1 : scaled <= 2 ? 2 : scaled <= 2.5 ? 2.5 : scaled <= 5 ? 5 : 10;
    return Math.max(1, Math.ceil(nice * power));
}


function $(id) {
    return document.getElementById(id);
}


function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, character => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[character]);
}


function hideTooltip() {
    const tooltip = $("chartTooltip");
    if (tooltip) tooltip.hidden = true;
    $("chartDots")?.querySelectorAll(".chart-point.active")
        .forEach(dot => dot.classList.remove("active"));
}


let chartState = null;


function showTooltip(index) {
    const tooltip = $("chartTooltip");
    if (!tooltip || !chartState || !chartState.points[index]) return;

    const point = chartState.points[index];
    const count = chartState.values[index];
    tooltip.innerHTML =
        `<span>${esc(chartState.details[index] ?? chartState.labels[index] ?? "")}</span>` +
        `<strong>${esc(count.toLocaleString())} tender${count === 1 ? "" : "s"}</strong>`;

    tooltip.style.left = `${(point.x / SVG_W) * 100}%`;
    tooltip.style.top = `${(point.y / SVG_H) * 100}%`;
    tooltip.classList.toggle("align-left", index === 0);
    tooltip.classList.toggle("align-right", index === chartState.points.length - 1 && index !== 0);
    tooltip.hidden = false;

    $("chartDots")?.querySelectorAll(".chart-point").forEach((dot, dotIndex) => {
        dot.classList.toggle("active", dotIndex === index);
    });
}


let hoverReady = false;

function setUpHover() {
    if (hoverReady) return;
    const wrap = document.querySelector(".overview-chart-wrap");
    if (!wrap) return;
    hoverReady = true;

    // Show the point closest to the mouse along the x axis.
    wrap.addEventListener("mousemove", event => {
        if (!chartState?.points.length) return;
        const box = wrap.getBoundingClientRect();
        const x = ((event.clientX - box.left) / box.width) * SVG_W;
        let nearest = 0;
        chartState.points.forEach((point, index) => {
            if (Math.abs(point.x - x) < Math.abs(chartState.points[nearest].x - x)) nearest = index;
        });
        showTooltip(nearest);
    });
    wrap.addEventListener("mouseleave", hideTooltip);

    // Keyboard: focus the chart and use the arrow keys.
    wrap.tabIndex = 0;
    wrap.addEventListener("keydown", event => {
        if (!chartState?.points.length) return;
        const active = [...($("chartDots")?.querySelectorAll(".chart-point") || [])]
            .findIndex(dot => dot.classList.contains("active"));
        if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
            event.preventDefault();
            const step = event.key === "ArrowRight" ? 1 : -1;
            const next = active < 0 ? 0 : Math.min(chartState.points.length - 1, Math.max(0, active + step));
            showTooltip(next);
        } else if (event.key === "Escape") {
            hideTooltip();
        }
    });
    wrap.addEventListener("blur", hideTooltip);
}


export function renderChart(data) {

    const values = Array.isArray(data.values) ? data.values.map(value => Number(value) || 0) : [];
    const labels = Array.isArray(data.labels) ? data.labels : [];
    const details = Array.isArray(data.details) ? data.details : labels;

    if (!values.length) {
        renderChartError();
        return;
    }

    // Start the axis at zero so small changes are not exaggerated.
    const step = niceStep(Math.max(...values));
    const max = step * GRID_STEPS;

    const points = values.map((value, index) => ({
        x: values.length === 1
            ? SVG_W / 2
            : (index / (values.length - 1)) * (SVG_W - PADDING_LEFT - PADDING_RIGHT) + PADDING_LEFT,
        y: PLOT_BOTTOM - (value / max) * (PLOT_BOTTOM - PLOT_TOP)
    }));

    const linePath = points
        .map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`)
        .join(" ");

    const first = points[0];
    const last = points[points.length - 1];

    $("chartLine").setAttribute("d", linePath);
    $("chartArea").setAttribute(
        "d",
        `${linePath} L ${last.x} ${PLOT_BOTTOM} L ${first.x} ${PLOT_BOTTOM} Z`
    );

    $("chartDots").innerHTML = points
        .map((point, index) =>
            `<circle class="chart-point" cx="${point.x}" cy="${point.y}" r="5">` +
            `<title>${esc(details[index] ?? labels[index] ?? "")}: ${values[index].toLocaleString()} tenders</title>` +
            `</circle>`)
        .join("");

    // Values for the grid lines, top to bottom.
    const scale = $("chartScale");
    if (scale) {
        const gridY = [PLOT_TOP, PLOT_TOP + (PLOT_BOTTOM - PLOT_TOP) / 3, PLOT_TOP + (2 * (PLOT_BOTTOM - PLOT_TOP)) / 3];
        scale.innerHTML = gridY
            .map((y, index) =>
                `<span style="top:${(y / SVG_H) * 100}%">${(step * (GRID_STEPS - index)).toLocaleString()}</span>`)
            .join("");
    }

    const labelBox = $("chartLabels");
    labelBox.style.setProperty("--chart-cols", labels.length || 1);
    labelBox.innerHTML = labels.map(label => `<span>${esc(label)}</span>`).join("");

    $("chartTotal").textContent = data.total ?? "—";

    const change = String(data.change ?? "");
    const trend = $("chartTrend");
    trend.textContent = change || "—";
    const direction = data.trend
        ?? (change.startsWith("+") ? "up" : change.startsWith("-") ? "down" : "flat");
    trend.className = `trend ${direction === "up" ? "positive" : direction === "down" ? "negative" : "neutral"}`;
    trend.title = data.compareTitle ?? "";

    const compare = $("chartCompare");
    if (compare) {
        compare.textContent = data.compare ?? "";
        compare.title = data.compareTitle ?? "";
    }

    chartState = { points, values, labels, details };
    hideTooltip();
    setUpHover();
}


export function renderChartError() {

    chartState = null;
    hideTooltip();

    $("chartTotal").textContent = "—";
    const trend = $("chartTrend");
    trend.textContent = "Unavailable";
    trend.className = "trend neutral";
    trend.title = "";

    const compare = $("chartCompare");
    if (compare) compare.textContent = "";

    const scale = $("chartScale");
    if (scale) scale.innerHTML = "";

    $("chartLine").setAttribute("d", "");
    $("chartArea").setAttribute("d", "");
    $("chartDots").innerHTML = "";
    $("chartLabels").innerHTML = "";
}
