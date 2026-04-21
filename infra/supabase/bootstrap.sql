-- Ligilo Supabase bootstrap
-- Ejecuta este script en el SQL Editor de Supabase.

create extension if not exists pgcrypto;

create table if not exists public.ligilo_ingestion_events (
    id uuid primary key default gen_random_uuid(),
    source text not null,
    event_type text not null,
    event_ts timestamptz not null,
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists idx_ligilo_ingestion_events_type_ts
    on public.ligilo_ingestion_events (event_type, event_ts desc);

create table if not exists public.ligilo_media_metadata (
    id uuid primary key default gen_random_uuid(),
    provider text not null,
    provider_media_id text,
    media_kind text not null check (media_kind in ('audio', 'video')),
    storage_bucket text not null,
    storage_path text not null,
    content_hash char(64) not null,
    mime_type text,
    duration_seconds numeric(10,2),
    size_bytes bigint,
    width integer,
    height integer,
    transcript_excerpt text,
    language_code varchar(8),
    captured_at timestamptz,
    created_at timestamptz not null default now(),
    constraint uq_ligilo_media_provider_media unique (provider, provider_media_id),
    constraint uq_ligilo_media_hash unique (content_hash)
);

create index if not exists idx_ligilo_media_created_at
    on public.ligilo_media_metadata (created_at desc);

create index if not exists idx_ligilo_media_kind_lang
    on public.ligilo_media_metadata (media_kind, language_code);

create table if not exists public.ligilo_safe_from_harm (
    id uuid primary key default gen_random_uuid(),
    source text not null,
    matched_terms text[] not null,
    input_excerpt text,
    blocked boolean not null default true,
    created_at timestamptz not null default now()
);

create index if not exists idx_ligilo_sfh_created_at
    on public.ligilo_safe_from_harm (created_at desc);

create index if not exists idx_ligilo_sfh_blocked
    on public.ligilo_safe_from_harm (blocked, created_at desc);
