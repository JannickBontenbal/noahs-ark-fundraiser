create table if not exists public.donations (
  id uuid primary key default gen_random_uuid(),
  amount numeric not null check (amount > 0),
  donor_name text,
  note text,
  stripe_session_id text unique,
  stripe_payment_intent text,
  created_at timestamptz not null default now()
);

alter table public.donations
add column if not exists stripe_session_id text unique;

alter table public.donations
add column if not exists stripe_payment_intent text;

alter table public.donations enable row level security;

drop policy if exists "Public can read donations" on public.donations;

create policy "Public can read donations"
on public.donations
for select
to anon, authenticated
using (true);

insert into public.donations (amount, donor_name, note)
values (25, 'Testdonateur', 'Controle')
on conflict do nothing;
