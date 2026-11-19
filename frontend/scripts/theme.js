// One light / dark mode for every Tender Scrapper page.
//
// Load it in <head>, before the stylesheets, so the page never flashes the
// wrong colours:  <script src="scripts/theme.js"></script>
//
// - The choice is saved under "tenderScrapperTheme" and shared by every page
//   on this address, including other open tabs.
// - With no saved choice, pages follow the device setting (light or dark).
// - Pages on other ports (like the sign-up page) have their own storage, so
//   links to them carry the theme as ?theme=light|dark; tsTheme.link() adds it,
//   and a page opened with ?theme= adopts and saves it.
(function () {
    var KEY = "tenderScrapperTheme";
    var media = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

    function read() {
        try {
            var value = localStorage.getItem(KEY);
            return value === "light" || value === "dark" ? value : null;
        } catch (error) {
            return null;
        }
    }

    function write(theme) {
        try {
            localStorage.setItem(KEY, theme);
        } catch (error) {
            // Private browsing can block storage; the theme still applies to this page.
        }
    }

    try {
        var fromLink = new URLSearchParams(window.location.search).get("theme");
        if (fromLink === "light" || fromLink === "dark") write(fromLink);
    } catch (error) {
        // Old browsers without URLSearchParams keep the saved theme.
    }

    function current() {
        return read() || (media && media.matches ? "dark" : "light");
    }

    function apply(theme) {
        var root = document.documentElement;
        root.dataset.theme = theme;
        root.style.colorScheme = theme;
        if (document.body) document.body.dataset.theme = theme;
        document.dispatchEvent(new CustomEvent("tstheme", { detail: { theme: theme } }));
    }

    window.tsTheme = {
        get: current,
        set: function (theme) {
            if (theme !== "light" && theme !== "dark") return;
            write(theme);
            apply(theme);
        },
        toggle: function () {
            var next = current() === "dark" ? "light" : "dark";
            this.set(next);
            return next;
        },
        // Add the current theme to a link that goes to another port.
        link: function (url) {
            try {
                var target = new URL(url, window.location.href);
                target.searchParams.set("theme", current());
                return target.href;
            } catch (error) {
                return url;
            }
        }
    };

    apply(current());

    // Follow the device setting until the user picks a theme.
    if (media) {
        var follow = function () {
            if (!read()) apply(current());
        };
        if (media.addEventListener) media.addEventListener("change", follow);
        else if (media.addListener) media.addListener(follow);
    }

    // Another tab changed the theme.
    window.addEventListener("storage", function (event) {
        if (event.key === KEY) apply(current());
    });

    // <body> did not exist yet when this first ran.
    document.addEventListener("DOMContentLoaded", function () {
        apply(current());
    });
})();
