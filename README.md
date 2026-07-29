# Domain Typosquatting

Generate and inspect typosquatting variants of domain names, and identify which
well-known domain an unknown domain is most likely impersonating.

## Components

- **`squatter.py`** — variant generators (character omission, transposition,
  adjacent-key error, alternate TLD, homoglyph, vowel substitution) plus a
  bounded-Levenshtein reverse lookup that finds the closest known domain.
- **`main.py`** — CLI to download top-domain lists (Tranco, Majestic, Cisco
  Umbrella), cache them, and bulk-generate typosquat variants to CSV.
- **`app.py`** — Flask web app (a visual checker) served at
  `http://127.0.0.1:8080`.

## Usage

```bash
# CLI — preview a single domain
python main.py google.com

# CLI — download lists, then generate variants for every cached domain
python main.py --download --run

# Web app
python app.py    # then open http://127.0.0.1:8080
```

## Notes

The domain lists (`domains.txt`) and generated output (`typosquats.csv`) are
large and are not tracked in git; regenerate them with `python main.py --download`.

Requires Python 3.12+, `flask`, and (optionally, for speed) `rapidfuzz`.
