import json
import os
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

import requests

OUTPUT_FOLDER = "YouTube"
DELAY_SECONDS = 1

SOURCES = {
    "formula_1": {
        "name": "Formula 1",
        "id": "UCB_qrNyFAFJGdxK69F8S3FQ"
    },
    "the_race": {
        "name": "The Race",
        "id": "UC9suvGlsc2EFr7SIsgWInXQ"
    },
    "driver61": {
        "name": "Driver61",
        "id": "UCJpChgSOTKT9wdxw5fJ53gQ"
    },
    "p1_matt_tommy": {
        "name": "P1 with Matt & Tommy",
        "id": "UCRXn6VOfHAt8zNf8D3ndFcw"
    },
    "autosport": {
        "name": "Autosport",
        "id": "UCZ0SstM3sS_vD_f6v798pDw"
    },
    "sky_sports_f1": {
        "name": "Sky Sports F1",
        "id": "UCgN40g9_RE93nNfX-vS_uRw"
    }
}

NAMESPACES = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/"
}


def fetch_via_rss(slug: str, info: dict) -> None:
    """
    Fetch the latest videos from a YouTube RSS feed
    and save them as a JSON file.
    """
    channel_id = info["id"]
    channel_name = info["name"]

    print(f"Processing: {channel_name}")

    rss_url = (
        f"https://www.youtube.com/feeds/videos.xml"
        f"?channel_id={channel_id}"
    )

    try:
        response = requests.get(rss_url, timeout=10)
        response.raise_for_status()

        root = ET.fromstring(response.content)

        video_ids = []
        video_details = []

        entries = root.findall("atom:entry", NAMESPACES)[:10]

        for entry in entries:
            video_id = entry.find("yt:videoId", NAMESPACES)
            title = entry.find("atom:title", NAMESPACES)
            published = entry.find("atom:published", NAMESPACES)

            thumbnail_url = ""

            media_group = entry.find("media:group", NAMESPACES)
            if media_group is not None:
                thumbnails = media_group.findall(
                    "media:thumbnail",
                    NAMESPACES
                )

                if thumbnails:
                    thumbnail_url = thumbnails[0].attrib.get("url", "")

            if video_id is None or not video_id.text:
                continue

            video_ids.append(video_id.text)

            video_details.append({
                "video_id": video_id.text,
                "title": title.text if title is not None else "",
                "published_at": (
                    published.text if published is not None else ""
                ),
                "thumbnail": thumbnail_url
            })

        embed_url = ""

        if video_ids:
            embed_url = (
                f"https://www.youtube.com/embed/{video_ids[0]}"
                f"?playlist={','.join(video_ids)}"
            )

        output_data = {
            "source_name": channel_name,
            "channel_id": channel_id,
            "updated_at": datetime.now(UTC).isoformat(),
            "video_ids": video_ids,
            "playlist_embed_url": embed_url,
            "videos": video_details
        }

        os.makedirs(OUTPUT_FOLDER, exist_ok=True)

        output_file = os.path.join(
            OUTPUT_FOLDER,
            f"{slug}.json"
        )

        with open(output_file, "w", encoding="utf-8") as file:
            json.dump(
                output_data,
                file,
                indent=4,
                ensure_ascii=False
            )

        print(
            f"Saved {len(video_ids)} videos "
            f"to {output_file}"
        )

    except requests.RequestException as error:
        print(f"Network error ({channel_name}): {error}")

    except ET.ParseError as error:
        print(f"XML parsing error ({channel_name}): {error}")

    except Exception as error:
        print(f"Unexpected error ({channel_name}): {error}")


def main() -> None:
    """Process all configured YouTube channels."""

    for index, (slug, info) in enumerate(SOURCES.items()):
        fetch_via_rss(slug, info)

        if index < len(SOURCES) - 1:
            time.sleep(DELAY_SECONDS)


if __name__ == "__main__":
    main()
