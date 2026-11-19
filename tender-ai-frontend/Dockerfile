FROM nginx:alpine

# Our server config: security headers, no version number, no hidden files.
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy only the site. COPY . . used to publish .git (with its config), the
# Dockerfile and the compose file.
RUN rm -rf /usr/share/nginx/html/*
COPY index.html THIRD_PARTY_NOTICES.md /usr/share/nginx/html/
COPY css /usr/share/nginx/html/css
COPY scripts /usr/share/nginx/html/scripts
COPY icons /usr/share/nginx/html/icons
COPY fonts /usr/share/nginx/html/fonts
COPY docker-entrypoint.sh /app-entrypoint.sh
RUN chmod 0755 /app-entrypoint.sh

# Writes scripts/runtime-config.js at start-up. Production sets no AGENT_URL,
# LOGIN_URL or MAIN_SITE_PORT, so its build-time addresses stay in force; staging
# sets them (compose.staging.yaml).
COPY docker-entrypoint.d/40-runtime-config.sh /docker-entrypoint.d/40-runtime-config.sh
RUN sed -i 's/\r$//' /docker-entrypoint.d/40-runtime-config.sh && chmod 755 /docker-entrypoint.d/40-runtime-config.sh

EXPOSE 80

ENTRYPOINT ["/app-entrypoint.sh"]
