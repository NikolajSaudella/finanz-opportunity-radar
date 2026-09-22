"""
Esegue la pipeline e scrive i risultati in outputs/.

    python run_pipeline.py                # usa la cache LLM se c'è
    python run_pipeline.py --refresh-llm  # rifà le chiamate LLM (serve ANTHROPIC_API_KEY)
"""

import argparse
import json
from pathlib import Path

from radar.pipeline import build

OUT = Path(__file__).resolve().parent / "outputs"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh-llm", action="store_true", help="ignora la cache e richiama l'LLM")
    args = ap.parse_args()

    res = build(refresh_llm=args.refresh_llm, verbose=True)
    OUT.mkdir(exist_ok=True)

    users = res["users"].sort_values("expected_value_eur", ascending=False)
    cols = [
        "user_id", "priority", "segment", "opportunity_name", "expected_value_eur", "propensity",
        "channel", "action", "confidence", "secondary_opportunities", "evidence", "dq_flags",
    ]
    u = users[cols].copy()
    for c in ("secondary_opportunities", "evidence", "dq_flags"):
        u[c] = u[c].apply(lambda x: " | ".join(x) if isinstance(x, list) else "")
    u.to_csv(OUT / "priority_list.csv", index=False)

    lo = res["long"].copy()
    lo["evidence"] = lo["evidence"].apply(" | ".join)
    lo.sort_values(["user_id", "rank_in_user"]).to_csv(OUT / "all_opportunities.csv", index=False)

    res["flags"].to_csv(OUT / "data_quality_flags.csv", index=False)

    with open(OUT / "segments.json", "w", encoding="utf-8") as f:
        json.dump({seg: {"stats": res["segment_stats"][seg], **res["segment_briefs"][seg]}
                   for seg in res["segment_stats"]}, f, ensure_ascii=False, indent=2)
    with open(OUT / "insights.json", "w", encoding="utf-8") as f:
        json.dump({"sintesi": res["summary"], "insight": res["insights"]}, f, ensure_ascii=False, indent=2)

    print(f"\nScritti in {OUT}/: priority_list.csv, all_opportunities.csv, data_quality_flags.csv, "
          "segments.json, insights.json")
    print("\nTop 10 per valore atteso:")
    print(users[["user_id", "segment", "opportunity_name", "expected_value_eur", "channel"]].head(10).to_string(index=False))


if __name__ == "__main__":
    main()
