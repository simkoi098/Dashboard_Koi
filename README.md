# Dashboard Kolam Koi (Streamlit)
## Jalan lokal

```
cd dashboard
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # isi URL dan kunci
streamlit run app.py
```
## Tes

```
cd dashboard
python -m pytest tests -q
```
