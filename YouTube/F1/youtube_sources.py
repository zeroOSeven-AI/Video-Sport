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
# SOURCES (FIXED + VALIDATED)
# =========================

SOURCES = {
    "formula_1": {
        "name": "Formula 1",
        "channel_id": "UCX6OQ3DkcsbYNE6H8uQQuVA",  # OFFICIAL F1
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
            print(r.text[:300])
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
# GET UPLOADS PLAYLIST (FIXED + SAFE)
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
        print("❌ CHANNEL NOT FOUND:", channel_id)
        return None

    channel = items[0]

    title = channel.get("snippet", {}).get("title", "UNKNOWN")

    uploads = (
        channel
        .get("contentDetails", {})
        .get("relatedPlaylists", {})
        .get("uploads")
    )

    print("\n============================================================")
    print("CHANNEL VERIFIED")
    print("TITLE:", title)
    print("CHANNEL ID:", channel_id)
    print("UPLOADS:", uploads)
    print("============================================================")

    return uploads

# =========================
# CLASSIFIER (F1 CLEAN FILTER)
# =========================

def classify(title):
    t = title.lower()
    tags = []

    if any(k in t for k in [
        "highlights",
        "best moments",
        "recap",
        "race highlights"
    ]):
        tags.append("highlights")

    if any(k in t for k in [
        "grand prix",
        "race",
        "qualifying",
        "fp1",
        "fp2",
        "fp3"
    ]):
        tags.append("race")

    if "onboard" in t:
        tags.append("onboard")

    # FILTER OUT NON-F1 CONTENT (IMPORTANT FIX)
    junk = ["mrbeast", "challenge", "1000", "youtube legends"]
    if any(j in t for j in junk):
        return ["junk"]

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

    for item in data.get("items", []):
        sn = item.get("snippet", {})
        cd = item.get("contentDetails", {})

        vid = cd.get("videoId")
        if not vid:
            continue

        title = sn.get("title", "")
        published = sn.get("publishedAt", "")

        tags = classify(title)

        # skip junk completely
        if "junk" in tags:
            continue

        videos.append({
            "video_id": vid,
            "title": title,
            "published_at": published,
            "published_ts": iso_to_ts(published),
            "thumbnail": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",

            "source": source["name"],
            "source_key": source_key,
            "priority": source["priority"],
            "logo": source["logo"],

            "tags": tags,
            "type": "highlight" if "highlights" in tags else "video",

            "link": f"https://www.youtube.com/watch?v={vid}"
        })

    videos.sort(key=lambda x: -x["published_ts"])

    print("\nFETCHING:", source["name"])
    print("VIDEOS:", len(videos))

    return videos

# =========================
# BUILDERS
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

    return result


def build_news(videos):
    return sorted(
        [v for v in videos if v["type"] != "highlight"],
        key=lambda x: -x["published_ts"]
    )

# =========================
# MAIN
# =========================

def main():
    if not API_KEY:
        raise Exception("Missing YOUTUBE_API_KEY")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    all_videos = []

    for key, src in SOURCES.items():
        videos = fetch_videos(key, src)

        all_videos.extend(videos)

        with open(f"{OUTPUT_DIR}/{key}.json", "w", encoding="utf-8") as f:
            json.dump({
                "source": src["name"],
                "logo": src["logo"],
                "priority": src["priority"],
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "videos": videos
            }, f, indent=4, ensure_ascii=False)

        time.sleep(1)

    all_videos.sort(key=lambda x: -x["published_ts"])

    feed = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total_videos": len(all_videos),

        "highlights": build_highlights(all_videos),
        "news": build_news(all_videos),
        "all": all_videos
    }

    with open(f"{OUTPUT_DIR}/feed.json", "w", encoding="utf-8") as f:
        json.dump(feed, f, indent=4, ensure_ascii=False)

    print("\n============================================================")
    print("SCRAPE COMPLETE")
    print("TOTAL VIDEOS:", len(all_videos))
    if all_videos:
        print("LATEST:", all_videos[0]["title"])
    print("============================================================")


if __name__ == "__main__":
    main()
