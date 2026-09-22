"""
Segmenti "da stakeholder": poche regole leggibili, first-match, in ordine di priorità.

Ho scelto regole e non clustering (k-means & co.) perché con 120 utenti un
clustering è instabile e soprattutto non è spiegabile a chi deve usarlo:
"cluster 3" non dice niente a un product manager, "Acquisto casa in vista" sì.
L'ordine conta: chi è sotto pressione finanziaria finisce lì anche se vuole
comprare casa, perché la prima cosa da sapere su di lui è quella.
"""

import pandas as pd

SEGMENT_RULES = [
    ("Sotto pressione finanziaria",
     "Risparmio nullo/negativo, debiti alti o nessun cuscinetto con debiti aperti",
     lambda r: r.financial_stress or r.primary_financial_goal == "Reduce debt"),
    ("Acquisto casa in vista",
     "Vogliono comprare casa nei prossimi 1-3 anni",
     lambda r: r.plans_home_purchase == "Yes"),
    ("Verso la pensione",
     "55-64 anni o con la pensione come obiettivo principale",
     lambda r: r.age_band == "55-64" or r.primary_financial_goal == "Prepare for retirement"),
    ("Investitori evoluti",
     "Esperti o con patrimonio investito importante",
     lambda r: r.investment_experience == "Experienced" or r.investable_assets_eur >= 100_000
     or r.primary_financial_goal == "Optimise investments"),
    ("Freelance e reddito variabile",
     "Autonomi o appena passati alla libera professione",
     lambda r: r.is_freelance),
    ("Famiglie in crescita",
     "Con persone a carico e un matrimonio/figlio recente o la famiglia come priorità",
     lambda r: r.dependents >= 1 and (r.primary_financial_goal == "Protect family finances"
                                      or r.recent_life_event in ("Had a child", "Got married"))),
    ("Liquidità da far lavorare",
     "Molta liquidità oltre il cuscinetto di sicurezza",
     lambda r: r.excess_cash_eur >= 15_000),
    ("Primi passi",
     "Giovani con pochi risparmi o che partono dal fondo emergenza",
     lambda r: (r.age_band in ("18-24", "25-34") and r.liquid < 10_000)
     or r.primary_financial_goal == "Build emergency fund"),
]
FALLBACK_SEGMENT = ("Altri risparmiatori", "Nessun tratto dominante")
SEGMENT_DESCRIPTIONS = {name: desc for name, desc, _ in SEGMENT_RULES} | {FALLBACK_SEGMENT[0]: FALLBACK_SEGMENT[1]}
SEGMENT_ORDER = [s[0] for s in SEGMENT_RULES] + [FALLBACK_SEGMENT[0]]


def assign_segment(df: pd.DataFrame) -> pd.Series:
    def pick(r):
        for name, _, rule in SEGMENT_RULES:
            if rule(r):
                return name
        return FALLBACK_SEGMENT[0]
    return pd.Series([pick(r) for r in df.itertuples(index=False)], index=df.index, name="segment")


def segment_stats(users: pd.DataFrame, long: pd.DataFrame) -> dict:
    """Statistiche per segmento. È anche l'unico input che l'LLM vede per scrivere i brief."""
    out = {}
    for seg in SEGMENT_ORDER:
        u = users[users["segment"] == seg]
        if u.empty:
            continue
        ids = set(u["user_id"])
        lo = long[long["user_id"].isin(ids) & ~long["blocked"]]
        top_opps = (
            lo.groupby("opportunity_name")["expected_value_eur"].sum().sort_values(ascending=False).head(3).round(0)
        )
        latent = long[long["user_id"].isin(ids) & long["latent"]]["user_id"].nunique()
        blocked = long[long["user_id"].isin(ids) & long["blocked"]]["user_id"].nunique()
        needs = u["primary_need"].value_counts().head(3)
        out[seg] = {
            "descrizione": SEGMENT_DESCRIPTIONS[seg],
            "utenti": int(len(u)),
            "contattabili_outbound": int((u["marketing_contact_consent"] == "Yes").sum()),
            "chiedono_no_chiamate": int(u["no_calls"].sum()),
            "aperti_a_call_consulente": int((u["open_to_financial_advisor_call"] == "Yes").sum()),
            "reddito_mediano_eur": int(u["income"].median()),
            "liquidita_mediana_eur": int(u["liquid"].median()),
            "asset_investiti_mediani_eur": int(u["investable_assets_eur"].median()),
            "liquidita_in_eccesso_totale_eur": int(u["excess_cash_eur"].sum()),
            "con_debito_al_consumo": int((u["consumer_debt_eur"] > 0).sum()),
            "con_persone_a_carico": int((u["dependents"] > 0).sum()),
            "fascia_eta_principale": u["age_band"].mode().iat[0],
            "obiettivo_principale_piu_comune": u["primary_financial_goal"].mode().iat[0],
            "bisogni_dal_testo": {k: int(v) for k, v in needs.items()},
            "top_opportunita_per_valore_atteso_eur": {k: int(v) for k, v in top_opps.items()},
            "valore_atteso_totale_eur": int(lo["expected_value_eur"].sum()),
            "utenti_con_opportunita_sospese_da_guardrail": int(blocked),
            "utenti_con_bisogno_protezione_latente": int(latent),
            "utenti_confidenza_dati_bassa": int((u["confidence"] == "bassa").sum()),
        }
        # dettagli che hanno senso solo per alcuni segmenti: li includo solo se non nulli
        extra = {
            "acquisto_casa_entro_18_mesi": int(((u["plans_home_purchase"] == "Yes")
                                                & (u["home_purchase_horizon_months"] <= 18)).sum()),
            "anticipo_casa_gia_coperto": int((u["deposit_coverage"] >= 1).sum()),
            "contratto_tempo_determinato": int((u["employment_type"] == "Fixed-term").sum()),
            "autonomi": int((u["employment_type"] == "Self-employed").sum()),
            "tolleranza_rischio_bassa_1_2": int((u["risk_tolerance_1_5"] <= 2).sum()),
            "investitori_esperti": int((u["investment_experience"] == "Experienced").sum()),
            "risparmio_mensile_nullo_o_negativo": int((u["monthly_savings_eur"] <= 0).sum()),
        }
        out[seg].update({k: v for k, v in extra.items() if v > 0})
    return out
