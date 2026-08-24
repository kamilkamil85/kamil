import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import html
import time
import json
import os
from datetime import datetime, timedelta

# ──────────────────────────────────────────────
# Konfiguracja
# ──────────────────────────────────────────────

KNOWN_PLAYS_FILE = "kamil_pivot_emisje.json"
NEW_PLAYS_FILE   = "kamil_pivot_nowe_emisje.csv"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
}

st.set_page_config(page_title="Monitor emisji — Kamil Pivot", page_icon="🎵", layout="wide")

# ──────────────────────────────────────────────
# Znane emisje (bez zmian logicznych)
# ──────────────────────────────────────────────

def load_known_plays() -> set:
    if not os.path.exists(KNOWN_PLAYS_FILE):
        return set()
    with open(KNOWN_PLAYS_FILE, "r", encoding="utf-8") as f:
        return set(json.load(f))

def save_known_plays(known: set):
    with open(KNOWN_PLAYS_FILE, "w", encoding="utf-8") as f:
        json.dump(list(known), f, ensure_ascii=False, indent=2)

def make_play_key(play: dict) -> str:
    return f"{play['song_id']}|{play['date']}|{play['time']}|{play['station']}"

# ──────────────────────────────────────────────
# Scraping listy piosenek
# ──────────────────────────────────────────────

def scrape_song_list(query: str, log) -> list[dict]:
    all_songs = []
    page = 1

    while True:
        url = (f"https://www.odsluchane.eu/wyszukaj.php"
               f"?q={query.replace(' ', '+')}&page={page}")

        try:
            response = requests.get(url, headers=HEADERS, timeout=15)
            response.raise_for_status()
        except requests.RequestException as e:
            log(f"❌ Błąd strony {page}: {e}")
            break

        soup  = BeautifulSoup(response.text, "html.parser")
        links = soup.select("table.table tbody tr td a.title-link")

        if not links:
            log(f"✅ Strona {page} — brak wyników, koniec.")
            break

        for link in links:
            song_url   = link.get("href", "")
            song_title = html.unescape(link.get_text(strip=True))
            parts      = song_url.strip("/").split("/")
            song_id    = parts[1] if len(parts) >= 2 else ""

            if song_url.startswith("http"):
                full_url = song_url
            else:
                full_url = f"https://www.odsluchane.eu{song_url}"

            all_songs.append({
                "id":    song_id,
                "title": song_title,
                "url":   full_url,
            })

        log(f"📄 Strona {page}: {len(links)} piosenek")
        page += 1
        time.sleep(1)

    return all_songs

# ──────────────────────────────────────────────
# Scraping emisji z filtrem dat
# ──────────────────────────────────────────────

def scrape_song_plays(song: dict, date_from: datetime) -> list[dict]:
    try:
        response = requests.get(song["url"], headers=HEADERS, timeout=15)
        response.raise_for_status()
    except requests.RequestException:
        return []

    soup         = BeautifulSoup(response.text, "html.parser")
    plays        = []
    current_date = None
    stop         = False

    for row in soup.select("table.table tbody tr"):
        if stop:
            break

        date_cell = row.find("td", {"colspan": "2"})
        if date_cell:
            date_str = date_cell.get_text(strip=True)
            try:
                current_date = datetime.strptime(date_str, "%d-%m-%Y")
            except ValueError:
                current_date = None
                continue

            if current_date < date_from:
                stop = True
            continue

        if not current_date or stop:
            continue

        cols = row.find_all("td")
        if len(cols) < 2:
            continue

        play_time = cols[0].get_text(strip=True)
        station   = cols[1].get_text(strip=True)

        if play_time and station:
            plays.append({
                "song_id":    song["id"],
                "song_title": song["title"],
                "song_url":   song["url"],
                "date":       current_date.strftime("%d-%m-%Y"),
                "time":       play_time,
                "station":    station,
            })

    return plays

# ──────────────────────────────────────────────
# UI
# ──────────────────────────────────────────────

st.title("🎵 Monitor emisji — Kamil Pivot")
st.caption(f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}")

known_plays = load_known_plays()
st.info(f"📂 Znanych emisji w bazie: **{len(known_plays)}**")

days = st.number_input(
    "Z ilu ostatnich dni mają być emisje?",
    min_value=1, max_value=365, value=7, step=1,
)

run = st.button("🚀 Szukaj emisji", type="primary")

if run:
    date_from = datetime.now() - timedelta(days=days)
    st.success(f"Szukam emisji od {date_from.strftime('%d.%m.%Y')} do dziś "
               f"({days} {'dzień' if days == 1 else 'dni'})")

    log_box = st.expander("📜 Log przebiegu", expanded=False)
    log_lines = []

    def log(msg: str):
        log_lines.append(msg)
        log_box.write(msg)

    with st.spinner("Pobieram listę piosenek Kamila Pivota..."):
        all_songs = scrape_song_list("kamil pivot", log)

    st.write(f"📋 Łącznie piosenek: **{len(all_songs)}**")

    all_new_plays     = []
    all_current_plays = set()

    progress = st.progress(0)
    status   = st.empty()

    for i, song in enumerate(all_songs, 1):
        status.write(f"[{i}/{len(all_songs)}] {song['title']}")

        plays = scrape_song_plays(song, date_from)

        for play in plays:
            key = make_play_key(play)
            all_current_plays.add(key)
            if key not in known_plays:
                all_new_plays.append(play)

        progress.progress(i / len(all_songs))
        time.sleep(1)

    progress.empty()
    status.empty()

    st.divider()

    if not all_new_plays:
        st.success(f"✅ Brak nowych emisji z ostatnich {days} dni!")
    else:
        st.subheader(f"🆕 Nowych emisji łącznie: {len(all_new_plays)}")

        by_song = {}
        for p in all_new_plays:
            by_song.setdefault(p["song_title"], []).append(p)

        for title, plays_list in sorted(by_song.items()):
            with st.expander(f"🎵 {title} ({len(plays_list)} emisji)", expanded=True):
                df_show = pd.DataFrame(sorted(plays_list, key=lambda x: (x["date"], x["time"])))
                st.dataframe(df_show[["date", "time", "station"]], hide_index=True, use_container_width=True)

        # Zapis do CSV
        df = pd.DataFrame(all_new_plays)
        df["wykryto"] = datetime.now().strftime("%d.%m.%Y %H:%M")

        if os.path.exists(NEW_PLAYS_FILE):
            existing = pd.read_csv(NEW_PLAYS_FILE, encoding="utf-8-sig")
            df_out = pd.concat([existing, df], ignore_index=True)
        else:
            df_out = df

        df_out.to_csv(NEW_PLAYS_FILE, index=False, encoding="utf-8-sig")
        st.success(f"💾 Zapisano do: {NEW_PLAYS_FILE}")

        st.download_button(
            "⬇️ Pobierz nowe emisje (CSV)",
            data=df.to_csv(index=False, encoding="utf-8-sig"),
            file_name=f"kamil_pivot_nowe_emisje_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
        )

    # Aktualizacja bazy
    updated_known = known_plays | all_current_plays
    save_known_plays(updated_known)
    st.info(f"💾 Zaktualizowano bazę: {len(updated_known)} rekordów → {KNOWN_PLAYS_FILE}")
