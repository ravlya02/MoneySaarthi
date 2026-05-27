# Spec: Login Logout

## Overview
The login page, session cookie, and logout route were scaffolded in Step 01, but four gaps
prevent the flow from working correctly end-to-end in a browser: (1) no route passes
`authenticated=True` to templates, so the nav bar's "Sign out" button never renders;
(2) protected SSR routes raise a JSON 401 instead of redirecting to `/login` when the
session is missing or expired; (3) `GET /login` and `GET /register` don't redirect
already-authenticated users away from the auth pages; and (4) there is no post-login
redirect, so a user who lands on `/dashboard` without a session is sent to `/login` but after
signing in is always dropped at `/dashboard` regardless of where they came from. This step
closes all four gaps and adds a `?logged_out=1` message on the login page after logout, plus
a `next` parameter so deep links survive the auth redirect.

## Depends on
- **Step 01 — Create Login Page:** `/auth/session`, `/auth/logout`, `app/dependencies.py`,
  `app/models/auth.py`, `login.html`, and `base.html` must all be complete.
- **Step 03 — User Registration:** `/register` route must exist so the redirect-if-authenticated
  guard can be applied there too.

## Architecture phase
**Capture** — correct auth redirection is the prerequisite to all data-capture routes.

## Routes
- `GET /login` *(modify)* — add redirect to `/dashboard` if valid cookie present; accept
  optional `?next=<path>` and `?logged_out=1` query params — public
- `GET /register` *(modify)* — add redirect to `/dashboard` if valid cookie present — public

No new routes; all changes are to existing routes and the dependency layer.

## Database changes
No database changes.

## Pydantic models
- **Create:** None
- **Modify:** None

## Templates
- **Create:** None
- **Modify:**
  - `app/templates/login.html` — read `logged_out` and `next` from template context; show a
    "You have been signed out." banner when `logged_out` is truthy; embed `next` as a hidden
    field or JS variable so the post-login redirect uses it; style with existing `.auth-error`
    class (green-tinted variant) or a new `.auth-notice` class in `app.css`
  - `app/templates/base.html` — no structural changes; the `{% if authenticated %}` guard is
    already correct; this step ensures every protected route passes `authenticated=True`
  - `app/templates/dashboard.html` — pass `authenticated=True` (via route fix, not template
    change; listed here for clarity)
  - `app/templates/dashboard_pending.html` — same
  - `app/templates/onboarding/demographics.html` — same

## Engine / AI changes
None. This step is purely routing and session management.

## Files to change

### `app/dependencies.py`
Add an `optional_user` variant that returns `None` instead of raising on missing/invalid
token — used by `GET /login` and `GET /register` to check if user is already signed in
without triggering a 401.

Also add a **redirect dependency** `redirect_if_unauthenticated(request, settings)` that
wraps `current_user` but, instead of raising `HTTPException(401)`, returns a
`RedirectResponse("/login?next=<url>")`. SSR routes replace `Depends(current_user)` with
this dependency so expired sessions yield a redirect, not a JSON error.

```python
def optional_user(request: Request, settings: Settings = Depends(get_settings)) -> CurrentUser | None:
    """Returns CurrentUser or None — never raises. Used to check auth without enforcing it."""
    try:
        return current_user(request, settings)
    except HTTPException:
        return None
```

```python
def require_user(request: Request, settings: Settings = Depends(get_settings)) -> CurrentUser:
    """Like current_user but redirects to /login for SSR routes instead of raising 401."""
    try:
        return current_user(request, settings)
    except HTTPException:
        next_url = str(request.url.path)
        raise HTTPException(
            status_code=307,
            headers={"Location": f"/login?next={next_url}"},
        ) from None
```

> **Implementation note:** FastAPI does not natively turn `HTTPException(307)` into a
> redirect for `HTMLResponse` routes. Use `raise` + an exception handler registered on
> `app`, or simply call `RedirectResponse` directly inside the except block and return it.
> The cleanest approach for SSR routes is to return the `RedirectResponse` from the
> dependency itself — but FastAPI dependencies cannot return responses. Instead, use a
> dedicated helper:
>
> ```python
> from fastapi.responses import RedirectResponse as _RR
>
> def require_user(request: Request, settings: Settings = Depends(get_settings)) -> CurrentUser:
>     try:
>         return current_user(request, settings)
>     except HTTPException:
>         from fastapi import HTTPException as _H
>         raise _H(status_code=307, headers={"Location": f"/login?next={request.url.path}"})
> ```
>
> Then register a global exception handler in `app/main.py`:
> ```python
> @app.exception_handler(307)
> async def redirect_307(request, exc):
>     return RedirectResponse(exc.headers["Location"], status_code=302)
> ```
>
> **Simpler alternative (recommended):** replace `Depends(current_user)` with inline
> try/except inside each SSR route handler. This avoids exception-handler gymnastics.

### `app/routers/auth.py`
- `GET /login`: use `optional_user`; if authenticated, redirect to `?next` or `/dashboard`.
  Pass `logged_out=True` and `next_url` into template context.
- `GET /register`: use `optional_user`; if authenticated, redirect to `/dashboard`.
- `POST /auth/logout`: append `?logged_out=1` to the redirect URL → `/login?logged_out=1`.

### `app/routers/dashboard.py`
- `GET /dashboard`: replace `Depends(current_user)` with inline auth check; on failure
  redirect to `/login?next=/dashboard`. Pass `authenticated=True` to all
  `TemplateResponse` calls.
- `GET /jobs/{job_id}/status`: keep `Depends(current_user)` — this is a JSON endpoint,
  a 401 JSON response is correct here.

### `app/routers/onboarding.py`
- `GET /onboarding/{step}`: add inline auth check + redirect on failure + pass
  `authenticated=True`.
- `POST /onboarding/submit`: keep `Depends(current_user)` — form POSTs returning 401 are
  acceptable (browser will handle).

### `app/static/app.css`
Add `.auth-notice` style — a green-tinted information banner for non-error messages like
"You have been signed out.":
```css
.auth-notice {
  background: rgba(16, 185, 129, .15);
  border: 1px solid #6ee7b7;
  color: #6ee7b7;
  border-radius: 6px;
  padding: .6rem .9rem;
  font-size: .875rem;
  margin-bottom: 1rem;
}
```

## Files to create
No new files.

## New dependencies
No new dependencies.

## Rules for implementation
- Use `Decimal` for all money math — never float *(not applicable here)*
- Tax rules must live in `app/engine/tax/rules.py`, keyed by assessment year *(not applicable)*
- Gemini writes narrative only; it must never compute or invent a rupee figure *(not applicable)*
- After Gemini responds, run the numeric-consistency check in `app/ai/validation.py` *(not applicable)*
- RLS is enforced on every table; derive `user_id` from the Supabase JWT only — `optional_user`
  and `require_user` must still derive identity from the JWT, never from the request body
- `service_role` key is used only in the background worker — never in templates
- Plotly figures are built server-side, serialized with `pio.to_json`, hydrated client-side
  with `Plotly.newPlot` — no iframes or static images
- All templates extend `app/templates/base.html`
- The `next` parameter in `/login?next=<path>` must only accept relative paths (no scheme,
  no host) to prevent open-redirect attacks; validate with a simple `next.startswith("/")`
  check and default to `/dashboard` if invalid
- `authenticated` must be passed as `True` (boolean) — not a string — in every protected
  route's `TemplateResponse` context; a missing key evaluates as falsy (fine for public
  pages), but protected routes must be explicit
- `GET /login` and `GET /register` must redirect authenticated users **before** rendering
  any template, so valid-session users never see the auth pages
- The `?logged_out=1` flag must only trigger the "signed out" banner — it must not affect
  any server-side state or be persisted anywhere

## Definition of done
- [ ] After sign-in, the nav bar shows the "Sign out" button on both `/dashboard` and
      `/onboarding/demographics` (visible in browser; verify by inspecting rendered HTML
      for `<nav class="site-nav">`)
- [ ] `GET /dashboard` with no cookie redirects to `/login?next=/dashboard` (HTTP 302)
- [ ] `GET /onboarding/demographics` with no cookie redirects to
      `/login?next=/onboarding/demographics` (HTTP 302)
- [ ] After signing in when `?next=/onboarding/demographics` is present, the browser lands
      on `/onboarding/demographics` (not `/dashboard`)
- [ ] `GET /login` with a valid cookie redirects to `/dashboard` (HTTP 302)
- [ ] `GET /register` with a valid cookie redirects to `/dashboard` (HTTP 302)
- [ ] After `POST /auth/logout` the browser shows the login page with a "You have been
      signed out." notice (green banner, not an error)
- [ ] `GET /jobs/{job_id}/status` with no cookie still returns JSON `{"detail": "..."}` with
      HTTP 401 (not a redirect — this is a JSON API endpoint)
- [ ] `tests/test_login_logout.py` passes: covers (a) dashboard redirects to login without
      cookie, (b) login redirects to dashboard with valid cookie, (c) logout appends
      `?logged_out=1`, (d) `?next=` param is respected post-login, (e) open-redirect
      rejected (invalid `next` falls back to `/dashboard`)
