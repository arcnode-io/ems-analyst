from src import config
import logging
import uvicorn

from src.app_module import AppModule

app_module = AppModule()
app = app_module.create_app()


def main() -> None:
    """Execute the main entry point of the application.

    Load configuration, set up logging, and run the FastAPI app.

    Example:
        >>> main()  # Loads config and runs FastAPI server

    """
    cfg = config.load_config()
    config.setup_logger(cfg)
    logging.info(f"Running with: Config( {cfg} )")
    uvicorn.run(
        "src.main:app",
        host=str(cfg.host),
        port=cfg.port,
        log_level=cfg.log_level.value.lower(),
        reload=cfg.reload,
    )


if __name__ == "__main__":
    main()
