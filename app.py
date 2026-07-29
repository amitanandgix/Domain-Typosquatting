import os
import socket
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from flask import Flask, jsonify, render_template, request

import squatter

# Ensure Unicode output works on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

app = Flask(__name__)

DNS_TIMEOUT   = 1.5
DNS_MAX_BATCH = 600
DNS_WORKERS   = 120
KNOWN_LIMIT   = 10_000   # quick preview pool (top domains)

# Resolve paths relative to this file so the app works regardless of the
# process working directory (e.g. Vercel / other serverless runtimes).
_BASE = Path(__file__).resolve().parent

# Candidate domain-list locations, in priority order:
#   1. DOMAINS_FILE env var (explicit override)
#   2. domains.txt          (full local cache, gitignored — used in dev)
#   3. data/domains_top.txt (trimmed top list committed to the repo — used in prod)
_CANDIDATES = [
    p for p in (
        Path(os.environ["DOMAINS_FILE"]) if os.environ.get("DOMAINS_FILE") else None,
        _BASE / "domains.txt",
        _BASE / "data" / "domains_top.txt",
        Path.cwd() / "domains.txt",
        Path.cwd() / "data" / "domains_top.txt",
    ) if p is not None
]

# Load domains once at startup and build a length index + rank map for fast lookup.
# Always defined (possibly empty) so request handlers never hit a NameError.
_KNOWN_DOMAINS: list[str] = []
_ALL_DOMAINS:   list[str] = []
_LENGTH_INDEX:  dict      = {}
_DOMAIN_RANK:   dict      = {}

_CACHE = next((p for p in _CANDIDATES if p.exists()), None)
if _CACHE is not None:
    print(f"Loading domain list from {_CACHE} …", end=" ", flush=True)
    _ALL_DOMAINS   = [d for d in _CACHE.read_text(encoding="utf-8").splitlines() if d]
    _KNOWN_DOMAINS = _ALL_DOMAINS[:KNOWN_LIMIT]
    _LENGTH_INDEX  = squatter.build_length_index(_ALL_DOMAINS)
    _DOMAIN_RANK   = {d: i for i, d in enumerate(_ALL_DOMAINS)}
    print(f"{len(_ALL_DOMAINS):,} domains loaded, length index + rank map built.")
else:
    print("WARNING: no domain list found — closest-match lookups will be empty. "
          "Set DOMAINS_FILE or add data/domains_top.txt.")


def _dns_exists(domain: str) -> bool:
    try:
        socket.setdefaulttimeout(DNS_TIMEOUT)
        socket.gethostbyname(domain)
        return True
    except Exception:
        return False


def _check_dns_batch(domains: list[str]) -> dict[str, bool]:
    targets = domains[:DNS_MAX_BATCH]
    results: dict[str, bool] = {d: False for d in domains}
    with ThreadPoolExecutor(max_workers=DNS_WORKERS) as ex:
        futures = {ex.submit(_dns_exists, d): d for d in targets}
        for future in as_completed(futures):
            d = futures[future]
            try:
                results[d] = future.result()
            except Exception:
                results[d] = False
    return results


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/check", methods=["POST"])
def check():
    data = request.get_json(force=True)
    domain = (data.get("domain") or "").strip().lower()
    do_dns = bool(data.get("dns", False))

    if not domain:
        return jsonify({"error": "No domain provided."}), 400

    # Is the entered domain in the verified list?
    is_known = domain in _DOMAIN_RANK

    # Find the closest verified domains across the FULL list (fast via length index).
    # Computed once and reused for analysis-domain selection and the response.
    closest = squatter.find_closest(
        domain, _ALL_DOMAINS, length_index=_LENGTH_INDEX, rank=_DOMAIN_RANK, bound=2
    ) if _ALL_DOMAINS else []

    # For unknown domains, analyse the closest verified domain instead
    closest_target = None
    analysis_domain = domain
    if not is_known and closest:
        closest_target  = closest[0]["domain"]
        analysis_domain = closest_target

    results = squatter.generate_all(analysis_domain)

    if do_dns:
        all_variants: set[str] = set()
        for entry in results.values():
            all_variants.update(entry["variants"])
        dns_map = _check_dns_batch(list(all_variants))
        for entry in results.values():
            entry["dns"] = {v: dns_map.get(v, False) for v in entry["variants"]}

    total = sum(len(set(e["variants"])) for e in results.values())
    registered = 0
    if do_dns:
        seen: set[str] = set()
        for entry in results.values():
            for v, hit in entry.get("dns", {}).items():
                if hit and v not in seen:
                    seen.add(v)
                    registered += 1

    return jsonify({
        "domain":          domain,
        "analysis_domain": analysis_domain,
        "is_known":        is_known,
        "closest_target":  closest_target,
        "total":           total,
        "registered":      registered if do_dns else None,
        "dns_checked":     do_dns,
        "results":         results,
        "closest":         closest,
    })


@app.route("/api/closest", methods=["POST"])
def closest():
    data   = request.get_json(force=True)
    domain = (data.get("domain") or "").strip().lower()
    if not domain:
        return jsonify({"error": "No domain provided."}), 400

    import time
    t0      = time.time()
    results = squatter.find_closest(domain, _ALL_DOMAINS, length_index=_LENGTH_INDEX, rank=_DOMAIN_RANK, bound=2)
    elapsed = round(time.time() - t0, 3)

    return jsonify({"domain": domain, "closest": results, "searched": len(_ALL_DOMAINS), "elapsed": elapsed})


if __name__ == "__main__":
    print("Starting Domain Typosquat Checker at http://127.0.0.1:8080")
    app.run(debug=False, port=8080, host="0.0.0.0")
