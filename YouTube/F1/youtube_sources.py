import os
import json
import time
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, UTC

OUTPUT_FOLDER = "YouTube/F1"
DELAY_SECONDS = 1

SOURCES = {
    "formula_1": {
        "name": "Formula 1",
        "id": "UCB_qr75-ydFVKSF9Dmo6izg"
    },
    "the_race": {
        "name": "The Race",
        "id": "UCaTxfj0BzL-MaCy-YUqPRoQ"
    },
    "driver61": {
        "name": "Driver61",
        "id": "UCtbLA0YM6EpwUQhFUyPQU9Q"
    },
    "p1_matt_tommy": {
        "name": "P1 with Matt & Tommy",
        "id": "UCD5jAyCSDRR5yTgswfDbK8w"
    },
    "autosport": {
        "name": "Autosport",
        "id": "UCxuksozHJD_f1w9nVa6UhAw"
    },
    "sky_sports_f1": {
        "name": "Sky Sports F1",
        "id": "UC3kxJQ9RfaS5CKeYbbFMi4Q"
    }
}

NAMESPACES = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/"
}

FILTERS = {
    "highlights": ["highlights", "best moments"],
    "onboard": ["onboard", "on board"],
    "race": ["grand prix", "race"],
    "qualifying": ["qualifying", "qualy", "q1", "q2", "q3"]
}


def classify_video(title: str):
    title_low = title.lower()
    tags = []

    for category, keywords in FILTERS.items():
        if any(kw in title_low for kw in keywords):
            tags.append(category)

    return tags


def parse_time_to_ts(date_str):
    try:
        return int(datetime.fromisoformat(date_str.replace("Z", "+00:00")).timestamp())
    except:
        return 0


def fetch_channel(slug, info):
    print(f"Processing: {info['name']}")

    rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={info['id']}"

    try:
        r = requests.get(rss_url, timeout=10)
        r.raise_for_status()

        root = ET.fromstring(r.content)

        video_ids = []
        videos = []

        entries = root.findall("atom:entry", NAMESPACES)[:10]

        for entry in entries:
            vid = entry.find("yt:videoId", NAMESPACES)
            title = entry.find("atom:title", NAMESPACES)
            published = entry.find("atom:published", NAMESPACES)

            if vid is None or not vid.text:
                continue

            title_text = title.text if title is not None else "Untitled"
            published_text = published.text if published is not None else ""

            thumbnail = f"https://i.ytimg.com/vi/{vid.text}/hqdefault.jpg"

            tags = classify_video(title_text)

            video_ids.append(vid.text)

            videos.append({
                "video_id": vid.text,
                "title": title_text,
                "published_at": published_text,
                "published_at_ts": parse_time_to_ts(published_text),
                "thumbnail": thumbnail,
                "tags": tags,
                "channel": info["name"],
                "source_key": slug,
                "link": f"https://www.youtube.com/watch?v={vid.text}"
            })

        # EMBED FIX (always safe)
        embed = ""
        if video_ids:
            embed = (
                f"https://www.youtube.com/embed/{video_ids[0]}"
                f"?playlist={','.join(video_ids)}"
            )

        output = {
            "source": info["name"],
            "source_key": slug,
            "channel_id": info["id"],
            "updated_at": datetime.now(UTC).isoformat(),
            "video_ids": video_ids,
            "playlist_embed_url": embed,
            "videos": videos
        }

        os.makedirs(OUTPUT_FOLDER, exist_ok=True)

        with open(f"{OUTPUT_FOLDER}/{slug}.json", "w", encoding="utf-8") as f:
            json.dump(output, f, indent=4, ensure_ascii=False)

        print(f"OK: {info['name']} ({len(video_ids)} videos)")

    except Exception as e:
        print(f"ERROR {info['name']}: {e}")


def main():
    for i, (slug, info) in enumerate(SOURCES.items()):
        fetch_channel(slug, info)
        if i < len(SOURCES) - 1:
            time.sleep(DELAY_SECONDS)


if __name__ == "__main__":
    main()
