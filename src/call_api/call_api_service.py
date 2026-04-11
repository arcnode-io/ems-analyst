import httpx
from .dto.api_response_dto import ApiResponseDto


class CallApiService:
    """
    Service for handling external API calls and data validation.
    Provides methods for calling httpbin.org and returning validated responses.
    """

    async def call_httpbin(self) -> ApiResponseDto:
        """
        Calls external httpbin API and returns validated URL data.
        Returns: Promise of validated API response containing URL
        """
        async with httpx.AsyncClient() as client:
            response = await client.get("https://httpbin.org/get")
            data = response.json()

            return ApiResponseDto(url=data["url"])
