from itertools import combinations as _combinations

try:
    from rapidfuzz.distance import Levenshtein as _RF
    def _levenshtein_bounded(a: str, b: str, bound: int) -> int:
        if abs(len(a) - len(b)) > bound:
            return bound + 1
        d = _RF.distance(a, b, score_cutoff=bound)
        return d if d <= bound else bound + 1
except ImportError:
    def _levenshtein_bounded(a: str, b: str, bound: int) -> int:  # pure-Python fallback
        if abs(len(a) - len(b)) > bound:
            return bound + 1
        if a == b:
            return 0
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a, 1):
            curr = [i]; row_min = i
            for j, cb in enumerate(b, 1):
                val = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + (ca != cb))
                curr.append(val)
                if val < row_min: row_min = val
            if row_min > bound: return bound + 1
            prev = curr
        return prev[-1]

# ── Constants ──────────────────────────────────────────────────────────────────

QWERTY: dict[str, str] = {
    "q": "was",    "w": "qesad",  "e": "wrsdf",  "r": "etdfg",
    "t": "ryfgh",  "y": "tughj",  "u": "yihjk",  "i": "uojkl",
    "o": "ipkl",   "p": "ol",
    "a": "qwsz",   "s": "awedzx", "d": "serfxc", "f": "drtgcv",
    "g": "ftyhvb", "h": "gyujbn", "j": "huikbn", "k": "jiolm",
    "l": "kop",
    "z": "asx",    "x": "zsdc",   "c": "xdfv",   "v": "cfgb",
    "b": "vghn",   "n": "bhjm",   "m": "njk",
}

HOMOGLYPHS: dict[str, list[str]] = {
    "a": ["а"],        # Cyrillic а
    "c": ["с"],        # Cyrillic с
    "e": ["е"],        # Cyrillic е
    "i": ["і", "1"],   # Cyrillic і, digit 1
    "o": ["о", "0"],   # Cyrillic о, digit 0
    "p": ["р"],        # Cyrillic р
    "s": ["ѕ"],        # Cyrillic ѕ
    "x": ["х"],        # Cyrillic х
    "y": ["у"],        # Cyrillic у
}

ALTERNATE_TLDS = [
    ".com", ".net", ".org", ".io", ".co",
    ".info", ".biz", ".us", ".uk", ".de",
]

VOWELS = frozenset("aeiou")

TECHNIQUE_INFO: dict[str, dict] = {
    "omission": {
        "label": "Character Omission",
        "description": "A letter is removed from the domain name.",
        "example": "google.com → gogle.com",
        "color": "#3b82f6",
    },
    "transposition": {
        "label": "Character Transposition",
        "description": "Two adjacent letters are swapped.",
        "example": "google.com → googel.com",
        "color": "#8b5cf6",
    },
    "adjacent_key": {
        "label": "Adjacent Key Error",
        "description": "A letter is replaced by a neighbouring key on a QWERTY keyboard.",
        "example": "google.com → googlr.com",
        "color": "#f59e0b",
    },
    "alternate_tld": {
        "label": "Alternate TLD",
        "description": "The TLD is swapped for another common extension.",
        "example": "example.com → example.net",
        "color": "#10b981",
    },
    "homoglyph": {
        "label": "Homoglyph",
        "description": "Visually identical Unicode characters (e.g. Cyrillic) replace Latin letters.",
        "example": "google.com → gооgle.com (Cyrillic о)",
        "color": "#ef4444",
    },
    "vowel_substitution": {
        "label": "Vowel Substitution",
        "description": "A vowel is swapped for another vowel (a, e, i, o, u).",
        "example": "paypal.com → paypel.com",
        "color": "#ec4899",
    },
}


# ── Single-technique generators ────────────────────────────────────────────────

def _split(domain: str) -> tuple[str, str]:
    dot = domain.rfind(".")
    return (domain[:dot], domain[dot:]) if dot != -1 else (domain, "")


def omissions(domain: str) -> set[str]:
    name, tld = _split(domain)
    return {name[:i] + name[i + 1:] + tld for i in range(len(name)) if len(name) > 1}


def transpositions(domain: str) -> set[str]:
    name, tld = _split(domain)
    out: set[str] = set()
    for i in range(len(name) - 1):
        t = list(name)
        t[i], t[i + 1] = t[i + 1], t[i]
        c = "".join(t) + tld
        if c != domain:
            out.add(c)
    return out


def adjacent_key_errors(domain: str) -> set[str]:
    name, tld = _split(domain)
    out: set[str] = set()
    for i, ch in enumerate(name):
        for alt in QWERTY.get(ch.lower(), ""):
            out.add(name[:i] + alt + name[i + 1:] + tld)
    return out


def alternate_tlds(domain: str) -> set[str]:
    name, tld = _split(domain)
    return {name + t for t in ALTERNATE_TLDS if t != tld}


def homoglyph_variants(domain: str) -> set[str]:
    name, tld = _split(domain)
    out: set[str] = set()
    for i, ch in enumerate(name):
        for sub in HOMOGLYPHS.get(ch.lower(), []):
            out.add(name[:i] + sub + name[i + 1:] + tld)
    return out


def vowel_substitutions(domain: str) -> set[str]:
    name, tld = _split(domain)
    out: set[str] = set()
    for i, ch in enumerate(name):
        if ch.lower() in VOWELS:
            for v in VOWELS:
                if v != ch.lower():
                    out.add(name[:i] + v + name[i + 1:] + tld)
    return out


TECHNIQUES: dict[str, callable] = {
    "omission":           omissions,
    "transposition":      transpositions,
    "adjacent_key":       adjacent_key_errors,
    "alternate_tld":      alternate_tlds,
    "homoglyph":          homoglyph_variants,
    "vowel_substitution": vowel_substitutions,
}


# ── Combination engine ─────────────────────────────────────────────────────────

def _apply_sequence(domain: str, names: list[str]) -> set[str]:
    """Apply techniques in order; each step operates on all results of the previous."""
    current: set[str] = {domain}
    for name in names:
        fn = TECHNIQUES[name]
        nxt: set[str] = set()
        for d in current:
            nxt.update(fn(d))
        current = nxt
    return current - {domain}


def generate_all(domain: str) -> dict:
    """
    Returns every single-technique and pairwise-combination result for `domain`.

    Structure:
      {
        "omission":          {"label": ..., "description": ..., "example": ...,
                              "color": ..., "combo": False, "variants": [...]},
        "omission+homoglyph": {..., "combo": True, "variants": [...]},
        ...
      }
    """
    domain = domain.lower().strip()
    results: dict = {}
    names = list(TECHNIQUES.keys())

    # ── Single techniques ──────────────────────────────────────────────────────
    for name in names:
        variants = TECHNIQUES[name](domain)
        results[name] = {
            **TECHNIQUE_INFO[name],
            "combo": False,
            "variants": sorted(variants),
        }

    # ── All C(5, 2) = 10 pairs — both orderings merged ─────────────────────────
    for a, b in _combinations(names, 2):
        merged = _apply_sequence(domain, [a, b]) | _apply_sequence(domain, [b, a])
        key = f"{a}+{b}"
        results[key] = {
            "label": f"{TECHNIQUE_INFO[a]['label']} + {TECHNIQUE_INFO[b]['label']}",
            "description": (
                f"Applies {TECHNIQUE_INFO[a]['label'].lower()} and "
                f"{TECHNIQUE_INFO[b]['label'].lower()} together."
            ),
            "example": f"{TECHNIQUE_INFO[a]['example']}  ×  {TECHNIQUE_INFO[b]['example']}",
            "color": TECHNIQUE_INFO[a]["color"],
            "color2": TECHNIQUE_INFO[b]["color"],
            "combo": True,
            "variants": sorted(merged),
        }

    # Attach counts
    for v in results.values():
        v["count"] = len(v["variants"])

    return results


# ── Reverse lookup: find which known domain is being impersonated ──────────────

def build_length_index(domains: list[str]) -> dict[int, list[str]]:
    """Group domains by name length for fast candidate pre-filtering."""
    index: dict[int, list[str]] = {}
    for domain in domains:
        name = domain.split(".")[0]
        bucket = index.setdefault(len(name), [])
        bucket.append(domain)
    return index


def _identify_techniques(query: str, target: str) -> list[str]:
    """Return which single techniques transform `target` into `query`."""
    found = []
    for name, fn in TECHNIQUES.items():
        if query in fn(target):
            found.append(TECHNIQUE_INFO[name]["label"])
    return found


def find_closest(
    query: str,
    known: list[str],
    top_n: int = 5,
    length_index: dict[int, list[str]] | None = None,
    rank: dict[str, int] | None = None,
    bound: int = 3,
) -> list[dict]:
    """
    Find the top_n most similar domains from `known` to `query`.
    Sorts hits by (edit_distance, popularity_rank) so well-known domains
    always surface before obscure ones at the same distance.
    """
    query = query.lower().strip()
    q_name, q_tld = _split(query)
    q_len = len(q_name)

    # Narrow candidates to domains whose name length is within `bound` of query
    if length_index:
        candidates: list[str] = []
        for delta in range(-bound, bound + 1):
            candidates.extend(length_index.get(q_len + delta, []))
    else:
        candidates = known

    # Score with bounded Levenshtein
    # sort_key = (edit_dist - 1 if TLD matches, popularity_rank)
    # TLD bonus ensures facebook.net beats obscure facabook.com when query is *.net
    _max_rank = len(known)
    hits: list[tuple[int, int, str, int]] = []
    for domain in candidates:
        d_name, d_tld = _split(domain)
        dist = _levenshtein_bounded(q_name, d_name, bound)
        if dist <= bound:
            pop       = rank.get(domain, _max_rank) if rank else _max_rank
            tld_bonus = -1 if d_tld == q_tld else 0
            hits.append((dist + tld_bonus, pop, domain, dist))

    hits.sort()

    # Identify techniques — iterate in already-correct TLD+popularity order
    with_technique: list[dict] = []
    without_technique: list[dict] = []
    for _sort_key, _pop, domain, dist in hits[: top_n * 8]:
        techniques = _identify_techniques(query, domain)
        entry = {"domain": domain, "distance": dist, "techniques": techniques}
        (with_technique if techniques else without_technique).append(entry)

    # Technique matches first, then the rest — both groups keep TLD+popularity order
    return (with_technique + without_technique)[:top_n]
