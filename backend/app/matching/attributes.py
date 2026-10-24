"""Extract identity attributes (brand, storage, RAM, tier, generation…) from listing titles."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

KNOWN_BRANDS = [
    "apple", "samsung", "oneplus", "xiaomi", "redmi", "poco", "realme", "oppo", "vivo", "iqoo",
    "motorola", "nothing", "google", "nokia", "honor", "infinix", "tecno", "lava", "asus", "lenovo",
    "hp", "dell", "acer", "msi", "microsoft", "lg", "sony", "boat", "jbl", "bose", "sennheiser",
    "marshall", "noise", "amazfit", "garmin", "fitbit", "huawei", "tcl", "hisense", "mi", "panasonic",
    "philips", "canon", "nikon", "fujifilm", "gopro", "dji", "epson", "brother", "logitech", "razer",
    "corsair", "hyperx", "zebronics", "tp-link", "d-link", "netgear", "sandisk", "western digital", "wd",
    "seagate", "crucial", "kingston", "intel", "amd", "nvidia", "gigabyte", "zotac", "anker", "ambrane",
    "portronics", "belkin", "nintendo", "playstation", "xbox", "benq", "viewsonic", "skullcandy", "jabra",
]
COMPONENT_BRANDS = {"intel", "amd", "nvidia", "qualcomm", "mediatek"}
BRAND_ALIASES = {"wd": "western digital", "mi": "xiaomi", "playstation": "sony", "xbox": "microsoft"}

TIER_TOKENS = {"pro", "max", "plus", "ultra", "mini", "lite", "fe", "air", "se", "neo", "prime", "edge", "fold", "flip"}
REFURB_RE = re.compile(r"\b(refurbished|refurb|renewed|restored|pre-?owned|used|open[- ]box|unboxed|second ?hand)\b", re.I)
# US carrier-locked phones (Verizon, AT&T …) are a different, region-specific product from the Indian retail version.
CARRIER_RE = re.compile(r"\b(verizon|at&t|at ?& ?t|t-mobile|tmobile|sprint|us cellular|cricket wireless|boost mobile)\b", re.I)
COLOURS = [
    "black", "white", "blue", "green", "red", "pink", "purple", "yellow", "gold", "silver", "grey", "gray",
    "graphite", "titanium", "midnight", "starlight", "teal", "ultramarine", "orange", "cream", "lavender",
    "natural titanium", "desert titanium", "space black", "space grey", "space gray", "mint", "violet",
]

# Listings for accessories that carry a device's name ("iPhone 16 case", "Skin for iPhone 16 Plus").
ACCESSORY_RE = re.compile(
    r"(?<!charging )(?<!magsafe )(?<!wireless )\b(case|cases|cover|covers|skin|skins|screen ?protector|screen ?guard|"
    r"tempered glass|lens protector|camera protector|back glass|pouch|bumper|decal|sticker|wrap)\b"
    r"|\b(for|compatible with|fits)\s+(apple\s+)?(iphone|ipad|macbook|galaxy|pixel|oneplus|airpods|apple watch)\b",
    re.I,
)
# Listings that are not a product at all (services, placeholder/duplicate catalogue rows).
NON_PRODUCT_RE = re.compile(r"\bduplicate-\d+|\bunlock(ing)?\b|\bunlock service\b|\brepair\b|\b(on )?rent(al)?\b|\bfor hire\b|\bemi only\b", re.I)

STORAGE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(tb|gb)\b(?!\s*ram)", re.I)
RAM_RE = re.compile(r"(\d+)\s*gb\s*(?:lpddr\w*\s*|ddr\w*\s*)?ram\b|\bram\s*:?\s*(\d+)\s*gb", re.I)
RAM_SLASH_RE = re.compile(r"\b(\d{1,2})\s*gb\s*[/+|,]\s*(\d{2,4})\s*gb\b", re.I)  # "8GB/256GB" or "8GB+128GB"
SCREEN_RE = re.compile(r"(\d{2}(?:\.\d)?)\s*(?:-|\s)?(?:inch|inches|\"|”|in\b|cm)", re.I)
TOKEN_RE = re.compile(r"[a-z0-9]+(?:[-.][a-z0-9]+)*")
# Spec text that contains numbers but says nothing about which model it is (laptop titles are full of it).
SPEC_NOISE_RE = re.compile(
    r"\b(?:windows|win)\s*\d+\b"                                   # Windows 11
    r"|\b(?:rtx|gtx|rx|mx|arc)\s*[a-z]?\d{3,4}[a-z]{0,2}\b"        # GPU models
    r"|\b\d+(?:[ .]\d+)?\s*(?:cm|cms|inch|inches|hz|w|mm)\b"      # 40.64 cm, 144 Hz
    r"|\b\d+(?:st|nd|rd|th)\s*gen\b"                               # 14th Gen
    r"|\b(?:ddr|lpddr|gddr)\d+x?\b"                                  # DDR5
    r"|\b(?:ms\s*office|mso|m365|office)\s*\d*\b",                 # bundled software
    re.I)
ATTR_TOKEN_RE = re.compile(r"^\d+(gb|tb|mb|mah|w|hz|mp|cm|inch|inches|mm|g|kg)$")
STOPWORDS = {
    "with", "and", "the", "for", "of", "in", "new", "edition", "version", "smartphone", "mobile", "phone",
    "ram", "rom", "storage", "gb", "tb", "inch", "inches", "cm", "colour", "color", "5g", "4g", "lte",
    "wifi", "wi-fi", "dual", "sim", "display", "camera", "battery", "india", "unlocked", "a", "an",
}


@dataclass
class Attributes:
    brand: str | None = None
    storage_gb: int | None = None
    ram_gb: int | None = None
    colour: str | None = None
    condition: str = "new"
    screen_inches: float | None = None
    tier: frozenset[str] = field(default_factory=frozenset)
    model_tokens: frozenset[str] = field(default_factory=frozenset)  # tokens containing digits, e.g. "16", "s24"
    core_tokens: frozenset[str] = field(default_factory=frozenset)
    family: str | None = None
    kind: str = "device"  # device / accessory
    region: str | None = None  # "us_carrier" for carrier-locked US phones


def _to_gb(value: str, unit: str) -> int:
    v = float(value)
    return int(round(v * 1024)) if unit.lower() == "tb" else int(round(v))


def normalize_text(text: str) -> str:
    text = text.lower().replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text).strip()


def detect_brand(title: str, brand_hint: str | None = None) -> str | None:
    if brand_hint:
        b = normalize_text(brand_hint)
        return BRAND_ALIASES.get(b, b)
    t = normalize_text(title)
    # The brand named first wins ("ASUS TUF … NVIDIA GeForce" is an ASUS). Component makers (Intel, AMD, NVIDIA…)
    # count only when no device brand is named, so a laptop's GPU/CPU never becomes its brand.
    found: list[tuple[int, int, str]] = []
    for b in KNOWN_BRANDS:
        m = re.search(rf"(?<![a-z0-9]){re.escape(b)}(?![a-z0-9])", t)
        if m:
            found.append((b in COMPONENT_BRANDS, m.start(), -len(b), b))
    if found:
        b = min(found)[3]
        return BRAND_ALIASES.get(b, b)
    # iPhone/iPad/MacBook/AirPods imply Apple
    if re.search(r"\b(iphone|ipad|macbook|airpods|imac)\b", t):
        return "apple"
    if re.search(r"\bgalaxy\b", t):
        return "samsung"
    if re.search(r"\bpixel\b", t):
        return "google"
    return None


def extract_attributes(title: str, brand_hint: str | None = None, colour_hint: str | None = None) -> Attributes:
    t = normalize_text(title)
    attrs = Attributes()
    attrs.brand = detect_brand(title, brand_hint)
    attrs.condition = "refurbished" if REFURB_RE.search(t) else "new"
    attrs.kind = "accessory" if ACCESSORY_RE.search(t) else "device"
    attrs.region = "us_carrier" if CARRIER_RE.search(t) else None

    # RAM first ("8GB RAM", "RAM 8GB", "8GB/256GB"), then storage from the remaining text.
    remaining = t
    m = RAM_RE.search(t)
    if m:
        attrs.ram_gb = int(m.group(1) or m.group(2))
        remaining = t[: m.start()] + " " + t[m.end():]
    else:
        ms = RAM_SLASH_RE.search(t)
        if ms and int(ms.group(1)) <= 32 and int(ms.group(2)) >= 32:
            attrs.ram_gb = int(ms.group(1))
            attrs.storage_gb = int(ms.group(2))
            remaining = t[: ms.start()] + " " + t[ms.end():]
    if attrs.storage_gb is None:
        candidates = [_to_gb(v, u) for v, u in STORAGE_RE.findall(remaining)]
        # storage sizes are >= 16 GB; smaller numbers in titles are usually RAM or VRAM
        storage = [c for c in candidates if c >= 16]
        if storage:
            attrs.storage_gb = max(storage)
        if attrs.ram_gb is None:
            small = [c for c in candidates if c < 16 and c in (2, 3, 4, 6, 8, 12)]
            if small and storage:
                attrs.ram_gb = small[0]

    sm = SCREEN_RE.search(t)
    if sm:
        val = float(sm.group(1))
        unit_txt = t[sm.start(): sm.end()]
        if "cm" in unit_txt:
            val = round(val / 2.54, 1)
        if 3 <= val <= 120:
            attrs.screen_inches = val

    colour = None
    if colour_hint:
        colour = normalize_text(colour_hint)
    else:
        for c in sorted(COLOURS, key=len, reverse=True):
            if re.search(rf"\b{re.escape(c)}\b", t):
                colour = c
                break
    attrs.colour = colour.replace("gray", "grey") if colour else None

    # Identity tokens come from the "name" part of the title: marketing copy after ':' / '|' is dropped,
    # and capacity / screen expressions are removed so "128 GB" does not look like a model number.
    name_part = re.split(r"\s*[:|;]\s*|\s+-\s+", t, maxsplit=1)[0]
    if len(TOKEN_RE.findall(name_part)) < 2:
        name_part = t
    for rx in (SPEC_NOISE_RE, RAM_RE, RAM_SLASH_RE, STORAGE_RE, SCREEN_RE):
        name_part = rx.sub(" ", name_part)
    tokens = TOKEN_RE.findall(re.sub(r"[()\[\]]", " ", name_part))
    brand_tokens = set((attrs.brand or "").split())
    colour_tokens = set((attrs.colour or "").split())
    core = []
    for tok in tokens:
        if tok in STOPWORDS or tok in brand_tokens or tok in colour_tokens:
            continue
        if ATTR_TOKEN_RE.match(tok) or REFURB_RE.fullmatch(tok):
            continue
        core.append(tok)
    attrs.tier = frozenset(tok for tok in core if tok in TIER_TOKENS)
    def _is_model_token(tok: str) -> bool:
        if not any(ch.isdigit() for ch in tok):
            return False
        if re.fullmatch(r"(19|20)\d\d", tok):      # release year
            return False
        if re.fullmatch(r"\d+\.\d+", tok):         # decimal measurements such as 6.1
            return False
        return True

    attrs.model_tokens = frozenset(tok for tok in core if _is_model_token(tok))
    attrs.core_tokens = frozenset(core[:12])
    family_words = [tok for tok in core[:4] if tok not in TIER_TOKENS]
    attrs.family = " ".join(family_words[:3]) or None
    return attrs


CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("smartphones", ("iphone", "smartphone", "galaxy s", "galaxy a", "galaxy m", "galaxy z", "pixel", "redmi note", "oneplus nord", "5g mobile", "mobile phone")),
    ("laptops", ("laptop", "macbook", "notebook", "chromebook", "thinkpad", "vivobook", "ideapad", "zenbook")),
    ("tablets", ("ipad", "tablet", "galaxy tab", "tab s", "pad ")),
    ("smartwatches", ("smartwatch", "smart watch", "apple watch", "galaxy watch", "fitness band", "smart band")),
    ("headphones", ("earbuds", "headphone", "headset", "airpods", "tws", "neckband", "earphones", "buds")),
    ("speakers", ("speaker", "soundbar", "home theatre", "home theater")),
    ("televisions", ("smart tv", "television", " tv ", "qled", "oled tv", "led tv", "google tv")),
    ("monitors", ("monitor",)),
    ("components", ("graphics card", "processor", "motherboard", "ssd", "rtx", "radeon", "ryzen", "core i", "psu", "cabinet")),
    ("keyboards_mice", ("keyboard", "mouse", "mice")),
    ("cameras", ("camera", "dslr", "mirrorless", "gopro", "action cam")),
    ("gaming_consoles", ("playstation", "ps5", "xbox", "nintendo switch", "console")),
    ("printers", ("printer", "ink tank", "laserjet", "deskjet")),
    ("networking", ("router", "wi-fi mesh", "access point", "range extender", "modem")),
    ("storage", ("hard disk", "hard drive", "pendrive", "pen drive", "memory card", "microsd", "portable ssd", "flash drive")),
    ("accessories", ("charger", "cable", "power bank", "adapter", "case", "cover", "screen guard", "tempered glass")),
]


def classify_category(title: str, hint: str | None = None) -> str:
    if ACCESSORY_RE.search(normalize_text(title)):
        return "accessories"
    text = " " + normalize_text(f"{title} {hint or ''}") + " "
    for cat, keys in CATEGORY_RULES:
        if any(k in text for k in keys):
            return cat
    return "other"
