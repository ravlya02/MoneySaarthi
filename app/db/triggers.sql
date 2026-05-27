-- MoneySaarthi database triggers.
-- Source of truth: documents/architecture.md §B.
-- Run via app/db/apply.py after schema.sql and policies.sql.

-- Auto-create a profiles row whenever a new auth.users row is inserted.
-- This fires on every Supabase sign-up (email/password, OAuth, magic link, etc.)
-- and ensures the application layer never encounters a user without a profile.
--
-- Security notes:
--   SECURITY DEFINER  — runs with the function owner's privileges so it can write
--                        to public.profiles regardless of the caller's role.
--   search_path = public — pinned to prevent search-path injection attacks.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    insert into public.profiles (id, full_name)
    values (
        new.id,
        new.raw_user_meta_data ->> 'full_name'   -- may be null; that is fine
    )
    on conflict (id) do nothing;                  -- idempotent; safe to re-run
    return new;
end;
$$;

-- Drop first so this file is idempotent when re-applied.
drop trigger if exists on_auth_user_created on auth.users;

create trigger on_auth_user_created
    after insert on auth.users
    for each row
    execute procedure public.handle_new_user();
