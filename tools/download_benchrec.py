"""Download the attributed public release without credentials or extra packages.

Run: python3 tools/download_benchrec.py
The archive is version-pinned and SHA-256 checked before replacing local data.
"""

import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

BASE = Path(__file__).resolve().parents[1] / "sample_data/public/benchrec"
REF = "benchmarkteam/benchrec-real-world-cash-reconciliation-dataset"
DOWNLOAD = f"https://www.kaggle.com/api/v1/datasets/download/{REF}?datasetVersionNumber=3"
METADATA = f"https://www.kaggle.com/api/v1/datasets/view/{REF}"
CHECKSUM = "46d6851a47f1888a7295ac5f7d49295f845b5041ddd18965fef7b79be1b86b4b"


def fetch(url):
    return urlopen(Request(url, headers={"User-Agent": "LedgerSync educational dataset downloader"}), timeout=120)


def main():
    raw, evidence = BASE / "raw", BASE / "evidence"
    raw.mkdir(parents=True, exist_ok=True)
    evidence.mkdir(parents=True, exist_ok=True)
    destination = raw / "benchrec-v3.zip"
    temporary = raw / "benchrec-v3.zip.part"
    digest = hashlib.sha256()
    try:
        with fetch(DOWNLOAD) as response, temporary.open("wb") as file_object:
            for chunk in iter(lambda: response.read(1024 * 1024), b""):
                digest.update(chunk)
                file_object.write(chunk)
        if digest.hexdigest() != CHECKSUM:
            raise ValueError("Download checksum differs from the verified v3 snapshot; local data was not replaced.")
        with fetch(METADATA) as response:
            metadata = json.loads(response.read())
        if metadata["licenseName"] != "Attribution 4.0 International (CC BY 4.0)":
            raise ValueError("The publisher's license declaration changed; review before reuse.")
        if metadata["currentVersionNumber"] != 3:
            raise ValueError("Current metadata no longer describes v3; retain the saved v3 evidence and review the new release.")
        temporary.replace(destination)
        (evidence / "kaggle-metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    finally:
        temporary.unlink(missing_ok=True)
    print(f"Downloaded {destination.stat().st_size:,} bytes; SHA-256 {CHECKSUM}")


if __name__ == "__main__":
    main()
