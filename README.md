# OpenCTI GitHub Leak Incident Creator

This connector periodically searches GitHub code for sensitive keywords (e.g., company names, domains) using the GitHub Search API. When a new match is found and the corresponding file’s last commit is less than 30 days old, it creates a **Case Incident** in OpenCTI, allowing security teams to track possible leaks or exposed credentials.

## Features

- Searches GitHub code for multiple comma‑separated queries.
- Tracks already‑seen URLs to avoid duplicate incidents.
- Fetches the last commit date for each file; skips files older than 30 days.
- Creates OpenCTI `Case Incident` objects with medium severity and P2 priority.
- Fully configurable: search intervals, pagination, rate‑limit throttling.
- Persistent state using a `seen.json` file (mounted as a volume).

## Requirements

- An **OpenCTI** instance (accessible via URL and API token).
- A **GitHub personal access token** (with `repo` and `code search` permissions).
- Docker Engine and Docker Compose (recommended deployment).

## Configuration (Environment Variables)

| Variable | Description | Default / Example |
|----------|-------------|-------------------|
| `OPENCTI_URL` | URL of your OpenCTI instance | `http://opencti:8080` |
| `OPENCTI_TOKEN` | OpenCTI API token (required) | `2b3f...` |
| `GITHUB_TOKEN` | GitHub personal access token (required) | `ghp_...` |
| `QUERIES` | Comma‑separated search strings (e.g., domains, company names) | `tele.com,лидертелеком` |
| `PER_PAGE` | Results per page (max 100) | `100` |
| `MAX_PAGES` | Maximum number of pages to fetch per query | `10` |
| `COMMIT_DELAY` | Delay (seconds) between commit API calls to avoid secondary rate limits | `0.5` |
| `SEARCH_MIN_INTERVAL` | Minimum seconds between two search API calls (respects GitHub’s rate limit) | `6` |
| `INTERVAL` | Main loop sleep time (seconds) between full scan cycles | `3600` |
| `SEEN_FILE` | Path inside the container where `seen.json` is stored | `/app/seen.json` |

### Volume for persistent state

The `seen.json` file must be stored outside the container to survive restarts.  
Use a bind mount – for example:

```yaml
volumes:
  - /path/on/host/seen.json:/app/seen.json
```

Create an empty JSON file on the host before starting:
```bash
echo '{}' > /path/on/host/seen.json
```

## Building the Docker Image

Project structure:
.
── Dockerfile
── docker-compose.yml
── README.md
── src/
    ── githubbot_send_OpenCTI.py
    ── requirements.txt

Build the image:
```bash
docker build -t gitsearch/opencti-6.4.11:latest .
```

## Running with Docker Compose

1. Edit `docker-compose.yml` – set correct values for `OPENCTI_URL`, `OPENCTI_TOKEN`, `GITHUB_TOKEN`, and your `QUERIES`.
2. Ensure the `seen.json` file exists on the host and the volume path matches.
3. Start the container:
```bash
docker-compose up -d
```

Example `docker-compose.yml` (adjusted):
```yaml
version: "3"
services:
  githubbot:
    image: gitsearch/opencti-6.4.11:latest
    volumes:
      - /home/GitHubBot/seen.json:/app/seen.json
    environment:
      - OPENCTI_URL=http://opencti:8080
      - OPENCTI_TOKEN=your_token
      - GITHUB_TOKEN=${GITHUB_TOKEN}   # use environment variable or hardcode
      - QUERIES=tele.com,лидертелеком
      - PER_PAGE=100
      - MAX_PAGES=10
      - COMMIT_DELAY=0.5
      - SEARCH_MIN_INTERVAL=6
      - INTERVAL=3600
      - SEEN_FILE=/app/seen.json
    restart: always
    depends_on:
      opencti:
        condition: service_healthy
```

> **Note:** The connector always runs once immediately after startup, then follows the defined schedule.

## Deploying in Portainer

### Option 1: Import a pre‑built image

1. Build the image on a machine with Docker:
```bash
docker build -t gitsearch/opencti-6.4.11:latest .
docker save gitsearch/opencti-6.4.11:latest -o githubbot.tar
```

2. In Portainer, go to **Images** → **Import** and upload the `.tar` file.
3. Create a **Stack** with the `docker-compose.yml` content (adjust volumes and environment variables).

### Option 2: Build directly inside Portainer

1. In Portainer, navigate to **Images** → **Build image**.
2. Upload the `Dockerfile` and the `src/` folder (or point to a Git repository).
3. Tag the image (e.g., `gitsearch/opencti-6.4.11:latest`).
4. Go to **Stacks** → **Add stack**, paste the `docker-compose.yml` content, and deploy.

## Manual Testing (without Docker)

Install dependencies:
```bash
pip install -r src/requirements.txt
```

Set environment variables and run:
```bash
export OPENCTI_URL=http://localhost:8080
export OPENCTI_TOKEN=your_token
export GITHUB_TOKEN=ghp_...
export QUERIES=example.com
python src/githubbot_send_OpenCTI.py
```

## Logging

Logs are written to stdout. View them with:
```bash
docker logs githubbot
```

In Portainer, open the container’s **Logs** panel.

## Troubleshooting

- **No incidents created**:
    
    - Verify that `GITHUB_TOKEN` has the correct permissions (`repo`, `code search`).
        
    - Check that your queries actually return results (test manually with `curl` or GitHub’s web search).
        
    - Confirm that the last commit date is ≤ 30 days; older commits are ignored.
        
- **Rate limit errors**:  
    The bot automatically waits for rate limit resets. Adjust `SEARCH_MIN_INTERVAL` and `COMMIT_DELAY` if you see secondary rate limits.
    
- **`seen.json` not persisting**:  
    Ensure the host file path is correct and the volume is properly mounted. Check permissions – the container user (root) must be able to write to that file.
    
- **OpenCTI connection errors**:  
    Verify `OPENCTI_URL` and `OPENCTI_TOKEN`. The URL should be reachable from inside the container (no `localhost` unless using host networking).
