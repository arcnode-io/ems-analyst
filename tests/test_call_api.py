import pook
from typing import Literal
from pydantic import BaseModel
from fastapi.testclient import TestClient
from src.app_module import AppModule
from src.call_api.dto.api_response_dto import ApiResponseDto
from src.config import load_config


class MockResponse(BaseModel):
    """Mock response structure."""

    url: str


class ClientOpts(BaseModel):
    """Configuration options for the HTTP client."""

    base_url: str
    path: str
    method: Literal["get", "post", "put", "delete"] = "get"
    mock_response: MockResponse
    response_code: int = 200


class TestCallApi:
    """API Call Example tests."""

    def mockable_http_client(self, opts: ClientOpts) -> TestClient:
        """
        Creates a mockable HTTP client for testing external API calls.
        Args:
            opts: Configuration options for the HTTP client
        Returns:
            TestClient instance for making HTTP requests
        """
        cfg = load_config()

        if not cfg.e2e:
            # Enable pook for mocking external requests
            pook.on()
            pook.enable_network()

            # Mock the external API call
            getattr(pook, opts.method)(opts.base_url + opts.path).reply(
                opts.response_code
            ).json(opts.mock_response.model_dump())

        app_module = AppModule()
        app = app_module.create_app()
        return TestClient(app)

    def test_should_call_external_api_and_return_mocked_response(self) -> None:
        """Test external API call with mocked response."""
        # Arrange
        client = self.mockable_http_client(
            ClientOpts(
                base_url="https://httpbin.org",
                path="/get",
                mock_response=MockResponse(url="https://mocked-api.example.com/get"),
            )
        )

        # Act
        response = client.get("/call-api")

        # Assert
        assert response.status_code == 200
        assert isinstance(response.json(), dict)

        response_body = ApiResponseDto(**response.json())
        assert str(response_body.url) == "https://mocked-api.example.com/get"
