import os
import json
import time
import requests
from datetime import datetime, timezone

API_KEY = os.getenv("YOUTUBE_API_KEY")
OUTPUT_DIR = "YouTube/F1"
MAX_RESULTS_PER_PLAYLIST = 20

PRIORITY_CHANNELS = {
    "Formula 1": 3,
    "Sky Sports F1": 3,
    "The Race": 2,
    "Driver61": 2,
    "Autosport": 1,
    "P1 with Matt & Tommy": 1
}

# =========================
# CHANNELS (UC IDs)
# =========================
PLAYLISTS = {
    "formula_1": {
        "name": "Formula 1",
        "channel_id": "UCX6OQ3DkcsbYNE6H8uQQuVA"
    },
    "sky_sports_f1": {
        "name": "Sky Sports F1",
        "channel_id": "UC3kxJQ9RfaS5CKeYbbFMi4Q"
    },
    "the_race": {
        "name": "The Race",
        "channel_id": "UC4Q9T9R3Gq3V7h0b9vQwq0Q"
    }
}

# =========================
# HELPERS
# =========================

def yt_get(url):
    r = requests.get(url, timeout=15)
    if not r.ok:
        print("YT ERROR:", r.status_code, r.text[:200])
        return {}
    return r.json()


def iso_to_ts(iso):
    try:
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
    except:
        return 0


# 🔥 FIX: channel → uploads playlist
def channel_to_uploads_playlist(channel_id: str) -> str:
    if channel_id.startswith("UC"):
        return "UU" + channel_id[2:]
    return channel_id


def get_videos_from_playlist(playlist_id):
    url = (
        "https://www.googleapis.com/youtube/v3/playlistItems"
        f"?part=snippet,contentDetails"
        f"&maxResults={MAX_RESULTS_PER_PLAYLIST}"
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
        channel = sn.get("videoOwnerChannelTitle", "unknown")

        videos.append({
            "video_id": video_id,
            "title": title,
            "published_at": published,
            "published_ts": iso_to_ts(published),
            "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
            "channel": channel,
            "priority": PRIORITY_CHANNELS.get(channel, 0),
            "tags": classify(title),
            "link": f"https://www.youtube.com/watch?v={video_id}"
        })

    return videos


def classify(title):
    t = title.lower()
    tags = []

    if "highlights" in t:
        tags.append("highlights")
    if "onboard" in t:
        tags.append("onboard")
    if "qualifying" in t:
        tags.append("qualifying")
    if "race" in t:
        tags.append("race")

    return tags


# =========================
# MAIN
# =========================

def main():
    if not API_KEY:
        raise Exception("Missing YOUTUBE_API_KEY")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    all_videos = []

    for key, pl in PLAYLISTS.items():
        print(f"Fetching {pl['name']}")

        channel_id = pl["channel_id"]

        # 🔥 FIX: UC → UU playlist
        playlist_id = channel_to_uploads_playlist(channel_id)

        videos = get_videos_from_playlist(playlist_id)

        for v in videos:
            v["source_key"] = key
            v["source_name"] = pl["name"]

        all_videos.extend(videos)

        time.sleep(1)

    # sort
    all_videos.sort(key=lambda x: (-x["priority"], -x["published_ts"]))

    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "videos": all_videos
    }

    with open(f"{OUTPUT_DIR}/youtube.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=4, ensure_ascii=False)

    print("DONE -> youtube.json")


if __name__ == "__main__":
    main()
