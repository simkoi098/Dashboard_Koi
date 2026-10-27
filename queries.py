"""Akses data Supabase untuk dashboard. Hanya membaca, dan hanya kolom yang ditampilkan."""
from __future__ import annotations

from typing import Any, Callable

PAGE = 1000  # batas baris per request di Supabase


def _all_rows(make_query: Callable[[], Any]) -> list[dict[str, Any]]:
    """Ambil semua baris dengan paginasi (satu request maksimal 1000 baris)."""
    rows: list[dict[str, Any]] = []
    start = 0
    while True:
        batch = make_query().range(start, start + PAGE - 1).execute().data or []
        rows.extend(batch)
        if len(batch) < PAGE:
            return rows
        start += PAGE


def list_devices(client) -> list[dict[str, Any]]:
    res = client.table("devices").select("id,name,last_seen_at").order("created_at").execute()
    return res.data or []


def get_config(client, device_id: str) -> dict[str, Any]:
    cols = "cycle_s,ph_min,ph_max,temp_min,temp_max,do_min,tds_max"
    return client.table("device_config").select(cols).eq("device_id", device_id).single().execute().data


def get_readings(client, device_id: str, start_iso: str, end_iso: str) -> list[dict[str, Any]]:
    cols = "ts,ph,temp_c,tds_ppm,do_mgl,pump_acid_s,pump_base_s"
    return _all_rows(
        lambda: client.table("readings")
        .select(cols)
        .eq("device_id", device_id)
        .gte("ts", start_iso)
        .lt("ts", end_iso)
        .order("ts")
    )


def get_alarm_events(client, device_id: str, start_iso: str, end_iso: str) -> list[dict[str, Any]]:
    """Riwayat alarm = semua notifikasi selain info (info = catatan dosing, sudah ada di data pompa)."""
    return _all_rows(
        lambda: client.table("alert_events")
        .select("created_at,kind,severity,message")
        .eq("device_id", device_id)
        .neq("severity", "info")
        .gte("created_at", start_iso)
        .lt("created_at", end_iso)
        .order("created_at", desc=True)
    )


def get_active_alarms(client, device_id: str) -> list[dict[str, Any]]:
    res = (
        client.table("alert_state")
        .select("kind,since,last_value")
        .eq("device_id", device_id)
        .eq("active", True)
        .execute()
    )
    return res.data or []


def get_pump_usage(client, device_id: str) -> dict[str, Any]:
    data = client.rpc("device_pump_usage", {"p_device": device_id}).execute().data
    if isinstance(data, list):
        return data[0] if data else {}
    return data or {}
