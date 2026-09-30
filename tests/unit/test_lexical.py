from bank_assistant.retrieval.lexical import lexical_terms, strip_accents


def test_product_codes_and_operation_ids_stay_whole() -> None:
    terms = lexical_terms("El PRS-CONS-36 y la operación OP-104233")

    assert "prs-cons-36" in terms
    assert "op-104233" in terms
    assert "36" not in terms  # the code is not broken into pieces


def test_numbers_with_separators_stay_whole() -> None:
    assert lexical_terms("1.200 € y 4,50 %") == ["1.200", "4,50"]


def test_accents_plurals_and_case_are_normalised() -> None:
    assert lexical_terms("Comisiones") == lexical_terms("comisión")
    assert lexical_terms("LÍMITES") == lexical_terms("limite")


def test_stopwords_are_dropped() -> None:
    assert lexical_terms("¿Cuál es el límite de la cuenta?") == lexical_terms("límite cuenta")


def test_strip_accents() -> None:
    assert strip_accents("Diligencia debida en oficina: año, pingüino") == (
        "Diligencia debida en oficina: ano, pinguino"
    )
