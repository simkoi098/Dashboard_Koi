"""Pengolahan data untuk tampilan dan CSV (tanpa Streamlit, supaya mudah diuji)."""
from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

TZ = ZoneInfo("Asia/Jakarta")
TIME_FMT = "%Y-%m-%d %H:%M:%S"

READING_COLS = ["ts", "ph", "temp_c", "tds_ppm", "do_mgl", "pump_acid_s", "pump_base_s"]
EVENT_COLS = ["created_at", "kind", "severity", "message"]

KIND_LABELS = {
    "ph_low": "pH rendah",
    "ph_high": "pH tinggi",
    "temp_low": "Suhu rendah",
    "temp_high": "Suhu tinggi",
    "do_low": "DO rendah",
    "tds_high": "TDS tinggi",
    "batt_low": "Baterai rendah",
    "fault_ph": "Sensor pH bermasalah",
    "fault_temp": "Sensor suhu bermasalah",
    "fault_tds": "Sensor TDS bermasalah",
    "fault_do": "Sensor DO bermasalah",
    "reservoir_acid_low": "Larutan asam hampir habis",
    "reservoir_base_low": "Larutan basa hampir habis",
    "dose_limit_acid": "Batas dosis asam tercapai",
    "dose_limit_base": "Batas dosis basa tercapai",
    "offline": "Perangkat offline",
}

SEVERITY_LABELS = {"warning": "Peringatan", "critical": "Kritis", "recovery": "Pulih"}


def kind_label(kind: str) -> str:
    return KIND_LABELS.get(kind, kind)


def _to_local(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, format="ISO8601").dt.tz_convert(TZ)


def readings_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=READING_COLS)
    if df.empty:
        return df
    df["ts"] = _to_local(df["ts"])
    for col in READING_COLS[1:]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.sort_values("ts").reset_index(drop=True)


def events_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=EVENT_COLS)
    if df.empty:
        df["jenis"] = pd.Series(dtype=str)
        return df
    df["created_at"] = _to_local(df["created_at"])
    df["jenis"] = df["kind"].map(kind_label)
    return df


def latest_value(df: pd.DataFrame, col: str):
    """Nilai non-null terakhir dan waktunya (sensor yang gagal di siklus terakhir tidak mengosongkan kartu)."""
    if df.empty:
        return None, None
    s = df[col].dropna()
    if s.empty:
        return None, None
    idx = s.index[-1]
    return float(s.loc[idx]), df.loc[idx, "ts"]


def value_status(param: str, value: float | None, cfg: dict[str, Any]) -> tuple[bool | None, str]:
    """(normal?, teks batas). normal=None kalau belum ada nilai."""
    limits = {
        "ph": (cfg.get("ph_min"), cfg.get("ph_max"), "{:.1f}"),
        "temp": (cfg.get("temp_min"), cfg.get("temp_max"), "{:.0f}"),
        "do": (cfg.get("do_min"), None, "{:.1f}"),
        "tds": (None, cfg.get("tds_max"), "{:.0f}"),
    }
    lo, hi, fmt = limits[param]
    if lo is not None and hi is not None:
        text = f"batas {fmt.format(lo)}–{fmt.format(hi)}"
    elif lo is not None:
        text = f"minimal {fmt.format(lo)}"
    else:
        text = f"maksimal {fmt.format(hi)}"
    if value is None:
        return None, text
    ok = (lo is None or value >= lo) and (hi is None or value <= hi)
    return ok, text


def sensor_csv(df: pd.DataFrame) -> bytes:
    """CSV data sensor + pompa. UTF-8 dengan BOM supaya terbuka benar di Excel."""
    if df.empty:
        out = pd.DataFrame(
            columns=["waktu_wib", "ph", "suhu_c", "tds_ppm", "do_mgl", "pompa_asam_detik", "pompa_basa_detik"]
        )
    else:
        out = pd.DataFrame(
            {
                "waktu_wib": df["ts"].dt.strftime(TIME_FMT),
                "ph": df["ph"],
                "suhu_c": df["temp_c"],
                "tds_ppm": df["tds_ppm"],
                "do_mgl": df["do_mgl"],
                "pompa_asam_detik": df["pump_acid_s"],
                "pompa_basa_detik": df["pump_base_s"],
            }
        )
    return out.to_csv(index=False).encode("utf-8-sig")


def alarm_csv(ev: pd.DataFrame) -> bytes:
    if ev.empty:
        out = pd.DataFrame(columns=["waktu_wib", "jenis", "tingkat", "pesan"])
    else:
        out = pd.DataFrame(
            {
                "waktu_wib": ev["created_at"].dt.strftime(TIME_FMT),
                "jenis": ev["jenis"],
                "tingkat": ev["severity"].map(SEVERITY_LABELS).fillna(ev["severity"]),
                "pesan": ev["message"],
            }
        )
    return out.to_csv(index=False).encode("utf-8-sig")


def pump_events(df: pd.DataFrame) -> pd.DataFrame:
    """Baris panjang (ts, jenis, detik) hanya untuk saat pompa menyala, untuk grafik batang."""
    if df.empty:
        return pd.DataFrame(columns=["ts", "jenis", "detik"])
    parts = []
    for col, name in (("pump_acid_s", "Asam"), ("pump_base_s", "Basa")):
        sub = df.loc[df[col] > 0, ["ts", col]].rename(columns={col: "detik"})
        sub["jenis"] = name
        parts.append(sub)
    return pd.concat(parts, ignore_index=True)
