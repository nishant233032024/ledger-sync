"""Upload public samples through the live API and evaluate Celery results.

Run from the repository root, with Docker services running:
    python3 tools/run_benchrec_demo.py --scenario all

The script writes batches/runs into the demo organization only. It never
deletes records. Reusing a completed scenario returns the existing run.
"""

import argparse
import json
import os
import shutil
import subprocess
import time
import uuid
from decimal import Decimal
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from prepare_benchrec_demo import EVIDENCE, NORMALIZED, ROOT, sha256

SCENARIOS = ("historical_2022", "historical_2023", "control_baseline_2023", "controlled_faults_2023")
DOCKER_FALLBACK = "/mnt/c/Users/nisha/AppData/Local/Programs/DockerDesktop/resources/bin/docker.exe"


class API:
    def __init__(self, base_url, token):
        self.base = base_url.rstrip("/")
        self.token = token

    def call(self, path, data=None, content_type="application/json"):
        headers = {"Content-Type": content_type, "Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        encoded = json.dumps(data).encode() if data is not None and content_type == "application/json" else data
        request = Request(self.base + path, data=encoded, headers=headers)
        try:
            with urlopen(request, timeout=120) as response:
                return json.loads(response.read())
        except HTTPError as exc:
            raise RuntimeError(f"HTTP {exc.code}: {exc.read().decode()}") from exc

    def upload(self, path, source_type, account):
        # Samples are only a few hundred KB: bounded multipart construction is
        # adequate for this CLI. The application's large upload path streams.
        boundary = f"LedgerSync{uuid.uuid4().hex}"
        body = bytearray()
        for key, value in (("source_type", source_type), ("source_account", account)):
            body.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
        body.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\nContent-Type: text/csv\r\n\r\n'.encode())
        body.extend(path.read_bytes())
        body.extend(f"\r\n--{boundary}--\r\n".encode())
        return self.call("/batches/upload/", bytes(body), f"multipart/form-data; boundary={boundary}")["data"]["id"]


def wait_until(get_value, ready, description, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = get_value()
        if ready(value):
            return value
        time.sleep(1)
    raise TimeoutError(f"Timed out waiting for {description}.")


def docker_command(override):
    if override:
        return override
    # WSL's 'docker' shim can exist but still fail; prefer the known Desktop
    # executable when present, without changing the user's shell configuration.
    if os.path.exists(DOCKER_FALLBACK):
        return DOCKER_FALLBACK
    command = shutil.which("docker")
    if not command:
        raise RuntimeError("Docker CLI not found; pass --docker-command with its path.")
    return command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=(*SCENARIOS, "all"), default="all")
    parser.add_argument("--api-url", default="http://localhost:8000/api/v1")
    parser.add_argument("--docker-command")
    options = parser.parse_args()
    docker = docker_command(options.docker_command)
    api = API(options.api_url, None)
    credentials = {"username": os.getenv("LEDGERSYNC_USERNAME", "admin@example.com"),
                   "password": os.getenv("LEDGERSYNC_PASSWORD", "Admin12345!")}
    api.token = api.call("/auth/token/", credentials)["access"]
    me = api.call("/auth/me/")["data"]
    if me["username"] != "admin@example.com" or me["organization"] != "Demo Finance Co.":
        raise RuntimeError("This demo loader expects seed_demo's Demo Finance Co. account.")
    # A dedicated zero-tolerance rule makes the fault manifest reproducible.
    rule_name = "BenchRec interview: exact reference, zero amount tolerance"
    rule = next((item for item in api.call("/rules/")["data"] if item["name"] == rule_name), None)
    if rule is None:
        rule = api.call("/rules/", {
            "name": rule_name, "priority": 10, "exact_reference_match": True,
            "date_variance_days": 2, "amount_tolerance_percent": "0", "is_active": True,
        })["data"]
    if (not rule["exact_reference_match"] or Decimal(rule["amount_tolerance_percent"]) != 0
            or rule["date_variance_days"] != 2):
        raise RuntimeError("The dedicated demo rule changed; restore its documented policy.")
    command_path = ROOT / "backend/ledger/management/commands/report_benchrec.py"
    # Copy only the diagnostic command into the existing container, without
    # rebuilding or restarting the running stack.
    compose = [docker, "compose"]
    subprocess.run(compose + ["cp", str(command_path), "web:/app/ledger/management/commands/report_benchrec.py"], check=True)
    scenarios = SCENARIOS if options.scenario == "all" else (options.scenario,)
    for scenario in scenarios:
        # Version the fixture namespace by BOTH input hashes. Regeneration
        # cannot silently reuse a stale batch or mutate audited source records.
        ledger_hash = sha256(NORMALIZED / f"{scenario}_ledger.csv")
        bank_hash = sha256(NORMALIZED / f"{scenario}_bank.csv")
        account = "demo-benchrec-" + scenario.replace("_", "-") + "-" + ledger_hash[:6] + bank_hash[:6]
        batch_ids = {}
        for label, source_type in (("ledger", "ERP"), ("bank", "BANK")):
            filename = f"{scenario}_{label}.csv"
            existing = next((item for item in api.call("/batches/")["data"]
                             if item["original_filename"] == filename and item["source_account"] == account), None)
            batch_id = existing["id"] if existing else api.upload(NORMALIZED / filename, source_type, account)
            result = wait_until(
                lambda: api.call(f"/batches/{batch_id}/status/")["data"],
                lambda value: value["state"] in ("COMPLETED", "FAILED"), filename,
            )
            if result["state"] != "COMPLETED" or result["failed_records"]:
                raise RuntimeError(f"Ingestion not clean for {filename}: {result}")
            batch_ids[label] = batch_id
        runs = api.call("/reconciliation/runs/")["data"]
        run = next((item for item in runs if item["ledger_batch_id"] == batch_ids["ledger"]
                    and item["external_batch_id"] == batch_ids["bank"]), None)
        if run is None:
            run = api.call("/reconciliation/runs/", {
                "ledger_batch_id": batch_ids["ledger"], "external_batch_id": batch_ids["bank"],
                "rule_id": rule["id"],
            })["data"]
        run_id = run["id"]
        completed = wait_until(
            lambda: next(item for item in api.call("/reconciliation/runs/")["data"] if item["id"] == run_id),
            lambda value: value["status"] in ("COMPLETED", "FAILED"), scenario,
        )
        if completed["status"] != "COMPLETED":
            raise RuntimeError(f"Run failed: {completed}")
        evidence = EVIDENCE / (f"{scenario}.json" if scenario == "controlled_faults_2023" else f"{scenario}_ground_truth.csv")
        container_path = f"/tmp/{evidence.name}"
        subprocess.run(compose + ["cp", str(evidence), f"web:{container_path}"], check=True)
        result = subprocess.run(compose + ["exec", "-T", "web", "python", "manage.py", "report_benchrec",
                                          "--run-id", run_id, "--evidence", container_path],
                                check=True, capture_output=True, text=True)
        report = json.loads(result.stdout)
        if report["stored_input_sha256"] != {"ledger": ledger_hash, "bank": bank_hash}:
            raise RuntimeError("Stored batch checksums differ from the files being evaluated.")
        report["scenario"] = scenario
        report["input_sha256"] = {"ledger": ledger_hash, "bank": bank_hash}
        report["fixture_source_account"] = account
        (EVIDENCE / f"{scenario}_live_report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
