import { businessProfileApi, authApi } from "./api.js";
import { redirectToLogin } from "./shared-utils.js";
import { emptyHint, FIELD_SOURCES } from "./profile-sources.js";

// My profile. The company details are built from the user's business documents by the
// profile service (POST /profile/refresh), so this page only shows them, read-only. The
// User profile tab (the account name) stays editable.
const fields = {
  business_name: "businessName",
  registration_number: "registrationNumber",
  vat_number: "vatNumber",
  industry: "industry",
  province: "province",
  bbbee_level: "bbbeeLevel",
  cidb_grade: "cidbGrade",
  csd_number: "csdNumber",
  tender_email: "tenderEmail",
  phone: "phone",
  services_offered: "servicesOffered",
  business_address: "businessAddress",
  company_description: "companyDescription"
};

const lists = { categories: [], keywords: [] };
let accountEmail = "";
const provinceCheckboxes = [...document.querySelectorAll("#tenderProvinces input[type=checkbox]")];

// A read-only list of tags; when it is empty, it says which document fills it.
function renderTags(listId, values, key) {
  const list = document.getElementById(listId);
  list.replaceChildren(...(values.length ? values : [emptyHint(key)]).map(text => {
    const item = document.createElement("li");
    item.textContent = text;
    if (!values.length) item.className = "profile-tag-hint";
    return item;
  }));
}

function fillMatching(profile = {}) {
  const provinces = new Set((profile.provinces || []).map(value => String(value).toLowerCase()));
  provinceCheckboxes.forEach(box => {
    box.checked = provinces.has(box.value.toLowerCase());
  });
  lists.categories = [...(profile.categories || [])];
  lists.keywords = [...(profile.keywords || [])];
  renderTags("categoryTags", lists.categories, "categories");
  renderTags("keywordTags", lists.keywords, "keywords");
  document.getElementById("minTenderValue").value = profile.min_tender_value ?? "";
  document.getElementById("maxTenderValue").value = profile.max_tender_value ?? "";
}

// Empty fields say which document fills them.
function showEmptyHints() {
  for (const [key, id] of Object.entries(fields)) {
    const input = document.getElementById(id);
    if (!input || key === "tender_email") continue;
    if (input.tagName === "SELECT") input.options[0].textContent = emptyHint(key);
    else input.placeholder = emptyHint(key);
  }
  for (const id of ["minTenderValue", "maxTenderValue"]) document.getElementById(id).placeholder = "Any value";
}

const statusBox = document.getElementById("profileStatus");
const userForm = document.getElementById("userProfileForm");
const userSaveButton = document.getElementById("saveUserProfile");
const userStatusBox = document.getElementById("userProfileStatus");

function userStatus(message, kind = "") {
  userStatusBox.textContent = message;
  userStatusBox.className = "settings-status" + (kind ? " " + kind : "");
  userStatusBox.hidden = !message;
}

async function loadUserProfile() {
  try {
    const user = await authApi.userProfile();
    const displayName = user.full_name || user.username || "User";
    document.getElementById("accountName").value = user.full_name || user.username || "";
    const accountEmailCard = document.getElementById("profileAccountEmail");
    if (accountEmailCard) accountEmailCard.textContent = user.email || user.username || "Your Tender Scrapper account";
    const initial = displayName.trim().charAt(0).toUpperCase() || "U";
    const accountAvatarCard = document.getElementById("profileAccountAvatar");
    if (accountAvatarCard) accountAvatarCard.textContent = initial;
    document.querySelectorAll("#topbarUsername").forEach(el => el.textContent = displayName);
    document.querySelectorAll("#topbarAvatar").forEach(el => el.textContent = initial);
    accountEmail = user.email || "";
    document.getElementById("accountEmail").value = accountEmail;
    const tenderEmail = document.getElementById("tenderEmail");
    if (tenderEmail) tenderEmail.value = accountEmail;
    if (user.full_name) localStorage.setItem("username", user.full_name);
  } catch (error) {
    console.error("User profile load failed:", error);
    userStatus("Could not load your account details. Please refresh and try again.", "error");
  }
}

userForm.addEventListener("submit", async event => {
  event.preventDefault();
  if (!userForm.reportValidity()) return;
  const full_name = document.getElementById("accountName").value.trim();
  if (full_name.length < 2) {
    userStatus("Please enter your full name.", "error");
    return;
  }
  userSaveButton.disabled = true;
  userSaveButton.textContent = "Saving...";
  userStatus("");
  try {
    const saved = await authApi.updateUserProfile({ full_name });
    document.getElementById("accountName").value = saved.full_name || full_name;
    localStorage.setItem("username", saved.full_name || full_name);
    document.querySelectorAll("#topbarUsername").forEach(el => el.textContent = saved.full_name || full_name);
    document.querySelectorAll("#topbarAvatar").forEach(el => el.textContent = (saved.full_name || full_name).trim().charAt(0).toUpperCase());
    userStatus("User profile saved successfully.", "success");
  } catch (error) {
    console.error("User profile save failed:", error);
    userStatus("Could not save your name. Please try again.", "error");
  } finally {
    userSaveButton.disabled = false;
    userSaveButton.textContent = "Save user profile";
  }
});

function status(message, kind = "") {
  statusBox.textContent = message;
  statusBox.className = "settings-status" + (kind ? " " + kind : "");
  statusBox.hidden = !message;
}

function renderHero() {
  const name = document.getElementById("businessName").value.trim();
  const initials = name
    .replace(/\((pty|proprietary)\)|\b(ltd|limited|inc|cc)\b\.?/gi, "")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map(word => word[0].toUpperCase())
    .join("");
  document.getElementById("profileHeroName").textContent = name || "Your company";
  document.getElementById("profileHeroInitials").textContent = initials || "C";

  const industry = document.getElementById("industry").value;
  const province = document.getElementById("province").value;
  document.getElementById("profileHeroSummary").textContent =
    industry && province ? `${industry}, head office in ${province}`
      : industry || (province ? `Head office in ${province}` : "Upload your business documents to build your profile.");

  for (const [credentialId, fieldId] of Object.entries(CREDENTIALS)) {
    const value = document.getElementById(fieldId).value.trim();
    const cell = document.getElementById(credentialId);
    cell.textContent = value || "Not added";
    cell.classList.toggle("is-missing", !value);
  }

  renderReadiness();
}

// The supplier card's readiness bar and each collapsible section's
// "Complete" / "2 missing" label count the details below.
const CREDENTIALS = {
  credentialCsd: "csdNumber",
  credentialBbbee: "bbbeeLevel",
  credentialCidb: "cidbGrade",
  credentialVat: "vatNumber"
};

// Listed in the order the readiness hint suggests them: tender matching first.
const READINESS = [
  { section: "company", key: "industry", field: "industry" },
  { section: "alerts", key: "categories", list: "categories" },
  { section: "alerts", key: "keywords", list: "keywords" },
  { section: "about", key: "services_offered", field: "servicesOffered" },
  { section: "registration", key: "csd_number", field: "csdNumber" },
  { section: "registration", key: "bbbee_level", field: "bbbeeLevel" },
  { section: "registration", key: "registration_number", field: "registrationNumber" },
  { section: "company", key: "business_name", field: "businessName" },
  { section: "company", key: "province", field: "province" },
  { section: "contact", key: "phone", field: "phone" },
  { section: "contact", key: "business_address", field: "businessAddress" },
  { section: "about", key: "company_description", field: "companyDescription" }
];

const value = id => document.getElementById(id).value.trim();
const join = parts => parts.filter(Boolean).join(", ");
const rands = amount => "R" + Number(amount).toLocaleString("en-ZA", { maximumFractionDigits: 0 });
const count = (n, one, many) => `${n} ${n === 1 ? one : many}`;

// One line shown on each closed section, so the profile reads at a glance.
const RECAPS = {
  company: () => join([value("businessName"), value("industry"), value("province")]),
  registration: () => join([
    value("registrationNumber") && `CIPC ${value("registrationNumber")}`,
    value("csdNumber") && `CSD ${value("csdNumber")}`,
    value("bbbeeLevel") && `B-BBEE ${value("bbbeeLevel").replace(/^b-?bbee\s*/i, "")}`,
    value("vatNumber") && `VAT ${value("vatNumber")}`,
    value("cidbGrade") && `CIDB ${value("cidbGrade")}`
  ]),
  contact: () => join([value("phone"), value("businessAddress").replace(/\s+/g, " ")]),
  about: () => value("servicesOffered").replace(/\s+/g, " "),
  alerts: () => {
    const provinces = provinceCheckboxes.filter(box => box.checked).length;
    const min = value("minTenderValue");
    const max = value("maxTenderValue");
    return join([
      provinces ? count(provinces, "province", "provinces") : "All provinces",
      lists.categories.length && count(lists.categories.length, "category", "categories"),
      lists.keywords.length && count(lists.keywords.length, "keyword", "keywords"),
      (min || max) && `${min ? rands(min) : "R0"} to ${max ? rands(max) : "any value"}`
    ]);
  }
};

function isFilled(item) {
  return item.list ? lists[item.list].length > 0 : Boolean(value(item.field));
}

function renderReadiness() {
  const missing = READINESS.filter(item => !isFilled(item));
  const done = READINESS.length - missing.length;

  const bar = document.getElementById("profileReadinessBar");
  bar.setAttribute("aria-valuenow", String(done));
  document.getElementById("profileReadinessFill").style.width = `${(done / READINESS.length) * 100}%`;
  document.getElementById("profileReadinessText").textContent = missing.length
    ? `${done} of ${READINESS.length} details found in your documents.`
    : `All ${READINESS.length} details found in your documents.`;
  const next = document.getElementById("profileReadinessNext");
  next.hidden = !missing.length;
  next.textContent = missing.length ? `Next: upload your ${FIELD_SOURCES[missing[0].key]} on Business Documents.` : "";

  document.querySelectorAll("#profileForm details[data-section]").forEach(section => {
    const gaps = missing.filter(item => item.section === section.dataset.section).length;
    const check = section.querySelector("[data-check]");
    check.textContent = gaps ? `${gaps} missing` : "Complete";
    check.classList.toggle("is-complete", !gaps);
    section.querySelector("[data-recap]").textContent = RECAPS[section.dataset.section]() || "Nothing found yet";
  });
}

function openFirstIncompleteSection() {
  const sections = [...document.querySelectorAll("#profileForm details[data-section]")];
  const first = sections.find(section => !section.querySelector("[data-check]").classList.contains("is-complete"));
  if (first) first.open = true;
}

function fillProfile(profile = {}) {
  for (const [key, id] of Object.entries(fields)) {
    const input = document.getElementById(id);
    if (input && key !== "tender_email") input.value = profile[key] ?? "";
  }
  fillMatching(profile);
  showEmptyHints();
  renderHero();
}

function setupTabs() {
  const tabs = [
    ["companyTab", "companyPanel"],
    ["userTab", "userPanel"],
    ["notificationsTab", "notificationsPanel"]
  ];
  tabs.forEach(([tabId, panelId]) => {
    document.getElementById(tabId).addEventListener("click", () => {
      tabs.forEach(([otherTab, otherPanel]) => {
        const active = otherTab === tabId;
        document.getElementById(otherTab).classList.toggle("active", active);
        document.getElementById(otherTab).setAttribute("aria-selected", String(active));
        document.getElementById(otherPanel).hidden = !active;
      });
    });
  });
  // profile.html#notifications (linked from the bell) opens the Notifications tab.
  const openFromHash = () => {
    if (window.location.hash === "#notifications") document.getElementById("notificationsTab").click();
  };
  openFromHash();
  window.addEventListener("hashchange", openFromHash);
}

// Rebuilds the company profile from the documents, then shows it. When that is not
// possible, the last saved profile is shown with the reason.
async function loadProfile() {
  status("Checking your business documents...", "info");
  try {
    fillProfile(await businessProfileApi.refresh());
    status("");
    return;
  } catch (error) {
    console.warn("Company profile refresh failed:", error);
    const noDocuments = error.status === 409 && error.detail;
    status(noDocuments ? error.detail : "Your documents could not be checked right now. Please try again in a moment.",
      noDocuments ? "info" : "error");
  }
  try {
    fillProfile(await businessProfileApi.get());
  } catch (error) {
    if (error.status !== 404) console.error("Company profile load failed:", error);
    fillProfile({});
  }
}

const refreshButton = document.getElementById("refreshFromDocuments");
refreshButton.addEventListener("click", async () => {
  refreshButton.disabled = true;
  refreshButton.querySelector("span").textContent = "Updating...";
  await loadProfile();
  refreshButton.disabled = false;
  refreshButton.querySelector("span").textContent = "Update from documents";
});

document.getElementById("profileReadinessNext").addEventListener("click", () => {
  window.location.href = "./onboarding.html";
});

async function start() {
  if (!localStorage.getItem("access_token")) {
    redirectToLogin();
    return;
  }
  const username = localStorage.getItem("username") || localStorage.getItem("user") || "User";
  document.getElementById("accountName").value = username;
  document.getElementById("profileAccountName")?.replaceChildren(document.createTextNode(username));
  setupTabs();
  fillProfile({});
  await Promise.all([loadProfile(), loadUserProfile()]);
  openFirstIncompleteSection();
}

start();
