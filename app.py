from __future__ import annotations

from io import BytesIO

import pandas as pd
import streamlit as st

from comparator import compare_documents, overall_status, summary_dict
from parsers import parse_order_confirmation, parse_purchase_order

st.set_page_config(page_title="PO vs Order Confirmation Checker", layout="wide")
st.title("PO vs Order Confirmation Price Checker")
st.caption("Optimized for Mustafa Sultan PO format and KARL STORZ Order Confirmations used in the supplied 2026 test set.")

with st.sidebar:
    st.header("Comparison rules")
    st.write("• Match by catalogue/article number")
    st.write("• Handle repeated catalogue numbers by occurrence")
    st.write("• Detect supplier replacements via 'Replacement for:'")
    st.write("• Validate PO quantity × unit price")
    st.write("• Treat freight/insurance/packing separately from goods prices")
    st.write("• OCR fallback for image-only PO tables")

c1, c2 = st.columns(2)
with c1:
    po_file = st.file_uploader("Upload Purchase Order (PO)", type=["pdf"], key="po")
with c2:
    oc_file = st.file_uploader("Upload Order Confirmation (OC)", type=["pdf"], key="oc")

if po_file and not oc_file:
    st.info("Purchase Order received. Please upload the corresponding Order Confirmation.")
elif oc_file and not po_file:
    st.info("Order Confirmation received. Please upload the corresponding Purchase Order.")
elif po_file and oc_file:
    if st.button("Compare Documents", type="primary", use_container_width=True):
        try:
            with st.spinner("Reading and validating both PDFs..."):
                po = parse_purchase_order(po_file)
                oc = parse_order_confirmation(oc_file)
                report = compare_documents(po, oc)
                summary = summary_dict(report, po, oc)

            if po.document_no and oc.reference_po and po.document_no != oc.reference_po:
                st.error(f"Wrong document pair: PO is {po.document_no}, but OC references {oc.reference_po}.")

            status = overall_status(report, po, oc)
            if status.startswith("APPROVED"):
                st.success(status)
            elif status.startswith("HOLD"):
                st.error(status)
            else:
                st.warning(status)

            st.subheader("Summary")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("PO", po.document_no or "Not detected")
            m2.metric("Order Confirmation", oc.document_no or "Not detected")
            m3.metric("PO Goods Value", f"EUR {po.goods_value:,.2f}" if po.goods_value is not None else "N/A")
            m4.metric(
                "OC Goods Value Difference",
                f"EUR {summary['Goods Value Difference']:+,.2f}" if summary["Goods Value Difference"] is not None else "N/A",
            )

            st.caption(f"PO extraction method: {po.extraction_method} | OC extraction method: {oc.extraction_method}")

            st.subheader("Item-by-item price comparison")
            display = report.copy()
            money_cols = ["PO Unit Price", "OC Unit Price", "Price Difference", "PO Line Value", "OC Line Value", "Financial Impact"]
            for col in money_cols:
                if col in display:
                    display[col] = display[col].map(lambda x: "" if pd.isna(x) else f"{x:,.2f}")
            if "Difference %" in display:
                display["Difference %"] = display["Difference %"].map(lambda x: "" if pd.isna(x) else f"{x:+.2f}%")
            if "Description Similarity" in display:
                display["Description Similarity"] = display["Description Similarity"].map(lambda x: "" if pd.isna(x) else f"{x:.0%}")

            def highlight(row):
                s = row.get("Status", "")
                if s == "MATCH":
                    return ["background-color: #e8f5e9"] * len(row)
                if s in {"PRICE HIGHER", "ITEM REPLACED", "MANUAL REVIEW - PO ARITHMETIC"}:
                    return ["background-color: #ffebee"] * len(row)
                if s in {"PRICE LOWER", "DESCRIPTION REVIEW", "QUANTITY DIFFERENCE"}:
                    return ["background-color: #fff8e1"] * len(row)
                return [""] * len(row)

            st.dataframe(display.style.apply(highlight, axis=1), use_container_width=True, hide_index=True)

            exceptions = report[report["Status"] != "MATCH"].copy()
            st.subheader("Exceptions requiring attention")
            if exceptions.empty:
                st.success("No item-level exceptions detected.")
            else:
                st.dataframe(exceptions, use_container_width=True, hide_index=True)

            st.subheader("Charges separated from goods value")
            charges = pd.DataFrame([
                {"Charge": "Transport insurance", "EUR": oc.insurance},
                {"Charge": "Freight", "EUR": oc.freight},
                {"Charge": "Packing", "EUR": oc.packing},
                {"Charge": "OC Total amount", "EUR": oc.total_amount},
            ])
            st.dataframe(charges, use_container_width=True, hide_index=True)

            output = BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                pd.DataFrame([summary]).to_excel(writer, index=False, sheet_name="Summary")
                report.to_excel(writer, index=False, sheet_name="Item Comparison")
                exceptions.to_excel(writer, index=False, sheet_name="Exceptions")
                charges.to_excel(writer, index=False, sheet_name="Charges")
            output.seek(0)
            st.download_button(
                "Download Excel Comparison Report",
                data=output,
                file_name=f"PO_{po.document_no}_vs_OC_{oc.document_no}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

        except Exception as exc:
            st.exception(exc)
