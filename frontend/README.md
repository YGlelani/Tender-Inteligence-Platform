# Tender Scrapper Frontend

The containerized frontend interface for the AI-Enhanced Tender Scraper system. This application provides a responsive, web-based UI for users to browse tender feeds, track applications, manage alerts, and save tenders. It is built with static web technologies and served efficiently via Nginx using Docker.

## Tech Stack

- **Frontend:** HTML5, CSS3, Vanilla JavaScript
- **Web Server:** Nginx 
- **Containerization:** Docker & Docker Compose

## Run Locally

Follow these steps to spin up the frontend environment on your local machine using Docker.

### Prerequisites
Make sure you have [Docker](https://docs.docker.com/get-docker/) and Docker Compose installed.

### Setup Instructions

1. **Create an environment file:**
   Create a local `.env` file in the root directory (this file is ignored by Git).
   ```bash
   touch .env
   Configure the port:
Set the USER_SERVER_PORT variable in your .env file to the host port where you want this frontend to be available. For example, to use port 8004:

Code snippet
USER_SERVER_PORT=8004

Start the frontend container:
Build and run the container in detached mode using Docker Compose:

Bash
docker compose up --build -d
Access the application:
Open http://localhost:<USER_SERVER_PORT> in your web browser (e.g., http://localhost:8004).

Configuration Details
API Routing: The frontend's API configuration dynamically uses the hostname from the page URL and the configured service ports defined in scripts/config.js.

Port Mapping: Compose's USER_SERVER_PORT controls only the host port mapped to the Nginx server; it does not configure the backend API service ports.

Security Warning: Do not put passwords, API tokens, or other private secrets in frontend environment variables. Browser configurations are publicly exposed to the client.

Project Structure
Plaintext
frontend/
|-- .github/                # GitHub Actions workflows and configurations
|-- css/                    # Stylesheets for the application
|-- scripts/                # JavaScript logic and API config (config.js)
|-- compose.yaml            # Docker Compose configuration for the frontend
|-- Dockerfile              # Docker image build instructions (Nginx setup)
|-- index.html              # Main landing page
|-- dashboard.html          # User analytics and overview dashboard
|-- feed.html               # Live tender feed
|-- application-tracker.html# Track ongoing tender applications
|-- alerts.html             # Notification and alert settings
|-- saved-tenders.html      # Bookmarked tenders
|-- login.html              # User authentication view
|-- onboarding.html         # New user setup flow
|-- profile.html            # User profile management
|-- privacy.html            # Privacy policy documentation
`-- script.js               # Global JavaScript functions
