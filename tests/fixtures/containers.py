"""Testcontainer fixtures with dynamic port allocation."""

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from urllib.parse import quote_plus

from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy
from testcontainers.postgres import PostgresContainer


@dataclass(frozen=True)
class Container:
    """Connection info for a running testcontainer.

    Attributes:
        host: Container host (always localhost)
        port: Dynamic mapped port
        url: Pre-built connection URL
    """

    host: str
    port: int
    url: str


@contextmanager
def _start_container(
    image: str,
    port: int,
    wait_for_log: str,
) -> Generator[Container]:
    """Start a generic Docker container with dynamic port. Internal building block.

    Args:
        image: Docker image (e.g. "neo4j:latest")
        port: Internal container port to expose
        wait_for_log: Log message indicating readiness

    Yields:
        Container with http:// URL and dynamic port
    """
    c = (
        DockerContainer(image)
        .with_exposed_ports(port)
        .waiting_for(LogMessageWaitStrategy(wait_for_log))
    )

    with c:
        mapped = int(c.get_exposed_port(port))
        yield Container(
            host="localhost",
            port=mapped,
            url=f"http://localhost:{mapped}",
        )


@contextmanager
def start_postgres(
    password: str,
    image: str = "postgres:15",
    username: str = "postgres",
    dbname: str = "postgres",
) -> Generator[Container]:
    """Start a Postgres container with dynamic port.

    Args:
        password: DB password
        image: Docker image (postgres:15, pgvector/pgvector:pg16)
        username: Database username
        dbname: Database name

    Yields:
        Container with postgresql:// URL and dynamic port
    """
    with PostgresContainer(
        image, username=username, password=password, dbname=dbname
    ) as c:
        port = int(c.get_exposed_port(5432))
        # quote_plus the pw so URL stays parseable when the shared dev
        # creds contain `@` or `!` — real consumers (MemoryService etc.)
        # use postgres.url directly, not kwargs.
        yield Container(
            host="localhost",
            port=port,
            url=f"postgres://{username}:{quote_plus(password)}@localhost:{port}/{dbname}",
        )


@contextmanager
def start_neo4j(password: str) -> Generator[Container]:
    """Start a Neo4j container with dynamic bolt port.

    Args:
        password: Neo4j auth password

    Yields:
        Container with bolt:// URL and dynamic port
    """
    c = (
        DockerContainer("neo4j:latest")
        .with_exposed_ports(7687)
        .with_env("NEO4J_AUTH", f"neo4j/{password}")
    )

    with c:
        mapped = int(c.get_exposed_port(7687))
        yield Container(
            host="localhost",
            port=mapped,
            url=f"bolt://localhost:{mapped}",
        )
