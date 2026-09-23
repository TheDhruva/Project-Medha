# docs/evaluation

Phase 11 evaluation harness is implemented.

See root **`EVALUATION.md`** for experiment design, metrics, baselines, reproducibility commands, and measured results.

Runners:

```bash
cd backend
.venv\Scripts\python.exe -m app.evaluation.run_cnp
.venv\Scripts\python.exe -m app.evaluation.run_ceg
.venv\Scripts\python.exe -m app.evaluation.run_all
```

Do not invent evaluation results. Artifacts land in `backend/data/evaluation/`.
