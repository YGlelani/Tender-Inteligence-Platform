import { icon } from "./icons.js";
// Adds the profile-match panel without replacing the dashboard markup owned by dashboard.html.
// Keeping this enhancement additive prevents dashboard sections and IDs from being destroyed.
const page = document.querySelector(".overview-page");
if (page && !document.getElementById("topMatchCards")) {
  const section = document.createElement("section");
  section.className = "overview-panel overview-matches-panel";
  section.innerHTML = `<div class="overview-panel-heading"><div><span class="overview-section-kicker">PERSONALISED</span><h2>Your top matches</h2><p>Opportunities matched to your business profile</p></div><a class="overview-text-link" href="./alerts.html">View all matches <span>${icon("arrow-right")}</span></a></div><div id="topMatchCards" class="overview-match-grid"><p class="state-msg">Loading your top matches…</p></div>`;
  const footer = page.querySelector(".overview-footer");
  if (footer) page.insertBefore(section, footer);
  else page.appendChild(section);
}
