"""Tes dashboard tanpa koneksi Supabase (klien palsu).

Jalankan dari folder dashboard/:   python -m pytest tests -q
"""
import io
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import queries  # noqa: E402
import transform as tf  # noqa: E402

DEVICE_ID = "11111111-1111-1111-1111-111111111111"
NOW = datetime.now(timezone.utc).replace(second=0, microsecond=0)


def z(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class FakeQuery:
    def __init__(self, rows):
        self.rows = list(rows)
        self._single = False

    def select(self, *_):
        return self

    def eq(self, col, val):
        self.rows = [r for r in self.rows if r.get(col) == val]
        return self

    def neq(self, col, val):
        self.rows = [r for r in self.rows if r.get(col) != val]
        return self

    def gte(self, col, val):
        self.rows = [r for r in self.rows if r[col] >= val]
        return self

    def lt(self, col, val):
        self.rows = [r for r in self.rows if r[col] < val]
        return self

    def order(self, col, desc=False):
        self.rows.sort(key=lambda r: r[col], reverse=desc)
        return self

    def range(self, a, b):
        self.rows = self.rows[a : b + 1]
        return self

    def single(self):
        self._single = True
        return self

    def execute(self):
        return SimpleNamespace(data=self.rows[0] if self._single else self.rows)


class FakeClient:
    def __init__(self, tables, usage):
        self.tables, self.usage = tables, usage
        self.reading_requests = 0

    def table(self, name):
        if name == "readings":
            self.reading_requests += 1
        return FakeQuery(self.tables[name])

    def rpc(self, name, args):
        assert name == "device_pump_usage" and args == {"p_device": DEVICE_ID}
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=[self.usage]))


def make_client(n_readings=1200):
    readings = []
    for i in range(n_readings):  # 1200 pembacaan tiap 15 menit, termasuk > 1000 baris
        ts = NOW - timedelta(minutes=15 * (n_readings - 1 - i))
        readings.append(
            {
                "device_id": DEVICE_ID,
                "ts": z(ts),
                "ph": 7.4 + (i % 7) * 0.05,
                "temp_c": 25 + (i % 5) * 0.2,
                "tds_ppm": 300 + i % 20,
                "do_mgl": None if i % 50 == 0 else 7.0 + (i % 4) * 0.1,
                "pump_acid_s": 3.0 if i % 400 == 399 else 0,
                "pump_base_s": 0,
            }
        )
    tables = {
        "devices": [
            {"id": DEVICE_ID, "name": "kolam-koi-1", "created_at": "2026-10-27T00:00:00+00:00",
             "last_seen_at": z(NOW)}
        ],
        "device_config": [
            {"device_id": DEVICE_ID, "cycle_s": 900, "ph_min": 6.5, "ph_max": 8.0, "temp_min": 20,
             "temp_max": 28, "do_min": 6.0, "tds_max": 500}
        ],
        "readings": readings,
        "alert_events": [
            {"device_id": DEVICE_ID, "created_at": z(NOW - timedelta(hours=2)), "kind": "ph_high",
             "severity": "critical", "message": "pH tinggi: 8.30 (batas 8.00)"},
            {"device_id": DEVICE_ID, "created_at": z(NOW - timedelta(hours=1)), "kind": "ph_high",
             "severity": "recovery", "message": "pH kembali normal: 7.90"},
            {"device_id": DEVICE_ID, "created_at": z(NOW - timedelta(hours=3)), "kind": "dose_acid",
             "severity": "info", "message": "Dosing asam 3.0 detik"},
        ],
        "alert_state": [
            {"device_id": DEVICE_ID, "kind": "do_low", "active": True, "since": z(NOW), "last_value": 5.2},
            {"device_id": DEVICE_ID, "kind": "ph_high", "active": False, "since": None, "last_value": 7.9},
        ],
    }
    return FakeClient(tables, {"acid_today": 6.0, "base_today": 0.0, "acid_since_refill": 9.0, "base_since_refill": 0.0})


def window():
    return z(NOW - timedelta(days=30)), z(NOW + timedelta(minutes=1))


def test_pagination_returns_all_rows():
    client = make_client(1200)
    rows = queries.get_readings(client, DEVICE_ID, *window())
    assert len(rows) == 1200
    assert client.reading_requests == 2  # 1000 + 200
    assert rows == sorted(rows, key=lambda r: r["ts"])


def test_pagination_exact_page_boundary_terminates():
    client = make_client(1000)
    assert len(queries.get_readings(client, DEVICE_ID, *window())) == 1000


def test_alarm_events_exclude_info_and_newest_first():
    client = make_client(10)
    rows = queries.get_alarm_events(client, DEVICE_ID, *window())
    assert [r["severity"] for r in rows] == ["recovery", "critical"]


def test_active_alarms_and_pump_usage():
    client = make_client(10)
    assert [a["kind"] for a in queries.get_active_alarms(client, DEVICE_ID)] == ["do_low"]
    assert queries.get_pump_usage(client, DEVICE_ID)["acid_today"] == 6.0


def test_sensor_csv_columns_and_local_time():
    client = make_client(50)
    df = tf.readings_frame(queries.get_readings(client, DEVICE_ID, *window()))
    csv = pd.read_csv(io.BytesIO(tf.sensor_csv(df)), encoding="utf-8-sig")
    assert list(csv.columns) == [
        "waktu_wib", "ph", "suhu_c", "tds_ppm", "do_mgl", "pompa_asam_detik", "pompa_basa_detik",
    ]
    assert len(csv) == 50
    first_utc = datetime.fromisoformat(client.tables["readings"][0]["ts"])
    expected = first_utc.astimezone(tf.TZ).strftime(tf.TIME_FMT)
    assert csv["waktu_wib"].iloc[0] == expected  # WIB = UTC+7
    assert csv["do_mgl"].isna().iloc[0]  # nilai kosong tetap kosong, bukan 0


def test_alarm_csv_uses_indonesian_labels():
    client = make_client(10)
    ev = tf.events_frame(queries.get_alarm_events(client, DEVICE_ID, *window()))
    csv = pd.read_csv(io.BytesIO(tf.alarm_csv(ev)), encoding="utf-8-sig")
    assert list(csv.columns) == ["waktu_wib", "jenis", "tingkat", "pesan"]
    assert set(csv["tingkat"]) == {"Kritis", "Pulih"}
    assert set(csv["jenis"]) == {"pH tinggi"}


def test_empty_data_does_not_break_csv():
    assert tf.sensor_csv(tf.readings_frame([])).decode("utf-8-sig").startswith("waktu_wib,ph,suhu_c")
    assert tf.alarm_csv(tf.events_frame([])).decode("utf-8-sig").startswith("waktu_wib,jenis")


def test_latest_value_skips_null_and_status():
    df = tf.readings_frame(
        [
            {"ts": "2026-10-27T01:00:00+00:00", "ph": 7.5, "temp_c": 25, "tds_ppm": 300, "do_mgl": 7.0,
             "pump_acid_s": 0, "pump_base_s": 0},
            {"ts": "2026-10-27T01:15:00+00:00", "ph": 7.6, "temp_c": 25, "tds_ppm": 300, "do_mgl": None,
             "pump_acid_s": 0, "pump_base_s": 0},
        ]
    )
    value, _ = tf.latest_value(df, "do_mgl")
    assert value == 7.0
    cfg = {"ph_min": 6.5, "ph_max": 8.0, "temp_min": 20, "temp_max": 28, "do_min": 6.0, "tds_max": 500}
    assert tf.value_status("ph", 8.4, cfg)[0] is False
    assert tf.value_status("do", 7.0, cfg)[0] is True
    assert tf.value_status("tds", None, cfg)[0] is None


def test_pump_events_only_when_on():
    client = make_client(1200)
    df = tf.readings_frame(queries.get_readings(client, DEVICE_ID, *window()))
    pumps = tf.pump_events(df)
    assert len(pumps) == 3 and set(pumps["jenis"]) == {"Asam"}


def run_app(client, preset=None):
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    st.cache_data.clear()  # cache antar-tes (device dan rentang sama) tidak boleh bocor
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at.session_state["client"] = client
    at.run()
    if preset:
        at.radio[0].set_value(preset).run()
    return at


def test_app_renders_with_data_and_alarm():
    at = run_app(make_client(1200), preset="30 hari")
    assert not at.exception, [e.value for e in at.exception]
    assert any("Alarm aktif" in e.value and "DO rendah" in e.value for e in at.error)
    labels = [m.label for m in at.metric]
    assert {"pH", "Suhu", "Oksigen terlarut (DO)", "TDS"} <= set(labels)
    assert any("Hari ini" in label for label in labels)


def test_app_renders_without_data():
    client = make_client(0)
    client.tables["device_config"][0]["cycle_s"] = 900
    at = run_app(client)
    assert not at.exception, [e.value for e in at.exception]
    assert any("Belum ada data" in i.value for i in at.info)


def test_app_without_devices():
    client = make_client(0)
    client.tables["devices"] = []
    at = run_app(client)
    assert not at.exception, [e.value for e in at.exception]
    assert any("Belum ada perangkat" in i.value for i in at.info)
