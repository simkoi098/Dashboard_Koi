"""Dashboard monitoring kolam koi (Streamlit). Hanya membaca dari Supabase."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import altair as alt
import pandas as pd
import streamlit as st

import queries
import transform as tf

st.set_page_config(page_title="Monitoring Kolam Koi", page_icon="🐟", layout="wide")

PRESET_HOURS = {"24 jam": 24, "3 hari": 72, "7 hari": 168, "30 hari": 720}
CUSTOM = "Pilih tanggal"


@st.cache_resource
def make_client():
    from supabase import create_client

    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_SERVICE_KEY"])


def get_client():
    # session_state["client"] dipakai oleh tes; di produksi selalu lewat make_client()
    return st.session_state.get("client") or make_client()


@st.cache_data(ttl=55, show_spinner=False)
def load_devices(_client):
    return queries.list_devices(_client)


@st.cache_data(ttl=55, show_spinner=False)
def load(_client, device_id: str, start_iso: str, end_iso: str):
    return {
        "config": queries.get_config(_client, device_id),
        "readings": queries.get_readings(_client, device_id, start_iso, end_iso),
        "events": queries.get_alarm_events(_client, device_id, start_iso, end_iso),
        "active": queries.get_active_alarms(_client, device_id),
        "pump": queries.get_pump_usage(_client, device_id),
    }


def resolve_range(preset: str, picked) -> tuple[datetime, datetime]:
    if preset in PRESET_HOURS:
        end = datetime.now(tf.TZ).replace(second=0, microsecond=0) + timedelta(minutes=1)
        return end - timedelta(hours=PRESET_HOURS[preset]), end
    if isinstance(picked, (tuple, list)) and len(picked) == 2:
        start_d, end_d = picked
    else:  # pengguna baru memilih satu tanggal
        start_d = end_d = picked[0] if isinstance(picked, (tuple, list)) else picked
    return (
        datetime.combine(start_d, time.min, tf.TZ),
        datetime.combine(end_d + timedelta(days=1), time.min, tf.TZ),
    )


def iso_utc(dt: datetime) -> str:
    # bentuk ...Z (bukan +00:00): tanda '+' di URL bisa terbaca sebagai spasi
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def line_chart(df: pd.DataFrame, col: str, title: str, unit: str, lo=None, hi=None) -> alt.Chart:
    data = df[["ts", col]].dropna()
    base = (
        alt.Chart(data)
        .mark_line(point=alt.OverlayMarkDef(size=16))
        .encode(
            x=alt.X("ts:T", title=None),
            y=alt.Y(f"{col}:Q", title=unit, scale=alt.Scale(zero=False)),
            tooltip=[
                alt.Tooltip("ts:T", title="Waktu", format="%d %b %H:%M"),
                alt.Tooltip(f"{col}:Q", title=title, format=".2f"),
            ],
        )
    )
    rules = [
        alt.Chart(pd.DataFrame({"y": [v]})).mark_rule(strokeDash=[5, 4], color="#d62728").encode(y="y:Q")
        for v in (lo, hi)
        if v is not None
    ]
    return alt.layer(base, *rules).properties(height=230, width="container", title=title)


def metric_card(col, label: str, param: str, value, unit: str, cfg: dict, digits: int) -> None:
    ok, limit_text = tf.value_status(param, value, cfg)
    with col:
        st.metric(label, "—" if value is None else f"{value:.{digits}f} {unit}".strip())
        if ok is None:
            st.caption(f"Belum ada data · {limit_text}")
        elif ok:
            st.markdown(f":green[Normal] · {limit_text}")
        else:
            st.markdown(f":red[**Di luar batas**] · {limit_text}")


def render(client, device: dict, start: datetime, end: datetime) -> None:
    data = load(client, device["id"], iso_utc(start), iso_utc(end))
    cfg = data["config"]
    df = tf.readings_frame(data["readings"])
    ev = tf.events_frame(data["events"])

    # --- status ---
    last_seen = pd.to_datetime(device.get("last_seen_at"), utc=True) if device.get("last_seen_at") else None
    if last_seen is not None:
        silent_min = (datetime.now(timezone.utc) - last_seen.to_pydatetime()).total_seconds() / 60
        stamp = last_seen.tz_convert(tf.TZ).strftime("%d %b %Y %H:%M")
        late = silent_min > cfg["cycle_s"] / 60 * 2.5
        text = f"Data terakhir masuk: {stamp} WIB ({silent_min:.0f} menit lalu)"
        (st.warning if late else st.caption)(text)
    else:
        st.caption("Belum ada data dari perangkat ini.")

    if data["active"]:
        names = ", ".join(tf.kind_label(a["kind"]) for a in data["active"])
        st.error(f"Alarm aktif: {names}")
    else:
        st.success("Tidak ada alarm aktif")

    # --- nilai terbaru ---
    cols = st.columns(4)
    ph, _ = tf.latest_value(df, "ph")
    temp, _ = tf.latest_value(df, "temp_c")
    do, _ = tf.latest_value(df, "do_mgl")
    tds, _ = tf.latest_value(df, "tds_ppm")
    metric_card(cols[0], "pH", "ph", ph, "", cfg, 2)
    metric_card(cols[1], "Suhu", "temp", temp, "°C", cfg, 1)
    metric_card(cols[2], "Oksigen terlarut (DO)", "do", do, "mg/L", cfg, 2)
    metric_card(cols[3], "TDS", "tds", tds, "ppm", cfg, 0)

    if df.empty:
        st.info("Belum ada data pada rentang waktu ini.")
        return

    # --- grafik sensor ---
    c1, c2 = st.columns(2)
    c1.altair_chart(line_chart(df, "ph", "pH", "pH", cfg["ph_min"], cfg["ph_max"]))
    c2.altair_chart(line_chart(df, "temp_c", "Suhu", "°C", cfg["temp_min"], cfg["temp_max"]))
    c3, c4 = st.columns(2)
    c3.altair_chart(line_chart(df, "do_mgl", "Oksigen terlarut (DO)", "mg/L", cfg["do_min"], None))
    c4.altair_chart(line_chart(df, "tds_ppm", "TDS", "ppm", None, cfg["tds_max"]))
    st.caption("Garis merah putus-putus = batas alarm.")

    # --- pompa ---
    st.subheader("Pompa koreksi pH")
    usage = data["pump"]
    p1, p2, p3 = st.columns(3)
    p1.metric("Hari ini · pompa asam", f"{usage.get('acid_today', 0):.0f} detik")
    p2.metric("Hari ini · pompa basa", f"{usage.get('base_today', 0):.0f} detik")
    p3.metric("Total di rentang ini", f"{df['pump_acid_s'].sum() + df['pump_base_s'].sum():.0f} detik")
    pumps = tf.pump_events(df)
    if pumps.empty:
        st.info("Pompa tidak menyala pada rentang waktu ini.")
    else:
        bars = (
            alt.Chart(pumps)
            .mark_bar(size=6)
            .encode(
                x=alt.X("ts:T", title=None),
                y=alt.Y("detik:Q", title="detik menyala"),
                color=alt.Color("jenis:N", title="Pompa"),
                tooltip=[
                    alt.Tooltip("ts:T", title="Waktu", format="%d %b %H:%M"),
                    alt.Tooltip("jenis:N", title="Pompa"),
                    alt.Tooltip("detik:Q", title="Detik", format=".1f"),
                ],
            )
            .properties(height=180, width="container")
        )
        st.altair_chart(bars)

    # --- alarm ---
    st.subheader("Riwayat alarm")
    if ev.empty:
        st.info("Tidak ada alarm pada rentang waktu ini.")
    else:
        shown = pd.DataFrame(
            {
                "Waktu (WIB)": ev["created_at"].dt.strftime("%d %b %Y %H:%M"),
                "Jenis": ev["jenis"],
                "Tingkat": ev["severity"].map(tf.SEVERITY_LABELS).fillna(ev["severity"]),
                "Pesan": ev["message"],
            }
        )
        st.dataframe(shown, hide_index=True)

    # --- unduh ---
    st.subheader("Unduh data")
    stamp = f"{start.strftime('%Y%m%d')}-{(end - timedelta(minutes=1)).strftime('%Y%m%d')}"
    d1, d2 = st.columns(2)
    d1.download_button(
        "Data sensor + pompa (CSV)",
        tf.sensor_csv(df),
        file_name=f"kolam-koi-sensor-{stamp}.csv",
        mime="text/csv",
    )
    d2.download_button(
        "Riwayat alarm (CSV)",
        tf.alarm_csv(ev),
        file_name=f"kolam-koi-alarm-{stamp}.csv",
        mime="text/csv",
    )


def main() -> None:
    client = get_client()
    devices = load_devices(client)
    st.title("🐟 Monitoring Kolam Koi")
    if not devices:
        st.info("Belum ada perangkat terdaftar.")
        return

    with st.sidebar:
        st.header("Tampilan")
        device = devices[0]
        if len(devices) > 1:
            name = st.selectbox("Perangkat", [d["name"] for d in devices])
            device = next(d for d in devices if d["name"] == name)
        else:
            st.caption(f"Perangkat: **{device['name']}**")
        preset = st.radio("Rentang waktu", [*PRESET_HOURS, CUSTOM], index=0)
        picked = None
        if preset == CUSTOM:
            today = datetime.now(tf.TZ).date()
            picked = st.date_input("Tanggal", value=(today - timedelta(days=6), today), max_value=today)
        auto = st.toggle("Perbarui otomatis tiap menit", value=True)

    start, end = resolve_range(preset, picked)
    st.fragment(run_every=60 if auto else None)(render)(client, device, start, end)


main()
