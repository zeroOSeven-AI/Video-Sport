import os
import json
import time
import requests
from datetime import datetime, timezone

# =========================
# CONFIG
# =========================

API_KEY = os.getenv("YOUTUBE_API_KEY")
OUTPUT_DIR = "YouTube/F1"

MAX_RESULTS = 25

# =========================
# SOURCES (PRIORITY SYSTEM)
# =========================

SOURCES = {
    "formula_1": {
        "name": "Formula 1",
        "channel_id": "UCX6OQ3DkcsbYNE6H8uQQuVA",
        "priority": 3,
        "logo": "logo/formula_1.png"
    },
    "sky_sports_f1": {
        "name": "Sky Sports F1",
        "channel_id": "UC3kxJQ9RfaS5CKeYbbFMi4Q",
        "priority": 3,
        "logo": "logo/sky_sports_f1.png"
    },
    "the_race": {
        "name": "The Race",
        "channel_id": "UC4Q9T9R3Gq3V7h0b9vQwq0Q",
        "priority": 2,
        "logo": "logo/the_race.png"
    }
}

# =========================
# HTTP
# =========================

def yt_get(url):
    try:
        r = requests.get(url, timeout=15)
        if not r.ok:
            print("YT ERROR:", r.status_code)
            return {}
        return r.json()
    except Exception as e:
        print("REQUEST FAILED:", e)
        return {}

# =========================
# HELPERS
# =========================

def iso_to_ts(iso):
    try:
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
    except:
        return 0


def channel_to_uploads(channel_id):
    return "UU" + channel_id[2:]


# =========================
# CLASSIFY ENGINE (v3)
# =========================

def classify(title):
    t = title.lower()

    tags = []

    # STRICT highlights
    if any(k in t for k in ["highlights", "best moments", "recap"]):
        tags.append("highlights")

    # race content
    if "grand prix" in t or "race" in t:
        tags.append("race")

    # qualifying
    if any(k in t for k in ["qualifying", "q1", "q2", "q3"]):
        tags.append("qualifying")

    # onboard
    if "onboard" in t or "on board" in t:
        tags.append("onboard")

    # news fallback
    if not tags:
        tags.append("news")

    return tags


def is_highlight(v):
    return "highlights" in v["tags"]


# =========================
# FETCH PLAYLIST VIDEOS
# =========================

def fetch_videos(key, src):
    playlist = channel_to_uploads(src["channel_id"])

    url = (
        "https://www.googleapis.com/youtube/v3/playlistItems"
        f"?part=snippet,contentDetails"
        f"&maxResults={MAX_RESULTS}"
        f"&playlistId={playlist}"
        f"&key={API_KEY}"
    )

    data = yt_get(url)

    videos = []

    for item in data.get("items", []):
        sn = item.get("snippet", {})
        cd = item.get("contentDetails", {})

        vid = cd.get("videoId")
        if not vid:
            continue

        title = sn.get("title", "")
        published = sn.get("publishedAt", "")

        tags = classify(title)

        videos.append({
            "video_id": vid,
            "title": title,
            "published_at": published,
            "published_ts": iso_to_ts(published),
            "thumbnail": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",

            "source": src["name"],
            "source_key": key,
            "priority": src["priority"],
            "logo": src["logo"],

            "tags": tags,
            "type": "highlight" if is_highlight({"tags": tags}) else "video",

            "link": f"https://www.youtube.com/watch?v={vid}"
        })

    return videos


# =========================
# HIGHLIGHTS BUILDER
# =========================

def build_highlights(videos):
    result = {}

    for v in videos:
        if v["type"] != "highlight":
            continue

        src = v["source"]

        if src not in result:
            result[src] = {
                "source": src,
                "priority": v["priority"],
                "logo": v["logo"],
                "videos": []
            }

        result[src]["videos"].append(v)

    for s in result.values():
        s["videos"].sort(key=lambda x: (-x["priority"], -x["published_ts"]))

    return dict(sorted(result.items(), key=lambda x: -x[1]["priority"]))


# =========================
# NEWS BUILDER
# =========================

def build_news(videos):
    news = []

    for v in videos:
        if v["type"] != "highlight":
            news.append(v)

    return sorted(news, key=lambda x: -x["published_ts"])


# =========================
# MAIN
# =========================

def main():
    if not API_KEY:
        raise Exception("Missing YOUTUBE_API_KEY")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    all_videos = []

    for key, src in SOURCES.items():
        print("Fetching:", src["name"])

        videos = fetch_videos(key, src)

        all_videos.extend(videos)

        # per-channel JSON
        with open(f"{OUTPUT_DIR}/{key}.json", "w", encoding="utf-8") as f:
            json.dump({
                "source": src["name"],
                "logo": src["logo"],
                "priority": src["priority"],
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "videos": sorted(videos, key=lambda x: -x["published_ts"])
            }, f, indent=4, ensure_ascii=False)

        time.sleep(1)

    # =========================
    # GLOBAL OUTPUTS (v3 UI READY)
    # =========================

    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),

        "highlights": build_highlights(all_videos),
        "news": build_news(all_videos),
        "all": sorted(all_videos, key=lambda x: -x["published_ts"])
    }

    with open(f"{OUTPUT_DIR}/feed.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=4, ensure_ascii=False)

    print("DONE -> feed.json ready (v3 UI structure)")


if __name__ == "__main__":
    main()
