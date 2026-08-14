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

# Rank I-III (shared-cache tier, see get_pet_cache_key) pools its art into this many distinct
# looks PER species+rank, instead of exactly one -- bounded on purpose (this tier's whole
# point is capping API cost by reusing art across many players' pets), but "everyone's Rank 1
# Vampiric Beetle looks the literal same" was a real complaint once that bound was 1. Rank IV+
# (unique tier) needs no such bound -- every pet already gets its own real generation, so it
# uses the pet's own full pet_id instead (see _flavor_seed) for maximum variety.
PORTRAIT_VARIANT_COUNT = 6


def _flavor_seed(pet: dict) -> int:
    """Deterministic per-pet seed feeding every random.Random pick in build_pet_prompt/
    get_pet_cache_key -- same pet always reproduces the same flavor combination (e.g. if its
    stored image ever needs regenerating), but two different pets very rarely land on the
    exact same one. Rank I-III is deliberately bounded (see PORTRAIT_VARIANT_COUNT) since that
    tier's art is shared/cached across players; Rank IV+ uses the unbounded real pet_id."""
    if should_generate_unique_image(pet):
        return pet["pet_id"]
    return pet["pet_id"] % PORTRAIT_VARIANT_COUNT


def build_pet_prompt(pet: dict) -> str:
    """pet needs species/path/rank/pet_id set (i.e. already crystallized -- see GameManager.
    crystallize_gu_pet) -- a still-growing pet has no species yet to portray."""
    species = gu_pet.SPECIES[pet["species"]]
    rng = random.Random(_flavor_seed(pet))
    element = rng.choice(gu_pet.FLAVOR_ELEMENT_OPTIONS.get(pet["species"], ["spirit qi"]))
    palette = rng.choice(gu_pet.FLAVOR_COLOR_PALETTE_OPTIONS.get(pet["species"], ["muted earth tones"]))
    temperament = rng.choice(gu_pet.FLAVOR_TEMPERAMENT_OPTIONS.get(pet["path"], ["calm"]))
    markings = rng.choice(gu_pet.FLAVOR_MARKINGS)
    pose = rng.choice(gu_pet.FLAVOR_POSE)
    intensity = gu_pet.FLAVOR_RANK_INTENSITY.get(pet["rank"], "a")
    rarity = gu_pet.rank_to_rarity(pet["rank"])
    return (
        f"A detailed xianxia (Chinese cultivation fantasy) portrait of {intensity} {species.name}, "
        f"a Gu-beast spirit companion infused with {element}, marked with {markings}. "
        f"Color palette: {palette}. Temperament: {temperament}. Pose: {pose}. {species.tagline} "
        f"Rarity tier: {rarity}. Square composition, single centered subject, dramatic lighting, "
        f"painterly fantasy game-art style. No text, no watermark, no UI elements, no borders, no frame."
    )


def get_pet_cache_key(pet: dict) -> str:
    """Deterministic across every Rank I-III pet that lands on the same species+path+rank+
    variant bucket (see _flavor_seed/PORTRAIT_VARIANT_COUNT) -- nothing else feeds
    build_pet_prompt for this tier, so this fully determines its prompt."""
    return f"{pet['species']}|{pet['path']}|{pet['rank']}|{_flavor_seed(pet)}"


def should_generate_unique_image(pet: dict) -> bool:
    return pet["rank"] >= 4  # Epic+ (see gu_pet.GU_PET_RANK_TO_RARITY)


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
