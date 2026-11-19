FROM nginx:alpine

# Replaces the stock server block: security headers, no version number, no hidden files.
COPY nginx.conf /etc/nginx/conf.d/default.conf

COPY index.html /usr/share/nginx/html/index.html
COPY login.html /usr/share/nginx/html/login.html
COPY privacy.html /usr/share/nginx/html/privacy.html
COPY cookies.html /usr/share/nginx/html/cookies.html
COPY tender-hero.png /usr/share/nginx/html/tender-hero.png
COPY dashboard.html /usr/share/nginx/html/dashboard.html
COPY feed.html /usr/share/nginx/html/feed.html
COPY tender.html /usr/share/nginx/html/tender.html
COPY tender-search.html /usr/share/nginx/html/tender-search.html
COPY saved-tenders.html /usr/share/nginx/html/saved-tenders.html
COPY alerts.html /usr/share/nginx/html/alerts.html
COPY application-tracker.html /usr/share/nginx/html/application-tracker.html
COPY profile.html /usr/share/nginx/html/profile.html
COPY onboarding.html /usr/share/nginx/html/onboarding.html

COPY css /usr/share/nginx/html/css
COPY fonts /usr/share/nginx/html/fonts
COPY styles.css /usr/share/nginx/html/styles.css
COPY script.js /usr/share/nginx/html/script.js
COPY scripts /usr/share/nginx/html/scripts

# Licence notices for the icons and typeface, readable at /third-party-notices.txt.
COPY THIRD_PARTY_NOTICES.md /usr/share/nginx/html/third-party-notices.txt

EXPOSE 80
