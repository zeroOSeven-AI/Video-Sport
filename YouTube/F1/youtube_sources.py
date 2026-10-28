import os
import json
import time
import logging
import requests

from datetime import datetime, timezone
from pathlib import Path

API_KEY = os.getenv("YOUTUBE_API_KEY")

OUTPUT_DIR = Path("YouTube/F1")
MAX_RESULTS = 25
PAGE_SIZE = 50
REQUEST_TIMEOUT = 20
REQUEST_DELAY = 0.5

SOURCES = {
    "formula_1": {
        "name": "Formula 1",
        "playlist_id": "PLj7RD7nCnlE3G9WeItHi-ZA0figXsX3Ky",
        "priority": 3,
        "logo": "logo/formula_1.png",
    },
    "sky_sports_f1": {
        "name": "Sky Sports F1",
        "playlist_id": "PLo5BbNWSTIgirAVUnnvyejFVyuZ_QIWsd",
        "priority": 3,
        "logo": "logo/sky_sports_f1.png",
    },
    "the_race": {
        "name": "The Race F1",
        "playlist_id": "PLtElEI41NT-nT4c0F09iqxPm-nTCQldFk",
        "priority": 2,
        "logo": "logo/the_race.png",
    },
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

YOUTUBE_API_URL = "https://www.googleapis.com/youtube/v3"


# =========================
# HTTP
# =========================

def yt_get(endpoint, params):
    """Dohvaća podatke s YouTube Data API-ja."""

    try:
        response = requests.get(
            f"{YOUTUBE_API_URL}/{endpoint}",
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        if not response.ok:
            logging.error(
                "YouTube API greška (%s): %s",
                response.status_code,
                response.text[:500],
            )
            return None

        return response.json()

    except requests.RequestException as exc:
        logging.error("HTTP zahtjev nije uspio: %s", exc)
        return None


# =========================
# TIME
# =========================

def iso_to_ts(value):
    """Pretvara ISO datum u Unix timestamp."""

    if not value:
        return 0

    try:
        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return int(dt.timestamp())

    except (ValueError, TypeError, OverflowError):
        return 0


def now_iso():
    return datetime.now(timezone.utc).isoformat()


# =========================
# CLASSIFIER
# =========================

def classify(title):
    t = title.lower()
    tags = []

    if any(x in t for x in [
        "highlights",
        "extended highlights",
        "best moments",
        "race highlights",
    ]):
        tags.append("highlights")

    if any(x in t for x in [
        "grand prix",
        "race",
        "sprint",
    ]):
        tags.append("race")

    if any(x in t for x in [
        "qualifying",
        "q1",
        "q2",
        "q3",
    ]):
        tags.append("qualifying")

    if "onboard" in t or "on-board" in t:
        tags.append("onboard")

    if not tags:
        tags.append("news")

    return tags


# =========================
# VIDEO METADATA
# =========================

def enrich_video_dates(videos):
    """
    Dohvaća stvarni publishedAt za videozapise.
    Playlist API datum dodavanja u playlistu nije nužno
    jednak datumu objave samog videa.
    """

    missing_ids = [
        v["video_id"]
        for v in videos
        if not v.get("published_at")
        or v.get("date_needs_verification")
    ]

    # YouTube videos.list podržava do 50 ID-jeva po zahtjevu.
    for start in range(0, len(missing_ids), 50):
        batch_ids = missing_ids[start:start + 50]

        if not batch_ids:
            continue

        data = yt_get(
            "videos",
            {
                "part": "snippet",
                "id": ",".join(batch_ids),
                "key": API_KEY,
            },
        )

        if not data:
            continue

        details = {
            item["id"]: item.get("snippet", {}).get(
                "publishedAt", ""
            )
            for item in data.get("items", [])
        }

        for video in videos:
            real_date = details.get(video["video_id"])

            if real_date:
                video["published_at"] = real_date
                video["published_ts"] = iso_to_ts(real_date)

    return videos


# =========================
# FETCH PLAYLIST
# =========================

def fetch_playlist_videos(source_key, source):
    playlist_id = source["playlist_id"]
    videos = []
    page_token = None

    logging.info("Dohvaćam playlistu: %s", source["name"])

    while len(videos) < MAX_RESULTS:
        params = {
            "part": "snippet,contentDetails",
            "maxResults": min(
                PAGE_SIZE,
                MAX_RESULTS - len(videos),
            ),
            "playlistId": playlist_id,
            "key": API_KEY,
        }

        if page_token:
            params["pageToken"] = page_token

        data = yt_get("playlistItems", params)

        if data is None:
            logging.error(
                "Prekidam dohvat playliste %s zbog API greške.",
                source["name"],
            )
            break

        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            details = item.get("contentDetails", {})

            video_id = details.get("videoId")

            if not video_id:
                continue

            title = snippet.get("title", "").strip()

            # Preskoči uklonjene ili nedostupne videozapise.
            if not title or title.lower() in {
                "deleted video",
                "private video",
            }:
                continue

            # Ovo je datum dodavanja u playlistu.
            # Stvarni datum objave provjeravamo preko videos.list.
            playlist_date = snippet.get("publishedAt", "")

            # U nekim odgovorima contentDetails može sadržavati
            # videoPublishedAt, koji je datum objave videa.
            published = (
                details.get("videoPublishedAt")
                or ""
            )

            tags = classify(title)

            videos.append({
                "video_id": video_id,
                "title": title,
                "published_at": published or playlist_date,
                "published_ts": iso_to_ts(
                    published or playlist_date
                ),
                "thumbnail": (
                    f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
                ),
                "source": source["name"],
                "source_key": source_key,
                "priority": source["priority"],
                "logo": source["logo"],
                "tags": tags,
                "type": (
                    "highlight"
                    if "highlights" in tags
                    else "video"
                ),
                "link": (
                    f"https://www.youtube.com/watch?v={video_id}"
                ),
                "date_needs_verification": not bool(published),
            })

        page_token = data.get("nextPageToken")

        if not page_token:
            break

        time.sleep(REQUEST_DELAY)

    # Ukloni duplikate unutar izvora.
    unique = {}

    for video in videos:
        unique[video["video_id"]] = video

    videos = list(unique.values())

    # Dohvati stvarne datume objave videozapisa.
    videos = enrich_video_dates(videos)

    # Ukloni pomoćno polje iz izlaznog JSON-a.
    for video in videos:
        video.pop("date_needs_verification", None)

    # Najnoviji video prvi.
    videos.sort(
        key=lambda video: video["published_ts"],
        reverse=True,
    )

    logging.info(
        "%s: dohvaćeno %d videa",
        source["name"],
        len(videos),
    )

    if videos:
        logging.info(
            "Najnoviji: %s | %s",
            videos[0]["published_at"],
            videos[0]["title"],
        )

    return videos


# =========================
# HIGHLIGHTS
# =========================

def build_highlights(videos):
    result = {}

    for video in videos:
        if video["type"] != "highlight":
            continue

        source_name = video["source"]

        if source_name not in result:
            result[source_name] = {
                "source": source_name,
                "priority": video["priority"],
                "logo": video["logo"],
                "videos": [],
            }

        result[source_name]["videos"].append(video)

    for source in result.values():
        source["videos"].sort(
            key=lambda video: video["published_ts"],
            reverse=True,
        )

    return result


# =========================
# NEWS
# =========================

def build_news(videos):
    return sorted(
        [
            video
            for video in videos
            if video["type"] != "highlight"
        ],
        key=lambda video: video["published_ts"],
        reverse=True,
    )


# =========================
# JSON SAVE
# =========================

def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    temp_path = path.with_suffix(path.suffix + ".tmp")

    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=4,
        )

    temp_path.replace(path)


# =========================
# MAIN
# =========================

def main():
    if not API_KEY:
        raise RuntimeError(
            "Nedostaje environment variable YOUTUBE_API_KEY."
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    all_videos = []

    for source_key, source in SOURCES.items():
        videos = fetch_playlist_videos(source_key, source)

        # Ako API zahtjev nije uspio, ne prepisuj izvorni JSON
        # praznom listom.
        if not videos:
            logging.warning(
                "Nema novih rezultata za %s; provjeri API i playlistu.",
                source["name"],
            )

        source_path = OUTPUT_DIR / f"{source_key}.json"

        if videos:
            save_json(
                source_path,
                {
                    "source": source["name"],
                    "priority": source["priority"],
                    "updated_at": now_iso(),
                    "videos": videos,
                },
            )

        all_videos.extend(videos)

        time.sleep(REQUEST_DELAY)

    # Ukloni duplikate ako se isti video nalazi u više izvora.
    # Zadržavamo zapis prvog izvora koji ga je dao.
    unique_all = {}

    for video in all_videos:
        unique_all.setdefault(video["video_id"], video)

    all_videos = list(unique_all.values())

    all_videos.sort(
        key=lambda video: video["published_ts"],
        reverse=True,
    )

    feed = {
        "updated_at": now_iso(),
        "total_videos": len(all_videos),
        "highlights": build_highlights(all_videos),
        "news": build_news(all_videos),
        "all": all_videos,
    }

    if all_videos:
        save_json(OUTPUT_DIR / "feed.json", feed)

        logging.info("=" * 60)
        logging.info("SCRAPE COMPLETE")
        logging.info("UKUPNO VIDEA: %d", len(all_videos))
        logging.info(
            "NAJNOVIJI VIDEO: %s",
            all_videos[0]["title"],
        )
        logging.info(
            "DATUM OBJAVE: %s",
            all_videos[0]["published_at"],
        )
        logging.info("=" * 60)
    else:
        logging.error(
            "Nijedan video nije dohvaćen. feed.json nije prepisan."
        )


if __name__ == "__main__":
    main()
