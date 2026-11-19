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

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
