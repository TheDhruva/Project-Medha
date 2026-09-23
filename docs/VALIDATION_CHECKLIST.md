# VALIDATION_CHECKLIST.md — Phase 12

Run before viva. Mark honestly.

## Backend
- [ ] `pytest tests -q`
- [ ] API / health
- [ ] CNP unit + evaluation runner
- [ ] CEG / rollback tests + evaluation runner
- [ ] Verification / critic tests
- [ ] Demo scenario regression

## Frontend
- [ ] `npx tsc --noEmit`
- [ ] `npm run lint`
- [ ] `npm run build`

## Demo (manual)
- [ ] SUCCESSFUL_DEPLOYMENT
- [ ] PORT_CONFLICT
- [ ] SECURITY_CONFLICT
- [ ] VERIFICATION_FAILURE
- [ ] PARTIAL_FAILURE (core research demo)

## Docker
- [ ] Preflight reports daemon status
- [ ] Controlled E2E if Docker available
- [ ] SKIPPED if Docker unavailable (do not claim pass)

## Evaluation
- [ ] `python -m app.evaluation.run_all`
- [ ] `/evaluation` shows artifact numbers
- [ ] No fabricated metrics in docs vs artifacts
