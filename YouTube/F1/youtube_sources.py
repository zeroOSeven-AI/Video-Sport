import os
import json
import time
import requests
from datetime import datetime, timezone

API_KEY = os.getenv("YOUTUBE_API_KEY")
OUTPUT_DIR = "YouTube/F1"

MAX_RESULTS = 20

# =========================
# SOURCES
# =========================
SOURCES = {
    "formula_1": {
        "name": "Formula 1",
        "channel_id": "UCX6OQ3DkcsbYNE6H8uQQuVA",
        "priority": 3
    },
    "sky_sports_f1": {
        "name": "Sky Sports F1",
        "channel_id": "UC3kxJQ9RfaS5CKeYbbFMi4Q",
        "priority": 3
    },
    "the_race": {
        "name": "The Race",
        "channel_id": "UC4Q9T9R3Gq3V7h0b9vQwq0Q",
        "priority": 2
    }
}

# =========================
# HTTP SAFE CALL
# =========================
def yt_get(url):
    try:
        r = requests.get(url, timeout=15)
        if not r.ok:
            print("YT ERROR:", r.status_code, r.text[:200])
            return {}
        return r.json()
    except Exception as e:
        print("REQUEST FAILED:", e)
        return {}


def iso_to_ts(iso):
    try:
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
    except:
        return 0


def channel_to_uploads(channel_id):
    return "UU" + channel_id[2:] if channel_id.startswith("UC") else channel_id


# =========================
# CLASSIFY
# =========================
def classify(title):
    t = title.lower()
    tags = []

    if "highlights" in t or "recap" in t:
        tags.append("highlights")

    if "race" in t or "grand prix" in t:
        tags.append("race")

    if "onboard" in t:
        tags.append("onboard")

    if "qualifying" in t or "q1" in t or "q2" in t or "q3" in t:
        tags.append("qualifying")

    return tags or ["other"]


def is_highlight(tags):
    return "highlights" in tags or "race" in tags


# =========================
# FETCH VIDEOS
# =========================
def fetch_videos(source_key, source):
    playlist_id = channel_to_uploads(source["channel_id"])

    url = (
        "https://www.googleapis.com/youtube/v3/playlistItems"
        f"?part=snippet,contentDetails"
        f"&maxResults={MAX_RESULTS}"
        f"&playlistId={playlist_id}"
        f"&key={API_KEY}"
    )

    data = yt_get(url)

    videos = []

    for item in data.get("items", []):
        sn = item.get("snippet", {})
        cd = item.get("contentDetails", {})

        video_id = cd.get("videoId")
        if not video_id:
            continue

        title = sn.get("title", "")
        published = sn.get("publishedAt", "")

        videos.append({
            "video_id": video_id,
            "title": title,
            "published_at": published,
            "published_ts": iso_to_ts(published),
            "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
            "source": source["name"],
            "source_key": source_key,
            "priority": source["priority"],
            "tags": classify(title),
            "link": f"https://www.youtube.com/watch?v={video_id}"
        })

    return videos


# =========================
# HIGHLIGHTS BUILDER
# =========================
def build_highlights(videos):
    highlights = {}

    for v in videos:
        if not is_highlight(v["tags"]):
            continue

        src = v["source"]

        if src not in highlights:
            highlights[src] = {
                "source": src,
                "priority": v["priority"],
                "videos": []
            }

        highlights[src]["videos"].append(v)

    # sort videos per source
    for src in highlights.values():
        src["videos"].sort(
            key=lambda x: (-x["priority"], -x["published_ts"])
        )

    # sort sources
    return dict(
        sorted(highlights.items(), key=lambda x: -x[1]["priority"])
    )


# =========================
# MAIN
# =========================
def main():
    if not API_KEY:
        raise Exception("Missing YOUTUBE_API_KEY")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    all_videos = []

    # =========================
    # FETCH ALL SOURCES
    # =========================
    for key, src in SOURCES.items():
        print(f"Fetching {src['name']}")

        videos = fetch_videos(key, src)

        for v in videos:
            v["source_name"] = src["name"]

        all_videos.extend(videos)

        # save per-channel JSON
        with open(f"{OUTPUT_DIR}/{key}.json", "w", encoding="utf-8") as f:
            json.dump({
                "source": src["name"],
                "videos": sorted(videos, key=lambda x: -x["published_ts"])
            }, f, indent=4, ensure_ascii=False)

        time.sleep(1)

    # =========================
    # HIGHLIGHTS ONLY OUTPUT
    # =========================
    highlights_data = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "categories": build_highlights(all_videos)
    }

    with open(f"{OUTPUT_DIR}/highlights.json", "w", encoding="utf-8") as f:
        json.dump(highlights_data, f, indent=4, ensure_ascii=False)

    print("DONE -> per-channel JSON + highlights.json")


if __name__ == "__main__":
    main()
