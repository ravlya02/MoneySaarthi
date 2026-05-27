# Spec: User Registration

## Overview
Completes the new-user journey for MoneySaarthi. The login page (Step 01) already contains
a sign-up mode toggle, but it is insufficient for production: it collects only email and
password, never passes `full_name` metadata to Supabase, and has no dedicated confirmation
screen. This step introduces a dedicated `/register` page that collects **full name + email +
password + confirm-password**, passes `full_name` in `signUp` metadata so the
`on_auth_user_created` trigger (Step 02) can immediately populate `profiles.full_name`, and
adds an `/register/confirm` holding page for users awaiting email verification. On successful
sign-in after confirmation the user is routed to `/onboarding/demographics` (first step of
data capture) instead of the dashboard, since new users have no report yet. The login page is
updated to point to `/register` instead of the inline toggle.

## Depends on
- **Step 01 — Create Login Page:** `/auth/session`, `/auth/logout`, `app/dependencies.py`,
  `app/models/auth.py`, and `base.html` must all be complete.
- **Step 02 — Create Database Setup:** The `on_auth_user_created` trigger must be applied to
  Supabase so `profiles` rows are auto-created; the full RLS policy set must be in place.

## Architecture phase
**Capture** — registration is the prerequisite to Phase 1 (form capture); a user must exist
and have a valid session before the onboarding form can start.

## Routes
- `GET /register` — render the registration page — public
- `GET /register/confirm` — render email-confirmation holding page — public
- `POST /auth/session` — already exists (Step 01); reused unchanged — public

No changes to existing routes beyond updating the login page link.

## Database changes
No new tables or columns. The `profiles` table already has `full_name` and `household_name`
columns (Step 02). The `on_auth_user_created` trigger already populates `profiles.full_name`
from `raw_user_meta_data ->> 'full_name'` — this step ensures the front-end actually passes
that metadata during `signUp`.

## Pydantic models
- **Create:** None
- **Modify:** None — registration is purely a front-end + routing concern; no new server-side
  models are needed.

## Templates
- **Create:**
  - `app/templates/register.html` — dedicated registration page (see below)
  - `app/templates/register_confirm.html` — email-confirmation holding page (see below)
- **Modify:**
  - `app/templates/login.html` — replace inline sign-up toggle with a plain link:
    `Don't have an account? <a href="/register">Create one</a>`. Remove the `mode` JS toggle,
    `signUp` call, and related DOM updates. Keep sign-in only.
  - `app/templates/base.html` — no structural changes; confirm `{% block scripts %}` is present.

### `register.html` content
- Extends `base.html`
- Title: `Create account — MoneySaarthi`
- Brand panel identical to `login.html` (reuse `.login-brand` styles)
- Form fields (all required):
  - **Full name** — `type="text"`, `id="full-name"`, placeholder "Your full name",
    `autocomplete="name"`
  - **Email** — `type="email"`, `id="email"`, `autocomplete="email"`
  - **Password** — `type="password"`, `id="password"`, `autocomplete="new-password"`,
    minimum 8 characters enforced client-side
  - **Confirm password** — `type="password"`, `id="confirm-password"`,
    `autocomplete="new-password"`
- Inline error area `#auth-error` (hidden by default)
- Submit button `CREATE ACCOUNT` with loading spinner
- Footer link: `Already have an account? <a href="/login">Sign In</a>`
- `{% block scripts %}` with Supabase JS CDN and inline script:
  - Initialise `_sb` from `{{ supabase_url }}` / `{{ supabase_anon_key }}`
  - On submit: validate passwords match and length ≥ 8 client-side before any network call
  - Call `_sb.auth.signUp({ email, password, options: { data: { full_name } } })`
  - If `error` → show in `#auth-error`
  - If `data.session` is non-null (email confirmation disabled in Supabase project) →
    POST tokens to `/auth/session` → redirect to `/onboarding/demographics`
  - If `data.session` is null (email confirmation required) →
    redirect to `/register/confirm`

### `register_confirm.html` content
- Extends `base.html`
- Title: `Confirm your email — MoneySaarthi`
- Simple centred card:
  - Heading: "Check your inbox"
  - Body text: "We've sent a confirmation link to your email address. Click the link to
    activate your account, then return here to sign in."
  - Button / link: `Go to Sign In` → `href="/login"`
- No Supabase JS required on this page.

## Engine / AI changes
None. Registration is pure infrastructure; the deterministic engine and AI subsystem are
untouched.

## Files to change
- `app/routers/auth.py` — add `GET /register` and `GET /register/confirm` routes:
  ```python
  @router.get("/register", response_class=HTMLResponse)
  async def register_page(request: Request, settings: Settings = Depends(get_settings)):
      return templates.TemplateResponse(request=request, name="register.html", context={
          "supabase_url": settings.supabase_url,
          "supabase_anon_key": settings.supabase_anon_key,
      })

  @router.get("/register/confirm", response_class=HTMLResponse)
  async def register_confirm(request: Request):
      return templates.TemplateResponse(request=request, name="register_confirm.html")
  ```
- `app/templates/login.html` — replace inline sign-up toggle with a link to `/register`;
  remove `mode`, `signUp`, toggle JS logic.

## Files to create
- `app/templates/register.html` — registration form (spec above)
- `app/templates/register_confirm.html` — email confirmation holding page (spec above)

## New dependencies
No new dependencies. `@supabase/supabase-js` is already loaded from CDN in `login.html` and
will be loaded from CDN in `register.html` the same way.

## Rules for implementation
- Use `Decimal` for all money math — never float *(not applicable here)*
- Tax rules must live in `app/engine/tax/rules.py`, keyed by assessment year *(not applicable)*
- Gemini writes narrative only; it must never compute or invent a rupee figure *(not applicable)*
- After Gemini responds, run the numeric-consistency check in `app/ai/validation.py` *(not applicable)*
- RLS is enforced on every table; derive `user_id` from the Supabase JWT only — registration
  creates the Supabase `auth.users` row client-side; the server never receives the raw
  password and never stores it
- `service_role` key is used only in the background worker — never in templates; only the
  **anon key** may appear in rendered HTML
- Plotly figures are built server-side, serialized with `pio.to_json`, hydrated client-side
  with `Plotly.newPlot` *(not applicable)*
- All templates extend `app/templates/base.html`
- Client-side password validation (match + min-length 8) must run **before** any Supabase
  call to avoid consuming a sign-up attempt on an obviously bad input
- The `full_name` field must be passed as `options.data.full_name` in `supabase.auth.signUp()`
  so the `on_auth_user_created` trigger can populate `profiles.full_name` from
  `raw_user_meta_data`; if this metadata is absent the trigger falls back to `NULL` (acceptable)
- After a successful sign-up **with** a session (email confirmation disabled), redirect to
  `/onboarding/demographics` — **not** `/dashboard` — because a new user has no report yet
- After a successful sign-up **without** a session (email confirmation required), redirect to
  `/register/confirm` — do not show a raw "check email" message inside the registration form
- The confirm page is a static SSR page; it must not contain any Supabase JS or tokens
- Do not implement password reset or OAuth in this step; those are separate features

## Definition of done
- [ ] `GET /register` returns HTTP 200 with a page that contains inputs for full name, email,
      password, and confirm-password (verify with `httpx` or browser)
- [ ] Submitting mismatched passwords shows a client-side error without making any network
      request to Supabase (verify via browser dev tools — no outbound call on mismatch)
- [ ] Submitting a password shorter than 8 characters shows a client-side error without a
      network request
- [ ] Registering a new valid email/password calls `supabase.auth.signUp` with
      `options.data.full_name` set to the value entered in the full-name field (verify by
      checking the `profiles` row in Supabase after sign-up: `full_name` must not be NULL)
- [ ] After sign-up with email confirmation disabled (Supabase setting): tokens are POSTed to
      `/auth/session`, cookie is set, and browser is redirected to `/onboarding/demographics`
- [ ] After sign-up with email confirmation enabled: browser is redirected to
      `/register/confirm` (HTTP 302 or JS `location.href`)
- [ ] `GET /register/confirm` returns HTTP 200 with the holding page and a link back to `/login`
- [ ] `GET /login` no longer shows the sign-up toggle; it contains a plain link to `/register`
- [ ] `GET /register` and `GET /register/confirm` do not expose `supabase_service_role_key`
      or `supabase_jwt_secret` in their HTML responses
- [ ] The `on_auth_user_created` trigger populates `profiles.full_name` from the value passed
      during sign-up (verifiable in Supabase Table Editor)
- [ ] All new templates pass W3C HTML validation with no errors (run via browser or
      `html5validator` CLI)
- [ ] `tests/test_registration.py` passes: covers (a) `GET /register` returns 200,
      (b) `GET /register/confirm` returns 200, (c) anon key appears in `/register` HTML,
      (d) service_role key does NOT appear in `/register` HTML
