# Production Hardening Checklist

Date: 2026-06-23

## Required Environment

Set these before running with `APP_ENV=production`:

```powershell
$env:APP_ENV = "production"
$env:FLASK_SECRET_KEY = "replace-with-a-long-random-secret"
$env:APP_DATABASE_PATH = "C:\path\to\app.db"
$env:MODELS_CONFIG_PATH = "C:\path\to\models.json"
$env:DEFAULT_ADMIN_USERNAME = "admin"
$env:DEFAULT_ADMIN_PASSWORD = "P@ssw0rd"
```

## Current Production Guards

The app refuses to start in production when:

- `FLASK_SECRET_KEY` is missing.
- `DEFAULT_ADMIN_PASSWORD` is blank.
- `DEFAULT_ADMIN_PASSWORD` is `admin1234`.

Per the current product requirement, `P@ssw0rd` is not blocked in production.

## Cookie Security

When production mode is enabled, the app sets:

- `SESSION_COOKIE_HTTPONLY = True`
- `SESSION_COOKIE_SAMESITE = "Lax"`
- `SESSION_COOKIE_SECURE = True`

`SESSION_COOKIE_SECURE=True` means production should be served through HTTPS.

## Recommended Operational Steps

1. Use HTTPS in production.
2. Keep `FLASK_SECRET_KEY` private and stable across restarts.
3. Back up `app.db` before deployments.
4. Protect `app.db`, `.env`, and model configuration files with OS-level permissions.
5. Run regression tests before release:

```powershell
python -m pytest tests
```

6. Review audit logs after admin account changes:

```text
/admin/audit
```

## Remaining Hardening Candidates

- Add a session inactivity timeout.
- Add audit log filters by action/user/date.
- Add optional production first-run admin setup instead of static bootstrap credentials.
- Repair remaining corrupted Korean labels/messages in all screens.


