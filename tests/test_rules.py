"""Test minimi sulle regole che non devono rompersi: guardrail, consenso, fallback, grounding."""

import pytest

from radar import briefs, text_signals
from radar.pipeline import build


@pytest.fixture(scope="module")
def res():
    return build()


def test_every_user_gets_one_recommendation(res):
    assert len(res["users"]) == 120
    assert res["users"]["opportunity"].notna().all()


def test_no_investment_or_credit_push_to_stressed_users(res):
    lo, f = res["long"], res["features"]
    stressed = set(f.loc[f["financial_stress"], "user_id"])
    active = lo[lo["user_id"].isin(stressed) & ~lo["blocked"]]
    assert set(active["opportunity"]) <= {"DEBT_PLAN", "PREMIUM", "CASH_SAVINGS"}


def test_no_consent_means_in_app_only(res):
    lo, f = res["long"], res["features"]
    no_consent = set(f.loc[f["marketing_contact_consent"] != "Yes", "user_id"])
    ch = lo[lo["user_id"].isin(no_consent)]["channel"]
    assert ch.str.startswith("In-app").all()


def test_no_calls_request_is_respected(res):
    lo, f = res["long"], res["features"]
    ids = set(f.loc[f["no_calls"] & (f["marketing_contact_consent"] == "Yes"), "user_id"])
    assert ids, "nel dataset ci sono utenti che chiedono di non essere chiamati"
    ch = lo[lo["user_id"].isin(ids)]["channel"]
    assert not ch.str.contains("Phone|Call con consulente").any()


def test_credit_card_payable_from_cash_does_not_block_investing(res):
    # FZ-0002: 175k di liquidità, 10k su carta. Deve poter investire (dopo aver chiuso la carta).
    lo = res["long"]
    row = lo[(lo["user_id"] == "FZ-0002") & (lo["opportunity"] == "INVEST_START")].iloc[0]
    assert not row["blocked"]
    assert any("carta di credito" in e for e in row["evidence"])


def test_fallback_reads_contact_restriction():
    r = text_signals.keyword_fallback("I want a plan. I prefer not to be called about products.")
    assert "no_product_calls" in r["contact_restrictions"]


def test_validate_drops_unknown_labels():
    r = text_signals._validate({"needs": ["investing_start", "crypto_moonshot"], "primary_need": "crypto_moonshot"})
    assert r["needs"] == ["investing_start"] and r["primary_need"] == "investing_start"


def test_grounding_check_catches_invented_numbers():
    src = {"utenti": 24, "liquidita_mediana_eur": 38000}
    ok = {"testo": "24 utenti con liquidità mediana di €38.000"}
    bad = {"testo": "24 utenti, il 63% vuole un mutuo"}
    assert briefs.grounding_issues(ok, src) == []
    assert briefs.grounding_issues(bad, src) == ["63"]
