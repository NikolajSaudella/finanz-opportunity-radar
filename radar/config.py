"""
Catalogo delle opportunità e ipotesi numeriche.

Tutto quello che è un'ipotesi di business sta qui, non sparso nel codice.
I valori economici sono PLACEHOLDER: non conosco le economics reali di Finanz
(CPA dei partner, trail, prezzo e retention dell'abbonamento). Servono solo
a rendere confrontabili opportunità molto diverse tra loro (un lead mutuo
vale molto più di un'iscrizione a un conto deposito). Vanno sostituiti con i
numeri veri del team Monetisation, e dall'app si possono modificare al volo.
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Opportunity:
    code: str
    name: str            # nome mostrato agli stakeholder
    revenue_model: str   # come ci guadagna Finanz
    base_value_eur: float  # valore indicativo per utente convertito, primo anno
    high_touch: bool     # ha senso una call con consulente?
    action: str          # azione standard suggerita


OPPORTUNITIES = {
    o.code: o
    for o in [
        Opportunity(
            "MORTGAGE", "Mutuo prima casa", "Commissione broker/banca partner su mutuo erogato",
            700, True, "Simulazione di sostenibilità e lead al broker mutui partner",
        ),
        Opportunity(
            "WEALTH_REVIEW", "Revisione portafoglio", "Referral a consulenza/gestione partner (fee su masse)",
            400, True, "Check-up gratuito di allocazione, costi e concentrazione, poi referral consulente",
        ),
        Opportunity(
            "INVEST_START", "Avvio investimenti (PAC/ETF)", "CPA apertura conto + trail su masse dal partner",
            180, False, "Percorso guidato di primo investimento con PAC mensile",
        ),
        Opportunity(
            "PENSION", "Previdenza integrativa", "Commissione su adesione a fondo pensione/PIP partner",
            160, True, "Calcolo del gap pensionistico e proposta di piano di contribuzione",
        ),
        Opportunity(
            "PROTECTION", "Protezione famiglia e reddito", "Commissione su polizza vita/TCM o income protection",
            150, True, "Contenuto educativo sulla protezione + preventivo polizza partner",
        ),
        Opportunity(
            "FREELANCE_KIT", "Kit freelance (conto business + accantonamento tasse)",
            "CPA conto business partner + upsell Premium",
            90, False, "Onboarding conto business con regola automatica di accantonamento tasse",
        ),
        Opportunity(
            "CASH_SAVINGS", "Conto deposito / risparmio remunerato", "CPA partner su conto deposito",
            70, False, "Proposta di conto deposito per la liquidità ferma o vincolata a un obiettivo",
        ),
        Opportunity(
            "DEBT_PLAN", "Piano di rientro debiti", "Abbonamento Premium (budgeting); niente prodotti di credito",
            50, False, "Piano di rientro con priorità per costo del debito, dentro Finanz Premium",
        ),
        Opportunity(
            "PREMIUM", "Finanz Premium (piano e budget)", "Abbonamento",
            50, False, "Trial Premium con piano finanziario personalizzato",
        ),
    ]
}

# --- Pesi dello scoring --------------------------------------------------------
# propensione = W_INTENT * intento + W_NEED * bisogno
# L'intento (cosa l'utente dice di volere) pesa più del bisogno (cosa pensiamo
# gli serva): un'opportunità che l'utente non riconosce converte poco.
W_INTENT = 0.6
W_NEED = 0.4

# componenti dell'intento
INTEREST_WEIGHT = 0.40   # flag interested_in_* del survey
GOAL_WEIGHT = 0.30       # obiettivo principale coerente
TEXT_WEIGHT = 0.30       # bisogno espresso nella risposta aperta (estratto con LLM)
LIFE_EVENT_BONUS = 0.10  # evento di vita recente che fa da trigger
ADVISOR_BONUS = 0.10     # aperto a call con consulente, solo per opportunità high-touch

INTEREST_MAP = {"Yes": 1.0, "Maybe": 0.5, "No": 0.0}

# moltiplicatori di raggiungibilità
REACH_FULL = 1.0
REACH_NO_PRODUCT_CALLS = 0.85   # consenso sì, ma nel testo chiede di non essere chiamato
REACH_NO_CONSENT = 0.30         # niente outbound: solo contenuti in-app

# moltiplicatore di confidenza sui dati
CONFIDENCE_MULT = {"alta": 1.0, "media": 0.9, "bassa": 0.75}

# opportunità sospese dal guardrail: restano visibili ma con peso molto basso
BLOCKED_MULT = 0.15

# --- Ipotesi finanziarie grezze -------------------------------------------------
MORTGAGE_MAX_DTI = 0.30        # rata max = 30% del reddito netto
MORTGAGE_ANNUITY_FACTOR = 200  # ~25 anni al 3,5%: capitale ≈ rata * 200
MORTGAGE_LTV = 0.80            # la banca finanzia l'80% del prezzo
PURCHASE_COSTS = 0.05          # notaio, imposte, agenzia ≈ 5% del prezzo
BUFFER_TARGET_STABLE = 4       # mesi di spese per chi ha reddito stabile
BUFFER_TARGET_VOLATILE = 6     # autonomi, tempo determinato, stabilità <= 3

# eventi di vita -> opportunità che rendono più "calde"
LIFE_EVENT_TRIGGERS = {
    "Had a child": ["PROTECTION", "PREMIUM"],
    "Got married": ["PROTECTION", "MORTGAGE", "PREMIUM"],
    "Promotion": ["INVEST_START", "PENSION", "WEALTH_REVIEW"],
    "New job": ["INVEST_START", "PENSION", "PREMIUM"],
    "Started freelancing": ["FREELANCE_KIT", "PROTECTION", "PENSION"],
    "Unexpected expense": ["CASH_SAVINGS", "DEBT_PLAN"],
    "Relationship change": ["PREMIUM", "WEALTH_REVIEW", "PROTECTION"],
    "Moved city": ["MORTGAGE", "PREMIUM"],
    "Planning relocation": ["PREMIUM", "MORTGAGE"],
}

# bisogni estratti dal testo -> opportunità collegate
NEED_TAXONOMY = {
    "budgeting": "Gestire il budget mensile",
    "emergency_fund": "Costruire un fondo di emergenza",
    "debt_repayment": "Ridurre o riorganizzare i debiti",
    "investing_start": "Iniziare a investire",
    "investment_optimisation": "Ottimizzare investimenti esistenti",
    "cash_allocation": "Decidere come allocare la liquidità",
    "home_purchase": "Comprare casa",
    "mortgage": "Capire/confrontare il mutuo",
    "retirement_planning": "Pianificare la pensione",
    "protection": "Proteggere famiglia o reddito",
    "household_planning": "Pianificare le finanze familiari",
    "freelance_finances": "Gestire tasse e reddito da freelance",
    "general_plan": "Avere un piano finanziario",
}

NEED_TO_OPPS = {
    "budgeting": ["PREMIUM", "DEBT_PLAN"],
    "emergency_fund": ["CASH_SAVINGS", "PREMIUM"],
    "debt_repayment": ["DEBT_PLAN"],
    "investing_start": ["INVEST_START"],
    "investment_optimisation": ["WEALTH_REVIEW"],
    "cash_allocation": ["INVEST_START", "CASH_SAVINGS"],
    "home_purchase": ["MORTGAGE", "CASH_SAVINGS"],
    "mortgage": ["MORTGAGE"],
    "retirement_planning": ["PENSION", "WEALTH_REVIEW"],
    "protection": ["PROTECTION"],
    "household_planning": ["PREMIUM", "PROTECTION"],
    "freelance_finances": ["FREELANCE_KIT", "PREMIUM"],
    "general_plan": ["PREMIUM"],
}

GOAL_TO_OPPS = {
    "Buy a home": ["MORTGAGE", "CASH_SAVINGS"],
    "Prepare for retirement": ["PENSION", "WEALTH_REVIEW"],
    "Start investing": ["INVEST_START"],
    "Protect family finances": ["PROTECTION", "PREMIUM"],
    "Reduce debt": ["DEBT_PLAN"],
    "Make savings work harder": ["CASH_SAVINGS", "INVEST_START"],
    "Stabilise finances": ["FREELANCE_KIT", "PREMIUM", "CASH_SAVINGS"],
    "Optimise investments": ["WEALTH_REVIEW"],
    "Build emergency fund": ["CASH_SAVINGS", "PREMIUM"],
    "Build wealth": ["INVEST_START", "WEALTH_REVIEW"],
}

INTEREST_COLUMN = {
    "MORTGAGE": "interested_in_mortgage",
    "INVEST_START": "interested_in_investing",
    "WEALTH_REVIEW": "interested_in_investing",
    "CASH_SAVINGS": "interested_in_savings_products",
    "PROTECTION": "interested_in_insurance",
    "PENSION": "interested_in_pension",
}

# Data di riferimento del dataset, usata per riconoscere i survey con data futura.
# Non uso "oggi" perché i risultati cambierebbero a seconda di quando si esegue la pipeline.
# Assunzione: il dataset è stato estratto il giorno in cui ho ricevuto il case.
REFERENCE_DATE = "2026-09-22T23:59:59+02:00"

# modelli LLM (sovrascrivibili da env)
EXTRACTION_MODEL = os.getenv("FINANZ_EXTRACTION_MODEL", "claude-haiku-4-5-20251001")
BRIEF_MODEL = os.getenv("FINANZ_BRIEF_MODEL", "claude-sonnet-5")
PROMPT_VERSION_EXTRACTION = "v2"
PROMPT_VERSION_BRIEF = "v1"
