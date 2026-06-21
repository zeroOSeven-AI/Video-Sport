import os
import json
import time
import requests
from datetime import datetime, timezone

API_KEY = os.getenv("YOUTUBE_API_KEY")

OUTPUT_DIR = "YouTube/F1"
MAX_RESULTS = 25

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


def iso_to_ts(iso):
    try:
        return int(
            datetime.fromisoformat(
                iso.replace("Z", "+00:00")
            ).timestamp()
        )
    except:
        return 0


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

    uploads = (
        channel["contentDetails"]
        ["relatedPlaylists"]
        ["uploads"]
    )

    print("\n" + "=" * 70)
    print("CHANNEL VERIFIED")
    print("TITLE:", title)
    print("CHANNEL ID:", channel_id)
    print("UPLOADS:", uploads)
    print("=" * 70)

    return uploads


def classify(title):
    t = title.lower()

    tags = []

    if any(x in t for x in [
        "highlights",
        "race highlights",
        "extended highlights",
        "best moments",
        "recap"
    ]):
        tags.append("highlights")

    if any(x in t for x in [
        "grand prix",
        "race"
    ]):
        tags.append("race")

    if any(x in t for x in [
        "qualifying",
        "q1",
        "q2",
        "q3"
    ]):
        tags.append("qualifying")

    if any(x in t for x in [
        "onboard",
        "on board"
    ]):
        tags.append("onboard")

    if not tags:
        tags.append("news")

    return tags


def fetch_videos(source_key, source):
    uploads_playlist = get_uploads_playlist(
        source["channel_id"]
    )

    if not uploads_playlist:
        return []

    url = (
        "https://www.googleapis.com/youtube/v3/playlistItems"
        f"?part=snippet,contentDetails"
        f"&playlistId={uploads_playlist}"
        f"&maxResults={MAX_RESULTS}"
        f"&key={API_KEY}"
    )

    data = yt_get(url)

    videos = []

    for item in data.get("items", []):
        snippet = item.get("snippet", {})
        content = item.get("contentDetails", {})

        video_id = content.get("videoId")

        if not video_id:
            continue

        title = snippet.get("title", "")
        published = snippet.get("publishedAt", "")

        tags = classify(title)

        videos.append({
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
        })

    videos.sort(
        key=lambda x: x["published_ts"],
        reverse=True
    )

    print("\nFETCHED:", source["name"])
    print("VIDEOS :", len(videos))

    for v in videos[:5]:
        print("\nTITLE :", v["title"])
        print("DATE  :", v["published_at"])
        print("VIDEO :", v["video_id"])

    return videos


def build_highlights(videos):
    result = {}

    for video in videos:
        if video["type"] != "highlight":
            continue

        src = video["source"]

        if src not in result:
            result[src] = {
                "source": src,
                "priority": video["priority"],
                "logo": video["logo"],
                "videos": []
            }

        result[src]["videos"].append(video)

    return result


def build_news(videos):
    return sorted(
        [
            v for v in videos
            if v["type"] != "highlight"
        ],
        key=lambda x: x["published_ts"],
        reverse=True
    )


def main():
    if not API_KEY:
        raise Exception("Missing YOUTUBE_API_KEY")

    os.makedirs(
        OUTPUT_DIR,
        exist_ok=True
    )

    all_videos = []

    for key, source in SOURCES.items():
        videos = fetch_videos(
            key,
            source
        )

        all_videos.extend(videos)

        with open(
            f"{OUTPUT_DIR}/{key}.json",
            "w",
            encoding="utf-8"
        ) as f:
            json.dump(
                {
                    "source": source["name"],
                    "logo": source["logo"],
                    "priority": source["priority"],
                    "updated_at": datetime.now(
                        timezone.utc
                    ).isoformat(),
                    "videos": videos
                },
                f,
                indent=4,
                ensure_ascii=False
            )

        time.sleep(1)

    all_videos.sort(
        key=lambda x: x["published_ts"],
        reverse=True
    )

    feed = {
        "updated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "total_videos": len(all_videos),
        "highlights": build_highlights(all_videos),
        "news": build_news(all_videos),
        "all": all_videos
    }

    with open(
        f"{OUTPUT_DIR}/feed.json",
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            feed,
            f,
            indent=4,
            ensure_ascii=False
        )

    print("\n" + "=" * 70)
    print("SCRAPE COMPLETE")
    print("TOTAL VIDEOS:", len(all_videos))

    if all_videos:
        print("LATEST:", all_videos[0]["title"])

    print("=" * 70)


if __name__ == "__main__":
    main()
