# Phase 7 post-GO pilot startup checklist

Use this after Phase 6 GO and Phase 7 productionization GO. Phase 6 only
proved the software loop with **INTERNAL_ACCEPTANCE** data; it does **not**
mark a real business pilot complete.

## 1. Accounts

- [ ] Provision one independent temporary account per participant
      (`provision_pilot_user`); no shared credentials.
- [ ] Grant only non-critical business roles needed for the participant’s
      domain; critical roles stay on the approved assignment path.
- [ ] Confirm stop/deactivate path: inactive users cannot pilot-login.
- [ ] Confirm login audits are redacted (no passwords/hashes/cookies).

## 2. People and R/A

Default shape (editable per batch — do not hard-code in software):

| Seat | Count | Notes |
|---|---|---|
| Product director (acceptance A) | 1 | Owns GO/NO-GO for the pilot window |
| Product managers | 2 | One collects and triages feedback |
| R&D | 1 | Handles fixes |
| Quality / compliance | 1 | Retest and evidence |
| Packaging / design | 1 | Domain validation |
| Sales / channel | 1 | Domain validation |
| System admin | 1 | Accounts/config/environment only — **not** business acceptance |

- [ ] Record feedback **R** (handler) and **A** (acceptor) by name for the batch.
- [ ] System admin is not granted `pilot.feedback.read` on sensitive evidence
      unless separately authorized.

## 3. Cycle and data scope

- [ ] Create a `BUSINESS_PILOT` batch only after Phase 7 GO (Phase 6 APIs reject
      creating business purpose batches).
- [ ] Set planned participant count and duration (defaults ~8 / ~14 days are
      starting points, not fixed rules).
- [ ] Write `data_scope_note`: which products, files, and flows are in scope.
- [ ] Write `known_limits_note` and `stop_conditions_note` before start.
- [ ] Start the batch to freeze the participant/config snapshot.

## 4. Feedback governance

- [ ] P0/P1 must be zero before batch completion.
- [ ] P2 leftovers require workaround, owner, target version, and written
      acceptor note.
- [ ] P3 may move to a follow-up list.
- [ ] Evidence attachments are authorized controlled document versions only;
      summaries must not copy sensitive product body.

## 5. Environment

- [ ] LAN-only access via approved host; follow
      `docs/operations/pilot-environment-runbook.md`.
- [ ] Do not enable `ENABLE_PILOT_PASSWORD_LOGIN` in production without a
      formal decision.
- [ ] Confirm `ENABLE_PILOT_API` is intentionally on for the pilot window.

## 6. Stop conditions (examples)

- Unresolved P0 in production-affecting path
- Evidence of credential sharing
- Unauthorized public exposure of the pilot host
- Scope creep into live customer transactions without approval
