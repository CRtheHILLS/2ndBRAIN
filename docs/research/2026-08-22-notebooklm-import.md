# NotebookLM (Gemini Notebook) → 2nd BRAIN import — research (2026-08-22)

Target notebook: https://notebook.google.com/notebook/fd7a7958-36ea-4dfb-847d-20b96734d58a (CR's 양자역학 notebook). NotebookLM was renamed "Gemini Notebook" on 2026-07-16; URLs unchanged.

## 1. Official API?
- **Consumer NotebookLM (notebook.google.com): no public API.** No key, no console.
- **Enterprise only:** Google Cloud "Gemini Notebook Enterprise" REST API (Discovery Engine, v1alpha): create/get/list notebooks, `sources:batchCreate`, `sources:uploadFile`, `GET sources/{id}` (metadata only). Needs GCP project + billing + IAM + licenses (~$9/license/mo, 15-license minimum ≈ $135/mo). **No endpoint exports generated notes.** Docs: https://docs.cloud.google.com/gemini/enterprise/notebooklm-enterprise/docs/api-notebooks , .../api-notebooks-sources
- → Not viable for a solo $20–50/mo setup.

## 2. Can Clair fetch the share link without auth?
**No.** Even "Anyone with the link" public notebooks require a signed-in Google account and render client-side in JS; a private notebook returns a login wall. Server-side `curl`/fetch yields nothing usable. (https://support.google.com/notebooklm/answer/16322204)

## 3. Alternatives
| Method | Gets | Reliability |
|---|---|---|
| "Export to Google Docs" (Studio → note/report → ⋮ menu) | Notes, saved chat answers, reports as Google Docs | Official, manual per item |
| Audio/Video/Mind map download | WAV / MP4 / PNG | Official, per artifact |
| **Google Drive API** for Drive-originated sources | Original Docs/PDFs | Official, stable (`drive.readonly`) |
| Uploaded PDFs / pasted text / URLs | Not exportable — re-obtain from original place | — |
| `notebooklm-py` (github.com/teng-lin/notebooklm-py) | Unofficial client using browser cookies; lists sources, pulls notes | Fragile (internal endpoints), account-cookie risk → use dedicated account |
| Playwright automation / Apify scrapers | Same as above | Brittle, ToS risk, paid |

## 4. Recommendation (solo, $20–50/mo)
1. **Now (manual, official):** in the notebook, export each note/report to Google Docs → download as Markdown/TXT → drop into `~/Desktop/2ndBRAIN/양자역학/`. Original PDFs: copy from wherever they came from into the same folder. brain-sync does the rest.
2. **Ongoing (semi-automatic, unofficial):** `sync/notebooklm_import.py` wraps `notebooklm-py`; CR logs in once (cookie file, ideally a dedicated Google account) and the importer pulls new sources/notes into the book folder on a schedule. Wrap in try/except; fall back to manual export when Google changes internals.
3. Skip Enterprise API and paid scrapers.

## References
- https://blog.google/technology/google-labs/notebooklm-public-notebooks/
- https://www.sourclip.com/guides/notebooklm-export-guide
- https://workspaceupdates.googleblog.com/2026/05/keep-your-sources-up-to-date-with-automatic-Drive-syncing-in-NotebookLM.html
- https://developers.google.com/drive/api/guides/manage-downloads
- https://github.com/teng-lin/notebooklm-py
