import csv
import io
import sys
import time
import zipfile
import argparse
from urllib.request import urlopen
from urllib.error import URLError
from pathlib import Path

# Ensure Unicode output works on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Download ───────────────────────────────────────────────────────────────────

SOURCES = {
    "tranco":   "https://tranco-list.eu/top-1m.csv.zip",
    "majestic": "https://downloads.majestic.com/majestic_million.csv",
    "umbrella": "https://s3-us-west-1.amazonaws.com/umbrella-static/top-1m.csv.zip",
}

CACHE_FILE  = Path("domains.txt")
OUTPUT_FILE = Path("typosquats.csv")
TIMEOUT     = 60


def _fetch_zip(url: str, col: int = 1) -> list[str]:
    with urlopen(url, timeout=TIMEOUT) as resp:
        data = resp.read()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        text = zf.read(zf.namelist()[0]).decode()
    return [row.split(",")[col].strip() for row in text.splitlines() if row]


def _fetch_tranco() -> list[str]:
    return _fetch_zip(SOURCES["tranco"], col=1)


def _fetch_majestic() -> list[str]:
    with urlopen(SOURCES["majestic"], timeout=TIMEOUT) as resp:
        text = resp.read().decode()
    reader = csv.DictReader(text.splitlines())
    return [row["Domain"].strip() for row in reader]


def _fetch_umbrella() -> list[str]:
    return _fetch_zip(SOURCES["umbrella"], col=1)


def load_domains(force: bool = False) -> list[str]:
    if CACHE_FILE.exists() and not force:
        print(f"[cache] {CACHE_FILE} already exists — skipping download. Use --force to refresh.")
        return CACHE_FILE.read_text(encoding="utf-8").splitlines()

    fetchers = [
        ("Tranco",           _fetch_tranco),
        ("Majestic Million", _fetch_majestic),
        ("Cisco Umbrella",   _fetch_umbrella),
    ]

    seen: set[str] = set()
    merged: list[str] = []

    for name, fn in fetchers:
        print(f"Downloading {name} …", end=" ", flush=True)
        try:
            domains = fn()
            before = len(seen)
            for d in domains:
                d = d.lower()
                if d not in seen:
                    seen.add(d)
                    merged.append(d)
            print(f"{len(domains):,} fetched, {len(seen) - before:,} new unique")
        except (URLError, Exception) as exc:
            print(f"FAILED ({exc})")

    CACHE_FILE.write_text("\n".join(merged), encoding="utf-8")
    print(f"\nSaved {len(merged):,} unique domains → {CACHE_FILE}\n")
    return merged


# ── Typosquat generators (delegated to squatter.py) ───────────────────────────

from squatter import (
    omissions, transpositions, adjacent_key_errors,
    alternate_tlds, homoglyph_variants, TECHNIQUES,
)


def generate_typosquats(domain: str) -> dict[str, set[str]]:
    return {name: fn(domain) for name, fn in TECHNIQUES.items()}


# ── Bulk processing ────────────────────────────────────────────────────────────

def process_all(domains: list[str], out_path: Path, progress_every: int = 10_000) -> None:
    total = len(domains)
    print(f"Processing {total:,} domains → {out_path}")
    print("This may take a while. Progress printed every "
          f"{progress_every:,} domains.\n")

    t0 = time.time()
    rows_written = 0

    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["original", "technique", "variant"])

        for idx, domain in enumerate(domains, 1):
            results = generate_typosquats(domain)
            for technique, variants in results.items():
                for variant in sorted(variants):
                    writer.writerow([domain, technique, variant])
                    rows_written += 1

            if idx % progress_every == 0 or idx == total:
                elapsed = time.time() - t0
                rate = idx / elapsed
                remaining = (total - idx) / rate if rate else 0
                print(
                    f"  [{idx:>{len(str(total))}}/{total}] "
                    f"{rows_written:,} rows written  "
                    f"{rate:,.0f} domains/s  "
                    f"ETA {remaining/60:.1f} min"
                )

    elapsed = time.time() - t0
    print(f"\nDone. {rows_written:,} typosquat rows written to {out_path} "
          f"in {elapsed/60:.1f} min.")


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download top domain lists and generate typosquatting variants.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --download            # fetch & cache all 3 lists
  python main.py --run                 # generate typosquats for every cached domain
  python main.py --download --run      # download then immediately process all
  python main.py google.com            # preview a single domain
  python main.py --limit 100 --run     # process only the first 100 domains
  python main.py --download --force    # re-download even if cache exists
""",
    )
    parser.add_argument("domain", nargs="?", help="Single domain to preview")
    parser.add_argument("--download", action="store_true",
                        help="Download and cache the top-3 domain lists")
    parser.add_argument("--force", action="store_true",
                        help="Re-download even if the cache already exists")
    parser.add_argument("--run", action="store_true",
                        help=f"Process all cached domains and write to {OUTPUT_FILE}")
    parser.add_argument("--limit", type=int, default=0,
                        help="Process only the first N domains (0 = all, default: 0)")
    parser.add_argument("--sample", type=int, default=5,
                        help="Variants to preview per technique for single-domain mode (default: 5)")
    parser.add_argument("--out", type=Path, default=OUTPUT_FILE,
                        help=f"Output CSV path (default: {OUTPUT_FILE})")
    args = parser.parse_args()

    if args.download:
        load_domains(force=args.force)

    if args.domain:
        # Single-domain preview mode
        print(f"\n{'=' * 64}")
        print(f"  {args.domain}")
        print(f"{'=' * 64}")
        results = generate_typosquats(args.domain)
        total = sum(len(v) for v in results.values())
        for technique, variants in results.items():
            sample = sorted(variants)[: args.sample]
            print(f"  {technique:<14} {len(variants):>4} variants   e.g. {', '.join(sample)}")
        print(f"  {'TOTAL':<14} {total:>4}")
        return

    if args.run:
        if not CACHE_FILE.exists():
            print("No domain cache found. Run with --download first.")
            return
        domains = CACHE_FILE.read_text(encoding="utf-8").splitlines()
        if args.limit > 0:
            domains = domains[: args.limit]
        process_all(domains, args.out)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
