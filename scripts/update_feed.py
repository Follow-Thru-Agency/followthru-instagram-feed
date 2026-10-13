#!/usr/bin/env python3
"""Refresh feed.json + images/ with @followthruagency's newest Instagram posts.

Uses Apify's instagram-post-scraper (falls back to instagram-scraper).
Safety rule: if anything fails or fewer than MIN_POSTS usable posts come back,
exit non-zero WITHOUT touching feed.json or images/, so the site keeps serving
the last good feed.

Env:
  APIFY_TOKEN   required
  IG_USERNAME   optional, default "followthruagency"
  APIFY_INPUT_FILE  optional, path to a local JSON list of dataset items
                    (for offline testing; skips the Apify call)
"""
import io
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone

import requests
from PIL import Image, ImageOps

USERNAME = os.environ.get("IG_USERNAME", "followthruagency")

# Posts that must never appear on the website (no client permission to show them).
# Dc1Zx9BJ7uz = body sculpting brand hero test (client not cleared for public use).
EXCLUDE = set(filter(None, os.environ.get("IG_EXCLUDE", "").split(","))) | {"Dc1Zx9BJ7uz"}
FEED_SIZE = 9
MIN_POSTS = 6
RESULTS_LIMIT = 12
IMAGE_SIZE = 600
JPEG_QUALITY = 82
COST_PER_POST_USD = 0.0026  # conservative estimate; actual free-tier price is lower

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGES_DIR = os.path.join(ROOT, "images")
FEED_PATH = os.path.join(ROOT, "feed.json")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

ACTORS = [
    ("apify~instagram-post-scraper", {
        "username": [USERNAME],
        "resultsLimit": RESULTS_LIMIT,
        "dataDetailLevel": "basicData",  # default is the paid "detailedData" add-on
        "skipPinnedPosts": False,
        "includeMusicData": False,
    }),
    ("apify~instagram-scraper", {
        "directUrls": ["https://www.instagram.com/%s/" % USERNAME],
        "resultsType": "posts",
        "resultsLimit": RESULTS_LIMIT,
        "addParentData": False,
    }),
]


def log(msg):
    print(msg, flush=True)


def fail(msg):
    print("ERROR: " + msg, file=sys.stderr, flush=True)
    print("Existing feed.json and images/ were left untouched.", file=sys.stderr, flush=True)
    sys.exit(1)


def run_actor(actor, payload, token):
    url = "https://api.apify.com/v2/acts/%s/run-sync-get-dataset-items" % actor
    resp = requests.post(url, params={"token": token, "timeout": 240},
                         json=payload, timeout=300)
    if resp.status_code >= 300:
        raise RuntimeError("%s returned HTTP %s: %s" % (actor, resp.status_code, resp.text[:300]))
    items = resp.json()
    if not isinstance(items, list):
        raise RuntimeError("%s returned non-list JSON: %s" % (actor, str(items)[:300]))
    return items


def fetch_items(token):
    input_file = os.environ.get("APIFY_INPUT_FILE")
    if input_file:
        log("Using local test input %s (no Apify call)" % input_file)
        with open(input_file) as f:
            return json.load(f), 0
    last_err = None
    for actor, payload in ACTORS:
        try:
            log("Calling Apify actor %s ..." % actor)
            items = run_actor(actor, payload, token)
            usable = [i for i in items if isinstance(i, dict) and not i.get("error")]
            log("  got %d items (%d without error)" % (len(items), len(usable)))
            if len(usable) >= MIN_POSTS:
                return usable, len(items)
            last_err = "%s returned only %d usable items" % (actor, len(usable))
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
            log("  failed: %s" % last_err)
    raise RuntimeError(last_err or "no actor succeeded")


def image_url(item):
    """Cover for videos/reels, first image for carousels, the image otherwise."""
    for key in ("displayUrl", "thumbnailUrl"):
        if item.get(key):
            return item[key]
    images = item.get("images") or []
    if images and isinstance(images[0], str):
        return images[0]
    for child in item.get("childPosts") or []:
        if isinstance(child, dict) and child.get("displayUrl"):
            return child["displayUrl"]
    return None


def shortcode(item):
    sc = item.get("shortCode") or item.get("shortcode")
    if not sc and item.get("url"):
        parts = [p for p in item["url"].split("/") if p]
        if len(parts) >= 2 and parts[-2] in ("p", "reel", "tv"):
            sc = parts[-1]
    return sc


def alt_text(item):
    caption = " ".join((item.get("caption") or "").split())
    if not caption:
        return "FollowThru on Instagram"
    if len(caption) <= 120:
        return caption
    return caption[:119].rsplit(" ", 1)[0] + "…"


def to_square_jpeg(raw):
    img = Image.open(io.BytesIO(raw))
    img = ImageOps.exif_transpose(img).convert("RGB")
    img = ImageOps.fit(img, (IMAGE_SIZE, IMAGE_SIZE), Image.LANCZOS, centering=(0.5, 0.5))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    return out.getvalue()


def main():
    token = os.environ.get("APIFY_TOKEN", "").strip()
    if not token and not os.environ.get("APIFY_INPUT_FILE"):
        fail("APIFY_TOKEN secret not set")

    try:
        items, billed = fetch_items(token)
    except Exception as e:  # noqa: BLE001
        fail("Apify request failed: %s" % e)

    if billed:
        log("Estimated Apify cost this run: %d items x $%.4f = $%.4f"
            % (billed, COST_PER_POST_USD, billed * COST_PER_POST_USD))

    candidates = []
    seen = set()
    for item in items:
        sc, src = shortcode(item), image_url(item)
        if not sc or not src or sc in seen or sc in EXCLUDE:
            continue
        seen.add(sc)
        candidates.append((item.get("timestamp") or "", sc, src, item))
    candidates.sort(key=lambda c: c[0], reverse=True)

    # Download + resize into a temp dir first; only swap in if we end with enough posts.
    tmp = tempfile.mkdtemp(prefix="igfeed-")
    posts = []
    try:
        for ts, sc, src, item in candidates:
            if len(posts) >= FEED_SIZE:
                break
            try:
                r = requests.get(src, headers={"User-Agent": UA}, timeout=30)
                r.raise_for_status()
                data = to_square_jpeg(r.content)
            except Exception as e:  # noqa: BLE001
                log("  skip %s: image download/convert failed (%s)" % (sc, e))
                continue
            with open(os.path.join(tmp, sc + ".jpg"), "wb") as f:
                f.write(data)
            posts.append({
                "image": "images/%s.jpg" % sc,
                "url": "https://www.instagram.com/p/%s/" % sc,
                "alt": alt_text(item),
                "timestamp": ts or None,
            })

        if len(posts) < MIN_POSTS:
            fail("only %d usable posts (need at least %d)" % (len(posts), MIN_POSTS))

        os.makedirs(IMAGES_DIR, exist_ok=True)
        keep = set()
        for p in posts:
            name = os.path.basename(p["image"])
            keep.add(name)
            shutil.move(os.path.join(tmp, name), os.path.join(IMAGES_DIR, name))
        for name in os.listdir(IMAGES_DIR):
            if name.endswith(".jpg") and name not in keep:
                os.remove(os.path.join(IMAGES_DIR, name))
                log("  removed old image %s" % name)

        feed = {
            "updated": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "posts": posts,
        }
        with open(FEED_PATH + ".tmp", "w") as f:
            json.dump(feed, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(FEED_PATH + ".tmp", FEED_PATH)
        log("Wrote feed.json with %d posts." % len(posts))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
