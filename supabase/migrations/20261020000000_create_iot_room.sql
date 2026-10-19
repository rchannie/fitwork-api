-- Migrasi: tabel iot_room untuk unit sensor ruangan (Wemos D1 Mini: DHT11 + MQ135).
-- Jalankan sekali di Supabase Dashboard > SQL Editor (atau `supabase db push`).
-- Aman dijalankan ulang (IF NOT EXISTS / DROP POLICY IF EXISTS).
--
-- suhu_dummy = true berarti suhu & kelembapan pada baris itu adalah data
-- SIMULASI dari firmware (sensor DHT gagal dibaca), bukan hasil ukur.
-- Penulisan dilakukan backend FastAPI dengan service_role key (bypass RLS);
-- user yang login hanya boleh SELECT datanya sendiri.

create table if not exists public.iot_room (
    id          bigint generated always as identity primary key,
    user_id     uuid        not null references public.profiles (id) on delete cascade,
    device_id   text        not null,
    suhu        real                 check (suhu between -20 and 70),
    kelembapan  real                 check (kelembapan between 0 and 100),
    suhu_dummy  boolean     not null default false,
    gas_adc     smallint             check (gas_adc between 0 and 1023),
    gas_ppm     real                 check (gas_ppm >= 0),
    recorded_at timestamptz not null default now()
);

-- Bila tabel sudah ada dari sebelumnya tanpa kolom suhu_dummy, tambahkan.
alter table public.iot_room
    add column if not exists suhu_dummy boolean not null default false;

comment on table public.iot_room is
    'Data unit ruangan (suhu, kelembapan, MQ135) dari POST /iot/room, tiap ~30 detik';
comment on column public.iot_room.suhu_dummy is
    'true = suhu & kelembapan hasil simulasi firmware karena sensor DHT gagal dibaca';

create index if not exists iot_room_user_id_recorded_at_idx
    on public.iot_room (user_id, recorded_at desc);

alter table public.iot_room enable row level security;

drop policy if exists "iot_room_select_own" on public.iot_room;
create policy "iot_room_select_own"
    on public.iot_room
    for select
    to authenticated
    using ((select auth.uid()) = user_id);

-- Supaya PostgREST (API Supabase) langsung mengenali tabel/kolom baru.
notify pgrst, 'reload schema';
