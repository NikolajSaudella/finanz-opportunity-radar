"""
Caricamento e pulizia del survey + feature derivate + flag di qualità dei dati.

Scelta di fondo: non butto via nessuna riga. Un utente con dati sporchi può
essere comunque un'opportunità; semplicemente la raccomandazione avrà
confidenza più bassa e lo si dice in chiaro.
"""

import numpy as np
import pandas as pd

from . import config as C

NO_CALL_PHRASE = "prefer not to be called"


def load_survey(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.strip() for c in df.columns]
    for c in df.columns:
        if pd.api.types.is_string_dtype(df[c]):
            df[c] = df[c].astype("string").str.strip()
    return df


def _impute_income(df: pd.DataFrame) -> pd.Series:
    # mediana per tipo di contratto e fascia d'età, poi per tipo di contratto, poi globale
    inc = df["monthly_net_income_eur"].copy()
    by_both = df.groupby(["employment_type", "age_band"])["monthly_net_income_eur"].transform("median")
    by_type = df.groupby("employment_type")["monthly_net_income_eur"].transform("median")
    return inc.fillna(by_both).fillna(by_type).fillna(inc.median())


def add_features(df: pd.DataFrame, reference_date: str = C.REFERENCE_DATE) -> pd.DataFrame:
    df = df.copy()
    ref = pd.Timestamp(reference_date)

    # --- missing -------------------------------------------------------------
    df["income_imputed"] = df["monthly_net_income_eur"].isna()
    df["income"] = _impute_income(df)

    df["investment_experience"] = df["investment_experience"].fillna("Non dichiarata")
    df["recent_life_event"] = df["recent_life_event"].fillna("Nessuno/non dichiarato")
    df["open_to_financial_advisor_call"] = df["open_to_financial_advisor_call"].fillna("Non risponde")
    df["financial_confidence_1_5"] = df["financial_confidence_1_5"].fillna(df["financial_confidence_1_5"].median())
    df["debt_types"] = df["debt_types"].fillna("")
    df["debt_list"] = df["debt_types"].apply(lambda s: [x.strip() for x in s.split(";") if x.strip()])

    # spese mensili stimate = reddito - risparmio (il survey non chiede le spese)
    df["est_monthly_expenses"] = (df["income"] - df["monthly_savings_eur"].clip(lower=0)).clip(lower=300)

    # liquidità mancante: la ricostruisco dai mesi di fondo emergenza dichiarati
    df["liquid_imputed"] = df["liquid_savings_eur"].isna()
    df["liquid"] = df["liquid_savings_eur"].fillna(df["emergency_fund_months"] * df["est_monthly_expenses"])

    df["savings_rate"] = df["monthly_savings_eur"] / df["income"]
    df["implied_buffer_months"] = df["liquid"] / df["est_monthly_expenses"]
    df["debt_to_annual_income"] = df["consumer_debt_eur"] / (12 * df["income"])

    volatile = (
        (df["employment_type"].isin(["Self-employed", "Fixed-term", "Part-time"]))
        | (df["income_stability_1_5"] <= 3)
    )
    df["buffer_target_months"] = np.where(volatile, C.BUFFER_TARGET_VOLATILE, C.BUFFER_TARGET_STABLE)

    # --- casa: quanto mutuo potrebbe reggere e quanta liquidità è "vincolata" all'anticipo
    plans_home = df["plans_home_purchase"].eq("Yes")
    loan_by_income = df["income"] * C.MORTGAGE_MAX_DTI * C.MORTGAGE_ANNUITY_FACTOR
    price_by_income = loan_by_income / C.MORTGAGE_LTV
    deposit_needed = price_by_income * (1 - C.MORTGAGE_LTV + C.PURCHASE_COSTS)
    df["est_mortgage_eur"] = np.where(plans_home, loan_by_income, 0.0)
    df["deposit_needed_eur"] = np.where(plans_home, deposit_needed, 0.0)
    df["deposit_coverage"] = np.where(plans_home, df["liquid"] / deposit_needed, np.nan)
    earmarked = np.where(plans_home, np.minimum(df["liquid"], deposit_needed), 0.0)

    buffer_eur = df["buffer_target_months"] * df["est_monthly_expenses"]
    df["excess_cash_eur"] = (df["liquid"] - buffer_eur - earmarked).clip(lower=0)

    df["financial_stress"] = (
        (df["monthly_savings_eur"] <= 0)
        | ((df["emergency_fund_months"] <= 1) & (df["consumer_debt_eur"] > 0))
        | (df["debt_to_annual_income"] > 0.4)
    )

    df["is_freelance"] = df["employment_type"].eq("Self-employed") | df["recent_life_event"].eq("Started freelancing")

    # --- contatto ------------------------------------------------------------
    text = df["what_would_you_like_help_with"].fillna("").str.lower()
    df["no_product_calls"] = text.str.contains(NO_CALL_PHRASE, regex=False)
    # nota: questa regex è solo una rete di sicurezza. La restrizione viene estratta
    # anche dall'LLM (contact_restrictions), vedi text_signals.py; si usa l'OR delle due.

    df["survey_ts"] = pd.to_datetime(df["survey_completed_at"], errors="coerce", utc=True)
    df["survey_in_future"] = df["survey_ts"] > ref
    return df


def structural_flags(df: pd.DataFrame) -> pd.DataFrame:
    """Contraddizioni e anomalie rilevabili solo dai campi strutturati."""
    rules = {
        "reddito_mancante": df["income_imputed"],
        "liquidita_mancante": df["liquid_imputed"],
        "data_survey_futura": df["survey_in_future"],
        "orizzonte_casa_senza_piano": df["plans_home_purchase"].eq("No") & df["home_purchase_horizon_months"].notna(),
        "dipendenti_pari_o_oltre_nucleo": df["dependents"] >= df["household_size"],
        "studente_con_contratto_full_time": df["employment_status"].eq("Student + part-time")
        & df["employment_type"].eq("Full-time permanent"),
        "figlio_recente_senza_dipendenti": df["recent_life_event"].eq("Had a child") & df["dependents"].eq(0),
        "spese_casa_piu_risparmio_oltre_reddito": (
            ~df["income_imputed"]
            & (df["monthly_housing_cost_eur"] + df["monthly_savings_eur"].clip(lower=0) > df["monthly_net_income_eur"])
        ),
        # dichiara molti mesi di fondo emergenza ma la liquidità non li copre
        "fondo_emergenza_sovrastimato": (df["emergency_fund_months"] >= 6)
        & (df["implied_buffer_months"] < df["emergency_fund_months"] / 2),
    }
    out = []
    for name, mask in rules.items():
        for uid in df.loc[mask.fillna(False), "user_id"]:
            out.append({"user_id": uid, "flag": name, "source": "strutturato"})
    return pd.DataFrame(out, columns=["user_id", "flag", "source"])


# flag che segnalano un dato incoerente (pesano sulla confidenza più dei semplici missing)
CONTRADICTION_FLAGS = {
    "orizzonte_casa_senza_piano",
    "dipendenti_pari_o_oltre_nucleo",
    "studente_con_contratto_full_time",
    "figlio_recente_senza_dipendenti",
    "spese_casa_piu_risparmio_oltre_reddito",
    "fondo_emergenza_sovrastimato",
}


def confidence_level(flags: list[str]) -> str:
    # i flag "contatto:" riguardano le preferenze, non la qualità del dato
    flags = [f for f in flags if not f.startswith("contatto:")]
    contradictions = sum(1 for f in flags if f in CONTRADICTION_FLAGS or f.startswith("testo:"))
    soft = len(flags) - contradictions
    if contradictions >= 2 or (contradictions == 1 and soft >= 1):
        return "bassa"
    if contradictions == 1 or soft >= 1:
        return "media"
    return "alta"
