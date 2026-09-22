"""
Scoring delle opportunità: completamente deterministico.

Per ogni coppia (utente, opportunità) calcolo:
  - eleggibilità: l'opportunità ha senso per questa persona?
  - bisogno (0-1): quanto la situazione finanziaria la rende rilevante
  - intento (0-1): quanto l'utente la sta chiedendo (flag di interesse, obiettivo,
    testo libero estratto dall'LLM, eventi di vita)
  - readiness: solo per il mutuo, quanto è realistico che vada in porto
  - guardrail: casi in cui proporla sarebbe sbagliato per l'utente (es. investire
    con zero fondo emergenza e carta di credito aperta). Non la elimino, la sospendo.
  - raggiungibilità: consenso marketing e preferenze di contatto
  - confidenza: qualità dei dati di quell'utente

valore atteso = valore base × fattore dimensione × propensione × raggiungibilità × confidenza

Il "valore atteso" non è una previsione di ricavo: è un indice per ordinare,
espresso in euro solo perché così le ipotesi economiche sono leggibili e modificabili.
"""

import numpy as np
import pandas as pd

from . import config as C


def eur(x: float) -> str:
    return "€" + f"{x:,.0f}".replace(",", ".")


def _clip(x, lo=0.0, hi=1.0):
    return float(min(max(x, lo), hi))


# --- bisogno, per opportunità --------------------------------------------------
# ogni funzione ritorna None se l'opportunità non è eleggibile, altrimenti un dict
# con need, size, evidence, e opzionalmente readiness / blocked / note.

def _mortgage(r):
    plans = r.plans_home_purchase == "Yes"
    text_home = bool({"home_purchase", "mortgage"} & set(r.needs))
    if not (plans or text_home or r.interested_in_mortgage == "Yes"):
        return None
    if r.housing_status in ("Own outright", "Own with mortgage") and not plans:
        return None
    ev, readiness = [], 1.0
    h = r.home_purchase_horizon_months
    if plans:
        need = 0.4 if pd.isna(h) else 1.0 if h <= 18 else 0.8 if h <= 24 else 0.5 if h <= 36 else 0.3
        ev.append(f"Pianifica l'acquisto casa entro {h:.0f} mesi" if pd.notna(h) else "Pianifica l'acquisto casa")
    else:
        need = 0.2
        ev.append("Parla di casa nel testo, ma nel survey dice di non avere un piano di acquisto")
    if plans:
        cov = r.deposit_coverage
        if cov >= 1:
            ev.append(f"La liquidità ({eur(r.liquid)}) copre già anticipo e costi stimati ({eur(r.deposit_needed_eur)})")
        elif cov >= 0.5:
            readiness = 0.75
            ev.append(f"La liquidità copre circa il {cov:.0%} di anticipo e costi stimati")
        else:
            readiness = 0.45
            ev.append(f"Anticipo ancora lontano: liquidità al {cov:.0%} del necessario stimato")
    if r.employment_type == "Fixed-term":
        readiness *= 0.85
        ev.append("Contratto a tempo determinato: istruttoria bancaria più difficile")
    elif r.employment_type == "Self-employed":
        readiness *= 0.85
        ev.append("Autonomo: la banca chiederà più storico di reddito")
    if r.debt_to_annual_income > 0.3:
        readiness *= 0.7
        ev.append("Debito al consumo alto rispetto al reddito: sostenibilità da verificare")
    size = _clip(r.est_mortgage_eur / 150_000, 0.5, 2) if plans else 0.5
    if plans:
        ev.append(f"Mutuo sostenibile stimato: circa {eur(r.est_mortgage_eur)}")
    return dict(need=need, size=size, readiness=readiness, evidence=ev)


def _invest_start(r):
    wants = (
        r.interested_in_investing in ("Yes", "Maybe")
        or r.primary_financial_goal in ("Start investing", "Make savings work harder", "Build wealth")
        or bool({"investing_start", "cash_allocation"} & set(r.needs))
    )
    if not wants or r.investable_assets_eur >= 50_000 or r.investment_experience == "Experienced":
        return None
    ev = []
    need = 0.6 * _clip(r.excess_cash_eur / 20_000) + 0.4 * _clip(r.savings_rate / 0.2)
    if r.excess_cash_eur >= 5_000:
        ev.append(f"Liquidità oltre il cuscinetto di sicurezza: circa {eur(r.excess_cash_eur)}")
    if r.monthly_savings_eur > 0:
        ev.append(f"Risparmia {eur(r.monthly_savings_eur)} al mese ({r.savings_rate:.0%} del reddito)")
    blocked = None
    buffer_eur = r.buffer_target_months * r.est_monthly_expenses
    if "Credit card" in r.debt_list:
        if r.liquid - r.consumer_debt_eur < buffer_eur:
            blocked = "Prima chiudere il debito su carta di credito: costa più di quanto renderebbe investire"
        else:
            ev.append(f"Prima di investire conviene chiudere la carta di credito ({eur(r.consumer_debt_eur)}) "
                      "con parte della liquidità")
    if not blocked and r.emergency_fund_months < 3 and r.implied_buffer_months < 3:
        blocked = "Prima il fondo di emergenza (meno di 3 mesi di spese coperti)"
    size = _clip((r.excess_cash_eur + 6 * max(r.monthly_savings_eur, 0)) / 20_000, 0.5, 2)
    return dict(need=need, size=size, evidence=ev, blocked=blocked)


def _wealth_review(r):
    optimiser = r.primary_financial_goal == "Optimise investments" or "investment_optimisation" in r.needs
    if not (r.investable_assets_eur >= 50_000 or (optimiser and r.investment_experience in ("Intermediate", "Experienced"))):
        return None
    ev = [f"Patrimonio investito dichiarato: {eur(r.investable_assets_eur)}"]
    if r.investment_experience != "Non dichiarata":
        ev.append(f"Esperienza di investimento: {r.investment_experience}")
    concern = str(r.biggest_financial_concern)
    focus = any(k in concern for k in ("Fees", "concentration", "allocation", "Market risk", "wrong investment"))
    if focus:
        ev.append(f"Preoccupazione principale: \"{concern}\"")
    need = 0.7 * _clip(r.investable_assets_eur / 150_000) + 0.3 * focus
    size = _clip((r.investable_assets_eur + r.excess_cash_eur) / 150_000, 0.5, 2)
    return dict(need=need, size=size, evidence=ev)


_AGE_PENSION_NEED = {"18-24": 0.1, "25-34": 0.3, "35-44": 0.5, "45-54": 0.8, "55-64": 0.9}


def _pension(r):
    if not (
        r.age_band in ("35-44", "45-54", "55-64")
        or r.primary_financial_goal == "Prepare for retirement"
        or r.interested_in_pension in ("Yes", "Maybe")
        or "retirement_planning" in r.needs
    ):
        return None
    need = _AGE_PENSION_NEED.get(r.age_band, 0.3)
    ev = [f"Fascia d'età {r.age_band}"]
    if r.is_freelance:
        need += 0.1
        ev.append("Autonomo o freelance: pensione pubblica tipicamente più bassa")
    return dict(need=_clip(need), size=_clip(r.income / 3_500, 0.5, 2), evidence=ev)


def _protection(r):
    if not (
        r.dependents > 0
        or r.recent_life_event in ("Had a child", "Got married")
        or r.primary_financial_goal == "Protect family finances"
        or r.mortgage_remaining_eur > 0
        or r.plans_home_purchase == "Yes"
        or r.is_freelance
    ):
        return None
    ev = []
    need = 0.0
    if r.dependents > 0:
        need += 0.4
        ev.append(f"{r.dependents} persone a carico")
    if r.emergency_fund_months < 3:
        need += 0.25
        ev.append(f"Fondo di emergenza dichiarato: {r.emergency_fund_months} mesi")
    if r.mortgage_remaining_eur > 0 or r.plans_home_purchase == "Yes":
        need += 0.15
        ev.append("Mutuo in corso o in arrivo")
    if r.is_freelance or r.income_stability_1_5 <= 3:
        need += 0.2
        ev.append("Reddito non garantito (autonomo o stabilità bassa)")
    note = None
    if r.interested_in_insurance == "No" and need >= 0.5:
        note = "latente"
        ev.append("Bisogno latente: dice di non essere interessato alle assicurazioni")
    size = _clip(1 + 0.25 * r.dependents, 1, 2)
    return dict(need=_clip(need), size=size, evidence=ev, note=note)


def _freelance_kit(r):
    if not (r.is_freelance or "freelance_finances" in r.needs or r.m_is_freelancer is True):
        return None
    ev, need = [], 0.0
    if r.employment_type == "Self-employed":
        need += 0.5
        ev.append("Lavoratore autonomo")
    if r.recent_life_event == "Started freelancing":
        need += 0.3
        ev.append("Ha appena iniziato a lavorare in proprio")
    concern = str(r.biggest_financial_concern)
    if r.income_stability_1_5 <= 3 or any(k in concern for k in ("Irregular", "Tax", "weak months")):
        need += 0.2
        ev.append(f"Reddito variabile o tasse come preoccupazione (\"{concern}\")")
    return dict(need=_clip(need), size=1.0, evidence=ev)


def _cash_savings(r):
    if r.liquid < 10_000 or r.interested_in_savings_products == "No":
        return None
    ev = [f"Liquidità sul conto: {eur(r.liquid)}"]
    need = 0.6 * _clip(r.liquid / 40_000)
    if r.risk_tolerance_1_5 <= 2:
        need += 0.2
        ev.append(f"Tolleranza al rischio bassa ({r.risk_tolerance_1_5}/5)")
    h = r.home_purchase_horizon_months
    if r.plans_home_purchase == "Yes" and pd.notna(h) and h <= 36:
        need += 0.2
        ev.append("Liquidità vincolata all'anticipo casa: serve rendimento senza rischio")
    if any(k in str(r.biggest_financial_concern) for k in ("Inflation", "inflation", "too much cash")):
        need += 0.1
        ev.append(f"Preoccupazione: \"{r.biggest_financial_concern}\"")
    return dict(need=_clip(need), size=_clip(r.liquid / 30_000, 0.5, 2), evidence=ev)


def _debt_plan(r):
    if r.consumer_debt_eur <= 0:
        return None
    ev = [f"Debito al consumo: {eur(r.consumer_debt_eur)} ({r.debt_to_annual_income:.0%} del reddito annuo)"]
    need = 0.5 * _clip(r.debt_to_annual_income / 0.3)
    if len(r.debt_list) >= 2:
        need += 0.2
        ev.append(f"Più debiti aperti: {', '.join(r.debt_list)}")
    if "Credit card" in r.debt_list:
        need += 0.15
        ev.append("Debito su carta di credito (il più caro)")
    if r.monthly_savings_eur <= 0:
        need += 0.15
        ev.append("Risparmio mensile nullo o negativo")
    return dict(need=_clip(need), size=1.0, evidence=ev)


def _premium(r):
    ev, need = [], 0.0
    if r.financial_confidence_1_5 <= 2:
        need += 0.35
        ev.append(f"Sicurezza nelle decisioni finanziarie bassa ({r.financial_confidence_1_5:.0f}/5)")
    if r.recent_life_event != "Nessuno/non dichiarato":
        need += 0.25
        ev.append(f"Evento di vita recente: {r.recent_life_event}")
    if {"general_plan", "budgeting", "household_planning"} & set(r.needs):
        need += 0.2
        ev.append("Chiede esplicitamente un piano o un budget")
    if r.financial_stress or r.is_freelance:
        need += 0.2
    return dict(need=_clip(need), size=1.0, evidence=ev)


NEED_FUNCS = {
    "MORTGAGE": _mortgage,
    "WEALTH_REVIEW": _wealth_review,
    "INVEST_START": _invest_start,
    "PENSION": _pension,
    "PROTECTION": _protection,
    "FREELANCE_KIT": _freelance_kit,
    "CASH_SAVINGS": _cash_savings,
    "DEBT_PLAN": _debt_plan,
    "PREMIUM": _premium,
}


# --- intento ---------------------------------------------------------------------

INTEREST_LABEL = {
    "interested_in_mortgage": "Interesse per il mutuo",
    "interested_in_investing": "Interesse per gli investimenti",
    "interested_in_savings_products": "Interesse per prodotti di risparmio",
    "interested_in_insurance": "Interesse per le assicurazioni",
    "interested_in_pension": "Interesse per la previdenza",
}

# con l'utente sotto pressione finanziaria propongo solo ciò che lo aiuta a uscirne
STRESS_SAFE = {"DEBT_PLAN", "PREMIUM", "CASH_SAVINGS"}

def _intent(r, code):
    parts, ev = [], []
    col = C.INTEREST_COLUMN.get(code)
    if col:
        v = getattr(r, col)
        parts.append((C.INTEREST_WEIGHT, C.INTEREST_MAP.get(v, 0.3)))
        if v in ("Yes", "Maybe"):
            ev.append(f"{INTEREST_LABEL[col]}: {v}")
    goal_hit = code in C.GOAL_TO_OPPS.get(r.primary_financial_goal, [])
    parts.append((C.GOAL_WEIGHT, 1.0 if goal_hit else 0.0))
    if goal_hit:
        ev.append(f"Obiettivo principale: {r.primary_financial_goal}")

    primary_opps = C.NEED_TO_OPPS.get(r.primary_need, [])
    other_opps = {o for n in r.needs for o in C.NEED_TO_OPPS.get(n, [])}
    text_score = 1.0 if code in primary_opps else 0.6 if code in other_opps else 0.0
    parts.append((C.TEXT_WEIGHT, text_score))
    if text_score > 0 and r.summary_it:
        ev.append(f"Nel testo: {r.summary_it}")

    intent = sum(w * v for w, v in parts) / sum(w for w, _ in parts)
    if code in C.LIFE_EVENT_TRIGGERS.get(r.recent_life_event, []):
        intent += C.LIFE_EVENT_BONUS
        ev.append(f"Evento che fa da trigger: {r.recent_life_event}")
    if C.OPPORTUNITIES[code].high_touch and r.open_to_financial_advisor_call == "Yes" and not r.no_calls:
        intent += C.ADVISOR_BONUS
        ev.append("Aperto a una call con consulente")
    return _clip(intent), ev


# --- contatto ------------------------------------------------------------------------

def _reach(r, opp):
    advisor_ok = opp.high_touch and r.open_to_financial_advisor_call == "Yes"
    if r.marketing_contact_consent != "Yes":
        ch = "In-app (nessun consenso marketing)"
        if advisor_ok:
            ch += "; può prenotare lui la call"
        return C.REACH_NO_CONSENT, ch
    pref = r.preferred_contact_channel if pd.notna(r.preferred_contact_channel) else "Email"
    if r.no_calls:
        if pref == "Phone":
            pref = "Email"
        return C.REACH_NO_PRODUCT_CALLS, f"{pref} (niente chiamate commerciali, chiesto nel testo)"
    if advisor_ok:
        return C.REACH_FULL, "Call con consulente"
    return C.REACH_FULL, pref


# --- orchestrazione ------------------------------------------------------------------

def score_all(df: pd.DataFrame) -> pd.DataFrame:
    """Ritorna una tabella lunga: una riga per (utente, opportunità eleggibile)."""
    rows = []
    for r in df.itertuples(index=False):
        for code, fn in NEED_FUNCS.items():
            res = fn(r)
            if res is None:
                continue
            opp = C.OPPORTUNITIES[code]
            intent, intent_ev = _intent(r, code)
            readiness = res.get("readiness", 1.0)
            blocked = res.get("blocked")
            if not blocked and r.financial_stress and code not in STRESS_SAFE:
                blocked = "Utente sotto pressione finanziaria: prima il piano di rientro e il cash flow"
            propensity = (C.W_INTENT * intent + C.W_NEED * res["need"]) * readiness
            if blocked:
                propensity *= C.BLOCKED_MULT
            reach, channel = _reach(r, opp)

            if blocked:
                action = f"Sospesa. {blocked}"
            elif res.get("note") == "latente":
                action = "Contenuto educativo sulla protezione, nessuna offerta diretta per ora"
            else:
                action = opp.action

            rows.append({
                "user_id": r.user_id,
                "opportunity": code,
                "opportunity_name": opp.name,
                "need": round(res["need"], 3),
                "intent": round(intent, 3),
                "readiness": round(readiness, 3),
                "propensity": round(propensity, 3),
                "size_factor": round(res["size"], 3),
                "reach": reach,
                "confidence": r.confidence,
                "blocked": blocked is not None,
                "blocked_reason": blocked or "",
                "latent": res.get("note") == "latente",
                "channel": channel,
                "action": action,
                "evidence": intent_ev + res["evidence"],
            })
    long = pd.DataFrame(rows)
    # tolgo il rumore: opportunità eleggibili ma con propensione praticamente nulla
    long = long[(long["propensity"] >= 0.05) | long["blocked"]].reset_index(drop=True)
    return apply_values(long)


def apply_values(long: pd.DataFrame, base_values: dict | None = None) -> pd.DataFrame:
    """Calcola il valore atteso. Separato dallo scoring così l'app può cambiare le
    ipotesi economiche e riordinare senza ricalcolare tutto."""
    base_values = base_values or {k: o.base_value_eur for k, o in C.OPPORTUNITIES.items()}
    long = long.copy()
    long["base_value_eur"] = long["opportunity"].map(base_values)
    long["conf_mult"] = long["confidence"].map(C.CONFIDENCE_MULT)
    long["expected_value_eur"] = (
        long["base_value_eur"] * long["size_factor"] * long["propensity"] * long["reach"] * long["conf_mult"]
    ).round(1)
    long["rank_in_user"] = long.groupby("user_id")["expected_value_eur"].rank(ascending=False, method="first").astype(int)
    return long


def best_per_user(long: pd.DataFrame, users: pd.DataFrame) -> pd.DataFrame:
    """Opportunità principale per utente (preferendo quelle non sospese) + tier di priorità."""
    ranked = long.sort_values(["user_id", "blocked", "expected_value_eur"], ascending=[True, True, False])
    best = ranked.groupby("user_id").head(1).set_index("user_id").drop(columns=["confidence"])
    others = (
        long[~long["blocked"]]
        .sort_values("expected_value_eur", ascending=False)
        .groupby("user_id")
        .apply(lambda g: g["opportunity_name"].tolist()[1:3], include_groups=False)
        .rename("secondary_opportunities")
    )
    total = long[~long["blocked"]].groupby("user_id")["expected_value_eur"].sum().rename("total_ev_eur")
    out = users.set_index("user_id").join(best, how="left").join(others).join(total)
    out["secondary_opportunities"] = out["secondary_opportunities"].apply(lambda x: x if isinstance(x, list) else [])
    out["total_ev_eur"] = out["total_ev_eur"].fillna(0)

    # tier sul valore atteso dell'opportunità principale: top 20% alta, poi 30% media
    pct = out["expected_value_eur"].rank(pct=True, ascending=True)
    out["priority"] = np.select([pct > 0.8, pct > 0.5], ["Alta", "Media"], default="Bassa")
    return out.reset_index()
