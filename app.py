"""
Finanz Opportunity Radar – tool interno per Product / Monetisation.

    streamlit run app.py
"""

import altair as alt
import pandas as pd
import streamlit as st

from radar import briefs, config as C, scoring, segments
from radar.llm import get_client
from radar.pipeline import build
from radar.segments import SEGMENT_ORDER

LOGO = "assets/finanz_logo.png"
BRAND_DARK = "#163300"

st.set_page_config(page_title="Finanz Opportunity Radar", page_icon=LOGO, layout="wide")
st.logo(LOGO, size="large")

EUR = st.column_config.NumberColumn(format="€%d")
FLAG_LABELS = {
    "reddito_mancante": "Reddito mancante (stimato)",
    "liquidita_mancante": "Liquidità mancante (stimata)",
    "data_survey_futura": "Data del survey nel futuro",
    "orizzonte_casa_senza_piano": "Orizzonte acquisto casa compilato ma dice di non volerla comprare",
    "dipendenti_pari_o_oltre_nucleo": "Persone a carico ≥ componenti del nucleo",
    "studente_con_contratto_full_time": "Studente con contratto full-time permanente",
    "figlio_recente_senza_dipendenti": "Figlio appena nato ma zero persone a carico",
    "spese_casa_piu_risparmio_oltre_reddito": "Spese casa + risparmio superano il reddito",
    "fondo_emergenza_sovrastimato": "Fondo emergenza dichiarato non coperto dalla liquidità",
    "contatto:consenso_si_ma_chiede_no_chiamate": "Consenso marketing sì, ma nel testo chiede di non essere chiamato",
}


@st.cache_data(show_spinner="Calcolo le opportunità…")
def load():
    return build()


data = load()
features = data["features"]
long_default = data["long"]

# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.title("Opportunity Radar")
    st.caption("Opportunità di monetizzazione dalla Financial Life Survey · prototipo AIOps")

    seg_filter = st.multiselect("Segmenti", SEGMENT_ORDER, placeholder="Tutti")
    opp_names = [o.name for o in C.OPPORTUNITIES.values()]
    opp_filter = st.multiselect("Opportunità principale", opp_names, placeholder="Tutte")
    only_contactable = st.checkbox("Solo utenti contattabili outbound", value=False)
    hide_low_conf = st.checkbox("Nascondi utenti con dati poco affidabili", value=False)

    with st.expander("Ipotesi economiche (€ per utente convertito)"):
        st.caption(
            "Valori indicativi, da sostituire con le economics reali. "
            "Cambiandoli si riordinano opportunità e priorità."
        )
        base_values = {
            code: st.number_input(o.name, min_value=0, value=int(o.base_value_eur), step=10, key=f"bv_{code}")
            for code, o in C.OPPORTUNITIES.items()
        }

    st.divider()
    src = features["text_source"].value_counts().to_dict()
    has_key = get_client() is not None
    st.caption(
        f"Testo libero analizzato con LLM: {src.get('llm', 0)} utenti"
        + (f" · fallback keyword: {src['keyword_fallback']}" if src.get("keyword_fallback") else "")
    )
    st.caption("API key presente: sì" if has_key else "API key assente: uso i risultati LLM in cache")

# ricalcolo valore atteso e priorità con le ipotesi della sidebar
long = scoring.apply_values(long_default, base_values)
users = scoring.best_per_user(long, features)
seg_stats_live = segments.segment_stats(users, long)

view = users.copy()
if seg_filter:
    view = view[view["segment"].isin(seg_filter)]
if opp_filter:
    view = view[view["opportunity_name"].isin(opp_filter)]
if only_contactable:
    view = view[view["marketing_contact_consent"] == "Yes"]
if hide_low_conf:
    view = view[view["confidence"] != "bassa"]


def user_table(df: pd.DataFrame) -> pd.DataFrame:
    t = df.sort_values("expected_value_eur", ascending=False)[[
        "user_id", "priority", "segment", "opportunity_name", "expected_value_eur", "channel",
        "action", "confidence", "secondary_opportunities",
    ]].copy()
    t["secondary_opportunities"] = t["secondary_opportunities"].apply(lambda x: ", ".join(x))
    return t.rename(columns={
        "user_id": "Utente", "priority": "Priorità", "segment": "Segmento",
        "opportunity_name": "Opportunità principale", "expected_value_eur": "Valore atteso",
        "channel": "Canale", "action": "Azione suggerita", "confidence": "Affidabilità dati",
        "secondary_opportunities": "Altre opportunità",
    })


tab_over, tab_seg, tab_list, tab_prod, tab_dq, tab_method = st.tabs(
    ["Panoramica", "Segmenti", "Lista prioritaria", "Per prodotto", "Qualità dati", "Come funziona"]
)

# ---------------------------------------------------------------- panoramica
with tab_over:
    summ = data["summary"]
    if summ["summary"]:
        s = summ["summary"]
        with st.container(border=True):
            st.subheader(s["titolo"])
            for p in s["punti"]:
                st.markdown(f"- {p}")
            st.markdown(f"**Prossimo passo:** {s['prossimo_passo']}")
            st.caption("Sintesi generata con LLM a partire dalle statistiche calcolate (ipotesi economiche di default).")
            if summ["grounding_issues"]:
                st.warning(f"Numeri non ritrovati nei dati: {', '.join(summ['grounding_issues'])}. Verificare.")

    active = long[~long["blocked"] & long["user_id"].isin(view["user_id"])]
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Utenti nel filtro", len(view))
    c2.metric("Priorità alta", int((view["priority"] == "Alta").sum()))
    c3.metric("Valore atteso (indice €)", scoring.eur(active["expected_value_eur"].sum()))
    c4.metric("Contattabili outbound", int((view["marketing_contact_consent"] == "Yes").sum()))
    c5.metric("Con opportunità sospese", int(long[long["blocked"] & long["user_id"].isin(view["user_id"])]["user_id"].nunique()))

    left, right = st.columns(2)
    with left:
        st.markdown("**Valore atteso per opportunità**")
        by_opp = active.groupby("opportunity_name").agg(
            valore=("expected_value_eur", "sum"), utenti=("user_id", "nunique")).reset_index()
        st.altair_chart(
            alt.Chart(by_opp).mark_bar(color=BRAND_DARK).encode(
                x=alt.X("valore:Q", title="Valore atteso (€, indice)", axis=alt.Axis(format="d")),
                y=alt.Y("opportunity_name:N", sort="-x", title=None, axis=alt.Axis(labelLimit=320)),
                tooltip=["opportunity_name", alt.Tooltip("valore:Q", format=",.0f"), "utenti"],
            ).properties(height=320),
            width="stretch",
        )
    with right:
        st.markdown("**Segmenti: dimensione e valore per utente**")
        seg_df = pd.DataFrame([
            {"segmento": k, "utenti": v["utenti"], "valore_per_utente": v["valore_atteso_totale_eur"] / v["utenti"],
             "contattabili": v["contattabili_outbound"]}
            for k, v in seg_stats_live.items()
        ])
        st.altair_chart(
            alt.Chart(seg_df).mark_circle(opacity=0.8).encode(
                x=alt.X("utenti:Q", title="Utenti"),
                y=alt.Y("valore_per_utente:Q", title="Valore atteso per utente (€)"),
                size=alt.Size("contattabili:Q", legend=None, scale=alt.Scale(range=[80, 900])),
                color=alt.Color("segmento:N", legend=alt.Legend(orient="bottom", columns=2, title=None)),
                tooltip=["segmento", "utenti", alt.Tooltip("valore_per_utente:Q", format=",.0f"), "contattabili"],
            ).properties(height=320),
            width="stretch",
        )
        st.caption("In alto a destra: segmenti grandi e di valore. La dimensione del punto è il numero di contattabili.")

    st.markdown("### Cosa emerge dai dati")
    for ins in data["insights"]:
        with st.expander(ins["titolo"]):
            st.write(ins["testo"])

# ---------------------------------------------------------------- segmenti
with tab_seg:
    rows = []
    for seg, s in seg_stats_live.items():
        rows.append({
            "Segmento": seg, "Utenti": s["utenti"], "Contattabili": s["contattabili_outbound"],
            "Valore atteso": s["valore_atteso_totale_eur"],
            "Valore per utente": round(s["valore_atteso_totale_eur"] / s["utenti"]),
            "Opportunità principali": ", ".join(s["top_opportunita_per_valore_atteso_eur"]),
        })
    seg_table = pd.DataFrame(rows).sort_values("Valore atteso", ascending=False)
    st.dataframe(seg_table, hide_index=True, width="stretch",
                 column_config={"Valore atteso": EUR, "Valore per utente": EUR})

    chosen = st.selectbox("Apri un segmento", seg_table["Segmento"].tolist())
    b = data["segment_briefs"].get(chosen)
    s = seg_stats_live[chosen]
    col_a, col_b = st.columns([3, 2])
    with col_a:
        with st.container(border=True):
            st.markdown(f"#### {chosen}")
            st.caption(segments.SEGMENT_DESCRIPTIONS[chosen])
            if b:
                br = b["brief"]
                st.write(br["sintesi"])
                st.markdown("**Perché conta**")
                st.write(br["perche_conta"])
                st.markdown("**Azioni suggerite**")
                for a in br["azioni"]:
                    st.markdown(f"- {a}")
                st.markdown("**Attenzione**")
                st.write(br["attenzione"])
                label = "LLM" if b["source"] == "llm" else "template deterministico (nessun LLM disponibile)"
                st.caption(f"Brief: {label}. Scritto sulle statistiche con ipotesi economiche di default.")
                if b["grounding_issues"]:
                    st.warning(f"Numeri non ritrovati nelle statistiche: {', '.join(b['grounding_issues'])}")
            if has_key and st.button("Rigenera il brief con le ipotesi attuali"):
                fresh = briefs.segment_briefs({chosen: s}, refresh=True)[chosen]
                st.json(fresh["brief"])
    with col_b:
        st.markdown("**Numeri del segmento**")
        show = {
            k.replace("_eur", " (€)").replace("_", " ").capitalize(): v
            for k, v in s.items() if not isinstance(v, dict) and k != "descrizione"
        }
        st.dataframe(pd.DataFrame(show.items(), columns=["Metrica", "Valore"]).astype(str),
                     hide_index=True, width="stretch")
        st.markdown("**Bisogni espressi nel testo**")
        st.write(", ".join(f"{C.NEED_TAXONOMY.get(k, k)} ({v})" for k, v in s["bisogni_dal_testo"].items()))

    st.markdown("**Utenti del segmento, in ordine di valore atteso**")
    st.dataframe(user_table(users[users["segment"] == chosen]), hide_index=True, width="stretch",
                 column_config={"Valore atteso": EUR})

# ---------------------------------------------------------------- lista prioritaria
with tab_list:
    st.caption(
        "Un'opportunità principale per utente, scelta per valore atteso tra quelle non sospese. "
        "Priorità: top 20% alta, 30% successivo media."
    )
    table = user_table(view)
    st.dataframe(table, hide_index=True, width="stretch", column_config={"Valore atteso": EUR}, height=420)
    st.download_button("Scarica la lista (CSV)", table.to_csv(index=False).encode("utf-8"),
                       file_name="finanz_opportunita_prioritarie.csv", mime="text/csv")

    st.divider()
    uid = st.selectbox("Dettaglio utente", table["Utente"].tolist() or users["user_id"].tolist())
    u = users.set_index("user_id").loc[uid]
    st.markdown(f"#### {uid} · {u['segment']}")
    p1, p2, p3, p4 = st.columns(4)
    p1.metric("Reddito netto/mese", scoring.eur(u["income"]) + (" (stimato)" if u["income_imputed"] else ""))
    p2.metric("Liquidità", scoring.eur(u["liquid"]))
    p3.metric("Investimenti", scoring.eur(u["investable_assets_eur"]))
    p4.metric("Debito al consumo", scoring.eur(u["consumer_debt_eur"]))
    st.write(
        f"{u['age_band']} anni, {u['country']}, {u['employment_status'].lower()} ({u['employment_type']}), "
        f"{u['household_size']} in famiglia di cui {u['dependents']} a carico, {u['housing_status'].lower()}. "
        f"Obiettivo: **{u['primary_financial_goal']}** in {u['goal_horizon_months']} mesi. "
        f"Evento recente: {u['recent_life_event']}. Preoccupazione: {u['biggest_financial_concern']}."
    )
    with st.container(border=True):
        st.markdown(f"> {u['what_would_you_like_help_with']}")
        st.caption(
            f"Lettura LLM: {u['summary_it'] or 'n/d'} · bisogni: "
            + ", ".join(C.NEED_TAXONOMY.get(n, n) for n in u["needs"])
            + (" · chiede di non essere chiamato" if u["no_calls"] else "")
        )

    uo = long[long["user_id"] == uid].sort_values("expected_value_eur", ascending=False)
    st.markdown("**Tutte le opportunità per questo utente**")
    st.dataframe(
        uo[["opportunity_name", "expected_value_eur", "propensity", "need", "intent", "channel", "action"]].rename(columns={
            "opportunity_name": "Opportunità", "expected_value_eur": "Valore atteso", "propensity": "Propensione",
            "need": "Bisogno", "intent": "Intento", "channel": "Canale", "action": "Azione",
        }),
        hide_index=True, width="stretch",
        column_config={"Valore atteso": EUR, "Propensione": st.column_config.ProgressColumn(min_value=0, max_value=1),
                       "Bisogno": st.column_config.NumberColumn(format="%.2f"),
                       "Intento": st.column_config.NumberColumn(format="%.2f")},
    )
    top = uo.iloc[0]
    st.markdown(f"**Perché {top['opportunity_name']}**")
    for e in top["evidence"]:
        st.markdown(f"- {e}")
    if u["dq_flags"]:
        st.warning("Dati da verificare: " + "; ".join(FLAG_LABELS.get(f, f) for f in u["dq_flags"]))

# ---------------------------------------------------------------- per prodotto
with tab_prod:
    st.caption("Per costruire una campagna: tutti gli utenti per cui un'opportunità ha senso, non solo quelli per cui è la principale.")
    opp_code = st.selectbox("Opportunità", list(C.OPPORTUNITIES), format_func=lambda c: C.OPPORTUNITIES[c].name)
    po = long[long["opportunity"] == opp_code].merge(
        users[["user_id", "segment", "marketing_contact_consent"]], on="user_id")
    q1, q2, q3, q4 = st.columns(4)
    q1.metric("Utenti eleggibili", len(po))
    q2.metric("Sospesi dal guardrail", int(po["blocked"].sum()))
    q3.metric("Bisogno latente", int(po["latent"].sum()))
    q4.metric("Contattabili outbound", int((po["marketing_contact_consent"] == "Yes").sum()))
    st.caption(f"Modello di ricavo: {C.OPPORTUNITIES[opp_code].revenue_model}")
    po = po.sort_values(["blocked", "expected_value_eur"], ascending=[True, False])
    po["evidence"] = po["evidence"].apply(lambda x: " · ".join(x))
    st.dataframe(
        po[["user_id", "segment", "expected_value_eur", "propensity", "channel", "action", "evidence"]].rename(columns={
            "user_id": "Utente", "segment": "Segmento", "expected_value_eur": "Valore atteso",
            "propensity": "Propensione", "channel": "Canale", "action": "Azione", "evidence": "Evidenze",
        }),
        hide_index=True, width="stretch", height=480,
        column_config={"Valore atteso": EUR, "Propensione": st.column_config.ProgressColumn(min_value=0, max_value=1)},
    )

# ---------------------------------------------------------------- qualità dati
with tab_dq:
    fl = data["flags"].copy()
    fl["descrizione"] = fl["flag"].map(FLAG_LABELS).fillna(fl["flag"])
    counts = fl.groupby(["descrizione", "source"]).size().reset_index(name="utenti").sort_values("utenti", ascending=False)
    st.markdown(
        f"**{fl['user_id'].nunique()} utenti su {len(features)}** hanno almeno un'anomalia. Nessuno viene escluso: "
        "le anomalie abbassano l'affidabilità della raccomandazione (alta / media / bassa) e quindi il valore atteso."
    )
    st.dataframe(counts.rename(columns={"descrizione": "Anomalia", "source": "Rilevata da", "utenti": "Utenti"}),
                 hide_index=True, width="stretch")
    st.markdown("**Dettaglio**")
    st.dataframe(fl[["user_id", "descrizione", "source"]].rename(columns={"user_id": "Utente", "descrizione": "Anomalia",
                                                                          "source": "Rilevata da"}),
                 hide_index=True, width="stretch")
    st.caption(
        "\"testo vs dati\" = confronto tra quello che l'utente scrive nella risposta aperta (estratto dall'LLM) "
        "e quello che ha compilato nei campi strutturati."
    )

# ---------------------------------------------------------------- metodo
with tab_method:
    st.markdown(f"""
**Cosa fa.** Per ogni utente valuta 9 opportunità di monetizzazione (mutuo, revisione portafoglio, avvio investimenti,
previdenza, protezione, kit freelance, conto deposito, piano di rientro debiti, abbonamento Premium), le ordina per
valore atteso e suggerisce azione e canale, con le evidenze che hanno portato alla scelta.

**Valore atteso** = valore base × fattore dimensione × propensione × raggiungibilità × affidabilità dati.

- *Propensione* = {C.W_INTENT:.0%} intento + {C.W_NEED:.0%} bisogno. L'intento viene da interesse dichiarato, obiettivo
  principale, risposta aperta (letta con LLM), eventi di vita recenti e apertura a una call.
  Il bisogno viene dalla situazione finanziaria (liquidità, debiti, persone a carico, età, contratto…).
- *Raggiungibilità*: 1 con consenso marketing, {C.REACH_NO_PRODUCT_CALLS} se nel testo chiede di non essere chiamato,
  {C.REACH_NO_CONSENT} senza consenso (solo in-app).
- *Guardrail*: investimenti sospesi senza fondo emergenza o con carta di credito che non si riesce a chiudere; per chi è
  sotto pressione finanziaria restano solo piano di rientro, Premium e conto deposito.

**Dove c'è l'AI.** (1) Lettura della risposta aperta: bisogni in una tassonomia chiusa, vincoli di contatto, fatti
dichiarati da confrontare con i campi strutturati. (2) Brief di segmento e sintesi, scritti solo a partire da
statistiche aggregate, con controllo automatico che i numeri citati esistano. Scoring, segmenti e insight sono
deterministici.

**Il valore atteso non è una previsione di ricavo**: è un indice per ordinare. Le ipotesi economiche si cambiano dalla
barra laterale.
""")
