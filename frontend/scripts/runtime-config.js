// Default: no overrides, so the pages use the visitor's host name and the production ports.
// The container replaces this file at start-up (docker-entrypoint.d/40-runtime-config.sh);
// staging sets USER_SERVER_IP and FRONTEND_SERVICE_PORTS there.
window.APP_CONFIG = Object.assign(window.APP_CONFIG || {}, {});
