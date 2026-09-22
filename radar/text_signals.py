"""
Estrazione strutturata dalla risposta aperta "In cosa vorresti ricevere aiuto?".

Qui uso l'LLM perché è il punto dove le regole si rompono:
- in produzione le risposte arriveranno in italiano, spagnolo, francese (e inglese);
- le persone parafrasano, negano ("prima di pensare a investire..."), mettono
  vincoli ("non chiamatemi per prodotti") che un keyword match legge al contrario;
- serve distinguere il bisogno principale da quelli di contorno.

L'LLM NON decide chi è un'opportunità e non vede i dati finanziari: estrae solo
segnali dal testo, dentro una tassonomia chiusa. Il confronto con i campi
strutturati e lo scoring restano deterministici (scoring.py).

Il testo viene deduplicato prima della chiamata: in questo dataset ci sono
33 risposte distinte su 120 utenti, quindi 33 chiamate invece di 120.
"""

import re

import pandas as pd

from . import config as C
from .llm import JsonCache, cache_key, complete_json, get_client

MENTION_KEYS = [
    "is_freelancer", "has_children", "first_salary", "retirement_near",
    "already_invests", "mostly_cash", "is_renting",
]

SYSTEM_PROMPT = f"""Sei un analista del team AIOps di Finanz, un'app di finanza personale.
Ricevi la risposta libera di un utente alla domanda "In cosa vorresti ricevere aiuto?".
La risposta può essere in qualsiasi lingua. Estrai SOLO ciò che il testo dice; non
inferire dati che non ci sono. Rispondi esclusivamente con un oggetto JSON, senza
testo prima o dopo, con questo schema:

{{
  "needs": [lista di codici tra: {", ".join(C.NEED_TAXONOMY)}],
  "primary_need": "uno dei codici di needs, quello centrale nella richiesta",
  "mentions": {{ {", ".join(f'"{k}": true|false|null' for k in MENTION_KEYS)} }},
  "contact_restrictions": [lista tra: "no_product_calls", "no_contact"],
  "decision_stage": "exploring" | "planning" | "ready_to_act",
  "stress_signal": true|false,
  "summary_it": "sintesi in italiano, max 15 parole"
}}

Regole:
- "mentions": true solo se il testo lo afferma, false solo se lo nega, altrimenti null.
- Se l'utente dice che vuole fare X "prima di" Y, Y non è un bisogno attuale.
- "contact_restrictions" va compilato se l'utente esprime preferenze sul NON essere contattato.
- "stress_signal" = true se il testo esprime pressione economica o ansia concreta.
"""


def _validate(obj: dict) -> dict:
    """Tengo solo etichette note: se il modello inventa un codice, lo scarto."""
    needs = [n for n in obj.get("needs", []) if n in C.NEED_TAXONOMY]
    primary = obj.get("primary_need")
    if primary not in needs:
        primary = needs[0] if needs else "general_plan"
        needs = needs or ["general_plan"]
    mentions = {k: obj.get("mentions", {}).get(k) for k in MENTION_KEYS}
    mentions = {k: (v if isinstance(v, bool) else None) for k, v in mentions.items()}
    restr = [r for r in obj.get("contact_restrictions", []) if r in ("no_product_calls", "no_contact")]
    stage = obj.get("decision_stage")
    return {
        "needs": needs,
        "primary_need": primary,
        "mentions": mentions,
        "contact_restrictions": restr,
        "decision_stage": stage if stage in ("exploring", "planning", "ready_to_act") else "exploring",
        "stress_signal": bool(obj.get("stress_signal", False)),
        "summary_it": str(obj.get("summary_it", ""))[:140],
    }


# --- fallback senza LLM ----------------------------------------------------------
# Serve solo a non far crashare la pipeline se manca sia la cache sia la API key.
# Funziona solo in inglese ed è volutamente grezzo: l'output viene marcato come
# "keyword_fallback" e l'app lo segnala.
_KW = {
    "budgeting": r"budget|monthly payments|payday",
    "emergency_fund": r"emergency|buffer|safety cushion",
    "debt_repayment": r"debt|repay|payments every month",
    "investing_start": r"start investing|investment plan|etf|invest monthly|invest small",
    "investment_optimisation": r"optimis|portfolio|allocation|concentrated|fees",
    "cash_allocation": r"in cash|cash sitting|what to do with it|savings rather|organising it",
    "home_purchase": r"buy(ing)? (a|my first) home|deposit",
    "mortgage": r"mortgage",
    "retirement_planning": r"retirement|pension",
    "protection": r"protection|insurance",
    "household_planning": r"household|family expenses|children",
    "freelance_finances": r"freelanc|taxes|business volatility|income changes",
    "general_plan": r"plan|strategy|goal",
}


def keyword_fallback(text: str) -> dict:
    t = (text or "").lower()
    needs = [k for k, rx in _KW.items() if re.search(rx, t)]
    return _validate({
        "needs": needs,
        "primary_need": needs[0] if needs else "general_plan",
        "mentions": {
            "is_freelancer": True if "freelanc" in t else None,
            "has_children": True if re.search(r"child", t) else None,
            "first_salary": True if "first proper salary" in t else None,
            "retirement_near": True if "retirement is getting closer" in t else None,
            "already_invests": True if re.search(r"already invest|comfortable investing|my portfolio", t) else None,
            "mostly_cash": True if re.search(r"in cash|cash sitting", t) else None,
            "is_renting": True if "renting" in t else None,
        },
        "contact_restrictions": ["no_product_calls"] if "not to be called" in t else [],
        "decision_stage": "exploring",
        "stress_signal": bool(re.search(r"pressure|under control|payday", t)),
        "summary_it": "",
    })


def extract_text_signals(df: pd.DataFrame, refresh: bool = False, verbose: bool = True) -> pd.DataFrame:
    cache = JsonCache("text_extraction")
    client = get_client()
    model = C.EXTRACTION_MODEL
    rows, stats = {}, {"cache": 0, "llm": 0, "fallback": 0}

    for text in df["what_would_you_like_help_with"].fillna("").unique():
        key = cache_key(C.PROMPT_VERSION_EXTRACTION, text)
        hit = None if (refresh and client is not None) else cache.get(key)
        if hit:
            res, src = hit["result"], hit.get("source", "llm")
            stats["cache"] += 1
        elif client is not None:
            raw = complete_json(client, model, SYSTEM_PROMPT, f"Risposta dell'utente:\n\"\"\"{text}\"\"\"")
            res, src = _validate(raw), "llm"
            cache.set(key, {"text": text, "model": model, "source": src, "result": res})
            stats["llm"] += 1
        else:
            res, src = keyword_fallback(text), "keyword_fallback"
            stats["fallback"] += 1
        rows[text] = {**res, "text_source": src}

    cache.save()
    if verbose:
        print(f"[text] testi unici: {len(rows)} | da cache: {stats['cache']} | "
              f"chiamate LLM: {stats['llm']} | fallback keyword: {stats['fallback']}")

    sig = df[["user_id", "what_would_you_like_help_with"]].copy()
    ext = sig["what_would_you_like_help_with"].fillna("").map(rows)
    sig = pd.concat([sig[["user_id"]], pd.json_normalize(ext.tolist())], axis=1)
    sig.columns = [c.replace("mentions.", "m_") for c in sig.columns]
    return sig


def text_vs_data_flags(df: pd.DataFrame) -> pd.DataFrame:
    """Confronto deterministico tra quello che l'utente scrive e quello che ha compilato."""
    checks = {
        "testo:dice_freelance_ma_dipendente": df["m_is_freelancer"].eq(True) & ~df["is_freelance"],
        "testo:parla_di_figli_ma_zero_dipendenti": df["m_has_children"].eq(True) & df["dependents"].eq(0),
        "testo:primo_stipendio_ma_anzianita_alta": df["m_first_salary"].eq(True)
        & ((df["years_in_current_role"] > 3) | df["age_band"].isin(["45-54", "55-64"])),
        "testo:pensione_vicina_ma_under_45": df["m_retirement_near"].eq(True)
        & df["age_band"].isin(["18-24", "25-34", "35-44"]),
        "testo:dice_di_investire_ma_senza_asset": df["m_already_invests"].eq(True) & df["investable_assets_eur"].eq(0),
        "testo:tutto_in_cash_ma_investe_di_piu": df["m_mostly_cash"].eq(True)
        & (df["investable_assets_eur"] > df["liquid"]),
        "testo:affitto_ma_proprietario": df["m_is_renting"].eq(True)
        & df["housing_status"].isin(["Own outright", "Own with mortgage"]),
        "contatto:consenso_si_ma_chiede_no_chiamate": df["marketing_contact_consent"].eq("Yes")
        & df["contact_restrictions"].apply(lambda r: "no_product_calls" in r),
    }
    out = []
    for name, mask in checks.items():
        for uid in df.loc[mask.fillna(False), "user_id"]:
            out.append({"user_id": uid, "flag": name, "source": "testo vs dati"})
    return pd.DataFrame(out, columns=["user_id", "flag", "source"])
