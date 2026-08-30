# PO vs Order Confirmation Checker

A local Streamlit application tailored to the supplied Mustafa Sultan purchase-order PDFs and KARL STORZ order-confirmation PDFs.

## What this version fixes

- Reads multi-line PO tables instead of assuming one item per text line.
- Understands PO number format `1,234.56` and KARL STORZ European price format `1.234,56`.
- Matches repeated article numbers by occurrence.
- Detects supplier replacements when the OC states `Replacement for:`.
- Validates `PO quantity × PO unit price` against the printed PO line amount.
- Separates goods value from freight, insurance and packing.
- Uses OCR only when a PO table is image-only (needed by test PO 4500039469).
- Creates an Excel report with Summary, Item Comparison, Exceptions and Charges sheets.

## Permanent regression test set

The folder `tests/fixtures/` contains the 16 PDFs supplied for this project: 8 POs and 8 matching Order Confirmations. `pytest` runs all 8 pairs every time you change the parser or comparison logic.

Expected headline cases:

- 4500037402: item prices match.
- 4500037664: 27040BL1 OC price is EUR 26.72/unit higher.
- 4500038497: 27294N is replaced by 27040LB at EUR 123.80.
- 4500038598: item prices match.
- 4500039165: 26-line PO matches item prices.
- 4500039372: item price matches; OC charges are reported separately.
- 4500039469: image-only PO table is handled through OCR fallback.
- 4500033073: held for manual review because printed PO line amount does not equal quantity × unit price.

## Windows setup

1. Install Python 3.11 or 3.12 and enable **Add Python to PATH**.
2. Install Tesseract OCR (required for image-only PO tables). A common Windows build is UB Mannheim Tesseract. During installation, note the install path, normally `C:\\Program Files\\Tesseract-OCR\\tesseract.exe`.
3. Open Command Prompt in this project folder.
4. Create a virtual environment:

```bat
python -m venv .venv
.venv\Scripts\activate
```

5. Install Python packages:

```bat
pip install -r requirements.txt
```

6. If Tesseract is not automatically found, add this near the top of `parsers.py` after importing pytesseract in `_ocr_first_page`:

```python
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
```

7. Run the permanent tests first:

```bat
pytest -q
```

8. Start the app:

```bat
streamlit run app.py
```

The app opens at `http://localhost:8501`.

## Important deployment rule

Run `pytest -q` before every deployment. Do not deploy a parser change if any of the 16 permanent regression documents fails.

## Live deployment

This project is ready for Streamlit Community Cloud and Docker-based hosts. See `DEPLOYMENT.md`.

Cloud deployment files included:
- `packages.txt` - installs Tesseract OCR on Streamlit Cloud.
- `.streamlit/config.toml` - production server settings.
- `Dockerfile` - container deployment.
- `render.yaml` - Render deployment blueprint.
