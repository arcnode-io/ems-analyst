from .call_api_service import CallApiService
from .call_api_controller import CallApiController


class CallApiModule:
    """Example module demonstrating how to call an external API using FastAPI."""

    def __init__(self) -> None:
        call_api_service = CallApiService()
        self.router = CallApiController(call_api_service).router
