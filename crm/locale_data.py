"""Country, city, area, dial-code and currency data, plus money conversion/formatting.

All money is stored in BASE_CURRENCY and converted for display or entry.
"""
from contextvars import ContextVar
import math
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

BASE_CURRENCY = "QAR"
# Value of 1 unit in QAR. Indicative fixed rates; update here when needed.
CURRENCIES = {
    "QAR": {"label": "QAR · Qatari Riyal", "symbol": "QAR ", "rate": Decimal("1")},
    "USD": {"label": "USD · US Dollar", "symbol": "$", "rate": Decimal("3.64")},
    "AED": {"label": "AED · UAE Dirham", "symbol": "AED ", "rate": Decimal("0.991")},
    "SAR": {"label": "SAR · Saudi Riyal", "symbol": "SAR ", "rate": Decimal("0.970")},
    "KWD": {"label": "KWD · Kuwaiti Dinar", "symbol": "KWD ", "rate": Decimal("11.85")},
    "BHD": {"label": "BHD · Bahraini Dinar", "symbol": "BHD ", "rate": Decimal("9.66")},
    "OMR": {"label": "OMR · Omani Rial", "symbol": "OMR ", "rate": Decimal("9.46")},
    "INR": {"label": "INR · Indian Rupee", "symbol": "₹", "rate": Decimal("0.0437")},
    "PKR": {"label": "PKR · Pakistani Rupee", "symbol": "PKR ", "rate": Decimal("0.0131")},
    "PHP": {"label": "PHP · Philippine Peso", "symbol": "₱", "rate": Decimal("0.0636")},
    "EGP": {"label": "EGP · Egyptian Pound", "symbol": "EGP ", "rate": Decimal("0.0750")},
    "GBP": {"label": "GBP · British Pound", "symbol": "£", "rate": Decimal("4.62")},
}
CURRENCY_CHOICES = [(code, c["label"]) for code, c in CURRENCIES.items()]

current_currency = ContextVar("current_currency", default=BASE_CURRENCY)

# iso, name, flag, dial code, {city: [areas]}
COUNTRIES = [
    ("QA", "Qatar", "🇶🇦", "+974", {
        "Doha": ["West Bay", "The Pearl-Qatar", "Al Sadd", "Msheireb", "Al Dafna", "Old Airport", "Bin Mahmoud",
                 "Fereej Bin Omran", "Al Waab", "Abu Hamour", "Al Hilal", "Najma"],
        "Lusail": ["Marina District", "Fox Hills", "Energy City", "Al Erkyah", "Qetaifan Island", "Lusail Boulevard"],
        "Al Wakrah": ["Al Wakrah Corniche", "Al Wukair", "Barwa City", "Mesaimeer"],
        "Al Rayyan": ["Education City", "Al Gharrafa", "Muaither", "Ain Khaled", "Al Luqta"],
        "Al Khor": ["Al Khor Corniche", "Al Thakhira", "Simaisma"],
        "Umm Salal": ["Umm Salal Mohammed", "Umm Salal Ali"],
    }),
    ("AE", "United Arab Emirates", "🇦🇪", "+971", {
        "Dubai": ["Dubai Marina", "Downtown Dubai", "JLT", "Business Bay", "Palm Jumeirah"],
        "Abu Dhabi": ["Al Reem Island", "Yas Island", "Saadiyat Island"],
        "Sharjah": ["Al Majaz", "Al Nahda"],
    }),
    ("SA", "Saudi Arabia", "🇸🇦", "+966", {
        "Riyadh": ["Al Olaya", "Al Malqa"], "Jeddah": ["Al Rawdah", "Obhur"], "Dammam": ["Al Faisaliyah"],
    }),
    ("KW", "Kuwait", "🇰🇼", "+965", {"Kuwait City": ["Salmiya", "Hawalli", "Sharq"]}),
    ("BH", "Bahrain", "🇧🇭", "+973", {"Manama": ["Seef", "Juffair", "Amwaj Islands"]}),
    ("OM", "Oman", "🇴🇲", "+968", {"Muscat": ["Al Mouj", "Qurum", "Al Khuwair"]}),
    ("IN", "India", "🇮🇳", "+91", {
        "Chennai": ["Velachery", "Adyar", "Anna Nagar", "OMR"], "Mumbai": ["Andheri", "Bandra", "Powai"],
        "Bengaluru": ["Whitefield", "Koramangala"], "Kochi": ["Kakkanad", "Edappally"], "Hyderabad": ["Gachibowli"],
    }),
    ("PK", "Pakistan", "🇵🇰", "+92", {"Karachi": ["DHA", "Clifton"], "Lahore": ["Gulberg", "DHA"]}),
    ("PH", "Philippines", "🇵🇭", "+63", {"Manila": ["Makati", "BGC"]}),
    ("EG", "Egypt", "🇪🇬", "+20", {"Cairo": ["New Cairo", "Zamalek"]}),
    ("GB", "United Kingdom", "🇬🇧", "+44", {"London": ["Canary Wharf", "Kensington"], "Manchester": ["Salford"]}),
    ("US", "United States", "🇺🇸", "+1", {"New York": ["Manhattan", "Brooklyn"], "Houston": ["Downtown"]}),
]
DEFAULT_COUNTRY = "QA"
DEFAULT_DIAL = "+974"
COUNTRY_CHOICES = [(iso, f"{flag} {name}") for iso, name, flag, _dial, _cities in COUNTRIES]
DIAL_CHOICES = [(dial, f"{flag} {dial}") for _iso, _name, flag, dial, _cities in COUNTRIES]
COUNTRY_NAMES = {iso: name for iso, name, *_ in COUNTRIES}

# Approximate city centres, used for "nearby" project matching and map demand circles.
CITY_CENTERS = {
    ("QA", "doha"): (25.2854, 51.5310),
    ("QA", "lusail"): (25.4207, 51.4904),
    ("QA", "al wakrah"): (25.1715, 51.6034),
    ("QA", "al rayyan"): (25.2919, 51.4244),
    ("QA", "al khor"): (25.6839, 51.5058),
    ("QA", "umm salal"): (25.4152, 51.4065),
    ("AE", "dubai"): (25.2048, 55.2708),
    ("AE", "abu dhabi"): (24.4539, 54.3773),
    ("AE", "sharjah"): (25.3463, 55.4209),
    ("SA", "riyadh"): (24.7136, 46.6753),
    ("SA", "jeddah"): (21.4858, 39.1925),
    ("KW", "kuwait city"): (29.3759, 47.9774),
    ("BH", "manama"): (26.2285, 50.5860),
    ("OM", "muscat"): (23.5880, 58.3829),
}


def city_center(country, city):
    return CITY_CENTERS.get((country, (city or "").strip().lower()))


def distance_km(a, b):
    """Great-circle distance between two (lat, lng) points."""
    lat1, lng1, lat2, lng2 = map(math.radians, (float(a[0]), float(a[1]), float(b[0]), float(b[1])))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))
COUNTRY_CURRENCY = {
    "QA": "QAR", "AE": "AED", "SA": "SAR", "KW": "KWD", "BH": "BHD", "OM": "OMR",
    "IN": "INR", "PK": "PKR", "PH": "PHP", "EG": "EGP", "GB": "GBP", "US": "USD",
}


def currency_for(iso):
    return COUNTRY_CURRENCY.get(iso, BASE_CURRENCY)


def geo_data():
    """Shape consumed by the lead form JS: {iso: {dial, currency, cities: {city: [areas]}}}."""
    return {iso: {"dial": dial, "currency": currency_for(iso), "cities": cities}
            for iso, _n, _f, dial, cities in COUNTRIES}


def country_code(value):
    """Accept an ISO code or a country name (for imports)."""
    text = str(value or "").strip().lower()
    for iso, name, *_ in COUNTRIES:
        if text in (iso.lower(), name.lower()):
            return iso
    return None


def dial_for(iso):
    return next((dial for code, _n, _f, dial, _c in COUNTRIES if code == iso), DEFAULT_DIAL)


def country_for_dial(dial):
    return next((code for code, _n, _f, d, _c in COUNTRIES if d == dial), DEFAULT_COUNTRY)


# ---------------------------------------------------------------- money

def _dec(value):
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def to_base(amount, currency):
    amount = _dec(amount)
    if amount is None:
        return None
    rate = CURRENCIES.get(currency, CURRENCIES[BASE_CURRENCY])["rate"]
    return (amount * rate).quantize(Decimal("0.01"), ROUND_HALF_UP)


def from_base(amount, currency=None):
    amount = _dec(amount)
    if amount is None:
        return None
    rate = CURRENCIES.get(currency or current_currency.get(), CURRENCIES[BASE_CURRENCY])["rate"]
    return (amount / rate).quantize(Decimal("0.01"), ROUND_HALF_UP)


def _group(whole, indian):
    if not indian or len(whole) <= 3:
        return f"{int(whole):,}"
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups + [tail])


def format_money(value, currency=None):
    """Full amount in the display currency, e.g. QAR 1,250,000 / $343,407 / ₹2,86,04,119."""
    currency = currency or current_currency.get()
    amount = from_base(value, currency)
    if amount is None:
        return ""
    sign = "-" if amount < 0 else ""
    whole = f"{abs(amount):.0f}"
    return f"{sign}{CURRENCIES[currency]['symbol']}{_group(whole, currency == 'INR')}"


def format_money_short(value, currency=None):
    """Compact amount: QAR 1.25M / $343K / ₹2.86 Cr."""
    currency = currency or current_currency.get()
    amount = from_base(value, currency)
    if amount is None:
        amount = Decimal("0")
    symbol = CURRENCIES[currency]["symbol"]
    a = abs(amount)
    if currency == "INR":
        if a >= 10_000_000:
            text = f"{amount / 10_000_000:.2f} Cr"
        elif a >= 100_000:
            text = f"{amount / 100_000:.1f} L"
        else:
            return format_money(value, currency)
    elif a >= 1_000_000_000:
        text = f"{amount / 1_000_000_000:.2f}B"
    elif a >= 1_000_000:
        text = f"{amount / 1_000_000:.2f}M"
    elif a >= 10_000:
        text = f"{amount / 1_000:.0f}K"
    else:
        return format_money(value, currency)
    return symbol + text.replace(".00", "").replace(".0 ", " ")
