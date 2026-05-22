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


def test_health_endpoint() -> None:
    """GET /health for proxy / k8s liveness probes."""
    # Arrange
    app = AppModule().create_app()
    client = TestClient(app)

    # Act
    response = client.get("/health")

    # Assert
    assert response.status_code == 200
    assert response.text == "ok"


def test_cors_preflight_allows_cross_origin() -> None:
    """OPTIONS preflight from the HMI origin gets an allow-origin header."""
    # Arrange
    app = AppModule().create_app()
    client = TestClient(app)

    # Act — a browser preflight for the cross-origin /analyst/chat POST
    response = client.options(
        "/analyst/chat",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )

    # Assert — without this header the browser blocks the request
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"
