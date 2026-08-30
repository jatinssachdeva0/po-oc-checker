# Deploy the PO vs OC Checker Live

## Recommended: Streamlit Community Cloud

1. Create a GitHub repository, for example `po-oc-checker`.
2. Upload the contents of this folder to the repository root.
3. Confirm these files are present:
   - `app.py`
   - `parsers.py`
   - `comparator.py`
   - `requirements.txt`
   - `packages.txt`
   - `.streamlit/config.toml`
4. In Streamlit Community Cloud, choose **Create app** / **Deploy an app**.
5. Select the GitHub repository and branch.
6. Main file path: `app.py`.
7. Deploy.

`packages.txt` installs the Linux Tesseract OCR package needed for image-only PO tables.

### Privacy
The app processes uploaded PDFs during the Streamlit session. The current application does not deliberately save uploaded PO/OC files to disk or a database. For confidential commercial documents, use a private repository and access-controlled deployment where possible.

## Alternative: Render

This package contains both `Dockerfile` and `render.yaml`.

1. Put the project in GitHub.
2. In Render, create a new **Blueprint** or **Web Service** from the repository.
3. Render will build the Docker image and install Tesseract automatically.
4. After deployment, use the HTTPS URL provided by Render.

## Alternative: Internal office server / Windows laptop

Run:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

For Windows OCR, install Tesseract separately and ensure `tesseract.exe` is on PATH.

## Before every deployment

Run:

```bash
pytest -q
```

All permanent regression tests should pass before deployment.

## What new documents can be checked

The current parser is optimized for:
- Mustafa Sultan `PURCHASE ORDER(FOREIGN)` PDFs in the supplied format.
- KARL STORZ `Confirmation of Order` PDFs in the supplied format.

It can check new PO/OC pairs in those formats. If another supplier uses a substantially different OC layout, the app may return incomplete extraction or require a new supplier parser. Do not treat a partial extraction as an automatic approval.
