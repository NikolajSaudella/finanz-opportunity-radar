"""
Brief di segmento e sintesi per gli stakeholder, scritti dall'LLM.

Il secondo punto dove uso l'LLM: trasformare tabelle di numeri in un testo che
un PM o qualcuno del Monetisation legge in 30 secondi e che suggerisce cosa fare.
Un template deterministico produce frasi rigide e sempre uguali; l'LLM sa
scegliere cosa è rilevante per quel segmento e collegarlo al catalogo prodotti.

Il rischio è che inventi numeri. Mitigazioni:
1. vede SOLO le statistiche aggregate già calcolate (niente dati del singolo utente);
2. il prompt vieta di calcolare nuove percentuali o citare numeri non presenti;
3. dopo la generazione controllo che ogni numero nel testo esista nell'input
   (grounding check). Se non torna, il brief viene mostrato con un avviso.
"""

import json
import re

from . import config as C
from .llm import JsonCache, cache_key, complete_json, get_client

CATALOG = "\n".join(f"- {o.name}: {o.revenue_model}" for o in C.OPPORTUNITIES.values())

SEGMENT_SYSTEM = f"""Sei un analista del team AIOps di Finanz. Scrivi per il team Product/Monetisation.
Ricevi le statistiche aggregate di un segmento di utenti che hanno compilato la Financial Life Survey.
Scrivi in italiano, tono concreto e asciutto, niente marketing.

Catalogo delle opportunità di Finanz:
{CATALOG}

Regole di Finanz sui guardrail: agli utenti sotto pressione finanziaria non si propongono
prodotti di credito né di investimento; chi non ha consenso marketing si raggiunge solo in-app;
chi chiede di non essere chiamato non va chiamato.

Rispondi solo con JSON:
{{
  "sintesi": "1-2 frasi: chi sono e perché interessano commercialmente",
  "perche_conta": "2-3 frasi con le evidenze più importanti, citando i numeri",
  "azioni": ["2-3 azioni concrete, ognuna con prodotto, canale e tempistica"],
  "attenzione": "1 frase su rischi, guardrail o dubbi sui dati"
}}

Usa SOLO numeri presenti nelle statistiche. Non calcolare percentuali o totali nuovi."""

SUMMARY_SYSTEM = """Sei un analista del team AIOps di Finanz. Scrivi una sintesi per il responsabile
Monetisation a partire da statistiche aggregate già calcolate. Italiano, asciutto, niente marketing.
Rispondi solo con JSON:
{
  "titolo": "una frase che dice dove concentrarsi",
  "punti": ["3-4 punti, ognuno una frase con un numero dalle statistiche"],
  "prossimo_passo": "una frase: cosa fare questa settimana"
}
Usa SOLO numeri presenti nelle statistiche. Non calcolare percentuali o totali nuovi."""


# --- grounding check ---------------------------------------------------------------

_NUM = re.compile(r"(?<![\w.])\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?")


def _parse_it_number(tok: str) -> float:
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", tok):
        tok = tok.replace(".", "")
    return float(tok.replace(",", "."))


def _allowed_numbers(obj) -> set:
    vals = set()

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                walk(k)
                walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v)
        elif isinstance(x, bool):
            return
        elif isinstance(x, (int, float)):
            v = float(x)
            vals.update({v, round(v), round(v / 1000), round(v / 1000, 1), round(v / 1e6, 1), round(v * 100)})
        elif isinstance(x, str):
            for tok in _NUM.findall(x):
                vals.add(_parse_it_number(tok))

    walk(obj)
    return vals


def grounding_issues(text_obj, source) -> list[str]:
    allowed = _allowed_numbers(source)
    text = json.dumps(text_obj, ensure_ascii=False)
    issues = []
    for tok in _NUM.findall(text):
        v = _parse_it_number(tok)
        if v not in allowed and not any(abs(v - a) <= 1 for a in allowed if a >= 20):
            issues.append(tok)
    return sorted(set(issues))


# --- fallback deterministico ---------------------------------------------------------

def template_brief(seg: str, s: dict) -> dict:
    top = list(s["top_opportunita_per_valore_atteso_eur"])
    return {
        "sintesi": f"{s['utenti']} utenti. {s['descrizione']}.",
        "perche_conta": (
            f"Opportunità con più valore atteso: {', '.join(top) or 'nessuna'}. "
            f"Contattabili outbound: {s['contattabili_outbound']}."
        ),
        "azioni": [f"Partire da {top[0]}" if top else "Nessuna azione commerciale prioritaria"],
        "attenzione": f"Utenti con opportunità sospese dal guardrail: {s['utenti_con_opportunita_sospese_da_guardrail']}.",
    }


# --- generazione con cache ---------------------------------------------------------------

def _cached_llm(cache, key, system, payload, client, model):
    hit = cache.get(key)
    if hit:
        return hit["result"], hit.get("source", "llm")
    if client is None:
        return None, None
    res = complete_json(client, model, system, json.dumps(payload, ensure_ascii=False, indent=2), max_tokens=900)
    cache.set(key, {"model": model, "source": "llm", "result": res})
    return res, "llm"


def segment_briefs(stats: dict, refresh: bool = False, verbose: bool = False) -> dict:
    cache = JsonCache("segment_briefs")
    client = get_client()
    out = {}
    for seg, s in stats.items():
        payload = {"segmento": seg, **s}
        key = cache_key(C.PROMPT_VERSION_BRIEF, json.dumps(payload, sort_keys=True, ensure_ascii=False))
        if refresh and client is not None:
            cache.data.pop(key, None)
        res, src = _cached_llm(cache, key, SEGMENT_SYSTEM, payload, client, C.BRIEF_MODEL)
        if res is None:
            res, src = template_brief(seg, s), "template"
        out[seg] = {"brief": res, "source": src, "grounding_issues": grounding_issues(res, payload) if src == "llm" else []}
    cache.save()
    if verbose:
        srcs = [v["source"] for v in out.values()]
        print(f"[briefs] segmenti: {len(out)} | llm/cache: {srcs.count('llm')} | template: {srcs.count('template')}")
        for seg, v in out.items():
            if v["grounding_issues"]:
                print(f"  ! {seg}: numeri non trovati nei dati -> {v['grounding_issues']}")
    return out


def executive_summary(gstats: dict, refresh: bool = False) -> dict:
    cache = JsonCache("segment_briefs")
    client = get_client()
    key = cache_key(C.PROMPT_VERSION_BRIEF, "summary", json.dumps(gstats, sort_keys=True, ensure_ascii=False))
    if refresh and client is not None:
        cache.data.pop(key, None)
    res, src = _cached_llm(cache, key, SUMMARY_SYSTEM, gstats, client, C.BRIEF_MODEL)
    cache.save()
    if res is None:
        return {"summary": None, "source": "template", "grounding_issues": []}
    return {"summary": res, "source": src, "grounding_issues": grounding_issues(res, gstats)}
