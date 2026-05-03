"""Route user intents to public APIs with fallback to Tavily.

This module provides:
1. Intent detection from user messages
2. Parameter extraction for API calls
3. API execution with retry logic
4. Response formatting for LLM consumption
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import httpx
from loguru import logger

from .public_apis_catalog import PUBLIC_APIS, WEATHER_CODES

# ── Intent Detection ──────────────────────────────────────────────────────────

# Regex patterns for extracting parameters from user queries
_CITY_PATTERN = re.compile(
    r"(?:weather|temperature|forecast|conditions?)\s+(?:in\s+)?([A-Za-z][A-Za-z\s\.\-']+?)(?:\s*(?:today|now|current|$))|(?:weather|temperature|forecast)\s+(?:in\s+)?([A-Za-z][\w\s]+)",
    re.IGNORECASE,
)
_STOCK_PATTERN = re.compile(
    r"\b([A-Z]{2,5})\s+stock\b|\bstock\s+(?:price\s+)?(?:of\s+|for\s+)?([A-Z]{2,5})\b|\bticker\s+(?:for\s+)?([A-Z]{2,5})\b",
    re.IGNORECASE,
)
_CRYPTO_PATTERN = re.compile(
    r"(?:crypto|bitcoin|ethereum|price)\s+(?:of\s+|for\s+)?([a-zA-Z]+)(?:\s|$)",
    re.IGNORECASE,
)
_TIMEZONE_PATTERN = re.compile(
    r"(?:time|clock|current time)\s+(?:in\s+)?([A-Za-z][A-Za-z\s/]+?)(?:\s*(?:now|today|$))",
    re.IGNORECASE,
)


@dataclass
class IntentResult:
    """Result of intent detection."""

    intent: str | None  # API key from PUBLIC_APIS or None
    params: dict[str, Any]
    confidence: float  # 0.0-1.0


def detect_intent(message: str) -> IntentResult:
    """Detect intent from user message.

    Returns IntentResult with:
    - intent: API key if matched (e.g., "weather", "stock_quote")
    - params: Extracted parameters for the API call
    - confidence: How confident we are in the match
    """
    text = message.strip()
    text_lower = text.lower()

    # ── Weather intent ────────────────────────────────────────────────────────
    if (
        "weather" in text_lower
        or "temperature" in text_lower
        or "forecast" in text_lower
    ):
        match = _CITY_PATTERN.search(text)
        if match:
            # Pattern has two groups - try group 1 first, then group 2
            city = match.group(1) if match.group(1) else match.group(2)
            if city:
                city = city.strip()
                logger.info("Intent detected: weather for city={!r}", city)
                return IntentResult(
                    intent="weather",
                    params={"city": city},
                    confidence=0.9,
                )
        # Fallback: weather mentioned but no city found
        logger.info("Intent detected: weather (no city specified)")
        return IntentResult(
            intent="weather",
            params={"city": "current location"},
            confidence=0.5,
        )

    # Note: Stock/Finance intent removed - Marketstack requires API key.
    # Tavily handles financial queries instead.

    # ── Crypto intent ────────────────────────────────────────────────────────
    if any(
        kw in text_lower for kw in ["crypto", "bitcoin", "ethereum", "crypto price"]
    ):
        # Map common names to CoinGecko IDs
        crypto_id = "bitcoin"  # default
        if "ethereum" in text_lower:
            crypto_id = "ethereum"
        elif "bitcoin" in text_lower:
            crypto_id = "bitcoin"
        else:
            match = _CRYPTO_PATTERN.search(text)
            if match:
                crypto_id = match.group(1).lower()

        logger.info("Intent detected: crypto price for id={!r}", crypto_id)
        return IntentResult(
            intent="crypto_price",
            params={"crypto_id": crypto_id},
            confidence=0.8,
        )

    # ── Time/World clock intent ──────────────────────────────────────────────
    if "time" in text_lower and ("what" in text_lower or "current" in text_lower):
        match = _TIMEZONE_PATTERN.search(text)
        if match:
            location = match.group(1).strip()
            logger.info("Intent detected: world time for location={!r}", location)
            return IntentResult(
                intent="world_time",
                params={"location": location},
                confidence=0.7,
            )

    # ── Animal facts ─────────────────────────────────────────────────────────
    if "dog fact" in text_lower or "tell me about dogs" in text_lower:
        logger.info("Intent detected: dog fact")
        return IntentResult(
            intent="dog_fact",
            params={},
            confidence=0.9,
        )

    if "cat fact" in text_lower or "tell me about cats" in text_lower:
        logger.info("Intent detected: cat fact")
        return IntentResult(
            intent="cat_fact",
            params={},
            confidence=0.9,
        )

    # ── Jokes ────────────────────────────────────────────────────────────────
    if "tell me a joke" in text_lower or "give me a joke" in text_lower:
        logger.info("Intent detected: joke")
        return IntentResult(
            intent="joke",
            params={},
            confidence=0.95,
        )

    # ── Advice ───────────────────────────────────────────────────────────────
    if "give me advice" in text_lower or "some advice" in text_lower:
        logger.info("Intent detected: advice")
        return IntentResult(
            intent="advice",
            params={},
            confidence=0.9,
        )

    # ── Quotes ───────────────────────────────────────────────────────────────
    if "inspirational quote" in text_lower or "motivational quote" in text_lower:
        logger.info("Intent detected: quote")
        return IntentResult(
            intent="quote",
            params={},
            confidence=0.9,
        )

    # No intent matched
    logger.debug("No public API intent detected in: {!r}", text[:100])
    return IntentResult(intent=None, params={}, confidence=0.0)


# ── API Execution ─────────────────────────────────────────────────────────────

# HTTP client with connection pooling
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    """Get or create HTTP client with connection pooling."""
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            timeout=10.0,
            follow_redirects=True,
            headers={"User-Agent": "FreeClaudeCode/1.0"},
        )
    return _http_client


async def _geocode_city(city: str) -> tuple[float, float] | None:
    """Geocode city name to lat/lon using Open-Meteo Geocoding API."""
    client = _get_http_client()
    api_def = PUBLIC_APIS.get("geocoding")
    if not api_def:
        return None

    try:
        url = api_def.endpoint
        params = {"name": city, "count": "1", "language": "en", "format": "json"}
        logger.info("Geocoding city={!r} via {}", city, api_def.name)

        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        results = data.get("results", [])
        if not results:
            logger.warning("Geocoding: no results for city={!r}", city)
            return None

        lat = results[0].get("latitude")
        lon = results[0].get("longitude")
        logger.info(
            "Geocoding: {!r} -> lat={}, lon={}",
            city,
            lat,
            lon,
        )
        return (lat, lon)
    except httpx.HTTPError as e:
        logger.warning("Geocoding failed for {!r}: {} - {}", city, type(e).__name__, e)
        return None
    except Exception as e:
        logger.warning("Geocoding error for {!r}: {}", city, e)
        return None


async def _fetch_weather(params: dict[str, Any]) -> str | None:
    """Fetch weather data for a city."""
    city = params.get("city")
    if not city:
        return None

    # Step 1: Geocode city to lat/lon
    coords = await _geocode_city(city)
    if not coords:
        # Fallback: try with default coordinates (London)
        logger.warning("Geocoding failed, using fallback coordinates")
        coords = (51.5074, -0.1278)  # London

    lat, lon = coords

    # Step 2: Fetch weather data
    client = _get_http_client()
    api_def = PUBLIC_APIS.get("weather")
    if not api_def:
        return None

    try:
        url = api_def.endpoint
        query_params = {
            "latitude": str(lat),
            "longitude": str(lon),
            "current_weather": "true",
            "temperature_unit": "celsius",
        }

        logger.info(
            "Fetching weather from {} lat={} lon={}",
            api_def.name,
            lat,
            lon,
        )

        response = await client.get(url, params=query_params)
        response.raise_for_status()
        data = response.json()

        current = data.get("current_weather", {})
        if not current:
            logger.warning("Weather API returned no current_weather data")
            return None

        temp = current.get("temperature", "N/A")
        weather_code = current.get("weathercode", 0)
        wind = current.get("windspeed", 0)
        time_str = current.get("time", "")

        condition = WEATHER_CODES.get(weather_code, "Unknown")

        result = f"Weather: {temp}°C, {condition}, Wind: {wind} km/h (as of {time_str})"
        logger.info("Weather fetched: {!r}", result)
        return result

    except httpx.HTTPError as e:
        logger.warning("Weather API failed: {} - {}", type(e).__name__, e)
        return None
    except Exception as e:
        logger.warning("Weather error: {}", e)
        return None


# Note: _fetch_stock_quote removed - Marketstack requires API key.
# Tavily handles financial queries instead.


async def _fetch_crypto_price(params: dict[str, Any]) -> str | None:
    """Fetch cryptocurrency price from CoinGecko."""
    crypto_id = params.get("crypto_id", "bitcoin")

    client = _get_http_client()
    api_def = PUBLIC_APIS.get("crypto_price")
    if not api_def:
        return None

    try:
        url = api_def.endpoint
        query_params = {
            "ids": crypto_id,
            "vs_currencies": "usd",
            "include_24hr_change": "true",
        }

        logger.info(
            "Fetching crypto price for {} from {}",
            crypto_id,
            api_def.name,
        )

        response = await client.get(url, params=query_params)
        response.raise_for_status()
        data = response.json()

        if crypto_id not in data:
            return f"No data found for {crypto_id}"

        price_data = data[crypto_id]
        price = price_data.get("usd")
        change_24h = price_data.get("usd_24h_change", 0)

        result = (
            f"{crypto_id.title()}: ${price:,.2f} USD "
            f"({'+' if change_24h > 0 else ''}{change_24h:.2f}% 24h)"
        )
        logger.info("Crypto price fetched: {!r}", result)
        return result

    except httpx.HTTPError as e:
        logger.warning("Crypto price API failed: {} - {}", type(e).__name__, e)
        return None
    except Exception as e:
        logger.warning("Crypto price error: {}", e)
        return None


async def _fetch_world_time(params: dict[str, Any]) -> str | None:
    """Fetch current time for a timezone/location."""
    location = params.get("location", "")

    # Map common locations to timezones
    tz_map = {
        "london": "Europe/London",
        "new york": "America/New_York",
        "tokyo": "Asia/Tokyo",
        "paris": "Europe/Paris",
        "sydney": "Australia/Sydney",
        "dubai": "Asia/Dubai",
        "singapore": "Asia/Singapore",
    }

    # Try to map location to timezone
    tz = tz_map.get(location.lower())
    if not tz:
        # Default to UTC if location not recognized
        tz = "UTC"
        logger.warning(
            "Timezone not found for {!r}, using UTC",
            location,
        )

    client = _get_http_client()
    api_def = PUBLIC_APIS.get("world_time")
    if not api_def:
        return None

    try:
        url = f"{api_def.endpoint}/{tz}"

        logger.info(
            "Fetching time for timezone {} from {}",
            tz,
            api_def.name,
        )

        response = await client.get(url)
        response.raise_for_status()
        data = response.json()

        datetime_str = data.get("datetime", "")
        # Extract just the time portion
        time_str = (
            datetime_str.split("T")[1][:5] if "T" in datetime_str else datetime_str
        )

        result = f"Current time in {tz}: {time_str}"
        logger.info("Time fetched: {!r}", result)
        return result

    except httpx.HTTPError as e:
        logger.warning("Time API failed: {} - {}", type(e).__name__, e)
        return None
    except Exception as e:
        logger.warning("Time error: {}", e)
        return None


async def _fetch_simple_fact(api_key: str) -> str | None:
    """Fetch simple facts (dog, cat, advice, joke, quote)."""
    client = _get_http_client()
    api_def = PUBLIC_APIS.get(api_key)
    if not api_def:
        return None

    try:
        url = api_def.endpoint
        params = api_def.params.copy() if api_def.params else {}

        logger.info("Fetching {} from {}", api_key, api_def.name)

        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        # Extract based on response mapping
        result = None
        for field, path in api_def.response_mapping.items():
            if "[" in path:
                # Handle array access like "data[0].attributes.body"
                parts = path.replace("]", "").split("[")
                key = parts[0]
                idx = int(parts[1]) if parts[1].isdigit() else 0
                nested = data.get(key, [])[idx] if key in data else {}
                for remaining in parts[2:]:
                    if "." in remaining:
                        for sub_key in remaining.split("."):
                            if isinstance(nested, dict):
                                nested = nested.get(sub_key, {})
                result = nested if nested else data.get(field)
            elif "." in path:
                # Handle nested access like "slip.advice"
                keys = path.split(".")
                value = data
                for k in keys:
                    if isinstance(value, dict):
                        value = value.get(k)
                    else:
                        value = None
                        break
                result = value if value else data.get(field)
            else:
                result = data.get(field)

            if result:
                break

        if result:
            logger.info(
                "Fetched {}: {!r}", api_key, result[:50] if len(result) > 50 else result
            )
            return result
        return None

    except httpx.HTTPError as e:
        logger.warning("{} API failed: {} - {}", api_key, type(e).__name__, e)
        return None
    except Exception as e:
        logger.warning("{} error: {}", api_key, e)
        return None


# ── Main Router ───────────────────────────────────────────────────────────────


async def route_to_public_api(intent: str, params: dict[str, Any]) -> str | None:
    """Route detected intent to appropriate API.

    Args:
        intent: API key from PUBLIC_APIS
        params: Extracted parameters for the API

    Returns:
        Formatted response string or None if API call failed
    """
    logger.info(
        "Routing intent={!r} with params={!r}",
        intent,
        params,
    )

    # Dispatch to appropriate handler
    if intent == "weather":
        return await _fetch_weather(params)
    elif intent == "crypto_price":
        return await _fetch_crypto_price(params)
    elif intent == "world_time":
        return await _fetch_world_time(params)
    elif intent in ("dog_fact", "cat_fact", "joke", "advice", "quote"):
        return await _fetch_simple_fact(intent)
    else:
        logger.warning("Unknown intent: {!r}", intent)
        return None


async def process_message_for_public_api(message: str) -> str | None:
    """High-level entry point: detect intent and fetch data.

    Args:
        message: User message text

    Returns:
        Formatted data string if API matched and succeeded, None otherwise
    """
    # Step 1: Detect intent
    intent_result = detect_intent(message)

    if not intent_result.intent:
        logger.debug("No public API intent detected")
        return None

    # Step 2: Check confidence threshold
    if intent_result.confidence < 0.5:
        logger.info(
            "Intent confidence too low ({:.2f}), skipping API call",
            intent_result.confidence,
        )
        return None

    # Step 3: Execute API call
    result = await route_to_public_api(intent_result.intent, intent_result.params)

    if result:
        logger.info(
            "Public API success: intent={!r} result={!r}",
            intent_result.intent,
            result[:60] if len(result) > 60 else result,
        )
    else:
        logger.warning(
            "Public API returned no data: intent={!r}",
            intent_result.intent,
        )

    return result


# ── Cleanup ───────────────────────────────────────────────────────────────────


async def close_http_client() -> None:
    """Close HTTP client on shutdown."""
    global _http_client
    if _http_client:
        await _http_client.aclose()
        _http_client = None
