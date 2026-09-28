# Pursefinder

An AI agent that keeps checking secondhand marketplaces for newly listed **Balenciaga City**
and **Chloé Paddington** bags under **$500**.

It decides which bag is in a listing **from the photos, not the title.** Sellers often write
"Chloe purse" or "black leather bag", so every new listing's photos go to Claude, which looks
for the features that identify each bag:

- **Balenciaga City:** slouchy distressed leather, knotted leather zipper tassels, studded
  buckle straps, whipstitched rolled handles, front zip pocket.
- **Chloé Paddington:** big brass padlock on the front, leather key pouch, brass rivets and
  eyelets, curved top handles.

When it finds one, it alerts you and also lists visible signs the bag might be fake.
Lots of bags under $500 are counterfeit, so read those notes before you buy.

## How it works

```
every ~10 min ─► search each site, newest first, for broad terms ("chloe bag", "padlock bag", ...)
             ─► drop anything over $500, without photos, or already checked
             ─► Claude looks at up to 3 photos: City? Paddington? neither?
             ─► match ⇒ alert (terminal + data/matches.html + optional phone push / Discord)
```

Every listing it has checked goes into `data/seen.sqlite3`, so it never looks at the same one
twice or alerts you twice.

## Sites

| Site | How | Notes |
|---|---|---|
| eBay | Official API | Most reliable. Needs free developer keys (below). |
| Poshmark | Site's own JSON feed | Unofficial, so it can break if Poshmark changes it. |
| Depop | Site's own JSON feed | Unofficial. |
| Vinted | Site's own JSON feed | Unofficial. Set `base_url` for other countries. |
| Mercari, ThredUp, Vestiaire Collective, TheRealReal | Headless browser | Needs Playwright. Sites may block automated browsers. |

Facebook Marketplace isn't included because it needs a logged-in account and its terms
forbid automated access. If a site blocks the agent, the others keep running and the log
shows a warning.

## Setup

You need Python 3.10 or newer.

```bash
git clone <this repo> && cd pursefinder-
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium          # only needed for Mercari/ThredUp/Vestiaire/TheRealReal
cp config.example.yaml config.yaml   # then edit to taste
```

### Keys

Set these in your terminal, or put them in a `.env` file you `source` first:

```bash
export ANTHROPIC_API_KEY=sk-ant-...        # required: console.anthropic.com → API Keys
export EBAY_CLIENT_ID=...                  # optional: developer.ebay.com → create a
export EBAY_CLIENT_SECRET=...              #   "Production" keyset (free)
export NTFY_TOPIC=pick-a-long-random-name  # optional: phone alerts, see below
export DISCORD_WEBHOOK_URL=https://...     # optional: alerts in a Discord channel
```

**Phone alerts (free, no account):** install the **ntfy** app (iOS/Android), subscribe to a
topic with a long, hard-to-guess name, and set `NTFY_TOPIC` to that name. Each match shows up
as a notification with the photo, and tapping it opens the listing.

## Run it

```bash
python -m pursefinder --once     # a single round, good for a first try
python -m pursefinder            # keep watching (Ctrl+C to stop)
```

Open `data/matches.html` in your browser to see every match so far as a photo grid.

To keep it running all the time, run it on a computer that stays on, or on a small cloud
server, with `nohup python -m pursefinder &` or as a service.

## Tuning (config.yaml)

- `max_price` / `min_price`: price range in USD.
- `queries`: search terms. Broad terms catch mislabeled listings. More terms check more
  listings, which costs more.
- `min_confidence`: how sure the AI must be before it alerts you (default 60).
- `include_other_balenciaga`: also alert on the First, Part Time, Work, Day and similar bags,
  which have the same hardware as the City.
- `interval_minutes`, `images_per_listing`, `max_classifications_per_cycle`: speed vs. cost.
- `model` / `effort`: which Claude model looks at the photos. The default is `claude-opus-5`
  at `low` effort. For roughly half the cost per listing, try `model: claude-sonnet-5`, but it
  may miss more bags.

## Cost

Each new listing costs one Claude request with up to 3 photos. The first round checks
everything currently listed, which can be a few hundred listings. Later rounds only check
listings that are new since the last round. `max_classifications_per_cycle` caps each round.
See your usage at console.anthropic.com.

## Tests

```bash
pip install pytest && python -m pytest
```
