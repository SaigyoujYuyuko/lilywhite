"""LilyWhite 配置初始化与 Uvicorn 启动入口。"""

import argparse
import sys
from pathlib import Path

import uvicorn

from .app import LilyWhiteApplication
from .cli.config import init_config
from .config import ConfigLoader
from .logger import shutdown_logging


def main(argv: list[str] | None = None) -> None:
    """处理配置初始化命令，或加载 YAML 启动服务端。"""
    arguments = sys.argv[1:] if argv is None else argv
    if arguments and arguments[0] == "init":
        init_config(arguments[1:])
        return

    parser = argparse.ArgumentParser(description="LilyWhite Framework")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument(
        "--log-level",
        type=str.upper,
        choices=("TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
    )
    parser.add_argument("--log-file", type=Path)
    parser.add_argument("--no-console", action="store_true")
    args = parser.parse_args(arguments)

    properties = ConfigLoader(args.config).load()
    properties = properties.override(
        server={
            "host": properties.server.host if args.host is None else args.host,
            "port": properties.server.port if args.port is None else args.port,
        },
        logging={
            "level": properties.logging.level if args.log_level is None else args.log_level,
            "console": properties.logging.console and not args.no_console,
            "file": properties.logging.file if args.log_file is None else args.log_file.resolve(),
        },
    )

    completed_normally = False
    try:
        application = LilyWhiteApplication(properties).create_app()
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
