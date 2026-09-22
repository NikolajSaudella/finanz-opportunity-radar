"""
Wrapper minimale sull'API Anthropic + cache su file JSON.

Perché la cache:
- le chiamate sono deterministiche rispetto all'input (stesso testo, stesso prompt,
  stessa versione) quindi non ha senso ripagarle a ogni run;
- chi valuta il progetto può eseguire tutto anche senza API key;
- i risultati dell'LLM diventano un artefatto versionato e revisionabile
  (si può aprire il JSON e vedere cosa ha estratto, riga per riga).
"""

import hashlib
import json
import os
import re
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "llm_cache"


def cache_key(*parts: str) -> str:
    return hashlib.sha1("||".join(parts).encode("utf-8")).hexdigest()[:16]


class JsonCache:
    def __init__(self, name: str):
        self.path = CACHE_DIR / f"{name}.json"
        self.data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        self.dirty = False

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value
        self.dirty = True

    def save(self):
        if not self.dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_client():
    if not os.getenv("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
    except ImportError:
        return None
    return anthropic.Anthropic()


def complete_json(client, model: str, system: str, user: str, max_tokens: int = 800) -> dict:
    """Chiama il modello chiedendo solo JSON e prova a parsarlo in modo tollerante."""
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=0,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    # se il modello aggiunge testo attorno, prendo il primo oggetto JSON
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    return json.loads(m.group(0) if m else text)
