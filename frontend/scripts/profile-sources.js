/**
 * Which business document each company profile value comes from. The profile service
 * builds the profile from the user's processed documents, so My profile shows these
 * values read-only and points to the document to upload when one is missing.
 */
export const FIELD_SOURCES = {
    business_name: "company registration certificate",
    registration_number: "company registration certificate",
    csd_number: "CSD report",
    bbbee_level: "B-BBEE certificate",
    cidb_grade: "CIDB certificate",
    business_address: "proof of address",
    province: "proof of address",
    phone: "company profile document",
    services_offered: "company profile document",
    company_description: "company profile document",
    industry: "company profile document",
    provinces: "company profile document",
    keywords: "company profile document",
    categories: "CSD report"
};

export function emptyHint(key) {
    const source = FIELD_SOURCES[key];
    return source ? `Upload your ${source}` : "Not read from documents";
}

// True when the user's documents were being processed and now are not, so the company
// profile can be rebuilt from them.
export function finishedProcessing(before, after) {
    return Boolean(before?.processing) && !after?.processing;
}
