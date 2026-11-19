// Default: no overrides, so app.js uses the addresses written into it at build time.
// The container replaces this file at start-up (docker-entrypoint.d/40-runtime-config.sh);
// staging sets AGENT_URL, LOGIN_URL and MAIN_SITE_PORT there.
window.APP_CONFIG = Object.assign(window.APP_CONFIG || {}, {});
