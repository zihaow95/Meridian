# Pilot environment runbook (non-production)

Controlled LAN pilot access for Phase 6. This is **not** a production auth
path. DingTalk remains the long-term identity direction; local password login
exists only for approved non-production pilot sessions.

## Boundaries

- Bind only an **approved company LAN address**. Do not publish to the public
  internet and do not open firewall ports from the start scripts.
- `ENABLE_PILOT_PASSWORD_LOGIN` is true in development/test settings and
  **hard-fails** if enabled under production settings.
- Frontend shows temporary login only when **both**
  `VITE_ENABLE_PILOT_PASSWORD_LOGIN=true` and
  `GET /api/v1/auth/capabilities` reports `pilot_password_login: true`.
- Every participant gets an **independent** account. Shared demo credentials
  are forbidden.

## Prerequisites

1. MySQL and Redis are up (`deploy/compose/compose.dev.yml` + `.env`).
2. Migrations applied (`uv run python manage.py migrate` from `backend/`).
3. An active operator account exists (for `--configured-by-login-key`).
4. Non-critical roles to assign already exist (critical roles stay on the
   approved assignment path).

## Provision one participant

```text
cd backend
uv run python manage.py provision_pilot_user ^
  --organization-public-id <ORG_PUBLIC_ID> ^
  --employee-no P-1001 ^
  --display-name "Pilot One" ^
  --password <unique-password> ^
  --roles PILOT_PARTICIPANT ^
  --configured-by-login-key <operator-login-key>
```

The command writes a redacted `identity.pilot_account.provision` audit event
(no password). Re-running updates the same `employee_no` without creating a
second identity.

## Start the LAN session

```text
.\scripts\start-pilot.cmd -PilotHost 192.168.x.x
```

or

```text
.\scripts\start-pilot.ps1 -PilotHost 192.168.x.x
```

The script:

- sets session `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS` for the
  LAN host;
- enables pilot password login for this process environment;
- starts Django on `127.0.0.1:8000` and Vite on the LAN host (`:5173`);
- prints the UI URL participants should open.

Vite proxies `/api` to the local Django process. Participants open the printed
LAN URL, not a public hostname.

## Login

1. Open the printed `http://<LAN-IP>:5173/login` page.
2. Confirm the UI labels the temporary form as a **非生产** path.
3. Sign in with `organization_public_id`, `employee_no`, and password.
4. Success and failure both write redacted `identity.pilot_login` audits.

## Stop / revoke

- Stop the start-pilot processes when the session ends.
- Deactivate a user (`status` not `ACTIVE`) to revoke access immediately;
  pilot login rejects inactive users.
- Do not leave `VITE_ENABLE_PILOT_PASSWORD_LOGIN=true` in shared production
  build pipelines.

## Known follow-ups

- Whether password login remains after DingTalk is production-ready is a later
  evaluation. Phase 6 does not delete the local auth code automatically.
- Real business pilot batches and feedback closure are Task 6.8 / Phase 7 GO
  startup work; this runbook only covers non-production access mechanics.
