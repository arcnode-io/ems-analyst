"""Weather forecast tool using OpenWeatherMap API."""

import os
from typing import Final

import httpx
from pydantic import BaseModel

# OpenWeatherMap API configuration
OPENWEATHERMAP_API_KEY: Final[str] = os.getenv("OPENWEATHERMAP_API_KEY", "")
OPENWEATHERMAP_BASE_URL: Final[str] = "https://api.openweathermap.org/data/2.5"


class WeatherForecast(BaseModel):
    """Weather forecast data structure."""

    location: str
    temperature: float
    conditions: str
    description: str


async def get_weather_forecast(location: str) -> str:
    """Get weather forecast for a location using OpenWeatherMap API.

    Args:
        location: City name or location to get weather for

    Returns:
        Weather forecast description as a string

    Raises:
        ValueError: If location is empty or API key is not set
        httpx.HTTPError: If API request fails

    Example:
        >>> forecast = await get_weather_forecast("London")
        >>> print(forecast)
        'Weather in London: Cloudy with light rain, temperature 15°C'

    """
    if not location:
        raise ValueError("Location cannot be empty")

    if not OPENWEATHERMAP_API_KEY:
        raise ValueError(
            "OPENWEATHERMAP_API_KEY environment variable not set. "
            "Get your API key from https://openweathermap.org/api"
        )

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{OPENWEATHERMAP_BASE_URL}/weather",
                params={
                    "q": location,
                    "appid": OPENWEATHERMAP_API_KEY,
                    "units": "metric",
                },
                timeout=10.0,
            )
            response.raise_for_status()
            data = response.json()

            # Extract weather information
            temp = data["main"]["temp"]
            conditions = data["weather"][0]["main"]
            description = data["weather"][0]["description"]

            forecast = WeatherForecast(
                location=location,
                temperature=temp,
                conditions=conditions,
                description=description,
            )

            return (
                f"Weather in {forecast.location}: {forecast.conditions} "
                f"({forecast.description}), temperature {forecast.temperature}°C"
            )

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return f"Location '{location}' not found. Please check the city name."
        elif e.response.status_code == 401:
            return "Invalid API key. Please check OPENWEATHERMAP_API_KEY environment variable."
        else:
            return f"Error fetching weather data: HTTP {e.response.status_code}"
    except httpx.RequestError as e:
        return f"Network error while fetching weather data: {e!s}"
    except (KeyError, ValueError) as e:
        return f"Error parsing weather data: {e!s}"
