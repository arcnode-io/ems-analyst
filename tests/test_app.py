from fastapi.testclient import TestClient
from src.app_module import AppModule


def test_healthcheck_endpoint() -> None:
    """Test the healthcheck endpoint returns 'ok'."""
    # Arrange
    app_module = AppModule()
    app = app_module.create_app()
    client = TestClient(app)
    expected_text = "ok"

    # Act
    response = client.get("/")

    # Assert
    assert response.text == expected_text
