# Spec: Create Login Page

## Overview
Implements the authenticated entry point for MoneySaarthi. The login page uses Supabase Auth
client-side (email/password + Google OAuth) via the `@supabase/supabase-js` CDN bundle. After
a successful client-side sign-in, the browser POSTs the Supabase `access_token` and
`refresh_token` to a lightweight FastAPI endpoint that sets an HttpOnly cookie. All subsequent
requests carry this cookie, which `app/dependencies.py:current_user` already knows how to
verify. This is Step 01 — the gate every other feature sits behind.

## Depends on
None — this is the first step and has no prerequisites.

## Architecture phase
Capture (auth is the prerequisite to any data capture).

## Routes
- `GET /` — redirect to `/dashboard` if valid cookie present, else `/login` — public
- `GET /login` — render the login/sign-up page *(already scaffolded; replace stub body)* — public
- `POST /auth/session` — receive `access_token` + `refresh_token` from browser after Supabase
  client-side sign-in; set `access_token` as an HttpOnly, SameSite=Lax cookie; return 204 — public
- `POST /auth/logout` — clear the `access_token` cookie; return redirect to `/login` — public

## Database changes
No database changes. Supabase Auth manages `auth.users` internally; `profiles` row creation
is deferred to Step 02 (onboarding).

## Pydantic models
- **Create:** `app/models/auth.py`
  - `SessionPayload(BaseModel)` — fields: `access_token: str`, `refresh_token: str`
- **Modify:** None

## Templates
- **Create:** None
- **Modify:**
  - `app/templates/login.html` — replace the `<div id="auth"></div>` stub with:
    - Branded header (logo text + tagline)
    - Email/password sign-in form (inputs + submit button)
    - Toggle to switch between Sign In and Sign Up modes
    - Google OAuth button (calls `supabase.auth.signInWithOAuth`)
    - Error message area
    - Inline `<script>` block that: initialises the Supabase JS client using
      `{{ supabase_url }}` and `{{ supabase_anon_key }}` injected from the route;
      handles form submit → calls `supabase.auth.signInWithPassword` (or
      `signUp`); on success POSTs tokens to `POST /auth/session`; redirects to
      `/dashboard`
  - `app/templates/base.html` — add a minimal nav bar with a "Sign out" button
    that calls `POST /auth/logout` (hidden via CSS when user is not authenticated,
    controlled by an `authenticated` context variable the routes pass)

## Engine / AI changes
No engine or AI changes. Authentication is purely infrastructure.

## Files to change
- `app/routers/auth.py` — add `GET /`, `POST /auth/session`, `POST /auth/logout` routes;
  update `GET /login` route to inject `supabase_url` and `supabase_anon_key` into the
  template context (anon key is safe in the browser per CLAUDE.md §B.3)
- `app/templates/login.html` — replace stub body (see Templates above)
- `app/templates/base.html` — add nav bar with sign-out affordance

## Files to create
- `app/models/auth.py` — `SessionPayload` Pydantic model

## New dependencies
No new dependencies. `supabase-py` is already in `requirements.txt`;
`@supabase/supabase-js` is loaded from CDN in the login template.

## Rules for implementation
- Use `Decimal` for all money math — never float *(not applicable here, but carry the rule)*
- Tax rules must live in `app/engine/tax/rules.py`, keyed by assessment year *(not applicable)*
- Gemini writes narrative only; it must never compute or invent a rupee figure *(not applicable)*
- After Gemini responds, run the numeric-consistency check in `app/ai/validation.py` *(not applicable)*
- RLS is enforced on every table; derive `user_id` from the Supabase JWT only — the
  `POST /auth/session` endpoint must NOT trust any `user_id` from the request body; only the
  decoded JWT inside `app/dependencies.py` is authoritative
- `service_role` key is used only in the background worker — never in templates; the anon key
  is the only key that may appear in Jinja2 context or rendered HTML
- Plotly figures are built server-side, serialized with `pio.to_json`, hydrated client-side
  with `Plotly.newPlot` — no iframes or static images *(not applicable to this step)*
- All templates extend `app/templates/base.html`
- The `access_token` cookie must be set with `httponly=True`, `samesite="lax"`,
  `secure=True` (set `secure=False` only when `DEBUG=True` / localhost)
- The `refresh_token` must NOT be stored in a cookie or any server-side state in this step;
  it stays in the browser's Supabase JS memory for silent token refresh
- Google OAuth redirect must point back to `/login` (Supabase handles the PKCE exchange
  client-side); no additional server route is needed for OAuth callback
- The `GET /` root redirect must check for the `access_token` cookie and attempt a lightweight
  JWT decode (using `current_user` dependency) — if invalid or missing, redirect to `/login`
- Do not add CSRF tokens in this step; SameSite=Lax on the cookie provides the CSRF
  protection adequate for the MVP

## Definition of done
- [ ] `GET /login` returns HTTP 200 with a rendered page that contains an email input,
      password input, and a submit button (verify with `httpx` or browser)
- [ ] Submitting valid Supabase credentials from the login form results in
      `POST /auth/session` returning HTTP 204 and setting a `Set-Cookie: access_token=...`
      response header with `HttpOnly` and `SameSite=Lax` attributes
- [ ] After the cookie is set, `GET /dashboard` (with the cookie) does not return 401
- [ ] `POST /auth/logout` clears the `access_token` cookie and redirects to `/login`
      (HTTP 302 with `Location: /login`)
- [ ] `GET /` with no cookie redirects to `/login` (HTTP 302)
- [ ] `GET /` with a valid cookie redirects to `/dashboard` (HTTP 302)
- [ ] The login page renders without JavaScript errors in the browser console
- [ ] Supabase anon key appears in the rendered HTML; `service_role` key and `jwt_secret`
      do NOT appear anywhere in rendered HTML or HTTP responses
- [ ] `tests/test_auth.py` passes: at minimum covers the `/auth/session` cookie-setting
      logic and the `/auth/logout` cookie-clearing logic using a mocked JWT
