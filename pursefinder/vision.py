"""Looks at listing photos with Claude and decides which bag (if any) is in them.

Titles are deliberately ignored as evidence: sellers often write just "Chloe purse"
or "leather bag", so only the photos count.
"""

from __future__ import annotations

import base64
import io
import logging
from typing import Literal

import anthropic
import requests
from PIL import Image
from pydantic import BaseModel

from .models import Listing

log = logging.getLogger(__name__)

BagType = Literal["balenciaga_city", "balenciaga_other_motorcycle", "chloe_paddington", "none"]


class Verdict(BaseModel):
    bag: BagType
    confidence: int  # 0-100
    reasoning: str
    authenticity_red_flags: list[str]


SYSTEM_PROMPT = """You identify designer handbags from secondhand-marketplace photos.

The buyer is hunting for exactly two bags:

1. Balenciaga City (from the "Motorcycle"/Classic line). Look for:
   - Soft, slouchy, often distressed/crinkled lambskin ("Arena" leather); medium rectangular
     body wider than it is tall.
   - Two short rolled handles with whipstitched leather ends.
   - Long knotted leather tassels hanging from the zipper pulls.
   - A zip pocket on the front, closed with a zip that has its own tassel.
   - Studded buckle straps at each side/front corner: small round studs on "Classic"
     hardware, large domed/flat studs on "Giant" hardware; often a detachable shoulder strap.
   - A small leather-framed mirror is sometimes attached inside or shown in photos.
   Sister styles from the same line (First, Part Time, Work, Day, Town, Velo, Twiggy,
   Weekender, Mini City...) share the hardware but differ in shape: the First is smaller
   with no shoulder strap, the Part Time and Work are larger and wider, the Day is a hobo
   with one strap, the Town is smaller with a long strap. Label those
   "balenciaga_other_motorcycle", not "balenciaga_city".

2. Chloé Paddington. Look for:
   - A large, heavy brass padlock hanging from the front (often engraved "Chloé"), frequently
     with its key held in a small leather pouch.
   - A slouchy leather satchel/bowling shape with two curved top handles fixed by brass
     rivets/studs.
   - A strap with brass eyelets running across the front, brass rivets on the pockets.
   - Common in tan, whisky, black, white and bright 2005-2008 colors.

Rules:
- Judge ONLY from the photos. The title may be vague, wrong, or absent; never let it
  convince you of something the photos don't show.
- If the photos show a different bag, a wallet, only a dust bag/box, or you can't see
  enough of the bag, answer "none".
- confidence is 0-100: how sure you are the photos show the bag you named.
- authenticity_red_flags: list visible signs the bag could be counterfeit (wrong hardware
  shape or colour, stiff/plastic-looking leather, sloppy stitching, wrong fonts, wrong
  tassel style). Empty list if none are visible. This does not change the bag label.
- Keep reasoning to one or two sentences naming the features you saw."""

MAX_IMAGE_SIDE = 1024
_UA = {"User-Agent": "Mozilla/5.0 (compatible; pursefinder/1.0)"}


def _image_block(url: str, session: requests.Session) -> dict:
    """Download and shrink an image; fall back to letting the API fetch the URL."""
    try:
        resp = session.get(url, headers=_UA, timeout=20)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
        img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        data = base64.standard_b64encode(buf.getvalue()).decode("ascii")
        return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}
    except Exception as exc:  # noqa: BLE001 - any failure: let the API try the URL itself
        log.debug("Image download failed for %s (%s); passing URL instead", url, exc)
        return {"type": "image", "source": {"type": "url", "url": url}}


class BagClassifier:
    def __init__(self, model: str, effort: str = "low", images_per_listing: int = 3):
        self.client = anthropic.Anthropic()
        self.model = model
        self.effort = effort
        self.images_per_listing = images_per_listing
        self.session = requests.Session()

    def classify(self, listing: Listing) -> Verdict | None:
        urls = listing.image_urls[: self.images_per_listing]
        if not urls:
            return None

        content: list[dict] = [_image_block(u, self.session) for u in urls]
        content.append(
            {
                "type": "text",
                "text": (
                    f"Listing from {listing.source}. Seller's title (unreliable, may be vague): "
                    f"{listing.title!r}. Price: {listing.price} {listing.currency}.\n"
                    "Which bag do the photos show?"
                ),
            }
        )

        extra: dict = {}
        if self.model.startswith(("claude-opus-5", "claude-fable")):
            # If a safety classifier declines a photo, retry on Anthropic's recommended backup model.
            extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        response = self.client.beta.messages.parse(
            model=self.model,
            max_tokens=4000,
            system=SYSTEM_PROMPT,
            output_config={"effort": self.effort},
            output_format=Verdict,
            messages=[{"role": "user", "content": content}],
            **extra,
        )

        if response.stop_reason == "refusal":
            log.warning("Classifier declined listing %s", listing.key)
            return None
        return response.parsed_output
