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


def test_cors_preflight_allows_vite_dev_origin() -> None:
    """OPTIONS preflight from local Vite dev gets the matched origin echoed back.

    Scoped CORS (not allow_origins=["*"]) reflects the specific matched
    origin per the CORS spec, rather than a literal "*".
    """
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
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_preflight_allows_public_demo_origin() -> None:
    """The public CloudFront demo site's custom domain is also allowed."""
    # Arrange
    app = AppModule().create_app()
    client = TestClient(app)

    # Act
    response = client.options(
        "/analyst/chat",
        headers={
            "Origin": "https://ems.arcnode.io",
            "Access-Control-Request-Method": "POST",
        },
    )

    # Assert
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://ems.arcnode.io"


def test_cors_preflight_rejects_unknown_origin() -> None:
    """An origin outside the allow-list gets no allow-origin header at all."""
    # Arrange
    app = AppModule().create_app()
    client = TestClient(app)

    # Act
    response = client.options(
        "/analyst/chat",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "POST",
        },
    )

    # Assert — Starlette still answers 200 to the preflight, but omits the
    # header a browser needs to actually allow the follow-up request
    assert "access-control-allow-origin" not in response.headers
