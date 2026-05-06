create table if not exists public.donations (
  id uuid primary key default gen_random_uuid(),
  amount numeric not null check (amount > 0),
  donor_name text,
  note text,
  created_by text,
  created_at timestamptz not null default now()
);

alter table public.donations enable row level security;

drop policy if exists "Public can read donations" on public.donations;

create policy "Public can read donations"
on public.donations
for select
to anon, authenticated
using (true);

alter table public.donations
add column if not exists created_by text;

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
  created_by text,
  created_at timestamptz not null default now()
);

alter table public.large_donation_forms enable row level security;

alter table public.large_donation_forms
add column if not exists donor_type text not null default 'particulier';

alter table public.large_donation_forms
add column if not exists company_name text;

alter table public.large_donation_forms
add column if not exists contact_person text;

alter table public.large_donation_forms
add column if not exists created_by text;

create table if not exists public.admin_changelog (
  id uuid primary key default gen_random_uuid(),
  admin_name text not null,
  action text not null,
  entity_type text not null,
  entity_id text,
  details text,
  created_at timestamptz not null default now()
);

alter table public.admin_changelog enable row level security;

create table if not exists public.admin_presence (
  session_id text primary key,
  device_id text not null default gen_random_uuid()::text,
  admin_name text not null,
  admin_color text not null,
  section text not null default 'Dashboard',
  last_seen timestamptz not null default now()
);

alter table public.admin_presence enable row level security;

alter table public.admin_presence
add column if not exists device_id text not null default gen_random_uuid()::text;

alter table public.admin_presence
add column if not exists admin_color text not null default '#d9ff3f';

alter table public.admin_presence
add column if not exists section text not null default 'Dashboard';

alter table public.admin_presence
add column if not exists last_seen timestamptz not null default now();

create unique index if not exists admin_presence_device_id_key
on public.admin_presence (device_id);

create table if not exists public.contact_messages (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  email text,
  subject text,
  message text not null,
  created_at timestamptz not null default now()
);

alter table public.contact_messages enable row level security;

create table if not exists public.site_settings (
  key text primary key,
  value jsonb not null,
  updated_at timestamptz not null default now()
);

alter table public.site_settings enable row level security;

alter table public.site_settings
add column if not exists updated_at timestamptz not null default now();

create or replace function public.prevent_admin_changelog_mutation()
returns trigger
language plpgsql
as $$
begin
  raise exception 'admin_changelog is append-only';
end;
$$;

drop trigger if exists prevent_admin_changelog_update on public.admin_changelog;
create trigger prevent_admin_changelog_update
before update on public.admin_changelog
for each row execute function public.prevent_admin_changelog_mutation();

drop trigger if exists prevent_admin_changelog_delete on public.admin_changelog;
create trigger prevent_admin_changelog_delete
before delete on public.admin_changelog
for each row execute function public.prevent_admin_changelog_mutation();

insert into public.donations (amount, donor_name, note)
values (25, 'Testdonateur', 'Controle')
on conflict do nothing;
