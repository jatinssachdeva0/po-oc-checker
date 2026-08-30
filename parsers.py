from __future__ import annotations

import io
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, Optional

import pdfplumber


@dataclass
class LineItem:
    line_no: str
    article: str
    description: str
    qty: float
    uom: str | None
    unit_price: float
    line_total: float
    internal_material: str | None = None
    delivery_date: str | None = None
    replacement_for: str | None = None

    def to_dict(self):
        return asdict(self)


@dataclass
class DocumentData:
    doc_type: str
    document_no: str | None
    reference_po: str | None
    date: str | None
    currency: str
    items: list[LineItem]
    goods_value: float | None
    total_amount: float | None
    freight: float | None
    insurance: float | None
    packing: float | None
    payment_terms: str | None
    incoterms: str | None
    raw_text: str
    extraction_method: str

    def to_dict(self):
        d = asdict(self)
        d["items"] = [x.to_dict() for x in self.items]
        return d


def _read_bytes(file_or_path) -> bytes:
    if isinstance(file_or_path, (str, Path)):
        return Path(file_or_path).read_bytes()
    if hasattr(file_or_path, "getvalue"):
        return file_or_path.getvalue()
    if hasattr(file_or_path, "read"):
        pos = None
        try:
            pos = file_or_path.tell()
        except Exception:
            pass
        data = file_or_path.read()
        if pos is not None:
            try:
                file_or_path.seek(pos)
            except Exception:
                pass
        return data
    raise TypeError("Unsupported file input")


def extract_pdf_text(file_or_path) -> str:
    data = _read_bytes(file_or_path)
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        pages = []
        for p in pdf.pages:
            pages.append(p.extract_text(x_tolerance=2, y_tolerance=2) or "")
    return "\n".join(pages)


def _ocr_first_page(file_or_path) -> str:
    """OCR fallback for image-only PO tables. Requires pymupdf, pillow, pytesseract + Tesseract."""
    try:
        import fitz
        import pytesseract
        from PIL import Image
    except Exception as exc:
        raise RuntimeError(
            "OCR fallback is required for this PDF, but OCR dependencies are unavailable. "
            "Install pymupdf, pillow, pytesseract and Tesseract OCR."
        ) from exc

    data = _read_bytes(file_or_path)
    doc = fitz.open(stream=data, filetype="pdf")
    page = doc[0]
    pix = page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
    image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    return pytesseract.image_to_string(image, config="--psm 3")


def parse_number(value: str | None, european: bool = False) -> float | None:
    if value is None:
        return None
    s = value.strip().replace(" ", "")
    if not s:
        return None
    if european:
        # 3.852,19 -> 3852.19; 561,29 -> 561.29
        s = s.replace(".", "").replace(",", ".")
    else:
        # 3,852.19 -> 3852.19
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _last_money_on_line(line: str, european: bool = False) -> float | None:
    pat = r"(?:\d{1,3}(?:[.,]\d{3})*[.,]\d{2}|\d+[.,]\d{2})"
    vals = re.findall(pat, line)
    if not vals:
        return None
    return parse_number(vals[-1], european=european)


def _extract_simple_field(text: str, patterns: Iterable[str]) -> str | None:
    for p in patterns:
        m = re.search(p, text, flags=re.I | re.M)
        if m:
            return m.group(1).strip()
    return None


def parse_purchase_order(file_or_path) -> DocumentData:
    text = extract_pdf_text(file_or_path)
    extraction_method = "embedded_text"

    po_no = _extract_simple_field(text, [r"P\.O Number\s*:\s*(\d+)", r"P\.O Number\s*=\s*(\d+)"])
    po_date = _extract_simple_field(text, [r"P\.O Date\s*:\s*([0-9.]+)"])

    items = _parse_po_items(text)
    # 4500039469-style PDF has its table as an image; OCR only when text parsing finds no rows.
    if not items:
        ocr = _ocr_first_page(file_or_path)
        items = _parse_po_items(ocr, ocr_mode=True)
        if items:
            text = text + "\n\n--- OCR PAGE 1 ---\n" + ocr
            extraction_method = "embedded_text+ocr"

    goods_value = None
    for line in text.splitlines():
        if re.match(r"^\s*Total\b", line, flags=re.I):
            maybe = _last_money_on_line(line, european=False)
            if maybe is not None:
                goods_value = maybe
                break

    payment_terms = _extract_simple_field(text, [r"Payment Terms\s*:?[ \t]*(.+)"])
    incoterms = _extract_simple_field(text, [r"Incoterms\s*:?[ \t]*(.+)"])

    return DocumentData(
        doc_type="PO",
        document_no=po_no,
        reference_po=po_no,
        date=po_date,
        currency="EUR",
        items=items,
        goods_value=goods_value,
        total_amount=goods_value,
        freight=0.0,
        insurance=0.0,
        packing=0.0,
        payment_terms=payment_terms,
        incoterms=incoterms,
        raw_text=text,
        extraction_method=extraction_method,
    )


def _parse_po_items(text: str, ocr_mode: bool = False) -> list[LineItem]:
    lines = [ln.rstrip() for ln in text.splitlines()]
    out: list[LineItem] = []
    material_re = re.compile(r"^\s*(\d{9})\s*/\s*([A-Za-z0-9]+)\s*$")
    # Standard text layer: line no + description + qty + UOM + unit + vat + vat amt + total
    row_re = re.compile(
        r"^\s*(\d+)\s+(.+?)\s+(\d+(?:\.\d+)?)\s+(EA|PAC)\s+([\d,]+\.\d{2})\s+\d+(?:\.\d+)?\s+\d+(?:\.\d+)?\s+([\d,]+\.\d{2})\s*$",
        re.I,
    )
    # OCR can insert pipes and can occasionally omit VAT columns.
    ocr_row_re = re.compile(
        r"^\s*(\d+)?\s*\|?\s*(.+?)\s+(?:(\d+(?:\.\d+)?)\s+)?(EA|PAC)\s+([\d,]+\.\d{2})(?:\s+\d+(?:\.\d+)?\s+\d+(?:\.\d+)?)?\s+([\d,]+\.\d{2})\s*$",
        re.I,
    )

    i = 0
    while i < len(lines):
        m = material_re.match(lines[i])
        if not m:
            i += 1
            continue
        internal, article = m.groups()
        candidate = None
        desc = ""
        scheduled_qty = None
        delivery_date = None
        line_no = str(len(out) + 1)
        # look ahead up to 6 lines
        for j in range(i + 1, min(len(lines), i + 8)):
            s = lines[j].strip()
            if not s:
                continue
            sm = re.search(r"Scheduled delivery Dt\s*:\s*([0-9.]+)\s+Qty:\s*(\d+(?:\.\d+)?)", s, re.I)
            if sm:
                delivery_date = sm.group(1)
                scheduled_qty = float(sm.group(2))
                continue
            rm = row_re.match(lines[j])
            if rm:
                candidate = rm
                break
            if ocr_mode:
                orm = ocr_row_re.match(lines[j].replace("|", " "))
                if orm:
                    candidate = orm
                    break
            if not re.match(r"^(Scheduled delivery|Total|TERMS)", s, re.I):
                desc = (desc + " " + s).strip()

        if candidate:
            g = candidate.groups()
            if len(g) == 6 and candidate.re is row_re:
                line_no, row_desc, qty_s, uom, unit_s, total_s = g
                qty = float(qty_s)
            else:
                line_no_s, row_desc, qty_s, uom, unit_s, total_s = g
                line_no = line_no_s or line_no
                qty = float(qty_s) if qty_s else (scheduled_qty if scheduled_qty is not None else 1.0)
            description = row_desc.strip(" |-\t") or desc
            out.append(
                LineItem(
                    line_no=str(line_no),
                    article=article.upper(),
                    description=description,
                    qty=qty,
                    uom=uom.upper(),
                    unit_price=parse_number(unit_s, european=False) or 0.0,
                    line_total=parse_number(total_s, european=False) or 0.0,
                    internal_material=internal,
                    delivery_date=delivery_date,
                )
            )
        i += 1
    return out


def parse_order_confirmation(file_or_path) -> DocumentData:
    text = extract_pdf_text(file_or_path)
    oc_no = _extract_simple_field(text, [r"\b(46\d{6})\s+[0-9]{2}\.[0-9]{2}\.[0-9]{4}\b"])
    # Prefer explicit header reference
    reference_po = _extract_simple_field(text, [r"Your order\s+(\d+)\s+of"])
    oc_date = None
    if oc_no:
        m = re.search(rf"\b{re.escape(oc_no)}\s+([0-9]{{2}}\.[0-9]{{2}}\.[0-9]{{4}})\b", text)
        if m:
            oc_date = m.group(1)

    items = _parse_oc_items(text)

    goods_value = _extract_money_field(text, "Goods value", european=True)
    if goods_value is None:
        goods_value = _extract_money_field(text, "Net value of goods", european=True)
    total_amount = _extract_money_field(text, "Total amount", european=True)
    insurance = _extract_money_field(text, "Transport insurance", european=True)
    freight = _extract_money_field(text, "Freight charges", european=True)
    packing = _extract_money_field(text, "Packing", european=True)

    payment_terms = None
    m = re.search(r"Payment terms:\s*\n?\s*([^\n]+)", text, flags=re.I)
    if m:
        payment_terms = m.group(1).strip()
    incoterms = None
    m = re.search(r"Terms of delivery:\s*\n?\s*([^\n]+)", text, flags=re.I)
    if m:
        incoterms = m.group(1).strip()

    return DocumentData(
        doc_type="OC",
        document_no=oc_no,
        reference_po=reference_po,
        date=oc_date,
        currency="EUR",
        items=items,
        goods_value=goods_value,
        total_amount=total_amount,
        freight=freight,
        insurance=insurance,
        packing=packing,
        payment_terms=payment_terms,
        incoterms=incoterms,
        raw_text=text,
        extraction_method="embedded_text",
    )


def _extract_money_field(text: str, label: str, european: bool) -> float | None:
    m = re.search(rf"{re.escape(label)}\s*:\s*([\d.,]+)", text, flags=re.I)
    if not m:
        return None
    return parse_number(m.group(1), european=european)


def _parse_oc_items(text: str) -> list[LineItem]:
    lines = [ln.rstrip() for ln in text.splitlines()]
    row_re = re.compile(
        r"^\s*(\d+)\s+([A-Za-z0-9]+)\s+(\d+(?:\.\d+)?)\s+(.+?)\s+([\d.]+,\d{2})\s+([\d.]+,\d{2})\s*$"
    )
    out: list[LineItem] = []
    for i, line in enumerate(lines):
        m = row_re.match(line)
        if not m:
            continue
        pos, article, qty_s, desc, unit_s, total_s = m.groups()
        # Exclude footer lines that coincidentally resemble rows.
        if article.lower() in {"carried", "page"}:
            continue
        delivery_date = None
        replacement_for = None
        extra_desc = []
        for j in range(i + 1, min(len(lines), i + 18)):
            nxt = lines[j].strip()
            if row_re.match(lines[j]) or re.match(r"^(Goods value|Net value|Transport insurance|Freight charges|Packing|Total amount|299\b|Pos\.)", nxt, re.I):
                break
            if not nxt:
                continue
            dm = re.search(r"(?:Ready for shipping|delivery date)\s*:\s*([0-9.]+)", nxt, re.I)
            if dm:
                delivery_date = dm.group(1)
            rm = re.search(r"Replacement for:\s*([A-Za-z0-9]+)", nxt, re.I)
            if rm:
                replacement_for = rm.group(1).upper()
            if not re.match(r"^(Country of origin|ECCN|Ready for shipping|delivery date)", nxt, re.I):
                extra_desc.append(nxt)
        description = " ".join([desc] + extra_desc).strip()
        out.append(
            LineItem(
                line_no=pos,
                article=article.upper(),
                description=description,
                qty=float(qty_s),
                uom=None,
                unit_price=parse_number(unit_s, european=True) or 0.0,
                line_total=parse_number(total_s, european=True) or 0.0,
                delivery_date=delivery_date,
                replacement_for=replacement_for,
            )
        )
    return out


def parse_document(file_or_path, expected_type: str | None = None) -> DocumentData:
    text = extract_pdf_text(file_or_path)
    if expected_type == "PO" or "PURCHASE ORDER(FOREIGN)" in text:
        return parse_purchase_order(file_or_path)
    if expected_type == "OC" or "Confirmation of Order" in text:
        return parse_order_confirmation(file_or_path)
    raise ValueError("Could not determine whether the PDF is a Purchase Order or Order Confirmation.")
