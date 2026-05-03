"""Catalog of public APIs for real-time data lookups.

Each API definition includes:
- endpoint: Base URL for the API
- auth: Auth type ("none", "api_key", "oauth") or None
- auth_header: Header name if auth required
- params: Required query parameters template
- response_mapping: How to extract display data from response
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class APIDefinition:
    """Definition for a public API."""

    name: str
    description: str
    endpoint: str
    method: str = "GET"
    auth: str | None = None  # "none", "api_key", "oauth"
    auth_header: str | None = None
    params: dict[str, str] = field(default_factory=dict)
    response_mapping: dict[str, str] = field(default_factory=dict)
    category: str = "general"


# Registry of available public APIs
PUBLIC_APIS: dict[str, APIDefinition] = {
    # ── Weather ────────────────────────────────────────────────────────────────
    "weather": APIDefinition(
        name="Open-Meteo",
        description="Free weather API - no API key required",
        endpoint="https://api.open-meteo.com/v1/forecast",
        method="GET",
        auth="none",
        params={
            "latitude": "{lat}",
            "longitude": "{lon}",
            "current_weather": "true",
            "temperature_unit": "celsius",
        },
        response_mapping={
            "temperature": "current_weather.temperature",
            "condition": "current_weather.weathercode",
            "wind_speed": "current_weather.windspeed",
            "time": "current_weather.time",
        },
        category="weather",
    ),
    # Geocoding for weather (convert city name → lat/lon)
    "geocoding": APIDefinition(
        name="Open-Meteo Geocoding",
        description="Convert city names to coordinates",
        endpoint="https://geocoding-api.open-meteo.com/v1/search",
        method="GET",
        auth="none",
        params={
            "name": "{city}",
            "count": "1",
            "language": "en",
            "format": "json",
        },
        response_mapping={
            "latitude": "results[0].latitude",
            "longitude": "results[0].longitude",
            "name": "results[0].name",
            "country": "results[0].country",
        },
        category="weather",
    ),
    # ── Finance ────────────────────────────────────────────────────────────────
    "stock_quote": APIDefinition(
        name="Marketstack",
        description="Real-time and historical stock market data",
        endpoint="http://api.marketstack.com/v1/eod",
        method="GET",
        auth="api_key",
        auth_header="apikey",
        params={
            "symbols": "{symbol}",
            "limit": "1",
        },
        response_mapping={
            "symbol": "data[0].symbol",
            "close": "data[0].close",
            "date": "data[0].date",
            "change": "data[0].change",
            "change_pct": "data[0].change_pct",
        },
        category="finance",
    ),
    # ── Sports ─────────────────────────────────────────────────────────────────
    "football_scores": APIDefinition(
        name="API-Football (free tier)",
        description="Live football/soccer scores and fixtures",
        endpoint="https://v3.football.api-sports.io/fixtures",
        method="GET",
        auth="api_key",
        auth_header="x-apisports-key",
        params={
            "live": "all",
        },
        response_mapping={
            "fixtures": "response",
        },
        category="sports",
    ),
    # ── News ───────────────────────────────────────────────────────────────────
    "news": APIDefinition(
        name="NewsAPI",
        description="Top headlines and breaking news",
        endpoint="https://newsapi.org/v2/top-headlines",
        method="GET",
        auth="api_key",
        auth_header="X-Api-Key",
        params={
            "country": "us",
            "pageSize": "5",
        },
        response_mapping={
            "articles": "articles",
        },
        category="news",
    ),
    # ── Crypto ─────────────────────────────────────────────────────────────────
    "crypto_price": APIDefinition(
        name="CoinGecko",
        description="Cryptocurrency prices and market data",
        endpoint="https://api.coingecko.com/api/v3/simple/price",
        method="GET",
        auth="none",
        params={
            "ids": "{crypto_id}",
            "vs_currencies": "usd",
            "include_24hr_change": "true",
        },
        response_mapping={
            "price": "{crypto_id}.usd",
            "change_24h": "{crypto_id}.usd_24h_change",
        },
        category="crypto",
    ),
    # ── Time & Date ────────────────────────────────────────────────────────────
    "world_time": APIDefinition(
        name="WorldTimeAPI",
        description="Current time by timezone",
        endpoint="http://worldtimeapi.org/api/timezone",
        method="GET",
        auth="none",
        params={},
        response_mapping={
            "datetime": "datetime",
            "timezone": "timezone",
            "utc_offset": "utc_offset",
        },
        category="time",
    ),
    # ── IP Geolocation ─────────────────────────────────────────────────────────
    "ip_lookup": APIDefinition(
        name="IP-API",
        description="IP address geolocation",
        endpoint="http://ip-api.com/json",
        method="GET",
        auth="none",
        params={
            "query": "{ip}",
        },
        response_mapping={
            "city": "city",
            "country": "country",
            "isp": "isp",
            "lat": "lat",
            "lon": "lon",
        },
        category="geolocation",
    ),
    # ── Animals ────────────────────────────────────────────────────────────────
    "dog_fact": APIDefinition(
        name="Dog API",
        description="Random dog facts and images",
        endpoint="https://dogapi.dog/api/v2/facts",
        method="GET",
        auth="none",
        params={},
        response_mapping={
            "fact": "data[0].attributes.body",
        },
        category="animals",
    ),
    "cat_fact": APIDefinition(
        name="Cat Fact API",
        description="Random cat facts",
        endpoint="https://catfact.ninja/fact",
        method="GET",
        auth="none",
        params={},
        response_mapping={
            "fact": "fact",
        },
        category="animals",
    ),
    # ── Quotes ─────────────────────────────────────────────────────────────────
    "quote": APIDefinition(
        name="Zen Quotes",
        description="Inspirational quotes",
        endpoint="https://zenquotes.io/api/random",
        method="GET",
        auth="none",
        params={},
        response_mapping={
            "quote": "q",
            "author": "a",
        },
        category="quotes",
    ),
    # ── Jokes ──────────────────────────────────────────────────────────────────
    "joke": APIDefinition(
        name="Joke API",
        description="Random jokes",
        endpoint="https://v2.jokeapi.dev/joke/Any",
        method="GET",
        auth="none",
        params={
            "safe-mode": "",
        },
        response_mapping={
            "joke": "joke",
            "setup": "setup",
            "delivery": "delivery",
        },
        category="entertainment",
    ),
    # ── Advice ─────────────────────────────────────────────────────────────────
    "advice": APIDefinition(
        name="Advice Slip",
        description="Random advice",
        endpoint="https://api.adviceslip.com/advice",
        method="GET",
        auth="none",
        params={},
        response_mapping={
            "advice": "slip.advice",
        },
        category="entertainment",
    ),
}

# Weather code descriptions for Open-Meteo
WEATHER_CODES: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Foggy",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    61: "Slight rain",
    63: "Rain",
    65: "Heavy rain",
    71: "Slight snow fall",
    73: "Snow fall",
    75: "Heavy snow fall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


def get_api_definition(api_key: str) -> APIDefinition | None:
    """Get API definition by key."""
    return PUBLIC_APIS.get(api_key)


def get_apis_by_category(category: str) -> dict[str, APIDefinition]:
    """Get all APIs in a category."""
    return {key: api for key, api in PUBLIC_APIS.items() if api.category == category}


def get_available_categories() -> set[str]:
    """Get all available categories."""
    return {api.category for api in PUBLIC_APIS.values()}
