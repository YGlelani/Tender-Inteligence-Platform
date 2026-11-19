import { CONFIG } from "./config.js";
import { esc } from "./utils.js";
import { getUsername } from "./shared-utils.js";

import { icon } from "./icons.js";
import {
    clientApi,
    cacheApi
} from "./api.js";
import { saveTenderButton, enableSaveTenderButtons } from "./save-tender.js";

enableSaveTenderButtons();


const $ = (id) =>
    document.getElementById(id);


/*
    Protect the page.
*/

function protectPage() {

    const token =
        localStorage.getItem(
            "access_token"
        );


    if (!token) {

        window.location.replace(
            CONFIG.services.loginFrontend
        );


        return false;
    }


    return true;
}



/*
    Get logged-in username.
*/




/*
    Format dates.
*/

function formatDate(value) {

    if (!value) {
        return "—";
    }


    const date =
        new Date(value);


    if (
        Number.isNaN(
            date.getTime()
        )
    ) {

        return String(value);

    }


    return date.toLocaleString(
        undefined,
        {
            year: "numeric",
            month: "short",
            day: "2-digit",
            hour: "2-digit",
            minute: "2-digit"
        }
    );

}



/*
    Get the tender number.
*/

function getTenderNumber(
    tender
) {

    return (
        tender?.tender_number ??
        tender?.reference_number ??
        tender?.reference ??
        tender?.number ??
        tender?.id ??
        "—"
    );

}



/*
    Get title.
*/

function getTenderTitle(
    tender
) {

    return (
        tender?.title ??
        tender?.name ??
        "Untitled tender"
    );

}



/*
    Extract a tender from
    different API response formats.
*/

function extractTender(
    data,
    number
) {

    if (!data) {
        return null;
    }


    /*
        Direct object.
    */

    if (
        !Array.isArray(data) &&
        typeof data === "object"
    ) {

        /*
            Some APIs return:

            {
                tender: {...}
            }
        */

        if (
            data.tender &&
            typeof data.tender === "object"
        ) {

            return data.tender;

        }


        /*
            Some APIs return:

            {
                data: {...}
            }
        */

        if (
            data.data &&
            typeof data.data === "object" &&
            !Array.isArray(data.data)
        ) {

            if (
                data.data.tender
            ) {

                return data.data.tender;

            }


            if (
                data.data.tender_number ||
                data.data.reference_number ||
                data.data.title
            ) {

                return data.data;

            }

        }


        /*
            If this itself looks
            like a tender.
        */

        if (
            data.tender_number ||
            data.reference_number ||
            data.title ||
            data.name
        ) {

            return data;

        }

    }


    /*
        Array response.
    */

    const items =
        Array.isArray(data)

            ? data

            : Array.isArray(data.tenders)

                ? data.tenders

                : Array.isArray(data.items)

                    ? data.items

                    : Array.isArray(data.results)

                        ? data.results

                        : Array.isArray(data.data)

                            ? data.data

                            : Array.isArray(
                                data.data?.tenders
                            )

                                ? data.data.tenders

                                : [];


    if (!items.length) {
        return null;
    }


    return (
        items.find(
            item =>
                String(
                    getTenderNumber(item)
                ) ===
                String(number)
        ) ||
        items[0]
    );

}



/*
    Get tender from Cache API
    or Client API.
*/

async function fetchTender(
    number
) {

    /*
        Try exact Cache API endpoint.
    */

    try {

        const data =
            await cacheApi.tender(
                number
            );


        const tender =
            extractTender(
                data,
                number
            );


        if (tender) {

            return tender;

        }

    } catch (error) {

        console.warn(
            "Cache API tender request failed:",
            error
        );

    }



    /*
        Try exact Client API endpoint.
    */

    try {

        const data =
            await clientApi.detail(
                number
            );


        const tender =
            extractTender(
                data,
                number
            );


        if (tender) {

            return tender;

        }

    } catch (error) {

        console.warn(
            "Client API tender request failed:",
            error
        );

    }



    /*
        Try Cache search.
    */

    try {

        const data =
            await cacheApi.search(
                number,
                {
                    limit: 10
                }
            );


        const tender =
            extractTender(
                data,
                number
            );


        if (tender) {

            return tender;

        }

    } catch (error) {

        console.warn(
            "Cache search failed:",
            error
        );

    }



    /*
        Try Client search.
    */

    try {

        const data =
            await clientApi.search(
                number,
                {
                    limit: 10
                }
            );


        const tender =
            extractTender(
                data,
                number
            );


        if (tender) {

            return tender;

        }

    } catch (error) {

        console.warn(
            "Client search failed:",
            error
        );

    }


    return null;

}



/*
    Get a field using several
    possible database names.
*/

function firstValue(
    object,
    keys,
    fallback = ""
) {

    for (
        const key of keys
    ) {

        if (
            object?.[key] !== undefined &&
            object?.[key] !== null &&
            object?.[key] !== ""
        ) {

            return object[key];

        }

    }


    return fallback;

}



/*
    Status CSS class.
*/

function getStatusClass(
    status
) {

    const value =
        String(
            status ?? ""
        )
        .toLowerCase()
        .trim();


    if (
        value.includes("open") ||
        value.includes("active") ||
        value.includes("published")
    ) {

        return "open";

    }


    if (
        value.includes("closed") ||
        value.includes("expired") ||
        value.includes("cancel")
    ) {

        return "closed";

    }


    return "";

}



/*
    Get documents.

    Supports several possible
    database/API field names.
*/

function getDocuments(
    tender
) {

    const possible =
        tender?.document_urls ??
        tender?.documents ??
        tender?.documentUrls ??
        tender?.attachments ??
        [];


    if (
        !Array.isArray(possible)
    ) {

        return [];

    }


    return possible;

}



/*
    Convert a document item
    into a usable URL.
*/

function getDocumentUrl(
    document
) {

    if (
        typeof document === "string"
    ) {

        return document;

    }


    if (
        document &&
        typeof document === "object"
    ) {

        return (
            document.url ??
            document.document_url ??
            document.download_url ??
            document.downloadUrl ??
            ""
        );

    }


    return "";

}



/*
    Get document name.
*/

function getDocumentName(
    document,
    index
) {

    if (
        document &&
        typeof document === "object"
    ) {

        const name =
            document.name ??
            document.filename ??
            document.file_name ??
            document.title;


        if (name) {
            return name;
        }

    }


    const url =
        getDocumentUrl(
            document
        );


    if (url) {

        try {

            const parsed =
                new URL(url);


            const filename =
                parsed.pathname
                    .split("/")
                    .filter(Boolean)
                    .pop();


            if (filename) {

                return decodeURIComponent(
                    filename
                );

            }

        } catch {}

    }


    return `Document ${index + 1}`;

}



/*
    Render tender header.
*/

function renderHeader(
    tender
) {

    const number =
        getTenderNumber(
            tender
        );


    const title =
        getTenderTitle(
            tender
        );


    const status =
        firstValue(
            tender,
            [
                "status",
                "tender_status"
            ]
        );


    const description =
        firstValue(
            tender,
            [
                "description",
                "scope",
                "summary",
                "brief_description"
            ]
        );


    const statusClass =
        getStatusClass(
            status
        );


    const header =
        $("detailHeader");


    if (!header) {
        return;
    }


    header.innerHTML = `

        <div
            class="detail-header-top">


            <span
                class="tender-number">

                ${esc(number)}

            </span>


            ${
                status

                    ? `

                        <span
                            class="tender-status ${statusClass}">

                            ${esc(status)}

                        </span>

                      `

                    : ""

            }


        </div>



        <h1
            class="detail-title">

            ${esc(title)}

        </h1>



        ${
            description

                ? `

                    <p
                        class="detail-description">

                        ${esc(description)}

                    </p>

                  `

                : ""

        }

        <div class="detail-header-actions" id="detailHeaderActions"></div>

    `;

    renderSaveButton(tender, number);


    document.title =
        `${number} - TenderScraping`;

}


/*
    Save tender button. If the loaded tender has no database id,
    save-tender.js looks it up by tender number when clicked.
*/

function renderSaveButton(
    tender,
    number
) {

    const box = $("detailHeaderActions");
    if (!box) return;

    box.innerHTML = saveTenderButton({
        id: tender?.id ?? tender?.tender_id,
        number,
        closingDate: firstValue(tender, ["closing_date", "closing_at", "close_date", "deadline"])
    }, "btn-primary");

}



/*
    Render tender information cards.
*/

function renderDetails(
    tender
) {

    const organisation =
        firstValue(
            tender,
            [
                "organisation_name",
                "organization_name",
                "organisation",
                "organization",
                "department",
                "entity_name"
            ]
        );


    const province =
        firstValue(
            tender,
            [
                "province",
                "province_name"
            ]
        );


    const category =
        firstValue(
            tender,
            [
                "category_name",
                "category",
                "category_description"
            ]
        );


    const published =
        firstValue(
            tender,
            [
                "published_date",
                "published_at",
                "publication_date",
                "created_at"
            ]
        );


    const closing =
        firstValue(
            tender,
            [
                "closing_date",
                "closing_at",
                "close_date",
                "deadline"
            ]
        );


    const briefing =
        firstValue(
            tender,
            [
                "briefing_date",
                "briefing_at"
            ]
        );


    const briefingVenue =
        firstValue(
            tender,
            [
                "briefing_venue",
                "briefing_location"
            ]
        );


    const contactName =
        firstValue(
            tender,
            [
                "contact_name",
                "contact_person"
            ]
        );


    const contactPhone =
        firstValue(
            tender,
            [
                "contact_telephone",
                "contact_phone",
                "phone"
            ]
        );


    const contactEmail =
        firstValue(
            tender,
            [
                "contact_email",
                "email"
            ]
        );


    const estimatedValue =
        firstValue(
            tender,
            [
                "estimated_value",
                "value",
                "budget"
            ]
        );


    const fields = [

        [
            "Organisation",
            organisation
        ],

        [
            "Province",
            province
        ],

        [
            "Category",
            category
        ],

        [
            "Published",
            published
                ? formatDate(published)
                : ""
        ],

        [
            "Closing Date",
            closing
                ? formatDate(closing)
                : ""
        ],

        [
            "Briefing Date",
            briefing
                ? formatDate(briefing)
                : ""
        ],

        [
            "Briefing Venue",
            briefingVenue
        ],

        [
            "Contact Person",
            contactName
        ],

        [
            "Contact Phone",
            contactPhone
        ],

        [
            "Contact Email",
            contactEmail
        ],

        [
            "Estimated Value",
            estimatedValue
        ]

    ];


    const visibleFields =
        fields.filter(
            ([, value]) =>
                value !== undefined &&
                value !== null &&
                value !== ""
        );


    const grid =
        $("detailGrid");


    if (!grid) {
        return;
    }


    if (!visibleFields.length) {

        grid.innerHTML = `

            <div
                class="detail-card">

                <div
                    class="detail-card-value">

                    No additional tender
                    information is available.

                </div>

            </div>

        `;


        return;
    }


    grid.innerHTML =
        visibleFields
            .map(
                ([label, value]) => `

                    <div
                        class="detail-card">


                        <div
                            class="detail-card-label">

                            ${esc(label)}

                        </div>


                        <div
                            class="detail-card-value">

                            ${esc(value)}

                        </div>


                    </div>

                `
            )
            .join("");

}



/*
    Render documents.
*/

function renderDocuments(
    tender
) {

    const section =
        $("detailDocsSection");


    const list =
        $("docList");


    if (
        !section ||
        !list
    ) {

        return;
    }


    const documents =
        getDocuments(
            tender
        );


    const usableDocuments =
        documents.filter(
            document =>
                getDocumentUrl(
                    document
                )
        );


    section.hidden =
        false;


    if (
        !usableDocuments.length
    ) {

        list.innerHTML = `

            <li
                class="state-msg">

                No documents attached
                to this tender.

            </li>

        `;


        return;
    }


    list.innerHTML =
        usableDocuments
            .map(
                (document, index) => {

                    const url =
                        getDocumentUrl(
                            document
                        );


                    const name =
                        getDocumentName(
                            document,
                            index
                        );


                    return `

                        <li
                            class="doc-item">


                            <span
                                class="doc-name">

                                ${esc(name)}

                            </span>


                            <a
                                class="doc-open"
                                href="${esc(url)}"
                                target="_blank"
                                rel="noopener noreferrer">

                                Open ${icon("external-link")}

                            </a>


                        </li>

                    `;

                }
            )
            .join("");

}



/*
    Render everything.
*/

function renderTender(
    tender
) {

    renderHeader(
        tender
    );


    renderDetails(
        tender
    );


    renderDocuments(
        tender
    );


    const number =
        getTenderNumber(
            tender
        );


    if (
        number &&
        number !== "—"
    ) {

        localStorage.setItem(
            "last_tender",
            String(number)
        );

    }

}



/*
    Setup username.
*/

function setupUser() {

    const username =
        getUsername();


    const user =
        $("currentUser");


    const avatar =
        $("userAvatar");


    if (user) {

        user.textContent =
            username;

    }


    if (avatar) {

        avatar.textContent =
            username
                .trim()
                .charAt(0)
                .toUpperCase() || "U";

    }

}



/*
    Load selected tender.

    If there is no URL number,
    use the last selected tender.
*/

async function load() {

    const params =
        new URLSearchParams(
            window.location.search
        );


    let number =
        params.get("number");


    if (number) {

        localStorage.setItem(
            "last_tender",
            number
        );

    } else {

        number =
            localStorage.getItem(
                "last_tender"
            );

    }


    /*
        No selected tender.

        Send the user to Feed.
    */

    if (!number) {

        window.location.replace(
            "./feed.html"
        );

        return;
    }


    const header =
        $("detailHeader");


    if (header) {

        header.innerHTML = `

            <h1 class="detail-title">Tender details</h1>

            <div
                class="state-msg">

                Loading tender details...

            </div>

        `;

    }


    try {

        const tender =
            await fetchTender(
                number
            );


        if (!tender) {

            throw new Error(
                `Tender "${number}" was not found.`
            );

        }


        renderTender(
            tender
        );


    } catch (error) {

        console.error(
            "Tender details error:",
            error
        );


        if (header) {

            header.innerHTML = `

                <h1 class="detail-title">Tender details</h1>

                <div
                    class="state-msg error">

                    <strong>
                        Could not load tender.
                    </strong>

                    <br>

                    ${esc(
                        error.message ||
                        "Unknown error"
                    )}

                    <br><br>

                    <a
                        href="./feed.html"
                        class="back-link">

                        ${icon("arrow-left")} Return to Tender Feed

                    </a>

                </div>

            `;

        }


        const grid =
            $("detailGrid");


        if (grid) {

            grid.innerHTML =
                "";

        }

    }

}



/*
    Start.
*/

function start() {

    if (
        !protectPage()
    ) {

        return;
    }


    setupUser();


    load();

}


start();