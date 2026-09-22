"""
Insight calcolati sui dati. Qui niente LLM: sono conteggi e rapporti, devono
essere esatti e riproducibili. L'LLM al massimo li racconta (vedi briefs.py).
"""

import pandas as pd

from .scoring import eur


def compute_insights(users: pd.DataFrame, long: pd.DataFrame) -> list[dict]:
    u = users
    n = len(u)
    out = []

    # 1. protezione: bisogno latente vs interesse dichiarato
    dep = u[u["dependents"] > 0]
    dep_no = dep[dep["interested_in_insurance"] == "No"]
    dep_no_thin = dep_no[dep_no["emergency_fund_months"] < 3]
    ins_yes = u[u["interested_in_insurance"] == "Yes"]
    ins_yes_goal = (ins_yes["primary_financial_goal"] == "Protect family finances").sum()
    quanti = "tutti" if ins_yes_goal == len(ins_yes) else f"quasi tutti ({ins_yes_goal})"
    out.append({
        "id": "protezione_latente",
        "titolo": "La protezione è il bisogno più sotto-dichiarato",
        "testo": (
            f"{len(dep)} utenti hanno persone a carico, ma {len(dep_no)} di loro dicono di non essere interessati "
            f"alle assicurazioni; {len(dep_no_thin)} hanno anche meno di 3 mesi di fondo emergenza. "
            f"I {len(ins_yes)} che dicono sì hanno {quanti} come obiettivo principale "
            "'Protect family finances': l'interesse segue l'obiettivo dichiarato, non la situazione reale. "
            "Qui un'offerta diretta converte poco: serve prima un contenuto che faccia emergere il rischio."
        ),
        "metriche": {"con_dipendenti": len(dep), "dipendenti_non_interessati": len(dep_no),
                     "di_cui_fondo_sotto_3_mesi": len(dep_no_thin)},
    })

    # 2. liquidità in eccesso
    excess = u["excess_cash_eur"]
    big = u[excess >= 15_000]
    top10_share = excess.sort_values(ascending=False).head(10).sum() / max(excess.sum(), 1)
    low_risk = big[big["risk_tolerance_1_5"] <= 2]
    out.append({
        "id": "liquidita_ferma",
        "titolo": "C'è molta liquidità ferma, ma è concentrata",
        "testo": (
            f"Tolto un cuscinetto di 4-6 mesi di spese (e l'anticipo per chi vuole comprare casa), restano circa "
            f"€{excess.sum() / 1e6:.1f} milioni di liquidità in eccesso.".replace(".", ",", 1) + f" {len(big)} utenti hanno più di €15.000 in eccesso e i primi "
            f"10 da soli ne detengono il {top10_share:.0%}. {len(low_risk)} di questi hanno tolleranza al rischio "
            "bassa: per loro il prodotto giusto è il conto deposito, non il PAC."
        ),
        "metriche": {"liquidita_in_eccesso_eur": int(excess.sum()), "utenti_oltre_15k": len(big),
                     "quota_top10": round(float(top10_share), 2), "oltre_15k_rischio_basso": len(low_risk)},
    })

    # 3. acquisto casa: timing e prontezza
    home = u[u["plans_home_purchase"] == "Yes"]
    soon = home[home["home_purchase_horizon_months"] <= 18]
    ready = home[home["deposit_coverage"] >= 1]
    fixed = home[home["employment_type"] == "Fixed-term"]
    out.append({
        "id": "casa",
        "titolo": "Chi vuole comprare casa è il segmento con più valore, ma non tutto è pronto",
        "testo": (
            f"{len(home)} utenti pianificano l'acquisto, {len(soon)} entro 18 mesi. Solo {len(ready)} hanno già "
            f"liquidità sufficiente per anticipo e costi stimati; {len(fixed)} hanno un contratto a tempo determinato, "
            f"che rende l'istruttoria più difficile. Volume di mutui stimato: {eur(home['est_mortgage_eur'].sum())}. "
            "Nell'attesa, la liquidità accantonata per l'anticipo è un'opportunità di conto deposito a breve termine."
        ),
        "metriche": {"acquirenti": len(home), "entro_18_mesi": len(soon), "anticipo_coperto": len(ready),
                     "tempo_determinato": len(fixed), "volume_mutui_stimato_eur": int(home["est_mortgage_eur"].sum())},
    })

    # 4. consenso e contattabilità
    no_consent = u[u["marketing_contact_consent"] != "Yes"]
    no_calls = u[(u["marketing_contact_consent"] == "Yes") & u["no_calls"]]
    ev_now = long.loc[~long["blocked"], "expected_value_eur"].sum()
    ev_now = round(ev_now)
    ev_full = round((long.loc[~long["blocked"], "expected_value_eur"] / long.loc[~long["blocked"], "reach"]).sum())
    out.append({
        "id": "consenso",
        "titolo": "Un utente su cinque è raggiungibile solo in-app",
        "testo": (
            f"{len(no_consent)} utenti ({len(no_consent) / n:.0%}) non hanno dato consenso marketing: con loro si "
            f"può lavorare solo in-app. Altri {len(no_calls)} hanno dato consenso ma nel testo chiedono di non essere "
            "chiamati per prodotti, e il campo strutturato non lo cattura. Con piena contattabilità il valore atteso "
            f"salirebbe da {eur(ev_now)} a {eur(ev_full)}: migliorare il flusso di consenso è un'iniziativa di prodotto "
            "a sé."
        ),
        "metriche": {"senza_consenso": len(no_consent), "consenso_ma_no_chiamate": len(no_calls),
                     "ev_attuale_eur": int(ev_now), "ev_piena_contattabilita_eur": int(ev_full)},
    })

    # 5. percezione del fondo emergenza
    valid = u[~u["income_imputed"] & ~u["liquid_imputed"] & (u["emergency_fund_months"] > 0)]
    under = valid[valid["implied_buffer_months"] >= 2 * valid["emergency_fund_months"]]
    out.append({
        "id": "percezione_buffer",
        "titolo": "Molti sottostimano il proprio cuscinetto",
        "testo": (
            f"Per {len(under)} utenti su {len(valid)} con dati completi, la liquidità copre almeno il doppio dei mesi "
            f"di fondo emergenza che dichiarano (mediana dichiarata {valid['emergency_fund_months'].median():.0f} mesi, "
            f"stimata {valid['implied_buffer_months'].median():.0f}). Due letture possibili: parte della liquidità è "
            "già destinata a un obiettivo, oppure le persone non hanno chiaro quanto sono coperte. In entrambi i casi "
            "un calcolatore del fondo emergenza è un buon aggancio verso risparmio e investimenti."
        ),
        "metriche": {"sottostimano": len(under), "con_dati_completi": len(valid)},
    })

    # 6. guardrail
    blocked_users = long.loc[long["blocked"], "user_id"].nunique()
    stress = u[u["financial_stress"]]
    out.append({
        "id": "guardrail",
        "titolo": "Più di un utente su dieci va aiutato prima di essere monetizzato",
        "testo": (
            f"{len(stress)} utenti sono sotto pressione finanziaria (risparmio nullo o negativo, debiti alti rispetto "
            f"al reddito o nessun cuscinetto con debiti aperti). Per {blocked_users} utenti almeno un'opportunità è "
            "sospesa dal guardrail. Per loro propongo solo il piano di rientro dentro Premium, niente credito né "
            "prodotti di investimento: è la scelta giusta per l'utente e riduce il rischio reputazionale e di "
            "compliance."
        ),
        "metriche": {"sotto_pressione": len(stress), "utenti_con_opportunita_sospese": blocked_users},
    })
    return out


def global_stats(users: pd.DataFrame, long: pd.DataFrame, insights: list[dict]) -> dict:
    """Input dell'executive summary generato dall'LLM."""
    by_opp = long[~long["blocked"]].groupby("opportunity_name")["expected_value_eur"].sum().sort_values(ascending=False)
    by_seg = long[~long["blocked"]].merge(users[["user_id", "segment"]], on="user_id") \
        .groupby("segment")["expected_value_eur"].sum().sort_values(ascending=False)
    return {
        "utenti": int(len(users)),
        "priorita_alta": int((users["priority"] == "Alta").sum()),
        "valore_atteso_totale_eur": int(long.loc[~long["blocked"], "expected_value_eur"].sum()),
        "valore_per_opportunita_eur": {k: int(v) for k, v in by_opp.items()},
        "valore_per_segmento_eur": {k: int(v) for k, v in by_seg.items()},
        "insight": {i["id"]: {"titolo": i["titolo"], **i["metriche"]} for i in insights},
    }
