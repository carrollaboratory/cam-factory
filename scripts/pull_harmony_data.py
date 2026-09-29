import asyncio
import os
from pathlib import Path

import httpx

# Configuration
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")  # Highly recommended to avoid rate limits
REPO_OWNER = "include-dcc"
REPO_NAME = "whistle-ingest-modular"
BRANCH = "main"  # or your default branch
TARGET_DIR = "harmony"  # Subfolder inside the repo holding the CSVs
OUTPUT_DIR = Path("./data/harmony")

HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"


async def download_file(
    client: httpx.AsyncClient, download_url: str, relative_path: str
):
    """Downloads a single CSV file from GitHub, preserving its subdirectory structure."""
    print(f"Downloading {relative_path}...")
    response = await client.get(download_url, headers=HEADERS)
    response.raise_for_status()

    output_path = OUTPUT_DIR / relative_path
    output_path.parent.mkdir(parents=True, exist_ok=True)  # recreate nested subdirs
    output_path.write_bytes(response.content)
    print(f"Saved {relative_path}")


async def fetch_harmony_files():
    """Fetches the file tree, filters for CSVs in the target directory, and downloads them."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Use the recursive trees API to get the structure in 1 call
    tree_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/git/trees/{BRANCH}?recursive=1"
    print(tree_url)

    async with httpx.AsyncClient() as client:
        response = await client.get(tree_url, headers=HEADERS)
        response.raise_for_status()

        tree_data = response.json()

        # Filter for files that are inside the target folder and end with .csv
        csv_entries = [
            item
            for item in tree_data.get("tree", [])
            if item.get("type") == "blob"
            and item.get("path", "").startswith(TARGET_DIR)
            and item.get("path", "").endswith(".csv")
        ]

        if not csv_entries:
            print(f"No CSV files found in '{TARGET_DIR}' folder.")
            return

        print(f"Found {len(csv_entries)} CSV files. Starting parallel download...")

        # Construct download tasks using GitHub's raw content URL.
        # relative_path is computed against TARGET_DIR so that subdirectory
        # structure (e.g. harmony/site_a/subjects.csv, harmony/site_b/subjects.csv)
        # is preserved under OUTPUT_DIR instead of colliding on basename.
        tasks = []
        for entry in csv_entries:
            path = entry["path"]
            relative_path = os.path.relpath(path, TARGET_DIR)
            raw_url = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/{BRANCH}/{path}"
            tasks.append(download_file(client, raw_url, relative_path))

        # Execute downloads concurrently
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(fetch_harmony_files())
