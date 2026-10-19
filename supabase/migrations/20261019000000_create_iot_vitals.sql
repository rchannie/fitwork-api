-- Migrasi: tabel iot_vitals untuk data gelang IoT (ESP32-C3 + MAX30102).
-- Jalankan sekali di Supabase Dashboard > SQL Editor (atau `supabase db push`).
-- Aman dijalankan ulang (pakai IF NOT EXISTS / DROP POLICY IF EXISTS).
--
-- Penulisan dilakukan backend FastAPI dengan service_role key (bypass RLS).
-- User yang login (role authenticated) hanya boleh SELECT datanya sendiri;
-- tidak ada policy INSERT/UPDATE/DELETE, jadi klien tidak bisa menulis langsung.

create table if not exists public.iot_vitals (
    id          bigint generated always as identity primary key,
    user_id     uuid        not null references public.profiles (id) on delete cascade,
    device_id   text        not null,
    heart_rate  smallint    not null check (heart_rate between 30 and 220),
    spo2        smallint             check (spo2 between 70 and 100),
    recorded_at timestamptz not null default now()
);

comment on table public.iot_vitals is
    'Detak jantung & SpO2 dari gelang IoT, dikirim tiap ~15 detik lewat POST /iot/vitals';

-- Query utama: data terbaru per user (GET /iot/vitals/{user_id}/terbaru).
create index if not exists iot_vitals_user_id_recorded_at_idx
    on public.iot_vitals (user_id, recorded_at desc);

alter table public.iot_vitals enable row level security;

drop policy if exists "iot_vitals_select_own" on public.iot_vitals;
create policy "iot_vitals_select_own"
    on public.iot_vitals
    for select
    to authenticated
    using ((select auth.uid()) = user_id);
