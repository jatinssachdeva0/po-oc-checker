from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from difflib import SequenceMatcher

import pandas as pd

from parsers import DocumentData, LineItem

PRICE_TOLERANCE = 0.005
ARITH_TOLERANCE = 0.02


def _norm_article(s: str | None) -> str:
    if not s:
        return ""
    return "".join(ch for ch in s.upper() if ch.isalnum())


def _desc_similarity(a: str, b: str) -> float:
    a = " ".join(a.upper().split())
    b = " ".join(b.upper().split())
    return SequenceMatcher(None, a, b).ratio()


def compare_documents(po: DocumentData, oc: DocumentData) -> pd.DataFrame:
    if po.doc_type != "PO" or oc.doc_type != "OC":
        raise ValueError("compare_documents expects PO then OC")

    oc_by_article: dict[str, list[LineItem]] = defaultdict(list)
    replacements: dict[str, list[LineItem]] = defaultdict(list)
    for x in oc.items:
        oc_by_article[_norm_article(x.article)].append(x)
        if x.replacement_for:
            replacements[_norm_article(x.replacement_for)].append(x)

    used = set()
    rows = []

    for po_idx, p in enumerate(po.items):
        key = _norm_article(p.article)
        match = None
        match_type = "EXACT"
        for cand in oc_by_article.get(key, []):
            if id(cand) not in used:
                match = cand
                break
        if match is None:
            for cand in replacements.get(key, []):
                if id(cand) not in used:
                    match = cand
                    match_type = "REPLACEMENT"
                    break
        if match is not None:
            used.add(id(match))

        arithmetic_expected = round(p.qty * p.unit_price, 2)
        po_arith_ok = abs(arithmetic_expected - p.line_total) <= ARITH_TOLERANCE

        if match is None:
            rows.append({
                "PO Line": p.line_no,
                "PO Item": p.article,
                "OC Line": "",
                "OC Item": "",
                "Description": p.description,
                "PO Qty": p.qty,
                "OC Qty": None,
                "PO Unit Price": p.unit_price,
                "OC Unit Price": None,
                "Price Difference": None,
                "Difference %": None,
                "PO Line Value": p.line_total,
                "OC Line Value": None,
                "Financial Impact": None,
                "PO Arithmetic": "OK" if po_arith_ok else f"CHECK: {p.qty:g} x {p.unit_price:.2f} = {arithmetic_expected:.2f}, printed {p.line_total:.2f}",
                "Match Type": "UNMATCHED",
                "Description Similarity": None,
                "Status": "MISSING IN OC",
            })
            continue

        diff = round(match.unit_price - p.unit_price, 2)
        pct = None if abs(p.unit_price) < 1e-12 else (diff / p.unit_price) * 100
        qty_diff = match.qty - p.qty
        financial_impact = round(match.line_total - p.line_total, 2)
        desc_sim = _desc_similarity(p.description, match.description)

        if not po_arith_ok:
            status = "MANUAL REVIEW - PO ARITHMETIC"
        elif match_type == "REPLACEMENT":
            status = "ITEM REPLACED"
        elif abs(qty_diff) > 1e-9:
            status = "QUANTITY DIFFERENCE"
        elif diff > PRICE_TOLERANCE:
            status = "PRICE HIGHER"
        elif diff < -PRICE_TOLERANCE:
            status = "PRICE LOWER"
        elif desc_sim < 0.30:
            status = "DESCRIPTION REVIEW"
        else:
            status = "MATCH"

        rows.append({
            "PO Line": p.line_no,
            "PO Item": p.article,
            "OC Line": match.line_no,
            "OC Item": match.article,
            "Description": p.description,
            "PO Qty": p.qty,
            "OC Qty": match.qty,
            "PO Unit Price": p.unit_price,
            "OC Unit Price": match.unit_price,
            "Price Difference": diff,
            "Difference %": pct,
            "PO Line Value": p.line_total,
            "OC Line Value": match.line_total,
            "Financial Impact": financial_impact,
            "PO Arithmetic": "OK" if po_arith_ok else f"CHECK: {p.qty:g} x {p.unit_price:.2f} = {arithmetic_expected:.2f}, printed {p.line_total:.2f}",
            "Match Type": match_type,
            "Description Similarity": desc_sim,
            "Status": status,
        })

    for x in oc.items:
        if id(x) in used:
            continue
        rows.append({
            "PO Line": "",
            "PO Item": "",
            "OC Line": x.line_no,
            "OC Item": x.article,
            "Description": x.description,
            "PO Qty": None,
            "OC Qty": x.qty,
            "PO Unit Price": None,
            "OC Unit Price": x.unit_price,
            "Price Difference": None,
            "Difference %": None,
            "PO Line Value": None,
            "OC Line Value": x.line_total,
            "Financial Impact": x.line_total,
            "PO Arithmetic": "",
            "Match Type": "UNMATCHED",
            "Description Similarity": None,
            "Status": "EXTRA IN OC",
        })

    return pd.DataFrame(rows)


def overall_status(df: pd.DataFrame, po: DocumentData, oc: DocumentData) -> str:
    serious = {"MANUAL REVIEW - PO ARITHMETIC", "ITEM REPLACED", "PRICE HIGHER", "QUANTITY DIFFERENCE", "MISSING IN OC", "EXTRA IN OC"}
    statuses = set(df["Status"].dropna()) if not df.empty else set()
    if "MANUAL REVIEW - PO ARITHMETIC" in statuses:
        return "HOLD - MANUAL REVIEW"
    if statuses & serious:
        return "REVIEW REQUIRED"
    if oc.reference_po and po.document_no and oc.reference_po != po.document_no:
        return "HOLD - WRONG PO REFERENCE"
    return "APPROVED - ITEM PRICES MATCH"


def summary_dict(df: pd.DataFrame, po: DocumentData, oc: DocumentData) -> dict:
    counts = df["Status"].value_counts().to_dict() if not df.empty else {}
    return {
        "PO Number": po.document_no,
        "OC Number": oc.document_no,
        "OC Reference PO": oc.reference_po,
        "Currency": po.currency,
        "PO Items": len(po.items),
        "OC Items": len(oc.items),
        "Matches": counts.get("MATCH", 0),
        "Price Higher": counts.get("PRICE HIGHER", 0),
        "Price Lower": counts.get("PRICE LOWER", 0),
        "Replacements": counts.get("ITEM REPLACED", 0),
        "Manual Reviews": counts.get("MANUAL REVIEW - PO ARITHMETIC", 0),
        "PO Goods Value": po.goods_value,
        "OC Goods Value": oc.goods_value,
        "Goods Value Difference": None if po.goods_value is None or oc.goods_value is None else round(oc.goods_value - po.goods_value, 2),
        "Freight": oc.freight,
        "Insurance": oc.insurance,
        "Packing": oc.packing,
        "OC Total Amount": oc.total_amount,
        "Overall Status": overall_status(df, po, oc),
    }
