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

MAX_RESULTS_PER_PLAYLIST = 20

PRIORITY_CHANNELS = {
    "Formula 1": 3,
    "Sky Sports F1": 3,
    "The Race": 2,
    "Driver61": 2,
    "Autosport": 1,
    "P1 with Matt & Tommy": 1
}

PLAYLISTS = {
    "formula_1": {
        "name": "Formula 1",
        "playlist_id": "UCX6OQ3DkcsbYNE6H8uQQuVA"
    },
    "sky_sports_f1": {
        "name": "Sky Sports F1",
        "playlist_id": "UC3kxJQ9RfaS5CKeYbbFMi4Q"
    },
    "the_race": {
        "name": "The Race",
        "playlist_id": "UUMpZ8C_6X_zN490NIn7n2oA"
    }
}

# =========================
# HELPERS
# =========================

def yt_get(url):
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.json()


def iso_to_ts(iso):
    try:
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
    except:
        return 0


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
        sn = item["snippet"]
        cd = item["contentDetails"]

        title = sn.get("title", "")
        published = sn.get("publishedAt", "")
        channel = sn.get("videoOwnerChannelTitle", "unknown")
        video_id = cd.get("videoId")

        if not video_id:
            continue

        priority = PRIORITY_CHANNELS.get(channel, 0)

        videos.append({
            "video_id": video_id,
            "title": title,
            "published_at": published,
            "published_ts": iso_to_ts(published),
            "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
            "channel": channel,
            "priority": priority,
            "tags": classify(title),
            "link": f"https://www.youtube.com/watch?v={video_id}"
        })

    return videos


def classify(title):
    t = title.lower()

    tags = []
    if any(x in t for x in ["highlights", "recap"]):
        tags.append("highlights")
    if any(x in t for x in ["onboard", "on board"]):
        tags.append("onboard")
    if any(x in t for x in ["qualifying", "q1", "q2", "q3"]):
        tags.append("qualifying")
    if any(x in t for x in ["race", "grand prix"]):
        tags.append("race")

    return tags


# =========================
# MAIN
# =========================

def main():

    if not API_KEY:
        raise Exception("Missing YOUTUBE_API_KEY (GitHub Secret)")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    all_videos = []

    for key, pl in PLAYLISTS.items():
        print(f"Fetching {pl['name']}")

        videos = get_videos_from_playlist(pl["playlist_id"])

        for v in videos:
            v["source_key"] = key
            v["source_name"] = pl["name"]

        all_videos.extend(videos)

        time.sleep(1)

    # =========================
    # PRIORITY SORT
    # =========================

    all_videos.sort(
        key=lambda x: (
            -x["priority"],
            -x["published_ts"]
        )
    )

    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "videos": all_videos
    }

    with open(f"{OUTPUT_DIR}/youtube.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=4, ensure_ascii=False)

    print("DONE -> youtube.json")


if __name__ == "__main__":
    main()
