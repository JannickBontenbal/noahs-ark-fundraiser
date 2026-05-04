create table if not exists public.donations (
  id uuid primary key default gen_random_uuid(),
  amount numeric not null check (amount > 0),
  donor_name text,
  note text,
  created_at timestamptz not null default now()
);

alter table public.donations enable row level security;

drop policy if exists "Public can read donations" on public.donations;

create policy "Public can read donations"
on public.donations
for select
to anon, authenticated
using (true);

create table if not exists public.large_donation_forms (
  id uuid primary key default gen_random_uuid(),
  donation_id uuid references public.donations(id) on delete cascade,
  donor_type text not null default 'particulier',
  company_name text,
  contact_person text,
  amount numeric not null check (amount > 0),
  donor_name text not null,
  email text,
  phone text,
  street text,
  postal_code text,
  city text,
  country text,
  description_primary text not null,
  description_secondary text,
  tax_year integer not null default 2027,
  created_at timestamptz not null default now()
);

alter table public.large_donation_forms enable row level security;

alter table public.large_donation_forms
add column if not exists donor_type text not null default 'particulier';

alter table public.large_donation_forms
add column if not exists company_name text;

alter table public.large_donation_forms
add column if not exists contact_person text;

insert into public.donations (amount, donor_name, note)
values (25, 'Testdonateur', 'Controle')
on conflict do nothing;
