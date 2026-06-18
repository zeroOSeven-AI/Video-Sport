import os
import json
import time
import requests
import xml.etree.ElementTree as ET
from datetime import datetime

OUTPUT_FOLDER = "YouTube"
DELAY_SECONDS = 1

SOURCES = {
    "formula_1": {"name": "Formula 1", "id": "UCB_qrNyFAFJGdxK69F8S3FQ"},
    "the_race": {"name": "The Race", "id": "UC9suvGlsc2EFr7SIsgWInXQ"},
    "driver61": {"name": "Driver61", "id": "UCJpChgSOTKT9wdxw5fJ53gQ"},
    "p1_matt_tommy": {"name": "P1 with Matt & Tommy", "id": "UCRXn6VOfHAt8zNf8D3ndFcw"},
    "autosport": {"name": "Autosport", "id": "UCZ0SstM3sS_vD_f6v798pDw"},
    "sky_sports_f1": {"name": "Sky Sports F1", "id": "UCgN40g9_RE93nNfX-vS_uRw"}
}

def fetch_via_rss(slug, info):
    print(f"Processing source via RSS: {info['name']}")
    channel_id = info["id"]
    
    # Pravi YouTube RSS URL
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    
    try:
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            print(f"Error fetching RSS for {info['name']}: {response.status_code}")
            return
            
        root = ET.fromstring(response.content)
        
        namespaces = {
            'atom': 'http://www.w3.org/2005/Atom',
            'yt': 'http://www.youtube.com/xml/schemas/2015',
            'media': 'http://search.yahoo.com/mrss/'
        }
        
        video_ids = []
        video_details = []
        
        entries = root.findall('atom:entry', namespaces)[:10]
        
        for entry in entries:
            v_id = entry.find('yt:videoId', namespaces)
            title = entry.find('atom:title', namespaces)
            published = entry.find('atom:published', namespaces)
            
            media_group = entry.find('media:group', namespaces)
            thumbnail_url = ""
            if media_group is not None:
                thumbnail = media_group.find('media:thumbnail', namespaces)
                if thumbnail is not None:
                    thumbnail_url = thumbnail.attrib.get('url', '')
            
            if v_id is not None and v_id.text:
                vid_text = v_id.text
                video_ids.append(vid_text)
                video_details.append({
                    "video_id": vid_text,
                    "title": title.text if title is not None else "",
                    "published_at": published.text if published is not None else "",
                    "thumbnail": thumbnail_url
                })
        
        # Pravi YouTube embed URL za prilagođenu playlistu
        ids_csv = ",".join(video_ids)
        embed_url = f"https://www.youtube.com/embed/{video_ids[0]}?playlist={ids_csv}" if video_ids else ""
        
        output_data = {
            "source_name": info["name"],
            "channel_id": channel_id,
            "updated_at": datetime.utcnow().isoformat() + "Z",
            "video_ids": video_ids,
            "playlist_embed_url": embed_url,
            "videos": video_details
        }
        
        os.makedirs(OUTPUT_FOLDER, exist_ok=True)
        filename = os.path.join(OUTPUT_FOLDER, f"{slug}.json")
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=4, ensure_ascii=False)
        print(f"Successfully saved {filename} with {len(video_ids)} videos.")
        
    except Exception as e:
        print(f"Exception while processing {info['name']}: {str(e)}")

def main():
    for i, (slug, info) in enumerate(SOURCES.items()):
        fetch_via_rss(slug, info)
        if i < len(SOURCES) - 1:
            time.sleep(DELAY_SECONDS)

if __name__ == "__main__":
    main()
