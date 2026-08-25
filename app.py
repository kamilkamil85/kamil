import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import html
import re
import time
import json
import os
from datetime import datetime, timedelta

# ──────────────────────────────────────────────
# Konfiguracja
# ──────────────────────────────────────────────

KNOWN_PLAYS_FILE = "kamil_pivot_emisje.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
}

st.set_page_config(page_title="Monitor emisji — Kamil Pivot", page_icon="🎵", layout="wide")

# ──────────────────────────────────────────────
# Normalizacja tytułów (dedup "Kamil Pivot" vs "Pivot Kamil" itp.)
# ──────────────────────────────────────────────

def normalize_title(title: str) -> str:
    """
    Zamienia tytuł na formę kanoniczną, niewrażliwą na:
    - kolejność 'Artysta - Tytuł' vs 'Tytuł - Artysta'
    - kolejność słów w nazwie, np. 'Kamil Pivot' vs 'Pivot Kamil'
    """
    title = html.unescape(title).strip().lower()
    segments = [s.strip() for s in title.split(" - ")]

    normalized_segments = []
    for seg in segments:
        words = re.findall(r"[a-ząćęłńóśźż0-9]+", seg)
        normalized_segments.append(" ".join(sorted(words)))

    normalized_segments.sort()
    return " | ".join(normalized_segments)

def make_play_key(canonical: str, date: str, time_: str, station: str) -> str:
    return f"{canonical}|{date}|{time_}|{station}"

# ──────────────────────────────────────────────
# Znane emisje (do oznaczania 🆕)
# ──────────────────────────────────────────────

def load_known_plays() -> set:
    if not os.path.exists(KNOWN_PLAYS_FILE):
        return set()
    with open(KNOWN_PLAYS_FILE, "r", encoding="utf-8") as f:
        return set(json.load(f))

def save_known_plays(known: set):
    with open(KNOWN_PLAYS_FILE, "w", encoding="utf-8") as f:
        json.dump(list(known), f, ensure_ascii=False, indent=2)

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
st.info(f"📂 Znanych (wcześniej wykrytych) emisji w bazie: **{len(known_plays)}**")

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

    def log(msg: str):
        log_box.write(msg)

    with st.spinner("Pobieram listę piosenek Kamila Pivota..."):
        all_songs = scrape_song_list("kamil pivot", log)

    st.write(f"📋 Łącznie piosenek (wersji tytułów) do sprawdzenia: **{len(all_songs)}**")

    raw_plays = []
    progress  = st.progress(0)
    status    = st.empty()

    for i, song in enumerate(all_songs, 1):
        status.write(f"[{i}/{len(all_songs)}] {song['title']}")
        raw_plays.extend(scrape_song_plays(song, date_from))
        progress.progress(i / len(all_songs))
        time.sleep(1)

    progress.empty()
    status.empty()

    # ── Deduplikacja: różne warianty tego samego tytułu (np. odwrócona
    # kolejność artysta/tytuł albo słów w nazwie) traktujemy jako jedną piosenkę,
    # a te same emisje (ta sama data/godzina/stacja) liczymy tylko raz. ──
    title_counts   = {}   # canonical -> {tytuł: liczba wystąpień}
    dedup_plays    = {}   # (canonical, date, time, station) -> play dict
    all_current_keys = set()

    for p in raw_plays:
        canonical = normalize_title(p["song_title"])
        title_counts.setdefault(canonical, {})
        title_counts[canonical][p["song_title"]] = title_counts[canonical].get(p["song_title"], 0) + 1

        key = make_play_key(canonical, p["date"], p["time"], p["station"])
        all_current_keys.add(key)

        if key not in dedup_plays:
            dedup_plays[key] = {**p, "canonical": canonical}

    # Wybierz najczęściej występujący wariant tytułu jako "ładną" nazwę wyświetlaną
    display_title = {
        canonical: max(variants.items(), key=lambda kv: kv[1])[0]
        for canonical, variants in title_counts.items()
    }

    final_plays = []
    for key, p in dedup_plays.items():
        final_plays.append({
            "tytuł":   display_title[p["canonical"]],
            "data":    p["date"],
            "godzina": p["time"],
            "stacja":  p["station"],
            "nowa":    "🆕" if key not in known_plays else "",
            "url":     p["song_url"],
        })

    st.divider()

    if not final_plays:
        st.warning(f"Brak emisji z ostatnich {days} dni.")
    else:
        st.subheader(f"📊 Wszystkie emisje w wybranym okresie: {len(final_plays)} "
                     f"(w tym 🆕 nowych: {sum(1 for p in final_plays if p['nowa'])})")

        by_title = {}
        for p in final_plays:
            by_title.setdefault(p["tytuł"], []).append(p)

        for title, plays_list in sorted(by_title.items()):
            new_count = sum(1 for p in plays_list if p["nowa"])
            label = f"🎵 {title} ({len(plays_list)} emisji"
            label += f", 🆕 {new_count} nowych)" if new_count else ")"
            with st.expander(label, expanded=True):
                df_show = pd.DataFrame(sorted(plays_list, key=lambda x: (x["data"], x["godzina"])))
                st.dataframe(
                    df_show[["data", "godzina", "stacja", "nowa"]],
                    hide_index=True, use_container_width=True,
                )

        df_all = pd.DataFrame(final_plays)
        df_all["wykryto"] = datetime.now().strftime("%d.%m.%Y %H:%M")

        st.download_button(
            "⬇️ Pobierz wszystkie emisje z okresu (CSV)",
            data=df_all.to_csv(index=False, encoding="utf-8-sig"),
            file_name=f"kamil_pivot_emisje_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
        )

    # Aktualizacja bazy "znanych" emisji (do oznaczania 🆕 przy kolejnym uruchomieniu)
    updated_known = known_plays | all_current_keys
    save_known_plays(updated_known)
    st.info(f"💾 Zaktualizowano bazę znanych emisji: {len(updated_known)} rekordów")
