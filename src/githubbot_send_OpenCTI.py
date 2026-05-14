import requests
import time
import json
import logging
import os
from datetime import datetime, timezone
from requests.exceptions import HTTPError

# переменные окружения
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
QUERIES = os.getenv("QUERIES", "").split(",")
PER_PAGE = int(os.getenv("PER_PAGE", 100))
MAX_PAGES = int(os.getenv("MAX_PAGES", 10))
COMMIT_DELAY = float(os.getenv("COMMIT_DELAY", 0.1))
SEARCH_MIN_INTERVAL = float(os.getenv("SEARCH_MIN_INTERVAL", 1))
INTERVAL = int(os.getenv("INTERVAL", 60))
SEEN_FILE = "/app/data/seen.json"

# --- OpenCTI настройки ---
OPENCTI_URL = os.getenv("OPENCTI_URL")
OPENCTI_TOKEN = os.getenv("OPENCTI_TOKEN")

def create_incident(domain: str, repo_url: str):
    """Создать Case Incident в OpenCTI через GraphQL API"""
    mutation = """
    mutation CaseIncidentAdd($input: CaseIncidentAddInput!) {
      caseIncidentAdd(input: $input) {
        id
        name
      }
    }
    """
    now = datetime.now(timezone.utc).isoformat()

    variables = {
        "input": {
            "name": f"Possible leak for {domain}",
            "description": f"Found on GitHub: {repo_url}",
            "severity": "medium",
            "priority": "P2",
            "created": now,
            "confidence": 70
        }
    }

    headers = {
        "Authorization": f"Bearer {OPENCTI_TOKEN}",
        "Content-Type": "application/json"
    }

    try:
        resp = requests.post(
            f"{OPENCTI_URL}graphql",
            headers=headers,
            json={"query": mutation, "variables": variables},
            timeout=30,
            proxies={"http": None, "https": None}
        )

        # Добавим вывод для отладки
        logging.info(f"OpenCTI HTTP {resp.status_code}: {resp.text}")
        data = resp.json()

        if "errors" in data:
            logging.error(f"OpenCTI API error: {data['errors']}")
        elif "data" in data and data["data"].get("caseIncidentAdd"):
            logging.info(f"✅ Incident created: {data['data']['caseIncidentAdd']['id']}")
        else:
            logging.error(f"Unexpected response: {data}")
    except Exception as e:
        logging.error(f"Error creating incident in OpenCTI: {e}")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)

class GitHubSearcher:
    MAX_RESULTS = 1000

    def __init__(self, token=None, per_page=100, max_pages=10, commit_delay=0.1):
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/vnd.github+json"})
        if token:
            self.session.headers.update({"Authorization": f"token {token}"})
        self.per_page = min(per_page, 100)
        self.max_pages_setting = max_pages
        self.commit_delay = commit_delay
        self._last_search_time = None

    def _wait_for_reset(self, response):
        reset_ts = int(response.headers.get("X-RateLimit-Reset", time.time() + 60))
        sleep_for = max(reset_ts - time.time(), 0) + 1
        logging.warning(f"Rate limit hit, sleeping {sleep_for:.0f}s until reset…")
        time.sleep(sleep_for)
        self._last_search_time = None

    def _check_rate_limit(self, response):
        if int(response.headers.get("X-RateLimit-Remaining", 0)) < 1:
            self._wait_for_reset(response)

    def _throttle_search(self):
        if self._last_search_time:
            elapsed = time.time() - self._last_search_time
            if elapsed < SEARCH_MIN_INTERVAL:
                time.sleep(SEARCH_MIN_INTERVAL - elapsed)
        self._last_search_time = time.time()

    def search_code(self, query):
        results = []
        total_count = None

        pages_to_fetch = self.max_pages_setting

        for page in range(1, pages_to_fetch + 1):
            self._throttle_search()
            params = {"q": query, "per_page": self.per_page, "page": page}
            resp = self.session.get("https://api.github.com/search/code", params=params)

            if resp.status_code == 403 and resp.headers.get("X-RateLimit-Remaining") == "0":
                self._wait_for_reset(resp)
                self._throttle_search()
                resp = self.session.get("https://api.github.com/search/code", params=params)

            try:
                resp.raise_for_status()
            except HTTPError as e:
                logging.error(f"Error fetching page {page} for '{query}': {e}")
                break

            self._check_rate_limit(resp)
            data = resp.json()

            if total_count is None:
                total_count = data.get("total_count", 0)
                effective = min(total_count, self.MAX_RESULTS)
                pages_to_fetch = min(
                    pages_to_fetch,
                    (effective + self.per_page - 1) // self.per_page
                )

            items = data.get("items", [])
            if not items:
                break

            results.extend(items)
            logging.info(f"Fetched {len(items)} items on page {page}/{pages_to_fetch}")
        return results

    def get_last_commit_date(self, owner, repo, path):
        url = f"https://api.github.com/repos/{owner}/{repo}/commits"
        params = {"path": path, "per_page": 1}
        resp = self.session.get(url, params=params)
        if resp.status_code == 403 and resp.headers.get("X-RateLimit-Remaining") == "0":
            self._wait_for_reset(resp)
            resp = self.session.get(url, params=params)
        try:
            resp.raise_for_status()
        except HTTPError as e:
            logging.warning(f"Failed to fetch commits for {owner}/{repo}: {e}")
            return None
        self._check_rate_limit(resp)
        time.sleep(self.commit_delay)
        commits = resp.json()
        return commits[0]["commit"]["committer"]["date"] if commits else None

    @staticmethod
    def compute_age_days(date_str):
        if not date_str:
            return None
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).days

def load_seen(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        return {q: set(raw.get(q, [])) for q in QUERIES}
    except FileNotFoundError:
        return {q: set() for q in QUERIES}


def save_seen(path, data_sets):
    tmp = path + ".tmp"
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump({q: list(data_sets[q]) for q in QUERIES}, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def main():
    searcher = GitHubSearcher(
        token=GITHUB_TOKEN,
        per_page=PER_PAGE,
        max_pages=MAX_PAGES,
        commit_delay=COMMIT_DELAY
    )
    seen = load_seen(SEEN_FILE)
    logging.info(f"Loaded seen.json: " +
                 ", ".join(f"{q}={len(seen[q])}" for q in QUERIES))
    logging.info(f"Starting monitor for queries: {QUERIES}")

    while True:
        any_new = False
        for q in QUERIES:
            logging.info(f"Query '{q}'…")
            items = searcher.search_code(q)
            seen_repos = {
                "/".join(url.split("/")[3:5])
                for url in seen[q]
            }

            for it in items:
                repo_full = it['repository']['full_name']
                url = it['html_url']

                # пропускаем репозитории-исключения, которые можно задать в .env
                if repo_full in repo_full in seen_repos:
                    logging.info(f"Skipping entire repo {repo_full}")
                    continue

                # если ещё не видели этот URL
                if url not in seen[q]:
                    # получаем дату последнего коммита
                    date_str = searcher.get_last_commit_date(
                        it['repository']['owner']['login'],
                        it['repository']['name'],
                        it['path']
                    )
                    age = searcher.compute_age_days(date_str)

                    # если коммит старше 30 дней — просто помечаем как увиденный
                    if age is not None and age > 30:
                        seen[q].add(url)
                        logging.info(
                            f"Marking {repo_full}/{it['name']} as seen (age {age}d > 30d), no alert"
                        )
                        continue

                    # иначе — формируем и шлём сообщение, и помечаем как увиденный
                    msg = (
                        f"Новый результат для '{q}':\n"
                        f"Repo: {repo_full}\n"
                        f"File: {it['name']}\n"
                        f"URL: {url}\n"
                        f"Commit age: {age if age is not None else '?'} дн"
                    )
                    create_incident(q, url)
                    seen[q].add(url)
                    seen_repos.add(repo_full)
                    any_new = True

        if any_new:
            save_seen(SEEN_FILE, seen)
            logging.info("Saved updated seen.json")

        logging.info(f"Cycle complete, sleeping {INTERVAL}s…")
        time.sleep(INTERVAL)

if __name__ == "__main__":
    main()
