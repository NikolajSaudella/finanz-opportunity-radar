from pathlib import Path

import pandas as pd

from . import briefs, clean, insights, scoring, segments, text_signals

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "finanz_financial_life_survey.csv"


def build(refresh_llm: bool = False, verbose: bool = False) -> dict:
    raw = clean.load_survey(DATA)
    df = clean.add_features(raw)

    # 1) segnali dal testo libero (LLM, con cache)
    sig = text_signals.extract_text_signals(df, refresh=refresh_llm, verbose=verbose)
    df = df.merge(sig, on="user_id", how="left")
    df["no_calls"] = df["no_product_calls"] | df["contact_restrictions"].apply(lambda r: "no_product_calls" in r)

    # 2) qualità dati: flag strutturali + confronto testo/dati
    flags = pd.concat([clean.structural_flags(df), text_signals.text_vs_data_flags(df)], ignore_index=True)
    per_user = flags.groupby("user_id")["flag"].apply(list)
    df["dq_flags"] = df["user_id"].map(per_user).apply(lambda x: x if isinstance(x, list) else [])
    df["confidence"] = df["dq_flags"].apply(clean.confidence_level)

    # 3) segmenti e scoring
    df["segment"] = segments.assign_segment(df)
    long = scoring.score_all(df)
    users = scoring.best_per_user(long, df)
    stats = segments.segment_stats(users, long)

    # 4) insight deterministici + testi per stakeholder (LLM, con cache)
    ins = insights.compute_insights(users, long)
    gstats = insights.global_stats(users, long, ins)
    seg_briefs = briefs.segment_briefs(stats, refresh=refresh_llm, verbose=verbose)
    summary = briefs.executive_summary(gstats, refresh=refresh_llm)

    return {
        "users": users, "long": long, "flags": flags, "features": df,
        "segment_stats": stats, "segment_briefs": seg_briefs,
        "insights": ins, "global_stats": gstats, "summary": summary,
    }
