"""Supabase client. Service-role key bypasses RLS — server-only."""

from functools import lru_cache

from supabase import Client, create_client

from src.settings import settings


@lru_cache(maxsize=1)
def supa() -> Client:
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env")
    return create_client(settings.supabase_url, settings.supabase_service_role_key)
