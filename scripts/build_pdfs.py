"""Generate the two fictitious PDF policies (with tables) and their metadata sidecars.

The PDFs are committed, so this script only needs to run when their content changes
(`make data`). Output is byte-for-byte deterministic (reportlab "invariant" mode), so
re-running it does not change the files and does not trigger a re-ingestion.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

CORPUS_DIR = Path(__file__).resolve().parents[1] / "data" / "corpus"
NOTICE = (
    "Documento ficticio de Banco Olvessa (entidad inventada), creado con fines de demostración."
)


@dataclass
class Section:
    heading: str
    paragraphs: list[str] = field(default_factory=list)
    table: list[list[str]] | None = None
    after_table: list[str] = field(default_factory=list)


@dataclass
class PdfPolicy:
    filename: str
    metadata: dict[str, object]
    sections: list[Section]


CATALOGO_FINANCIACION = PdfPolicy(
    filename="NOR-002_catalogo-productos-financiacion.pdf",
    metadata={
        "id": "NOR-002",
        "title": "Catálogo de productos de financiación",
        "version": "2.1",
        "date": "2025-06-15",
        "status": "vigente",
        "groups": ["todos"],
    },
    sections=[
        Section(
            "1. Objeto",
            [
                "Este catálogo recoge las condiciones de referencia de los productos de "
                "financiación que Banco Olvessa comercializa a particulares y empresas. Las "
                "condiciones finales de cada operación dependen del análisis de riesgo del "
                "cliente. Identifica siempre el producto por su código: hay productos con "
                "nombres parecidos y condiciones distintas.",
            ],
        ),
        Section(
            "2. Préstamos personales",
            ["Condiciones de referencia de los préstamos personales:"],
            table=[
                [
                    "Código",
                    "Producto",
                    "Plazo máximo",
                    "TIN desde",
                    "Comisión de apertura",
                    "Importe máximo",
                ],
                ["PRS-CONS-24", "Préstamo Consumo 24", "24 meses", "6,95 %", "1,00 %", "15.000 €"],
                ["PRS-CONS-36", "Préstamo Consumo 36", "36 meses", "7,45 %", "1,50 %", "30.000 €"],
                ["PRS-AUTO-60", "Préstamo Coche", "60 meses", "5,90 %", "0,75 %", "50.000 €"],
                ["PRS-EST-48", "Préstamo Estudios", "48 meses", "4,25 %", "0,00 %", "20.000 €"],
            ],
            after_table=[
                "El Préstamo Estudios (PRS-EST-48) solo puede contratarse por titulares de "
                "entre 18 y 35 años con matrícula en un centro oficial.",
            ],
        ),
        Section(
            "3. Hipotecas",
            ["Condiciones de referencia de los préstamos hipotecarios para vivienda habitual:"],
            table=[
                [
                    "Código",
                    "Producto",
                    "Plazo máximo",
                    "Tipo de interés",
                    "Comisión de apertura",
                    "Financiación máxima",
                ],
                [
                    "HIP-FIJ-25",
                    "Hipoteca Fija 25",
                    "25 años",
                    "2,85 % fijo",
                    "0,00 %",
                    "80 % del valor de tasación",
                ],
                [
                    "HIP-FIJ-30",
                    "Hipoteca Fija 30",
                    "30 años",
                    "3,10 % fijo",
                    "0,00 %",
                    "80 % del valor de tasación",
                ],
                [
                    "HIP-VAR-30",
                    "Hipoteca Variable 30",
                    "30 años",
                    "Euríbor + 0,79 %",
                    "0,00 %",
                    "80 % del valor de tasación",
                ],
                [
                    "HIP-MIX-20",
                    "Hipoteca Mixta 20",
                    "20 años",
                    "2,60 % fijo 5 años; después Euríbor + 0,69 %",
                    "0,00 %",
                    "70 % del valor de tasación",
                ],
            ],
            after_table=[
                "Todas las hipotecas exigen domiciliar la nómina y contratar un seguro de hogar, "
                "que el cliente puede suscribir con la aseguradora que elija.",
            ],
        ),
        Section(
            "4. Financiación para empresas",
            ["Condiciones de referencia para pymes y autónomos:"],
            table=[
                [
                    "Código",
                    "Producto",
                    "Plazo máximo",
                    "Tipo de interés",
                    "Comisión de apertura",
                    "Importe máximo",
                ],
                [
                    "LIN-PYM-12",
                    "Línea de Crédito Pyme",
                    "12 meses renovables",
                    "Euríbor + 2,25 %",
                    "0,50 %",
                    "250.000 €",
                ],
                [
                    "PRE-PYM-60",
                    "Préstamo Inversión Pyme",
                    "60 meses",
                    "5,40 %",
                    "1,00 %",
                    "500.000 €",
                ],
            ],
        ),
        Section(
            "5. Tramitación y aprobación",
            [
                "Toda solicitud de financiación se analiza según la Política de riesgo de "
                "crédito (NOR-011) y la aprueba el órgano que corresponda según la Matriz de "
                "delegación de facultades de riesgo (NOR-012). Ambos documentos son de acceso "
                "restringido al área de Riesgos.",
                "La oficina debe recopilar como mínimo el documento de identidad, las dos "
                "últimas nóminas o la última declaración de la renta y la autorización para "
                "consultar ficheros de solvencia.",
            ],
        ),
    ],
)

TARIFAS_TRANSFERENCIAS = PdfPolicy(
    filename="NOR-003_tarifas-transferencias-divisa.pdf",
    metadata={
        "id": "NOR-003",
        "title": "Tarifas de transferencias y cambio de divisa",
        "version": "1.3",
        "date": "2025-01-10",
        "status": "vigente",
        "groups": ["todos"],
    },
    sections=[
        Section(
            "1. Objeto",
            [
                "Este documento recoge las comisiones de las transferencias y los márgenes "
                "aplicados en las operaciones de cambio de divisa. Cada tarifa se identifica "
                "con un código que debe indicarse al registrar la operación.",
            ],
        ),
        Section(
            "2. Comisiones de transferencias",
            ["Comisiones por transferencia emitida, según tipo y canal:"],
            table=[
                ["Código", "Tipo de transferencia", "Canal", "Comisión"],
                ["TRF-SEPA-DIG", "SEPA estándar", "Banca digital", "0,00 €"],
                ["TRF-SEPA-OFI", "SEPA estándar", "Oficina", "3,00 €"],
                ["TRF-INM-DIG", "Inmediata", "Banca digital", "0,00 €"],
                ["TRF-INM-OFI", "Inmediata", "Oficina", "3,50 €"],
                ["TRF-URG-OFI", "Urgente (sistema de grandes pagos)", "Oficina", "12,00 €"],
                [
                    "TRF-INT-USD",
                    "Internacional no SEPA en dólares",
                    "Oficina",
                    "0,30 %, mínimo 15,00 € y máximo 90,00 €",
                ],
                [
                    "TRF-INT-OTR",
                    "Internacional no SEPA en otras divisas",
                    "Oficina",
                    "0,40 %, mínimo 18,00 €",
                ],
            ],
        ),
        Section(
            "3. Cambio de divisa",
            ["Margen aplicado sobre el tipo de cambio de referencia publicado cada día:"],
            table=[
                ["Divisa", "Margen en transferencias", "Margen en compraventa de billetes"],
                ["USD", "1,50 %", "2,50 %"],
                ["GBP", "1,50 %", "2,50 %"],
                ["CHF", "1,75 %", "3,00 %"],
                ["JPY", "2,00 %", "3,50 %"],
                ["MXN", "2,50 %", "No disponible"],
            ],
            after_table=[
                "Los billetes en divisa se solicitan con 48 horas de antelación y se recogen en "
                "la oficina.",
            ],
        ),
        Section(
            "4. Gastos compartidos",
            [
                "En las transferencias internacionales la opción por defecto es SHA (gastos "
                "compartidos). Si el cliente elige la opción OUR, asumiendo también los gastos "
                "de la entidad del beneficiario, se añade un recargo de 20,00 €.",
            ],
        ),
        Section(
            "5. Límites",
            [
                "Los límites diarios de cada tipo de transferencia y canal se establecen en la "
                "Política de límites operativos de transferencias (NOR-005).",
            ],
        ),
    ],
)


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": base["Title"],
        "heading": base["Heading2"],
        "body": base["BodyText"],
        "notice": ParagraphStyle("notice", parent=base["BodyText"], textColor=colors.grey),
        "cell": ParagraphStyle("cell", parent=base["BodyText"], fontSize=8, leading=10),
    }


def _table(rows: list[list[str]], styles: dict[str, ParagraphStyle]) -> Table:
    wrapped = [[Paragraph(cell, styles["cell"]) for cell in row] for row in rows]
    table = Table(wrapped, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return table


def _footer(policy: PdfPolicy) -> Callable[[Canvas, SimpleDocTemplate], None]:
    label = (
        f"Banco Olvessa (entidad ficticia) · {policy.metadata['id']} v{policy.metadata['version']}"
    )

    def draw(canvas: Canvas, doc: SimpleDocTemplate) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.drawString(2 * cm, 1.2 * cm, f"{label} · Página {doc.page}")
        canvas.restoreState()

    return draw


def build(policy: PdfPolicy) -> None:
    styles = _styles()
    story: list[object] = [
        Paragraph(str(policy.metadata["title"]), styles["title"]),
        Paragraph(NOTICE, styles["notice"]),
        Spacer(1, 0.4 * cm),
    ]
    for section in policy.sections:
        story.append(Paragraph(section.heading, styles["heading"]))
        story.extend(Paragraph(text, styles["body"]) for text in section.paragraphs)
        if section.table:
            story.append(_table(section.table, styles))
            story.append(Spacer(1, 0.3 * cm))
        story.extend(Paragraph(text, styles["body"]) for text in section.after_table)

    pdf_path = CORPUS_DIR / policy.filename
    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        title=str(policy.metadata["title"]),
        author="Banco Olvessa (ficticio)",
    )
    footer = _footer(policy)
    doc.build(story, onFirstPage=footer, onLaterPages=footer)

    sidecar = pdf_path.with_suffix(".meta.yaml")
    sidecar.write_text(
        yaml.safe_dump(policy.metadata, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    print(f"Wrote {pdf_path.name} and {sidecar.name}")


def main() -> None:
    rl_config.invariant = 1  # deterministic output: no timestamps or random ids
    for policy in (CATALOGO_FINANCIACION, TARIFAS_TRANSFERENCIAS):
        build(policy)


if __name__ == "__main__":
    main()
