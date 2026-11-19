// Greets the user by first name on the overview.
(() => {
    const name = localStorage.getItem("username") || localStorage.getItem("user") || "";
    const target = document.getElementById("overviewGreetingName");
    if (target && name) {
        target.textContent = String(name).trim().split(/\s+/)[0].replace(/[<>]/g, "");
    }
})();
