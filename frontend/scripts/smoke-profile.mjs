// Checks that My profile's company details are read-only: they are built from the user's
// business documents by the profile service, so the page offers no way to type, save or delete them.
import assert from "node:assert";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { emptyHint, finishedProcessing } from "./profile-sources.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const html = fs.readFileSync(path.join(root, "profile.html"), "utf8");
const form = (html.match(/<form id="profileForm">([\s\S]*?)<\/form>/) || ["", ""])[1];
assert.ok(form, "the company form is on the page");

for (const id of ["saveProfile", "deleteCompanyProfile", "deleteCompanyDialog", "fillFromDocuments", "categoryInput", "keywordInput"]) {
    assert.ok(!html.includes(`id="${id}"`), `#${id} must be gone: company details are not typed, saved or deleted`);
}
assert.ok(html.includes('id="refreshFromDocuments"'), "an Update from documents button is offered");
assert.ok(html.includes("These details come from your business documents."), "the page says where the details come from");

for (const tag of form.match(/<(input|textarea)\b[^>]*>/g) || []) {
    const locked = tag.includes('type="checkbox"') ? / disabled\b/.test(tag) : / readonly\b/.test(tag);
    assert.ok(locked, `form field must be read-only: ${tag.slice(0, 80)}`);
}
for (const tag of form.match(/<select\b[^>]*>/g) || []) {
    assert.ok(/ disabled\b/.test(tag), `select must be disabled: ${tag.slice(0, 80)}`);
}

assert.strictEqual(emptyHint("csd_number"), "Upload your CSD report");
assert.strictEqual(emptyHint("categories"), "Upload your CSD report");
assert.strictEqual(emptyHint("vat_number"), "Not read from documents");

const api = fs.readFileSync(path.join(root, "scripts/api.js"), "utf8");
const profileApi = (api.match(/export const businessProfileApi = \{([\s\S]*?)\n\};/) || ["", ""])[1];
assert.ok(/\brefresh:/.test(profileApi), "businessProfileApi.refresh asks the service to rebuild the profile");
assert.ok(!/\b(create|update):/.test(profileApi), "businessProfileApi cannot send typed profiles");

// The Business Documents page refreshes the profile once its documents finish processing.
assert.strictEqual(finishedProcessing({ processing: true }, { processing: false }), true, "processing just finished");
assert.strictEqual(finishedProcessing(null, { processing: false }), false, "first load: nothing finished");
assert.strictEqual(finishedProcessing({ processing: true }, { processing: true }), false, "still processing");
assert.strictEqual(finishedProcessing({ processing: false }, { processing: false }), false, "nothing was processing");
const onboarding = fs.readFileSync(path.join(root, "scripts/onboarding.js"), "utf8");
assert.ok(/finishedProcessing\(/.test(onboarding) && /businessProfileApi\.refresh\(/.test(onboarding),
    "the Business Documents page refreshes the profile when processing finishes");

console.log("Profile smoke test passed");
