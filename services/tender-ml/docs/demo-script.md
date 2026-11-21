# Demonstration script

A step-by-step demonstration of the tender category model, first on its own and then inside the Tender Scrapper platform. It takes about ten minutes.

## Before the demonstration

- [ ] tender-ml is running: `/health` answers `{"status": "ok", ...}`.
- [ ] The chat assistant, AI service and Smart Alerts API are running the versions that use tender-ml.
- [ ] A demonstration account has a business profile uploaded, for example an IT company that supplies laptops and provides IT support.
- [ ] `reports/` contains the latest `metrics.json`, `calibration.png`, `confusion_matrix.png` and `model_comparison.md` (run `python train.py`, `python compare_models.py` and `python audit.py` beforehand; they take several minutes).

## 1. The model on its own (tender-ml web page)

Open the tender-ml web page (port 9004).

1. **Tender tab → "Laptops".** The model picks *Supplies: Computer Equipment* with high confidence. Point out the words behind the guess: *laptops, delivery of*.
2. **"Security guards".** *Security and investigation activities*, explained by *security, guarding, security guarding*.
3. **"Vague tender"** ("Request for quotation"). The model refuses to choose: it only fills in a category when it is at least 50% sure.
4. Type **"Supply of laptps"** (misspelt). The best guess is still *Supplies: Computer Equipment*, because the model also reads 3- to 5-letter character pieces.
5. **Company tab → "Cleaning company".** The model places the company in *Services: Functional (Including Cleaning and Security Services)*. This is how the platform knows which tender categories a company works in.

Key message: *the model was not given rules; it learned which words point to which category from 6,707 real tenders.*

## 2. The model inside the platform

1. **Dashboard matches.** Open the dashboard. Matches whose category was found by the model show the reason *"Category matches your business (ML: …)"*.
2. **Chat: "5 tenders that match my business profile".** The assistant lists the company's best matches with scores and reasons. It also works with typos: *"5 tender that march my bussiness profile"*.
3. **Chat: "find laptop tenders".** The reply starts with *"Our ML model put your request in the category 'Supplies: Computer Equipment'"*, followed by tenders from that category.
4. **Smart Alerts.** The notifications and `/matches` list use the same ML category check, with the same reason text.

Key message: *the chat, the dashboard and the alerts all use the same model, and each one keeps working if the model is unavailable.*

## 3. Evidence for the report

| Evidence | Where |
|---|---|
| Results against a baseline: 49.9% exact and 72.5% in the top three, against 14.2% for guessing | `reports/metrics.json`, README *Results* |
| Calibration: how often the model is right at each confidence level | `reports/calibration.png` |
| Which categories are confused, and why (two overlapping category schemes) | `reports/confusion_matrix.png`, README *Results* |
| Comparison with a deep-learning model, which did worse | `reports/model_comparison.md`, README *Model comparison* |
| Tenders that are probably in the wrong category | `reports/suspected_mislabels.csv` |
| What changed in matching: no score went down, and no new strong alerts | Smart Alerts README, *Recent changes* |

## If something goes wrong during the demonstration

- **tender-ml is down:** search and matching still work, without the ML reasons. Show the tender-ml web page locally instead (`python -m uvicorn app:app --port 9004`).
- **The chat answers slowly:** the language model is remote; the ML part answers in milliseconds. Use the tender-ml web page to show the model directly.
