"""Real probabilities: measured win frequencies from the setup journals. No scores, no points.

A cell is (category, variant) or (category, variant, condition=value). Its probability is the win
frequency on the HOLDOUT period with a Wilson 95% range. A condition cell is only used when its win
frequency differs from the base cell in the same direction on discovery AND holdout (measured
effect), and both periods have at least MIN_SAMPLE trades. Below MIN_SAMPLE the probability is
unknown (None).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

MIN_SAMPLE = 100
Z95 = 1.959964
CONDITIONS = ("h4_alignment", "session", "pool", "open_location", "retrace_band", "sr_confluence",
              "fib_confluence", "premium_side")
TABLE_PATH = Path(__file__).resolve().parents[2] / "reports" / "v2" / "v3" / "probability_table.json"


def wilson(wins: int, n: int) -> tuple[float | None, float | None]:
    if n == 0:
        return None, None
    p = wins / n
    denom = 1 + Z95 ** 2 / n
    centre = (p + Z95 ** 2 / (2 * n)) / denom
    half = Z95 * math.sqrt(p * (1 - p) / n + Z95 ** 2 / (4 * n * n)) / denom
    return round(centre - half, 4), round(centre + half, 4)


def condition_values(row: dict) -> dict:
    c = dict(row.get("context") or {})
    d = 1 if row["side"] == "BUY" else -1
    h4 = c.get("htf_trend", c.get("h4_trend"))
    if h4 is not None:
        c["h4_alignment"] = "aligned" if h4 == d else ("against" if h4 == -d else "neutral")
    return {k: c[k] for k in CONDITIONS if k in c and c[k] is not None}


def _cell(rows: list[dict]) -> dict:
    n = len(rows)
    wins = sum(1 for r in rows if r["win"])
    lo, hi = wilson(wins, n)
    net = sum(r["net_r"] for r in rows) / n if n else None
    return {"n": n, "wins": wins, "value": round(wins / n, 4) if n else None, "low": lo, "high": hi,
            "net_r": round(net, 4) if net is not None else None}


def build_table(journal_paths: list[Path]) -> dict:
    rows = []
    for p in journal_paths:
        with open(p) as f:
            rows.extend(json.loads(line) for line in f)
    traded = [r for r in rows if r["status"] == "FILLED_CLOSED"]
    table: dict[str, dict] = {}
    by_base: dict[tuple, list[dict]] = {}
    for r in traded:
        by_base.setdefault((r["category"], r["variant"]), []).append(r)
    for (cat, var), g in by_base.items():
        disc = [r for r in g if r["period"] == "discovery"]
        hold = [r for r in g if r["period"] == "holdout"]
        base = {"discovery": _cell(disc), "holdout": _cell(hold), "conditions": {}}
        for cond in CONDITIONS:
            values = {condition_values(r).get(cond) for r in g} - {None}
            for v in values:
                d_sub = [r for r in disc if condition_values(r).get(cond) == v]
                h_sub = [r for r in hold if condition_values(r).get(cond) == v]
                cd, ch = _cell(d_sub), _cell(h_sub)
                effect_d = (cd["value"] - base["discovery"]["value"]) if cd["n"] and base["discovery"]["n"] else None
                effect_h = (ch["value"] - base["holdout"]["value"]) if ch["n"] and base["holdout"]["n"] else None
                confirmed = (cd["n"] >= MIN_SAMPLE and ch["n"] >= MIN_SAMPLE and effect_d is not None
                             and effect_h is not None and effect_d * effect_h > 0)
                base["conditions"][f"{cond}={v}"] = {"discovery": cd, "holdout": ch, "confirmed": confirmed,
                                                     "effect_discovery": round(effect_d, 4) if effect_d is not None else None,
                                                     "effect_holdout": round(effect_h, 4) if effect_h is not None else None}
        table[f"{cat}:{var}"] = base
    return {"min_sample": MIN_SAMPLE, "cells": table}


def probability_for(setup, table: dict) -> dict:
    """The setup's real probability: most specific confirmed cell, else the base holdout cell, else unknown."""
    cell = table.get("cells", {}).get(f"{setup.category}:{setup.variant}")
    unknown = {"value": None, "n": 0, "low": None, "high": None, "table": None}
    if not cell:
        return unknown
    row = {"side": setup.side, "context": setup.context}
    vals = condition_values(row)
    best, best_key = None, None
    for cond, v in vals.items():
        c = cell["conditions"].get(f"{cond}={v}")
        if c and c["confirmed"] and (best is None or c["holdout"]["n"] > best["holdout"]["n"]):
            best, best_key = c, f"{cond}={v}"
    chosen = best["holdout"] if best else cell["holdout"]
    if chosen["n"] < MIN_SAMPLE:
        return dict(unknown, n=chosen["n"], table=f"{setup.category}:{setup.variant}" + (f"|{best_key}" if best_key else ""))
    return {"value": chosen["value"], "n": chosen["n"], "low": chosen["low"], "high": chosen["high"],
            "net_r": chosen["net_r"], "table": f"{setup.category}:{setup.variant}" + (f"|{best_key}" if best_key else "")}


def load_table(path: Path = TABLE_PATH) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {"min_sample": MIN_SAMPLE, "cells": {}}


def main():
    journals = sorted(TABLE_PATH.parent.glob("*_journal.jsonl"))
    table = build_table(journals)
    TABLE_PATH.write_text(json.dumps(table, indent=1))
    for key, cell in table["cells"].items():
        conf = [k for k, c in cell["conditions"].items() if c["confirmed"]]
        print(key, "discovery", cell["discovery"], "holdout", cell["holdout"], "confirmed:", conf)


if __name__ == "__main__":
    main()
