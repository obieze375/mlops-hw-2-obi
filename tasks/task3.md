# Task 3 — Add a new config, score it, promote it

You'll use the promotion CLI you built in Task 2 to ship a new configuration through the full MLOps loop: design → evaluate → register → promote. 

**Files you'll touch:**
- `configs/v6.yaml` — *new*; the config you design
- optionally `prompts/*.txt` — only if you customize a prompt
- Run the existing `python -m src.eval --config v6` to evaluate
- Run `python scripts/promote.py set production <version>` to promote

## Grading (25 pts)

| Subtask | Points |
|---|---|
| Part A — v6 config exists and is a meaningful variation of an existing config | 8 |
| Part B — eval ran successfully and registered a new version in MLflow | 7 |
| Part C — promoted v6 via the CLI (`promote.py set production v6`) | 5 |
| Part D — service reloaded and serving the new config | 5 |

## Why this task exists

The repo has five configs (v1–v5) as worked examples:

- **v1** — minimal baseline prompt; no guardrails.
- **v2** — explicit-refusal prompt with the canned-refusal trick.
- **v3** — long anti-jailbreak rules.
- **v4** — input classifier in front of the main assistant.
- **v5** — sandwich: input classifier + main + output validator.

Your job is to design **v6** as a variation. Try whatever you find interesting :)

## Your TODOs

### Part A — design v6

Create `configs/v6.yaml`. Start by copying one of the previous configs. Run `python scripts/list_models.py --verbose` to see the live Nebius catalog with per-token prices.

In actual production settings, you should also have some hypotheses: the new model will be more precise / less prone to jailbreaking / faster than the previous one.

### Part B — score it

```bash
python -m src.eval --config v6
```

The eval runs the dataset through v6's pipeline, judges every example, computes metrics, logs an MLflow run, and (because there's no `--limit`) auto-registers a new version of the `travel-assistant` registered model. Watch the summary print — the line `registered: travel-assistant vN` tells you the version number. Open MLflow UI (http://localhost:5000 → Models → travel-assistant) and confirm the new version appears with its tags (`config_id=v6`, `model`, `guardrail_type`) and metrics.

### Part C — promote v6

Use your Task 2 CLI:

```bash
python scripts/promote.py show production       # what's currently deployed?
python scripts/promote.py set production v6     # move alias to v6
python scripts/promote.py show production       # confirm
```

After this, the model is ready to be deployed to production.

### Part D — deploy via hot reload

The service supports a `POST /admin/reload` endpoint that re-resolves the current alias and swaps the live pipeline — no uvicorn restart needed:

```powershell
Invoke-RestMethod -Method POST http://localhost:8000/admin/reload
```

The service follows the new alias target on the next request; the `assistant_info` Prometheus row should show your new version (visible in Grafana's "Current deployment" panel if you've done Task 4). Alternatively, just restart uvicorn — same effect, brief service downtime.

## Submission

Submit a `*.zip` file with:

- **`configs/v6.yaml`** — your config.
- **`promotion-log.jsonl`** — must contain a line with `"to": "v6"` and `"op": "set"`. (The file is gitignored, so grab it from the repo root after running `promote.py`.)
- Any **`prompts/*.txt`** files you created or edited for v6. Skip this if you reused existing prompts unchanged.
