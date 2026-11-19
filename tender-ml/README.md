# Tender Category Classifier

A machine learning service that reads a public tender (title, description and the organisation that published it) and predicts its procurement category, such as *Construction*, *Supplies: Computer Equipment* or *Security and investigation activities*. It can also read what a company does and predict which categories the company works in.

Part of the **Tender Scrapper** platform. The model is trained on tenders the platform's scraper has already collected, and three platform services use it:

- the **chat assistant** narrows tender searches to the category the user is asking about;
- the **dashboard matching** awards category points when a company and a tender share a likely category;
- the **Smart Alerts API** uses the same check to find matches that keyword rules miss.

Every one of these services keeps working exactly as before if this service is unavailable.

---

## Contents

- [Why it exists](#why-it-exists)
- [Results](#results)
- [How it works](#how-it-works)
- [Model comparison](#model-comparison)
- [How the platform uses it](#how-the-platform-uses-it)
- [API reference](#api-reference)
- [Getting started](#getting-started)
- [Deployment](#deployment)
- [Output files](#output-files)
- [Testing](#testing)
- [Project structure](#project-structure)
- [Known limitations](#known-limitations)
- [Data and privacy](#data-and-privacy)

---

## Why it exists

Tender Scrapper helps companies find government tenders worth bidding on. Matching a tender to a company depends heavily on its category, but:

- **Keyword rules miss tenders.** A rule looking for "laptops" does not find "ICT equipment". The model learns that both belong to *Supplies: Computer Equipment*.
- **Categories are inconsistent.** eTenders uses two overlapping category schemes at the same time, and the same kind of work is filed under different categories by different organisations.
- **Companies describe themselves in their own words**, not in eTenders category names.

The model reads text the way a person would scan a tender: it learns which words and phrases point to which category, from thousands of real examples, instead of following hand-written rules.

## Results

Measured on **1,342 tenders (20%) that were held back and never used for training.**

| Metric | Result | What it means |
|---|---|---|
| Baseline | 14.2% | Accuracy from always guessing the most common category. The model has to beat this |
| **Accuracy** | **49.9%** | The predicted category is exactly the saved one |
| **Top-3 accuracy** | **72.5%** | The saved category is among the model's three suggestions |
| Macro F1 | 0.41 | Average quality across all 58 categories, with small categories counting as much as large ones |
| At least 50% sure | 52% of tenders, **69.8% correct** | The threshold for filling in a category |
| At least 70% sure | 31% of tenders, **80.2% correct** | The threshold the chat assistant uses to narrow a search |

**Calibration.** A useful model's confidence should mean what it says. On the held-out tenders:

| The model said | Tenders | It was right |
|---|---|---|
| 16% sure (0–20%) | 107 | 15% |
| 30% sure (20–40%) | 363 | 26% |
| 50% sure (40–60%) | 317 | 43% |
| 70% sure (60–80%) | 267 | 68% |
| 90% sure (80–100%) | 288 | 84% |

The model is slightly over-confident in the middle range, so the thresholds above are based on the measured accuracy, not on the stated confidence.

**Why exact accuracy is not higher.** The saved categories disagree with each other. eTenders uses broad groups (*Services: General*, *Services: Professional*, *Supplies: General*) alongside standard economic-activity categories (*Other service activities*, *Construction of buildings*). Even identical re-advertised tenders were sometimes filed under different categories. The most frequent mistakes are all between these broad groups:

| Saved category | Predicted as | Times |
|---|---|---|
| Services: Professional | Services: General | 20 |
| Services: General | Services: Professional | 16 |
| Other service activities | Services: General | 16 |

This is why the platform compares each side's **few most likely** categories rather than a single answer.

## How it works

```
SQLite database ──► clean labels ──► build text ──► 80/20 split ──► TF-IDF + logistic regression ──► evaluate ──► save
```

1. **Load.** Read every tender with its category and organisation name. The database is opened **read-only**, so training can never change it.
2. **Clean.**

   | Step | Tenders removed | Reason |
   |---|---|---|
   | No usable category | 17 | The category is empty, *Uncategorised*, or a block of tender details the scraper saved by mistake |
   | Duplicate text | 148 | Re-advertised tenders. A copy in both the training and test sets would let the model "remember" the answer and overstate accuracy |
   | Rare category | 216 | 30 categories have fewer than 20 tenders, too few to learn or to test reliably |

   That leaves **6,707 tenders in 58 categories** (from 7,088 loaded).
3. **Build the text.** Title, description (skipped when it only repeats the title, as it does for most tenders) and organisation name are joined into one string. Training and prediction use the same function, so the model always sees text in the same shape.
4. **Split.** 80% for training, 20% for testing, stratified so every category has the same share in both sets, with a fixed seed so results are repeatable.
5. **Train.**
   - **TF-IDF** turns text into numbers in two ways: whole words and word pairs ("security services"), and 3- to 5-letter character pieces, which still match misspelt words.
   - **Logistic regression** learns how strongly each feature points to each category and gives a probability for every category.
6. **Evaluate** on the held-out 20% (see [Results](#results)), including calibration and the most frequent mistakes.
7. **Save** the model with its format version, training date, scikit-learn version and results. A new model only replaces the saved one if its top-3 accuracy is not more than one point lower (the **quality gate**).

### What the model learned

The model explains each prediction with the words that pushed it towards the category:

```
python predict.py "Provision of security guarding services for 36 months" --organisation "Department of Health"

Words behind the top guess: security, guarding, of security, security guarding, guarding services
```

Character pieces let it cope with spelling mistakes. For "Supply of laptps", the word-only model's best guess was *Supplies: General*; the final model's best guess is *Supplies: Computer Equipment*.

### Design decisions

| Decision | Reason |
|---|---|
| Logistic regression | Fast, explainable, and gives probabilities, which the confidence thresholds need |
| Include the organisation name | Organisations tend to buy the same kinds of things. It raised cross-validated accuracy by about 5 percentage points |
| Word pairs and character pieces | Phrases carry more meaning than single words; character pieces handle misspellings. Chosen by the [model comparison](#model-comparison) |
| `C=10` | Weaker regularisation than the default (`C=1`) scored clearly better in 5-fold cross-validation |
| Drop rare categories instead of merging them into "Other" | "Other" is not a real category, so it could never be matched to a company |
| A category is "likely" at 20% or more | On held-out tenders, a likely category at 20% is the saved one about half the time; at 10%, weak second guesses caused false matches |

## Model comparison

`compare_models.py` compares candidate models with 5-fold cross-validation on the training tenders, then checks each once on the held-out tenders. The rule for choosing was fixed before the comparison: a more complex model replaces a simpler one only if its cross-validated top-3 accuracy is at least 1 point higher (3 points for sentence embeddings).

| Model | CV accuracy | CV top-3 | CV macro F1 | Test accuracy | Test top-3 |
|---|---|---|---|---|---|
| Word TF-IDF (first version) | 49.2% ± 1.2% | 68.9% ± 0.6% | 35.8% ± 2.0% | 50.4% | 71.5% |
| **Word + character TF-IDF (chosen)** | 49.1% ± 1.1% | **70.7% ± 0.5%** | **36.3% ± 1.8%** | 49.9% | **72.5%** |
| Sentence embeddings (MiniLM) + logistic regression, C=10 | 40.3% ± 0.6% | 64.4% ± 2.3% | 31.8% ± 2.3% | 40.5% | 66.8% |
| Sentence embeddings (MiniLM) + logistic regression, C=1 | 37.1% ± 0.5% | 62.1% ± 1.4% | 19.1% ± 0.6% | 35.9% | 62.1% |

The pre-trained deep-learning model (`all-MiniLM-L6-v2`) did clearly worse. It was trained on general web text and knows nothing about procurement conventions, while TF-IDF learns them directly from this platform's tenders: organisation names, standard phrases such as "supply and delivery", and the categories each organisation tends to use.

## How the platform uses it

| Service | How it uses the model | If this service is down |
|---|---|---|
| Chat assistant (`tender-ai-agent`) | Predicts the category of a search request. At 70% confidence or more, searches inside that category first and tells the user | Normal search |
| Dashboard matching (AI service in `tender-scrapping-database`) | `POST /match-categories` for the tenders being ranked. A shared category earns 15 points | Keyword category rule (5 points) |
| Smart Alerts API (`alerts-api`) | `POST /match-categories` for every open tender, in batches of 2,000. A shared category earns the category points, and can only raise a score | Scoring exactly as before |

**Category overlap.** For a company, the model predicts up to three categories with at least 20% probability from its industries, services, keywords and description. For a tender, it uses the saved category plus up to three predicted ones at 20% or more. A tender matches when the two sets share a category. This absorbs the overlapping category schemes: a company predicted as *Construction* still meets a tender saved as *Civil engineering* when the model rates *Construction* likely for it. Company descriptions with fewer than three words or word pairs the model knows get no categories, so a vague profile never matches everything.

Tender predictions are cached by text, so the same open tenders are only run through the model once.

## API reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Web page for trying the model (tender and company tabs) |
| `POST` | `/predict` | Body: `title` (required), `description`, `organisation`. Returns `category` (or `null` below 50% confidence), the top three `suggestions` with probabilities, and the `explanation` words |
| `POST` | `/categorise-company` | Body: `industries`, `services`, `keywords` (lists) and `description`. Returns the company's likely `categories`, `suggestions` and `explanation` |
| `POST` | `/match-categories` | Body: `company` (as above) and up to 5,000 `tenders` (`id`, `title`, `description`, `organisation`, `category`). Returns the company's categories and, for each matching tender id, the shared category |
| `GET` | `/health` | Service status and model version |
| `GET` | `/model` | Model version, training date, scikit-learn version and results |
| `GET` | `/docs` | Interactive API documentation |

Requests are validated with size limits well above real data; a blank title or an oversized request is rejected with `422`.

## Getting started

### Requirements

- Python 3.12 or newer (the pinned numpy and scipy versions need it)
- A copy of the platform's SQLite database (`tenders.db`)

### 1. Install

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
```

`requirements.txt` holds what the service needs, `requirements-dev.txt` adds the test tools, and `requirements-experiments.txt` adds PyTorch and sentence-transformers for `compare_models.py` only.

### 2. Configure

Settings are read from environment variables or from a `.env` file in the project root. **`.env` is ignored by Git and must never be committed.**

| Variable | Default | Description |
|---|---|---|
| `DATABASE_PATH` | `tenders-copy.db` | Path to the platform database |
| `MODEL_PATH` | `models/category_model.joblib` | Where the trained model is saved and loaded |
| `REPORTS_DIR` | `reports` | Where evaluation reports are written |

### 3. Get a copy of the database

Never train on a database file another service is writing to. On the server, make a consistent copy with SQLite's backup API, then download it with `scp` or a similar tool:

```bash
python -c "import sqlite3; s = sqlite3.connect('tenders.db'); d = sqlite3.connect('tenders-copy.db'); s.backup(d); d.close()"
```

### 4. Use it

| Command | What it does |
|---|---|
| `python train.py` | Train, evaluate and save the model (about 3 minutes). `--force` skips the quality gate |
| `python predict.py "Supply of laptops"` | Top three categories and the words behind the best one |
| `python -m uvicorn app:app --reload --port 9004` | The web page and API at http://localhost:9004 |
| `python audit.py` | List tenders whose saved category the model strongly disagrees with |
| `python compare_models.py` | Rerun the model comparison (needs `requirements-experiments.txt`) |

`train.py` exits with `0` when it saved a new model, `1` when it could not train (unreadable database, or fewer than 1,000 usable tenders), and `2` when it kept the saved model because that one scored better.

## Deployment

The service runs as the `tender-ml` container on port 9004, on the platform's shared Docker network, so other services reach it at `http://tender-ml:9004`. It reads the shared database volume and keeps its model in its own volume.

- **CI** (`.github/workflows/ci.yml`): on every push and pull request to `main`, checks that the code compiles, runs the tests and builds the Docker image.
- **Deploy** (`.github/workflows/deploy.yml`): after CI succeeds on `main`, on the self-hosted runner, builds the image, trains the model (keeping the saved one if it scores better), restarts the container and checks `/health`. The first deployment therefore creates the model automatically.
- **Retrain** (`.github/workflows/retrain.yml`): every Monday at 03:00 UTC, retrains on the latest tenders and loads the new model only if it passed the quality gate.

The self-hosted runner must be registered for this repository. Deploy tender-ml before the services that call it; until it is running they simply work without it.

A saved model records its format version and scikit-learn version. A model saved by different code is refused with a clear message and replaced at the next training run, instead of failing at prediction time.

## Output files

All output is generated and ignored by Git.

| File | Contents |
|---|---|
| `models/category_model.joblib` | The trained model and its metadata (about 26 MB) |
| `reports/metrics.json` | Headline results, calibration and the most frequent mistakes |
| `reports/classification_report.txt` | Precision, recall and F1 for each category |
| `reports/confusion_matrix.png` | Which categories are predicted as which |
| `reports/calibration.png` | How often the model is right at each level of confidence |
| `reports/model_comparison.md` / `.json` | The model comparison table |
| `reports/suspected_mislabels.csv` | Tenders whose saved category the model strongly disagrees with |

## Testing

```bash
python -m pytest -q
```

The tests build their own small database and training data, so they need no real data and run in seconds. They cover text building, label cleaning, read-only loading, predictions and explanations, the confidence threshold, company categories and matching, saving and loading (including refusing incompatible models), the quality gate, the evaluation reports and every API endpoint.

## Project structure

```
tender_ml/
├── config.py        Settings from environment variables / .env
├── dataset.py       Loading tenders, cleaning labels, building the model's input text, train/test split
├── classifier.py    The model: build, predict, likely categories, explanations
├── model_file.py    Saving and loading the model with its metadata and compatibility checks
├── matching.py      Company and tender category overlap, with a prediction cache
├── evaluation.py    Metrics, calibration, most frequent mistakes and report files
└── schemas.py       API request and response shapes
static/index.html    The web page for trying the model
tests/               Pytest suite (conftest.py builds the test database and data)
app.py               Web page and API (FastAPI)
train.py             Train, evaluate and save the model, with the quality gate
predict.py           Suggest categories for one tender from the command line
audit.py             Find tenders that are probably in the wrong category
compare_models.py    Compare candidate models with cross-validation
docs/demo-script.md  Step-by-step demonstration of the model in the platform
```

## Known limitations

- **Overlapping category schemes** limit exact accuracy, as described in [Results](#results). The platform therefore compares several likely categories rather than one.
- **Slight over-confidence** in the 40–60% range. Thresholds are set from measured accuracy, not stated confidence.
- **30 small categories are never predicted.** They had fewer than 20 tenders each. Weekly retraining adds them once they are large enough.
- **Some saved categories are wrong.** Some organisations file tenders under their own sector rather than what they are buying (for example, protective clothing filed under "Water supply"). `audit.py` lists such cases for checking.
- **Scraper data gaps.** 17 tenders have a field label such as "Organ Of State:" as their title. 5,373 of 7,088 tenders, saved before the scraper read closing dates, had no closing date. The platform now treats an undated tender as open for 36 days after publishing, and a one-off scan of eTenders in November 2026 filled in real dates and statuses, leaving 317 without a closing date.
- **It does not learn from users.** Learning from which tenders companies save or dismiss needs a separate model and more user activity than the platform has today.

## Data and privacy

The platform database also stores user accounts, password hashes, business profiles and documents. Training **reads only tender, category and organisation fields**. The API writes nothing to disk: apart from an in-memory cache of tender predictions, which is cleared on restart, it keeps no record of the text it receives. All database files (`*.db`) and the `.env` file are ignored by Git and excluded from the Docker image. Never commit, upload or share a database copy.
