"""
Write MoatMap's two public datasets into a checkout of the moatmap-data repo.

1. The decile tracker: the site's own public CSV exports, copied as served
   (/api/decile-tracker/export.csv and /ai-cohorts.csv, both scopes). Nothing
   is recomputed here, so the repo can never disagree with /decile-tracker.
2. The monthly Best Stocks lists: one row per stock per edition, for every
   country edition plus the GLOBAL edition's four pillar lists.

What the Best Stocks rows leave out, on purpose:
  - `signal` (Strong Buy / Buy / ...): readers never see the band names
    (founder decision 2026-11-06, web/src/lib/scoreRanges.ts).
  - market cap, P/E, P/B, dividend yield, currency: vendor-sourced figures,
    which we show on the site but do not redistribute in bulk.
  - has_deep_dive: a site-internal flag.

Two derived columns and files, computed only from what is published:
  - `new_entry` on each Best Stocks row: not on the same list the month before.
  - `decile-tracker/summary-<scope>.csv`: decile 1 against decile 10 per
    vintage and score, with the ACWI ETF beside it.

The public repo runs a copy of this file monthly (moatmap-data
scripts/update.py, a GitHub Action, no database): edition files already in the
repo are kept, so the newest month is added and nothing earlier is lost. Copy
this file over that one after changing it here.

Sources: the latest edition per market comes from the public API, which is
what the site serves (an edition re-formed after a fix, like the UK in
November 2026, comes back corrected). Older editions are frozen once formed,
and the API serves only the newest, so `--from-db` backfills them from a
local copy of the production database (read-only). The API wins wherever both
hold the same (edition, market).

Usage:
    python tools/export_public_datasets.py --out ../moatmap-data
    python tools/export_public_datasets.py --out ../moatmap-data --from-db data/investor.db
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sqlite3
import sys
import urllib.request
from pathlib import Path

SITE = "https://moatmap.ai"
USER_AGENT = "moatmap-dataset-export/1.0"
GLOBAL_KEY = "GLOBAL"

# The country edition is a single list ranked on StockRank; the GLOBAL edition
# carries four lists, one per pillar, under `lists`.
COUNTRY_LIST = "stockrank"

BEST_STOCKS_COLUMNS = [
    "edition_date",
    "edition",
    "list",
    "rank",
    "ticker",
    "name",
    "listing_market",
    "sector",
    "stockrank",
    "quality_rank",
    "value_rank",
    "momentum_rank",
    "insider_buy",
    "buyback",
    "new_entry",
    "why",
]

# Never written, whatever a payload carries. Checked again on every output row.
EXCLUDED_FIELDS = frozenset({
    "signal", "market_cap_usd", "trailing_pe", "price_to_book",
    "dividend_yield", "currency", "has_deep_dive",
})

DECILE_EXPORTS = {
    "decile-tracker/deciles-investable.csv": "/api/decile-tracker/export.csv?scope=investable",
    "decile-tracker/deciles-full.csv": "/api/decile-tracker/export.csv?scope=full",
    "decile-tracker/ai-cohorts-investable.csv": "/api/decile-tracker/ai-cohorts.csv?scope=investable",
    "decile-tracker/ai-cohorts-full.csv": "/api/decile-tracker/ai-cohorts.csv?scope=full",
}


def fetch(base: str, path: str) -> bytes:
    req = urllib.request.Request(base + path, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        if resp.status != 200:
            raise RuntimeError(f"{path}: HTTP {resp.status}")
        return resp.read()


def _bool(v) -> str:
    return "true" if v else "false"


def _num(v) -> str:
    if v is None:
        return ""
    return f"{float(v):.1f}"


def edition_rows(payload: dict) -> list[dict]:
    """One output row per stock in an edition payload (schema_version 1)."""
    edition = str(payload["market"]).upper()
    date = str(payload["edition_date"])
    if edition == GLOBAL_KEY:
        lists = payload.get("lists") or {}
        sources = [(name, rows) for name, rows in sorted(lists.items())]
    else:
        sources = [(COUNTRY_LIST, payload.get("stocks") or [])]

    out = []
    for list_name, rows in sources:
        for r in rows:
            if not r.get("ticker") or r.get("rank") is None:
                raise ValueError(f"{date} {edition}: a row without ticker or rank")
            out.append({
                "edition_date": date,
                "edition": edition,
                "list": list_name,
                "rank": int(r["rank"]),
                "ticker": r["ticker"],
                "name": r.get("name") or "",
                # Editions before September 2026 carry no per-row market; a
                # country edition lists only its own market's stocks.
                "listing_market": r.get("market") or ("" if edition == GLOBAL_KEY else edition),
                "sector": r.get("sector") or "",
                "stockrank": _num(r.get("stockrank")),
                "quality_rank": _num(r.get("quality_rank")),
                "value_rank": _num(r.get("value_rank")),
                "momentum_rank": _num(r.get("momentum_rank")),
                "insider_buy": _bool(r.get("insider_buy")),
                "buyback": _bool(r.get("buyback")),
                "new_entry": "",  # set across months by mark_new_entries
                "why": (r.get("why") or "").strip(),
            })
    return out


def payloads_from_api(base: str) -> list[dict]:
    editions = json.loads(fetch(base, "/api/best-stocks/editions"))["editions"]
    return [json.loads(fetch(base, f"/api/best-stocks/{market}")) for market in sorted(editions)]


def payloads_from_db(db_path: Path) -> list[dict]:
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT payload_json FROM best_stocks_snapshot WHERE schema_version = 1 "
            "ORDER BY edition_date, market"
        ).fetchall()
    finally:
        conn.close()
    return [json.loads(r[0]) for r in rows]


def merge_payloads(db_payloads: list[dict], api_payloads: list[dict]) -> dict:
    """Keyed on (edition_date, market). The API is applied last, so it wins."""
    merged: dict[tuple[str, str], dict] = {}
    for p in [*db_payloads, *api_payloads]:
        merged[(str(p["edition_date"]), str(p["market"]).upper())] = p
    return merged


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    for r in rows:
        leaked = EXCLUDED_FIELDS.intersection(r)
        if leaked:
            raise ValueError(f"excluded field(s) {sorted(leaked)} reached {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(buf.getvalue(), encoding="utf-8", newline="")


def existing_groups(out: Path) -> dict[tuple[str, str], list[dict]]:
    """Rows already in the repo's edition files, keyed (edition_date, edition).

    The API serves only each market's newest edition, so a run without a
    database keeps every earlier month from the files it wrote before.
    """
    groups: dict[tuple[str, str], list[dict]] = {}
    for path in sorted((out / "data" / "best-stocks" / "editions").glob("*.csv")):
        with path.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                row = {c: row.get(c, "") for c in BEST_STOCKS_COLUMNS}
                row["rank"] = int(row["rank"])
                groups.setdefault((row["edition_date"], row["edition"]), []).append(row)
    return groups


def mark_new_entries(rows: list[dict]) -> None:
    """new_entry: "true" when the ticker was not on the same list the month
    before, "false" when it was, blank when that list has no earlier month."""
    by_list: dict[tuple[str, str], dict[str, set[str]]] = {}
    for r in rows:
        by_list.setdefault((r["edition"], r["list"]), {}).setdefault(r["edition_date"], set()).add(r["ticker"])
    previous: dict[tuple[str, str, str], set[str] | None] = {}
    for key, months in by_list.items():
        prior = None
        for date in sorted(months):
            previous[(*key, date)] = prior
            prior = months[date]
    for r in rows:
        prior = previous[(r["edition"], r["list"], r["edition_date"])]
        r["new_entry"] = "" if prior is None else ("false" if r["ticker"] in prior else "true")


def write_best_stocks(out: Path, merged: dict) -> dict[str, int]:
    """One file per edition month plus one combined file. Returns rows per month."""
    groups = existing_groups(out)
    for (date, market), payload in merged.items():
        groups[(date, market)] = edition_rows(payload)
    every = [r for rows in groups.values() for r in rows]
    mark_new_entries(every)
    every.sort(key=lambda r: (r["edition_date"], r["edition"] == GLOBAL_KEY, r["edition"], r["list"], r["rank"]))

    counts: dict[str, int] = {}
    by_month: dict[str, list[dict]] = {}
    for r in every:
        by_month.setdefault(r["edition_date"], []).append(r)
    for date, rows in by_month.items():
        write_csv(out / "data" / "best-stocks" / "editions" / f"{date}.csv", BEST_STOCKS_COLUMNS, rows)
        counts[date] = len(rows)
    write_csv(out / "data" / "best-stocks" / "best-stocks.csv", BEST_STOCKS_COLUMNS, every)
    return counts


SUMMARY_COLUMNS = [
    "vintage_date", "period_end", "period_days", "rank_field", "scope",
    "top_decile_return_usd", "bottom_decile_return_usd", "spread_usd",
    "top_decile_hit_rate", "acwi_return", "top_decile_minus_acwi",
]


def _f(v: str) -> float | None:
    return float(v) if v not in ("", None) else None


def decile_summary(rows: list[dict]) -> list[dict]:
    """Decile 1 (highest scores) against decile 10 (lowest), per vintage and
    score, with the ACWI ETF beside it. Rows with no return yet are skipped."""
    cells: dict[tuple[str, str, str], dict[str, dict]] = {}
    for r in rows:
        if r["decile"] in ("1", "10"):
            cells.setdefault((r["vintage_date"], r["rank_field"], r["scope"]), {})[r["decile"]] = r
    out = []
    for (vintage, field, scope), pair in sorted(cells.items()):
        top, bottom = pair.get("1"), pair.get("10")
        if not top or not bottom:
            continue
        t, b = _f(top["avg_return_usd"]), _f(bottom["avg_return_usd"])
        if t is None or b is None:
            continue
        acwi = _f(top["acwi_return"])
        out.append({
            "vintage_date": vintage,
            "period_end": top["period_end"],
            "period_days": top["period_days"],
            "rank_field": field,
            "scope": scope,
            "top_decile_return_usd": f"{t:.6f}",
            "bottom_decile_return_usd": f"{b:.6f}",
            "spread_usd": f"{t - b:.6f}",
            "top_decile_hit_rate": top["hit_rate"],
            "acwi_return": "" if acwi is None else f"{acwi:.6f}",
            "top_decile_minus_acwi": "" if acwi is None else f"{t - acwi:.6f}",
        })
    return out


def write_deciles(out: Path, base: str) -> dict[str, int]:
    counts = {}
    for rel, path in DECILE_EXPORTS.items():
        body = fetch(base, path).decode("utf-8")
        lines = body.splitlines()
        if len(lines) < 2 or not lines[0].startswith("regime_id,"):
            header = lines[0][:60] if lines else ""
            raise RuntimeError(f"{path}: not the expected CSV (header {header!r}, {len(lines)} lines)")
        target = out / "data" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="")
        counts[rel] = len(lines) - 1
        if "/deciles-" in rel:
            summary = decile_summary(list(csv.DictReader(io.StringIO("\n".join(lines)))))
            name = rel.replace("/deciles-", "/summary-")
            write_csv(out / "data" / name, SUMMARY_COLUMNS, summary)
            counts[name] = len(summary)
    return counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, type=Path, help="checkout of the moatmap-data repo")
    ap.add_argument("--from-db", type=Path, help="local DB copy to backfill older Best Stocks editions")
    ap.add_argument("--base-url", default=SITE)
    args = ap.parse_args(argv)

    db_payloads = payloads_from_db(args.from_db) if args.from_db else []
    api_payloads = payloads_from_api(args.base_url)
    months = write_best_stocks(args.out, merge_payloads(db_payloads, api_payloads))
    deciles = write_deciles(args.out, args.base_url)

    for date, n in months.items():
        print(f"best-stocks {date}: {n} rows")
    for rel, n in deciles.items():
        print(f"{rel}: {n} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
