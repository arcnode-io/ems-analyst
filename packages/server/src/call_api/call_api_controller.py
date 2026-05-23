from classy_fastapi import Routable, get
from .call_api_service import CallApiService
from .dto.api_response_dto import ApiResponseDto


class CallApiController(Routable):
    """Controller for handling external API calls via REST endpoints."""

    def __init__(self, call_api_service: CallApiService) -> None:
        super().__init__()
        self.call_api_service = call_api_service

    @get(
        "/call-api",
        response_model=ApiResponseDto,
        tags=["CallApi"],
        responses={200: {"description": ""}},
    )
    async def call_httpbin(self) -> ApiResponseDto:
        """Calls external httpbin API and returns validated URL data."""
        return await self.call_api_service.call_httpbin()
