"""
AI-generated Gu Pet portraits (OpenAI's image API). Rank I-III (Common/Uncommon/Rare) pets
share cached art keyed by species+path+rank (see get_pet_cache_key); Rank IV+ (Epic+) pets
each get their own unique, permanently-stored portrait (see should_generate_unique_image) --
see GameManager.get_or_create_gu_pet_image for the actual cache-check/generate/write/record
orchestration (that needs real DB access, so it lives in manager.py like everything else
that touches the database; this module stays pure computation + the one real network call,
mirroring how gu_pet.py itself stays DB-free).

Purely additive: config.OPENAI_API_KEY unset, or ANY failure along the way (network error,
timeout, malformed response), degrades to "no portrait" -- generate_pet_image never raises,
and nothing else about acquiring or using a Gu Pet depends on a portrait existing.

generate_pet_image is awaited directly, never wrapped in asyncio.to_thread -- that idiom is
reserved in this codebase for offloading sync/blocking DB calls onto a thread, not genuine
async network I/O (this bot makes zero OTHER outbound network calls anywhere, so there's no
existing precedent to follow here beyond that general principle).

Uses aiohttp directly (already a transitive dependency of discord.py, so this needed zero new
requirements.txt entry) rather than the official openai SDK, since only one simple endpoint
is ever called.
"""

import base64
import random
from typing import Optional

import aiohttp

import config
from . import gu_pet

OPENAI_IMAGE_ENDPOINT = "https://api.openai.com/v1/images/generations"
OPENAI_IMAGE_MODEL = "gpt-image-1"
OPENAI_IMAGE_SIZE = "1024x1024"
OPENAI_REQUEST_TIMEOUT_SECONDS = 60

# should_generate_unique_image/PORTRAIT_VARIANT_COUNT/pet_flavor_seed all now live in gu_pet.py
# itself (moved there so GameManager.crystallize_gu_pet can generate a pet's NAME from the
# exact same seed this module's own build_pet_prompt uses -- see gu_pet.pet_flavor_seed's own
# docstring) -- re-exported here so existing callers of gu_pet_images.should_generate_unique_
# image don't need to change.
should_generate_unique_image = gu_pet.should_generate_unique_image


def build_pet_prompt(pet: dict) -> str:
    """pet needs species/path/rank/pet_id set (i.e. already crystallized -- see GameManager.
    crystallize_gu_pet) -- a still-growing pet has no species yet to portray."""
    species = gu_pet.SPECIES[pet["species"]]
    rng = random.Random(gu_pet.pet_flavor_seed(pet))
    element = rng.choice(gu_pet.FLAVOR_ELEMENT_OPTIONS.get(pet["species"], ["spirit qi"]))
    palette = rng.choice(gu_pet.FLAVOR_COLOR_PALETTE_OPTIONS.get(pet["species"], ["muted earth tones"]))
    temperament = rng.choice(gu_pet.FLAVOR_TEMPERAMENT_OPTIONS.get(pet["path"], ["calm"]))
    markings = rng.choice(gu_pet.FLAVOR_MARKINGS)
    pose = rng.choice(gu_pet.FLAVOR_POSE)
    intensity = gu_pet.FLAVOR_RANK_INTENSITY.get(pet["rank"], "a")
    rarity = gu_pet.rank_to_rarity(pet["rank"])
    # The pet's own generated name (see gu_pet.generate_pet_name) is drawn from this exact
    # same seed -- threading it into the prompt too means the name's own random prefix/core
    # words (Frost/Ember/Crimson/Shell/Fang/...) become additional descriptive material for
    # the model to draw on, not just a display label, widening the image's own random space
    # further without introducing a second, uncoordinated source of randomness.
    name = pet.get("name") or gu_pet.generate_pet_name(random.Random(gu_pet.pet_flavor_seed(pet)))
    return (
        f"A detailed dark xianxia Gu-cultivation portrait, in the grim, insect-and-beast Gu "
        f"aesthetic of the novel Reverend Insanity -- ancient, eldritch, and sinister rather "
        f"than bright or whimsical -- of {intensity} {species.name} known among cultivators as "
        f"the \"{name}\", a Gu-beast spirit companion infused with {element}, marked with "
        f"{markings}. Color palette: {palette}. Temperament: {temperament}. Pose: {pose}. "
        f"{species.tagline} Rarity tier: {rarity}. Square composition, single centered subject, "
        f"dramatic moody lighting, painterly dark-fantasy game-art style. No text, no watermark, "
        f"no UI elements, no borders, no frame."
    )


def get_pet_cache_key(pet: dict) -> str:
    """Deterministic across every Rank I-III pet that lands on the same species+path+rank+
    variant bucket (see gu_pet.pet_flavor_seed/PORTRAIT_VARIANT_COUNT) -- nothing else feeds
    build_pet_prompt for this tier, so this fully determines its prompt."""
    return f"{pet['species']}|{pet['path']}|{pet['rank']}|{gu_pet.pet_flavor_seed(pet)}"


async def generate_pet_image(pet: dict) -> Optional[bytes]:
    """The real API call -- awaited directly (see module docstring). Returns the raw PNG
    bytes, or None on ANY failure (missing key, network error, timeout, non-200 response,
    malformed body) -- never raises, since a missing portrait must never block a pet grant."""
    if not config.OPENAI_API_KEY:
        return None
    prompt = build_pet_prompt(pet)
    headers = {"Authorization": f"Bearer {config.OPENAI_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": OPENAI_IMAGE_MODEL, "prompt": prompt, "size": OPENAI_IMAGE_SIZE, "n": 1}
    try:
        timeout = aiohttp.ClientTimeout(total=OPENAI_REQUEST_TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(OPENAI_IMAGE_ENDPOINT, headers=headers, json=payload) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                b64 = data["data"][0]["b64_json"]
                return base64.b64decode(b64)
    except Exception:
        return None
