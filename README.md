# Validatrix — demo edition

## Run locally
Use Python 3.12. Open a terminal inside this folder.

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:5000. Dependencies are installed fresh; a Windows virtual environment is intentionally not bundled.

## Deploy on Render
Upload the contents of this folder to a Git repository. Create a Render Web Service connected to it. Use Python runtime, build command `pip install -r requirements.txt`, and start command `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 2 --timeout 60`. Alternatively use the included render.yaml blueprint. Health check: `/health`.
If this folder is nested in your repository, set it as the service root directory.
Free instances can sleep when idle. Review current limits before deployment.

## Demo scope
No database is required. The application processes inputs in memory and returns downloads; it does not intentionally store uploaded content. Hosting infrastructure may retain request metadata. Use sample data only.

Use the sample download link and upload `samples/demo_survey.xml`. The report checks the existing rule set; it is not a complete survey certification. XML structure errors are rejected while Decipher namespace-prefix conventions are tolerated. Excel downloads validate their posted report data and escape formula-like values. Results are client-round-tripped, so exported reports are not tamper-proof.
