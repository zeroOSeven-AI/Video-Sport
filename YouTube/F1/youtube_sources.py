import os
import json
import time
import requests
from datetime import datetime, timezone

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
        r = requests.get(url, timeout=20)

        if not r.ok:
            print("YT ERROR:", r.status_code)
            print(r.text)
            return {}

        return r.json()

    except Exception as e:
        print("REQUEST FAILED:", e)
        return {}

# =========================
# TIME
# =========================

def iso_to_ts(iso):
    try:
        return int(datetime.fromisoformat(
            iso.replace("Z", "+00:00")
        ).timestamp())
    except:
        return 0

# =========================
# CHANNEL → UPLOADS
# =========================

def get_uploads_playlist(channel_id):
    url = (
        "https://www.googleapis.com/youtube/v3/channels"
        f"?part=snippet,contentDetails"
        f"&id={channel_id}"
        f"&key={API_KEY}"
    )

    data = yt_get(url)
    items = data.get("items", [])

    if not items:
        print("CHANNEL NOT FOUND:", channel_id)
        return None

    channel = items[0]

    title = channel["snippet"]["title"]
    uploads = channel["contentDetails"]["relatedPlaylists"]["uploads"]

    print("\n" + "=" * 60)
    print("CHANNEL VERIFIED")
    print("TITLE:", title)
    print("UPLOADS:", uploads)
    print("=" * 60)

    return uploads

# =========================
# CLASSIFIER (FIXED)
# =========================

def classify(title):
    t = title.lower()

    tags = []

    highlight_keywords = [
        "highlights",
        "race highlights",
        "extended highlights",
        "best moments",
        "recap"
    ]

    race_keywords = ["grand prix", "race"]
    quali_keywords = ["qualifying", "q1", "q2", "q3"]
    onboard_keywords = ["onboard", "on board"]

    if any(k in t for k in highlight_keywords):
        tags.append("highlights")

    if any(k in t for k in race_keywords):
        tags.append("race")

    if any(k in t for k in quali_keywords):
        tags.append("qualifying")

    if any(k in t for k in onboard_keywords):
        tags.append("onboard")

    if not tags:
        tags.append("news")

    return tags

# =========================
# FETCH VIDEOS
# =========================

def fetch_videos(source_key, source):
    uploads = get_uploads_playlist(source["channel_id"])

    if not uploads:
        return []

    url = (
        "https://www.googleapis.com/youtube/v3/playlistItems"
        f"?part=snippet,contentDetails"
        f"&playlistId={uploads}"
        f"&maxResults={MAX_RESULTS}"
        f"&key={API_KEY}"
    )

    data = yt_get(url)

    videos = []

    print("\nFETCHING:", source["name"])

    for item in data.get("items", []):
        sn = item.get("snippet", {})
        cd = item.get("contentDetails", {})

        video_id = cd.get("videoId")
        if not video_id:
            continue

        title = sn.get("title", "")
        published = sn.get("publishedAt", "")

        tags = classify(title)

        video = {
            "video_id": video_id,
            "title": title,
            "published_at": published,
            "published_ts": iso_to_ts(published),
            "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",

            "source": source["name"],
            "source_key": source_key,
            "priority": source["priority"],
            "logo": source["logo"],

            "tags": tags,
            "type": "highlight" if "highlights" in tags else "video",

            "link": f"https://www.youtube.com/watch?v={video_id}"
        }

        videos.append(video)

    videos.sort(key=lambda x: x["published_ts"], reverse=True)

    print("VIDEOS:", len(videos))

    return videos

# =========================
# HIGHLIGHTS (HOME)
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

    # sort inside each source
    for k in result:
        result[k]["videos"].sort(
            key=lambda x: (-x["priority"], -x["published_ts"])
        )

    return dict(sorted(result.items(), key=lambda x: -x[1]["priority"]))

# =========================
# NEWS FEED
# =========================

def build_news(videos):
    return sorted(
        [v for v in videos if v["type"] != "highlight"],
        key=lambda x: x["published_ts"],
        reverse=True
    )

# =========================
# MAIN
# =========================

def main():
    if not API_KEY:
        raise Exception("Missing YOUTUBE_API_KEY")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    all_videos = []

    for key, source in SOURCES.items():
        videos = fetch_videos(key, source)

        all_videos.extend(videos)

        # per-source file
        with open(f"{OUTPUT_DIR}/{key}.json", "w", encoding="utf-8") as f:
            json.dump({
                "source": source["name"],
                "logo": source["logo"],
                "priority": source["priority"],
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "videos": videos
            }, f, indent=4, ensure_ascii=False)

        time.sleep(1)

    # =========================
    # GLOBAL DEDUPE FIX
    # =========================

    seen = set()
    unique_videos = []

    for v in all_videos:
        if v["video_id"] in seen:
            continue
        seen.add(v["video_id"])
        unique_videos.append(v)

    unique_videos.sort(
        key=lambda x: x["published_ts"],
        reverse=True
    )

    feed = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total_videos": len(unique_videos),

        # HOME
        "highlights": build_highlights(unique_videos),

        # NEWS
        "news": build_news(unique_videos),

        # RAW
        "all": unique_videos
    }

    with open(f"{OUTPUT_DIR}/feed.json", "w", encoding="utf-8") as f:
        json.dump(feed, f, indent=4, ensure_ascii=False)

    print("\n" + "=" * 60)
    print("SCRAPE COMPLETE")
    print("TOTAL VIDEOS:", len(unique_videos))

    if unique_videos:
        print("LATEST:", unique_videos[0]["title"])

    print("=" * 60)


if __name__ == "__main__":
    main()
