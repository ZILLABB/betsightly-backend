"""
Download historical training data from GitHub Releases.

Run this BEFORE retraining models. The data is ~135 MB total and is
hosted as release assets on the repo so we don't bloat the Docker image.

Usage:
    python scripts/download_training_data.py

To create a new release:
    1. Compress training data:
       tar -czf training-data.tar.gz data/historical/ data/github-football/
    2. Create release on GitHub:
       gh release create training-data-v1 training-data.tar.gz
    3. Update RELEASE_URL below
"""

import os
import sys
import logging
from pathlib import Path
from urllib.request import urlopen
from urllib.error import URLError

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

REPO = "ZILLABB/betsightly-backend"
RELEASE_TAG = "training-data-v1"
ARCHIVE_NAME = "training-data.tar.gz"

RELEASE_URL = f"https://github.com/{REPO}/releases/download/{RELEASE_TAG}/{ARCHIVE_NAME}"

DATA_ROOT = Path(__file__).resolve().parent.parent
TARGET_DIRS = ["data/historical", "data/github-football"]


def already_downloaded() -> bool:
    """True if the historical data dirs already exist with content."""
    for d in TARGET_DIRS:
        p = DATA_ROOT / d
        if p.exists() and any(p.iterdir()):
            return True
    return False


def download_and_extract():
    import tarfile
    import tempfile

    if already_downloaded():
        logger.info("Training data already present locally — skipping download")
        return

    logger.info(f"Downloading training data from {RELEASE_URL}")
    try:
        with urlopen(RELEASE_URL, timeout=60) as resp, tempfile.NamedTemporaryFile(
            suffix=".tar.gz", delete=False
        ) as tmp:
            tmp_path = tmp.name
            total = 0
            while True:
                chunk = resp.read(1024 * 64)
                if not chunk:
                    break
                tmp.write(chunk)
                total += len(chunk)
                if total % (1024 * 1024) == 0:
                    print(f"  Downloaded {total // (1024*1024)} MB...", end="\r", flush=True)
        logger.info(f"Downloaded {total // (1024*1024)} MB to {tmp_path}")

        logger.info("Extracting archive...")
        with tarfile.open(tmp_path, "r:gz") as tar:
            tar.extractall(path=DATA_ROOT)

        os.unlink(tmp_path)
        logger.info("Training data ready at data/historical/ + data/github-football/")
    except URLError as e:
        logger.error(f"Could not download from {RELEASE_URL}: {e}")
        logger.error(
            "Make sure the release exists. To create it:\n"
            f"  tar -czf {ARCHIVE_NAME} data/historical/ data/github-football/\n"
            f"  gh release create {RELEASE_TAG} {ARCHIVE_NAME} --repo {REPO}"
        )
        sys.exit(1)


if __name__ == "__main__":
    download_and_extract()
