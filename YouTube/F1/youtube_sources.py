import os
import json
import time
import requests
from datetime import datetime, timezone

API_KEY = os.getenv("YOUTUBE_API_KEY")

OUTPUT_DIR = "YouTube/F1"
MAX_RESULTS = 25


# =========================
# PLAYLIST SOURCES (FIXED APPROACH)
# =========================

SOURCES = {
    "formula_1": {
        "name": "Formula 1",
        "playlist_id": "PLj7RD7nCnlE3G9WeItHi-ZA0figXsX3Ky",
        "priority": 3,
        "logo": "logo/formula_1.png"
    },
    "sky_sports_f1": {
        "name": "Sky Sports F1",
        "playlist_id": "PLo5BbNWSTIgirAVUnnvyejFVyuZ_QIWsd",
        "priority": 3,
        "logo": "logo/sky_sports_f1.png"
    },
    "the_race": {
        "name": "The Race F1",
        "playlist_id": "PLtElEI41NT-nT4c0F09iqxPm-nTCQldFk",
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
            print("YT ERROR:", r.status_code, r.text[:200])
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
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
    except:
        return 0


# =========================
# CLASSIFIER (CLEAN F1 FILTER)
# =========================

def classify(title):
    t = title.lower()
    tags = []

    # highlights = HOME content
    if any(x in t for x in [
        "highlights",
        "extended highlights",
        "best moments",
        "race highlights"
    ]):
        tags.append("highlights")

    # race content
    if "grand prix" in t or "race" in t:
        tags.append("race")

    # qualifying
    if "qualifying" in t or "q1" in t or "q2" in t or "q3" in t:
        tags.append("qualifying")

    # onboard
    if "onboard" in t:
        tags.append("onboard")

    # clean fallback
    if not tags:
        tags.append("news")

    return tags


# =========================
# FETCH PLAYLIST
# =========================

def fetch_playlist_videos(source_key, source):
    playlist_id = source["playlist_id"]

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

        # DEBUG (IMPORTANT FOR YOU)
        print("\nVIDEO DEBUG:")
        print("TITLE:", title)
        print("TAGS:", tags)
        print("ID:", video_id)

        videos.append(video)

    videos.sort(key=lambda x: -x["published_ts"])

    print("\nFETCHED:", source["name"])
    print("VIDEOS:", len(videos))

    return videos


# =========================
# HOME (HIGHLIGHTS)
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
    for s in result.values():
        s["videos"].sort(key=lambda x: -x["published_ts"])

    return result


# =========================
# NEWS (ALL NON-HIGHLIGHTS)
# =========================

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

    for key, source in SOURCES.items():

        videos = fetch_playlist_videos(key, source)

        all_videos.extend(videos)

        # per-source file
        with open(f"{OUTPUT_DIR}/{key}.json", "w", encoding="utf-8") as f:
            json.dump({
                "source": source["name"],
                "priority": source["priority"],
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "videos": videos
            }, f, indent=4, ensure_ascii=False)

        time.sleep(1)

    all_videos.sort(key=lambda x: -x["published_ts"])

    feed = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total_videos": len(all_videos),

        # HOME UI
        "highlights": build_highlights(all_videos),

        # NEWS UI
        "news": build_news(all_videos),

        # RAW
        "all": all_videos
    }

    with open(f"{OUTPUT_DIR}/feed.json", "w", encoding="utf-8") as f:
        json.dump(feed, f, indent=4, ensure_ascii=False)

    print("\n" + "=" * 60)
    print("SCRAPE COMPLETE")
    print("TOTAL VIDEOS:", len(all_videos))

    if all_videos:
        print("LATEST:", all_videos[0]["title"])

    print("=" * 60)


if __name__ == "__main__":
    main()
