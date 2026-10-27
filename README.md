# Dashboard Kolam Koi (Streamlit)

Hanya membaca dari Supabase, tanpa password. Isi: nilai terbaru pH, suhu, DO, TDS (dengan status terhadap batas alarm),
alarm aktif, grafik 4 sensor, pemakaian pompa asam/basa, riwayat alarm, dan unduhan CSV
(data sensor + pompa, dan riwayat alarm). Rentang waktu: 24 jam, 3 hari, 7 hari, 30 hari, atau pilih tanggal.
Halaman memuat ulang otomatis tiap menit (bisa dimatikan di sidebar).

## Jalan lokal

```
cd dashboard
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # isi URL dan kunci
streamlit run app.py
```

## Deploy ke Streamlit Community Cloud

1. Push folder proyek ke repo GitHub (pastikan `.streamlit/secrets.toml` TIDAK ikut; cukup file `.example`).
2. share.streamlit.io → New app → pilih repo → **Main file path: `dashboard/app.py`**.
3. Advanced settings → Secrets, tempel isi `secrets.toml.example` dengan nilai asli:
   - `SUPABASE_URL`: `https://<project-ref>.supabase.co`
   - `SUPABASE_SERVICE_KEY`: kunci `service_role` (atau *secret key*) dari Supabase → Project Settings → API Keys.
     Kunci ini hanya dipakai di server Streamlit dan tidak dikirim ke browser. Kalau satu jenis kunci ditolak, coba yang lain.

Karena dashboard tanpa password, siapa pun yang punya link bisa melihat datanya. Kodenya hanya menjalankan query baca
dengan kolom yang tetap, tanpa input pengguna ke database.

## Tes

```
cd dashboard
python -m pytest tests -q
```
Tes memakai klien Supabase palsu (termasuk 1200 baris untuk menguji paginasi dan render halaman).
