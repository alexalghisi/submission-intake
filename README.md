# submission-intake

Commercial insurance submissions arrive as broker emails with a pile of attachments: an application form, a statement of values with one row per location, and loss runs. Before an underwriter can look at the risk, someone has to read all of it and type the key facts into a system. This service does that step. Every value it produces comes with the document and the quote it came from, and it sends a submission to a person whenever the documents disagree or something required is missing.

![Processing a clean submission and a conflicting one, then the evals and checks](docs/preview.gif)

## How it works

```
broker email (.eml) ──▶ S3 ──▶ Lambda: record + queue ──▶ SQS ──▶ Lambda: extract + merge ──▶ Postgres
                                  (idempotent per                (partial batch failures,       (submissions, documents,
                                   Message-ID)                     DLQ after 5 attempts)          review queue)
```

1. **Read.** The email is parsed. PDFs become text through pdfplumber, and spreadsheets and CSVs become rows.
2. **Classify.** Each attachment is classified as application, SOV or loss run. Spreadsheets are classified with the same header detection the parsers use, so a sheet is only called an SOV if the SOV parser can read it.
3. **Extract, with the cheapest tool that is reliable for each document:**
   - **Spreadsheets go through parsers, not a model.** The SOV parser understands common header variants (`Building Value` / `Bldg`, `Contents` / `BPP`, `Business Income` / `BI`), skips totals rows and recomputes TIV from the locations. The loss run parser counts claims in the five years before the effective date.
   - **Labelled forms and the email body go through rules.**
   - **Unreadable fields can go to an LLM.** A model is called only for documents the rules couldn't fully read, and only when one is configured (`OPENAI_API_KEY`). Its answers are checked before they are accepted: each value needs a quote that really appears in the document, and the quote has to contain that value. Anything else is rejected and counted, so a hallucinated insured name or date can't reach an underwriter.
4. **Merge.** Forms and spreadsheets take precedence over the email body, and parsers over rules over the model. Values that only differ in formatting are treated as the same, for example `Harbor Point Logistics, LLC` and `HARBOR POINT LOGISTICS LLC.`.
5. **Route to review when:**
   - the documents disagree on a value;
   - a required field (insured, effective date, TIV) is missing;
   - a required value has low confidence.

   Otherwise the submission is `ready`.

### Running on AWS

`template.yaml` (AWS SAM) wires up the pieces:

- an encrypted, private S3 inbox that triggers on `.eml` files;
- a queue with a dead-letter queue after five attempts;
- two Lambda functions, the processing one using `ReportBatchItemFailures`.

**Duplicates.** S3 can deliver an event twice and brokers resend emails, so submissions are unique per `Message-ID`. A duplicate is recorded once and queued once.

**Retries.** One bad message in a batch fails alone and is retried by SQS, while the rest of the batch completes. A redelivered message for a finished submission is skipped. Processing that died mid-way, such as a Lambda timeout, can be claimed again after 15 minutes.

## Evals

`python -m evals.run_evals 0.98` generates 40 labelled submissions and checks every field and the ready / needs-review decision. Exit code 1 means it fell below the threshold, so it can gate a CI run. The submissions vary:

- company name forms;
- five date formats;
- three SOV layouts;
- 1–8 locations;
- loss histories inside and outside the five-year window;
- missing loss runs;
- conflicting insured names.

The set is synthetic, so 100% here doesn't mean 100% on real broker mail. Its value is as a regression gate. Its first run caught a real bug: SOVs with abbreviated headers were classified as "other", so their TIV was never extracted. That is fixed in `a9966a7`. Real submissions can be added as labelled cases in the same format.

## Tech stack

Python 3.12, Pydantic v2, PostgreSQL (psycopg 3), AWS Lambda, S3 and SQS (boto3, SAM), pdfplumber, openpyxl, an optional OpenAI-compatible LLM, pytest, moto, ruff, mypy (strict)

## Running it

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

submission-intake process examples/harbor-point.eml examples/harbor-point-conflict.eml
submission-intake process examples/harbor-point.eml --json      # full result with evidence per field
python -m evals.run_evals 0.98
```

Set `OPENAI_API_KEY`, and optionally `SUBMISSION_INTAKE_MODEL`, to let the model read documents the rules can't. Without it, everything runs offline.

Deploy with SAM:

```bash
sam build && sam deploy --guided --parameter-overrides DatabaseUrl=postgresql://…
```

## Tests

```bash
ruff check . && ruff format --check . && mypy
SUBMISSION_INTAKE_TEST_DATABASE_URL=postgresql://user:pass@localhost/intake pytest
```

The AWS tests run the real handlers against Postgres and moto's S3 and SQS. They cover:

- an email becoming a ready submission;
- duplicate events and resent emails;
- redelivery after success;
- conflicts landing in the review queue;
- a poisoned message failing alone and succeeding once fixed.

They are skipped when the database URL isn't set.

## License

MIT
