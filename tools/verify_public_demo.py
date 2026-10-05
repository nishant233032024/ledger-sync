"""Verify a deployed public demo through HTTP, without printing JWTs.

Example:
    python3 tools/verify_public_demo.py --api-url https://YOUR-API.onrender.com/api/v1 --frontend-origin https://YOUR-APP.vercel.app
"""

import argparse
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--frontend-origin")
    parser.add_argument("--proxy-https", action="store_true", help="Local trusted-proxy test only")
    options = parser.parse_args()
    base = options.api_url.rstrip("/")
    token = None

    def call(path, payload=None, expected=200):
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if options.frontend_origin:
            headers["Origin"] = options.frontend_origin
        if options.proxy_https:
            headers["X-Forwarded-Proto"] = "https"
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode()
        request = Request(base + path, data=data, headers=headers)
        try:
            response = urlopen(request, timeout=180)
        except HTTPError as exc:
            response = exc
        with response:
            body = json.loads(response.read())
            if response.status != expected:
                raise RuntimeError(f"{path}: expected HTTP {expected}, got {response.status}")
            if options.frontend_origin and response.headers.get("Access-Control-Allow-Origin") != options.frontend_origin:
                raise RuntimeError(f"CORS does not permit {options.frontend_origin}")
            return body

    call("/health/")
    tokens = call("/auth/token/", {"username": "demo@example.com", "password": "Demo12345!"})
    token = tokens["access"]
    user = call("/auth/me/")["data"]
    if user["role"] != "AUDITOR" or not user["read_only"] or not user["public_demo"]:
        raise RuntimeError("The public demo account or hosting mode is incorrect.")
    batches = {batch["id"]: batch for batch in call("/batches/")["data"]}
    runs = call("/reconciliation/runs/")["data"]
    expected = {
        "historical_2022": (118, 1764, 2000),
        "historical_2023": (144, 1712, 2000),
        "control_baseline_2023": (100, 0, 200),
        "controlled_faults_2023": (93, 11, 200),
    }
    for scenario, (matches, flags, transactions) in expected.items():
        run = next(item for item in runs if batches[item["ledger_batch_id"]]["original_filename"] == f"{scenario}_ledger.csv")
        if run["status"] != "COMPLETED" or (run["matched_count"], run["discrepancy_count"]) != (matches, flags):
            raise RuntimeError(f"Unexpected reconciliation results for {scenario}")
        summary = call(f"/summary/?run_id={run['id']}")["data"]
        if (summary["total_uploaded"], summary["matched"], summary["pending_discrepancies"]) != (transactions, matches, flags):
            raise RuntimeError(f"Unexpected summary for {scenario}")
        rows = call(f"/transactions/?run_id={run['id']}&page_size=100&page=2")
        if rows["meta"]["total"] != transactions or rows["meta"]["page"] != 2:
            raise RuntimeError(f"Transaction pagination failed for {scenario}")
        exceptions = call(f"/discrepancies/?run_id={run['id']}&status=OPEN")
        if exceptions["meta"]["total"] != flags:
            raise RuntimeError(f"Discrepancy filtering failed for {scenario}")
        print(f"PASS {scenario}: {matches} matches, {flags} flags, {transactions} source rows")
    for path in ("/rules/", "/batches/upload/", "/reconciliation/runs/"):
        call(path, {}, expected=403)
    refreshed = call("/auth/token/refresh/", {"refresh": tokens["refresh"]})
    token = refreshed["access"]
    call("/auth/me/")
    print("PASS health, login, refresh, scenario filters, pagination, read-only enforcement, and configured CORS")


if __name__ == "__main__":
    main()
