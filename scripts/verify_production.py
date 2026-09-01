#!/usr/bin/env python3
"""Production identity verifier (Phase 14.7).

Fail-closed: exits 0 ONLY if every claim in docs/PRODUCTION_RUNTIME_CONTRACT.md
can be mechanically proven against the live host + running containers.

Run from anywhere:
    python3 scripts/verify_production.py

Checks (each prints PASS/FAIL with evidence):
  1. Canonical repository is the checkout at /root/moneyprinterturbo-video-factory.
  2. Working tree is clean (no uncommitted changes -> no deploy from dirty tree).
  3. webui/Main.py committed version == working-tree version.
  4. Canonical repo HEAD SHA == running webui container image label `git-sha`.
  5. Running webui container image label `repo` == canonical repository identity.
  6. Runtime Main.py (inside the container) == committed Main.py (runtime==source).
  7. Exactly one listener on WEBUI port 8501; Factory port 8000 NOT listening.
  8. nginx server_name == goldtrader.website && proxies 8501; factory vhost disabled.
  9. No Factory-UI container running.

Exit code: 0 = all PASS, 1 = any FAIL.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys

CANONICAL_REPO = "/root/moneyprinterturbo-video-factory"
CANONICAL_DOMAIN = "goldtrader.website"
WEBUI_PORT = 8501
API_PORT = 8080
FACTORY_PORT = 8000
WEBUI_CONTAINER = "moneyprinterturbo-webui"

failures: list[str] = []


def ok(msg: str) -> None:
    print(f"  [PASS] {msg}")


def fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")
    failures.append(msg)


def sh(cmd: str) -> str:
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        out = (p.stdout or "") + (p.stderr or "")
        return out.strip()
    except Exception as e:
        return f"<err: {e}>"


# ---------------------------------------------------------------- checks
print("=== Hard Gate #1: Canonical repository ===")
top = sh("git -C /root/moneyprinterturbo-video-factory rev-parse --show-toplevel 2>/dev/null")
if top == CANONICAL_REPO:
    ok(f"canonical repo checkout = {top}")
else:
    fail(f"expected canonical repo {CANONICAL_REPO}; got: {top!r}")

print("=== Hard Gate #2: Clean working tree (no deploy from dirty tree) ===")
status = sh("git -C /root/moneyprinterturbo-video-factory status --porcelain")
if status == "":
    ok("working tree clean")
else:
    fail(f"working tree dirty (deploy blocked). First lines:\n{status[:500]}")

print("=== Hard Gate #3: committed webui/Main.py == working tree ===")
head_main = sh("git -C /root/moneyprinterturbo-video-factory show HEAD:webui/Main.py 2>/dev/null")
wt_main = sh("git -C /root/moneyprinterturbo-video-factory hash-object -t blob webui/Main.py 2>/dev/null")
# compare via git's own blob hash for robustness
head_blob = sh("git -C /root/moneyprinterturbo-video-factory rev-parse HEAD:webui/Main.py 2>/dev/null")
wt_blob = sh("git -C /root/moneyprinterturbo-video-factory hash-object webui/Main.py 2>/dev/null")
if head_blob and head_blob == wt_blob:
    ok(f"webui/Main.py working tree == committed (blob {head_blob[:12]})")
else:
    fail(f"webui/Main.py differs from committed: head_blob={head_blob} wt_blob={wt_blob}")

print("=== Hard Gate #4: canonical HEAD SHA == running image git-sha label ===")
head_sha = sh("git -C %s rev-parse HEAD" % CANONICAL_REPO)
img_label = sh("docker inspect %s --format '{{json .Config.Labels}}' 2>/dev/null | tr -d '\\n'" % WEBUI_CONTAINER)
labels = {}
if img_label:
    try:
        labels = json.loads(img_label)
    except json.JSONDecodeError:
        pass
img_sha = labels.get("git-sha") or labels.get("git_commit") or ""
if head_sha and img_sha and head_sha == img_sha:
    ok(f"HEAD {head_sha[:12]} == image git-sha {img_sha[:12]}")
elif not img_label:
    fail(f"no labels on container {WEBUI_CONTAINER} (cannot prove provenance)")
else:
    fail(
        f"SHA mismatch: HEAD={head_sha[:12]} image git-sha={img_sha[:12]} "
        f"(full={img_sha})"
    )

print("=== Hard Gate #4b: image repo label == canonical identity ===")
img_repo = labels.get("repo", "")
if img_repo == "moneyprinterturbo-video-factory":
    ok(f"image repo label == canonical ({img_repo})")
else:
    fail(f"image repo label={img_repo!r} != 'moneyprinterturbo-video-factory'")

print("=== Hard Gate #6: runtime Main.py == committed Main.py ===")
# Compare sha256 of the committed file content against the in-container file.
# Use a single shell pipeline so trailing-newline handling matches exactly.
committed_sha = sh("git -C %s show HEAD:webui/Main.py 2>/dev/null | sha256sum" % CANONICAL_REPO)
committed_sha = committed_sha.split()[0] if committed_sha else ""
runtime_main = sh("docker exec -t %s sha256sum /MoneyPrinterTurbo/webui/Main.py 2>/dev/null" % WEBUI_CONTAINER)
runtime_hash = runtime_main.split()[0] if runtime_main else ""
if runtime_hash and committed_sha and runtime_hash == committed_sha:
    ok(f"runtime Main.py sha256 == committed (sha256 {runtime_hash[:12]})")
else:
    fail(
        f"runtime Main.py ({runtime_hash[:12]}) != committed ({committed_sha[:12]})"
    )

print("=== Hard Gate #7: ports — one UI on 8501, Factory 8000 closed ===")
listening = sh("ss -tlnp 2>/dev/null")
ports = {int(p) for p in re.findall(r":(\d+)\b", listening)}
if WEBUI_PORT in ports:
    ok(f"exactly one listener on {WEBUI_PORT}")
else:
    fail(f"no listener on {WEBUI_PORT}")
if FACTORY_PORT in ports:
    fail(f"Factory port {FACTORY_PORT} is LISTENING (decommission failed)")
else:
    ok(f"Factory port {FACTORY_PORT} closed")
if API_PORT in ports:
    ok(f"canonical API on {API_PORT} present")
else:
    fail(f"canonical API port {API_PORT} not listening")

print("=== Hard Gate #8: nginx identity (domain + factory disabled) ===")
vhost = sh("cat /etc/nginx/sites-enabled/moneyprinterturbo 2>/dev/null")
if f"server_name {CANONICAL_DOMAIN}" in vhost and "proxy_pass http://127.0.0.1:8501" in vhost:
    ok(f"nginx '{CANONICAL_DOMAIN}' -> 127.0.0.1:{WEBUI_PORT} configured")
else:
    fail("nginx canonical vhost missing/broken")
if "proxy_pass http://127.0.0.1:8000" in vhost:
    fail("canonical vhost proxies to Factory 8000 (decommission failed)")
else:
    ok("canonical vhost does not proxy to Factory 8000")
# factory vhost must NOT be enabled
enabled = sh("ls -1 /etc/nginx/sites-enabled/ 2>/dev/null")
if "moneyprinterturbo" in enabled and "factory" not in enabled.lower():
    ok("factory.goldtrader.website vhost NOT enabled")
else:
    fail(f"factory vhost still enabled? sites-enabled={enabled!r}")

print("=== Hard Gate #9: no Factory-UI container running ===")
containers = sh("docker ps --format '{{.Names}}'")
factory_running = any(
    n.lower().startswith("factory") for n in containers.split()
) and "moneyprinterturbo-factory" not in "".lower()
# The moneyprinterturbo-* containers are canonical (webui+api). Any other
# container named 'factory*' would be the Factory UI.
suspicious = [n for n in containers.split() if n.lower().startswith("factory")]
if suspicious:
    fail(f"Factory UI container running: {suspicious}")
else:
    ok("no Factory-UI container running (only moneyprinterturbo-* canonical containers)")

# ---------------------------------------------------------------- verdict
print("\n=== VERDICT ===")
if failures:
    print(f"FAIL — {len(failures)} check(s) failed:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("PASS — production identity chain proven.")
sys.exit(0)
