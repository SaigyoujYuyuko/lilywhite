"""通用模板的命令行与Uvicorn启动入口。"""

import argparse
from pathlib import Path

import msgspec
import uvicorn

from .app import LilyWhiteApplication
from .config import ConfigLoader
from .logger import shutdown_logging


def main(argv: list[str] | None = None) -> None:
    """加载YAML，应用命令行覆盖并启动服务端。"""
    parser = argparse.ArgumentParser(description="Reusable Litestar server template")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--backend", action="append", help="启用后端，可重复传入")
    parser.add_argument(
        "--log-level",
        type=str.upper,
        choices=("TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
    )
    parser.add_argument("--log-file", type=Path)
    parser.add_argument("--no-console", action="store_true")
    args = parser.parse_args(argv)

    properties = ConfigLoader(args.config).load()
    server = msgspec.structs.replace(
        properties.server,
        host=properties.server.host if args.host is None else args.host,
        port=properties.server.port if args.port is None else args.port,
    )
    logging = msgspec.structs.replace(
        properties.logging,
        level=properties.logging.level if args.log_level is None else args.log_level,
        console=properties.logging.console and not args.no_console,
        file=properties.logging.file if args.log_file is None else args.log_file.resolve(),
    )
    properties = msgspec.structs.replace(properties, server=server, logging=logging)

    completed_normally = False
    try:
        backends = tuple(args.backend or ["memory"])
        application = LilyWhiteApplication(properties, backends=backends).create_app()
        uvicorn.run(
            application,
            host=properties.server.host,
            port=properties.server.port,
            log_config={"version": 1, "disable_existing_loggers": False},
        )
        completed_normally = True
    finally:
        if completed_normally:
            shutdown_logging()


if __name__ == "__main__":
    main()
