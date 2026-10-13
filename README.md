# followthru-instagram-feed

A free, self-hosted Instagram feed for the footer of followthruagency.com.

Once a day, a GitHub Action asks Apify for the newest posts on
[@followthrucreative](https://www.instagram.com/followthrucreative/), saves the 9 newest as
600×600 JPEGs in `images/`, and writes `feed.json`. GitHub Pages serves both publicly:

- Feed: https://follow-thru-agency.github.io/followthru-instagram-feed/feed.json
- Images: `https://follow-thru-agency.github.io/followthru-instagram-feed/images/<shortcode>.jpg`

A small script on the website (`embed/footer-feed.html`) reads that feed and swaps the 9 footer
marquee images for the latest posts, each linking to the post on Instagram. If the feed is
unreachable, slow (over 4 seconds), or has fewer than 9 posts, the script does nothing and the
footer keeps its original images.

This repo is public because free GitHub Pages requires it. It only contains images that are
already public on Instagram.

## Schedule

- Daily at 11:00 UTC (`.github/workflows/update-feed.yml`), plus a manual "Run workflow" button.
- The workflow only commits when `feed.json` or `images/` changed. `feed.json` carries an
  `updated` timestamp, so a successful run normally commits once a day; that daily commit also
  stops GitHub from auto-disabling the schedule after 60 days of inactivity.
- If Apify fails or returns fewer than 6 usable posts, the run fails (you get a GitHub email) and
  the existing feed and images are left exactly as they were.

## Cost

About $1/month of Apify usage at most: 12 posts per run at roughly $0.002–0.003 per post, once a
day. That sits well inside Apify's free plan, which includes monthly platform credit. The script
asks for Apify's cheaper "basic data" tier, and each run logs its estimated cost.

## The one manual setup step

1. Create a free Apify account for FollowThru at https://console.apify.com/sign-up using
   admin@followthruagency.com.
2. In Apify, open **Settings → API & Integrations** and copy the personal API token.
3. Store it as a repo secret (paste the token when prompted):

   ```sh
   gh secret set APIFY_TOKEN --repo Follow-Thru-Agency/followthru-instagram-feed
   ```

4. Run the workflow once: GitHub → this repo → **Actions** → **Update Instagram feed** →
   **Run workflow**, or:

   ```sh
   gh workflow run update-feed.yml --repo Follow-Thru-Agency/followthru-instagram-feed
   ```

Until the secret exists, every run fails with `APIFY_TOKEN secret not set` and the site keeps its
original footer images.

## Files

| Path | What it is |
| --- | --- |
| `scripts/update_feed.py` | Calls Apify (`apify~instagram-post-scraper`, falls back to `apify~instagram-scraper`), downloads and crops images, writes `feed.json`. |
| `.github/workflows/update-feed.yml` | Daily job that runs the script and commits changes. |
| `feed.json` | `{"updated": ISO time, "posts": [{"image", "url", "alt", "timestamp"}]}`. |
| `images/` | The current 9 post images. Old images are deleted automatically. |
| `embed/footer-feed.html` | The `<script>` to paste into a Webflow Code Embed. It targets `.footer-marquee-holder .footer-marquee-card` → `img.footer-marquee-image`. |

## Running locally

```sh
pip install Pillow requests
APIFY_TOKEN=... python3 scripts/update_feed.py
```

`APIFY_INPUT_FILE=items.json` runs the script against a saved Apify dataset instead of calling
Apify (useful for testing without spending credit).
