# ============================================================
# ITEM #5 — MULTI-DEGREE ELLIOTT WAVE LATTICE
# ============================================================
# FILE: core/wave_lattice.py
#
# patterns.py already runs Elliott Wave analysis independently per
# timeframe (visible in pattern_analysis["timeframes"]["M1"|"M5"|...
# ["elliott_waves"]). This is pure post-processing over that existing
# output -- no new wave-counting logic, no new data. It answers the
# question the flat per-TF output can't: is M1's current wave a genuine
# sub-wave inside H1's active structure, or does it actually contradict
# the higher-degree count?
#
# Convention: higher timeframe = larger (higher) wave degree.
#   H1 > M30 > M15 > M5 > M1
# A child timeframe's wave is classified as NESTED if its direction is
# consistent with the parent's implied bias, and CONTRADICTS if not.
# "Consistent" for a corrective wave (A-B-C) means: the parent's overall
# corrective direction and the child's current wave direction agree, OR
# the child is itself in a wave position that's a normal sub-leg of the
# parent's structure (e.g. parent is bearish-C, child's own A-leg within
# that same move is bearish too, even if the child's *current* sub-wave
# has since turned bullish for its own smaller C).
# ============================================================

from typing import Dict, Any, List, Optional

TIMEFRAME_DEGREE_ORDER = ["H1", "M30", "M15", "M5", "M1"]  # highest degree first

DEGREE_LABELS = {
    "H1": "primary",
    "M30": "intermediate",
    "M15": "minor",
    "M5": "minute",
    "M1": "minuette",
}


def _dominant_wave(tf_block: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Pick the highest-confidence Elliott wave call for a timeframe block."""
    waves = tf_block.get("elliott_waves", [])
    if not waves:
        return None
    return max(waves, key=lambda w: w.get("confidence", 0))


def build_wave_lattice(pattern_analysis: Dict[str, Any]) -> Dict[str, Any]:
    """
    Takes the existing pattern_analysis["timeframes"] block (unmodified)
    and returns an explicit parent->child nesting tree instead of five
    flat, independently-reported wave calls.
    """
    timeframes = pattern_analysis.get("timeframes", {})
    present_tfs = [tf for tf in TIMEFRAME_DEGREE_ORDER if tf in timeframes]

    if not present_tfs:
        return {"lattice": [], "note": "no timeframes present in pattern_analysis"}

    nodes = {}
    for tf in present_tfs:
        wave = _dominant_wave(timeframes[tf])
        nodes[tf] = {
            "timeframe": tf,
            "degree": DEGREE_LABELS.get(tf, tf.lower()),
            "wave": wave,
            "direction": wave.get("direction") if wave else "NONE",
            "current_wave_label": wave.get("current_wave") if wave else None,
            "confidence": wave.get("confidence_score", 0) if wave else 0,
            "children": [],
            "relationship_to_parent": None,  # filled in below
        }

    # Link each timeframe to its immediate higher-degree parent (the next
    # entry up in TIMEFRAME_DEGREE_ORDER that is actually present).
    for i, tf in enumerate(present_tfs):
        if i == 0:
            nodes[tf]["relationship_to_parent"] = "ROOT (highest available degree)"
            continue
        parent_tf = present_tfs[i - 1]
        parent = nodes[parent_tf]
        child = nodes[tf]

        parent_dir = parent["direction"]
        child_dir = child["direction"]

        if parent_dir in (None, "NONE", "NEUTRAL") or child_dir in (None, "NONE", "NEUTRAL"):
            relationship = "INDETERMINATE (parent or child has no directional wave call)"
        elif parent_dir == child_dir:
            relationship = f"NESTED (sub-wave consistent with {parent_tf}'s {parent_dir} structure)"
        else:
            relationship = (
                f"CONTRADICTS ({tf} shows {child_dir} against {parent_tf}'s {parent_dir} "
                f"structure — this is a genuine multi-degree disagreement, not noise to discard, "
                f"but it should be weighted as a lower-degree counter-move inside a higher-degree "
                f"trend rather than an equal-weight vote against it)"
            )
        child["relationship_to_parent"] = relationship
        parent["children"].append(tf)

    root_tf = present_tfs[0]
    single_tf_mode = len(present_tfs) == 1

    lattice_summary = {
        "root_timeframe": root_tf,
        "root_degree": DEGREE_LABELS.get(root_tf, root_tf.lower()),
        "root_direction": nodes[root_tf]["direction"],
        # ✅ FIXED: with only one timeframe present (the normal case under
        # PATTERN_ANALYSIS_CURRENT_TF_ONLY=True, default M1), there is
        # nothing to nest against - "fully_nested: True" would be
        # vacuously true and read as if real cross-timeframe confirmation
        # happened when none was possible. None means "not applicable",
        # not "yes, confirmed".
        "single_timeframe_mode": single_tf_mode,
        "fully_nested": None if single_tf_mode else all(
            "NESTED" in nodes[tf]["relationship_to_parent"] or nodes[tf]["relationship_to_parent"].startswith("ROOT")
            for tf in present_tfs
        ),
        "contradicting_timeframes": [
            tf for tf in present_tfs if "CONTRADICTS" in (nodes[tf]["relationship_to_parent"] or "")
        ],
    }

    return {
        "lattice_summary": lattice_summary,
        "nodes": nodes,
        "read_order": present_tfs,  # root to leaf, in degree order
    }


def explain_wave_lattice(lattice: Dict[str, Any]) -> str:
    """Deterministic natural-language walkthrough of the nesting tree."""
    if not lattice.get("nodes"):
        return lattice.get("note", "No wave lattice data available.")

    lines = []
    summary = lattice["lattice_summary"]
    lines.append(
        f"Root degree: {summary['root_timeframe']} ({summary['root_degree']}) — "
        f"{summary['root_direction']}"
    )

    if summary.get("single_timeframe_mode"):
        lines.append(
            f"Single-timeframe mode ({summary['root_timeframe']} only) — no other timeframe "
            f"was fetched or analyzed, so there is nothing to nest against. This is not a "
            f"cross-timeframe confirmation; it's a single wave read.\n"
        )
    else:
        lines.append(f"Fully nested across all timeframes: {summary['fully_nested']}\n")

    for tf in lattice["read_order"]:
        node = lattice["nodes"][tf]
        wave_label = node["current_wave_label"] or "n/a"
        lines.append(
            f"  {tf} ({node['degree']}): wave {wave_label}, direction {node['direction']}, "
            f"confidence {node['confidence']}%"
        )
        lines.append(f"    -> {node['relationship_to_parent']}")

    if summary["contradicting_timeframes"]:
        lines.append(
            f"\nGenuine multi-degree disagreement at: {', '.join(summary['contradicting_timeframes'])}. "
            f"Treat these as lower-degree counter-moves inside the higher-degree trend, not as "
            f"equal-weight opposing votes."
        )
    elif not summary.get("single_timeframe_mode"):
        lines.append("\nNo contradictions — all present timeframes nest consistently under the root.")

    return "\n".join(lines)