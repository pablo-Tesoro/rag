"""Lexical analysis for BM25: the same function turns documents and queries into terms.

Design choices, all aimed at Spanish policy text with product codes:
- Codes and numbers stay whole: "PRS-CONS-36", "OP-104233", "1.200", "4,50" are single
  terms. Exact codes are where dense retrieval fails, so the lexical side must keep them.
- Words are lower-cased, stemmed with the Snowball Spanish stemmer ("comisiones" and
  "comisión" -> "comision") and stripped of accents, so queries written without accents
  still match.
- Very common Spanish words are dropped (they carry no ranking signal).
"""

import re
import unicodedata
from functools import lru_cache

import snowballstemmer

# Bump when the analysis changes: it is part of the index fingerprint (forces re-indexing).
LEXICAL_VERSION = "1"

_TOKEN = re.compile(r"[0-9a-záéíóúüñ]+(?:[-_./,][0-9a-záéíóúüñ]+)*")

SPANISH_STOPWORDS = frozenset(
    [
        "a",
        "al",
        "algo",
        "algunas",
        "algunos",
        "ante",
        "antes",
        "como",
        "con",
        "contra",
        "cual",
        "cuales",
        "cuando",
        "de",
        "del",
        "desde",
        "donde",
        "durante",
        "e",
        "el",
        "ella",
        "ellas",
        "ellos",
        "en",
        "entre",
        "era",
        "es",
        "esa",
        "esas",
        "ese",
        "eso",
        "esos",
        "esta",
        "estas",
        "este",
        "esto",
        "estos",
        "esta",
        "fue",
        "ha",
        "han",
        "hay",
        "la",
        "las",
        "le",
        "les",
        "lo",
        "los",
        "mas",
        "me",
        "mi",
        "mis",
        "mucho",
        "muchos",
        "muy",
        "nada",
        "ni",
        "no",
        "nos",
        "nosotros",
        "o",
        "os",
        "otra",
        "otras",
        "otro",
        "otros",
        "para",
        "pero",
        "poco",
        "por",
        "porque",
        "que",
        "quien",
        "quienes",
        "se",
        "ser",
        "si",
        "sin",
        "sobre",
        "son",
        "su",
        "sus",
        "tambien",
        "te",
        "tiene",
        "tienen",
        "todo",
        "todos",
        "tu",
        "tus",
        "un",
        "una",
        "uno",
        "unos",
        "y",
        "ya",
        "yo",
        "cuanto",
        "cuanta",
        "cuantos",
        "cuantas",
        "debe",
        "deben",
        "puede",
        "pueden",
    ]
)


@lru_cache(maxsize=1)
def _stemmer() -> snowballstemmer.stemmer:
    return snowballstemmer.stemmer("spanish")


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


@lru_cache(maxsize=50_000)
def _normalise_word(word: str) -> str | None:
    plain = strip_accents(word)
    if plain in SPANISH_STOPWORDS:
        return None
    return strip_accents(_stemmer().stemWord(word))


def lexical_terms(text: str) -> list[str]:
    """Terms of `text`, in order and with repetitions (term frequency matters for BM25)."""
    terms: list[str] = []
    for token in _TOKEN.findall(text.lower()):
        if token.isalpha():
            normalised = _normalise_word(token)
            if normalised:
                terms.append(normalised)
        else:
            terms.append(strip_accents(token))  # codes and numbers: kept whole
    return terms
