from classy_fastapi import Routable, get
from fastapi import Response


class AppController(Routable):
    """
    Main application controller handling root-level routes.
    """

    @get("/")
    def healthcheck(self) -> Response:
        """
        Handles GET requests to the root path.

        Returns:
            A string response  'ok'
        """
        return Response("ok")

    @get("/health")
    def health(self) -> Response:
        """Liveness probe — proxies + k8s commonly hit /health, not /."""
        return Response("ok")
