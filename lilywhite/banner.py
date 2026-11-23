"""东方主题 LilyWhite 彩色启动 Banner。"""

import sys

LILY_GREEN = "\033[38;2;168;230;190m"
LILY_WHITE = "\033[97m"
SPRING_PINK = "\033[38;2;244;194;211m"
DIM = "\033[2m"
RESET = "\033[0m"


def server_url(host: str, port: int) -> str:
    """生成适合日志展示的本地访问地址。"""
    visible_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    return f"http://{visible_host}:{port}"


def render_banner(
    application_name: str,
    application_version: str,
    host: str | None,
    port: int | None,
    *,
    server_name: str = "Uvicorn",
) -> str:
    """生成百合绿、暖白与春樱粉的东方主题 Banner。"""
    endpoint = (
        server_url(host, port)
        if host is not None and port is not None
        else "ASGI endpoint managed by host server"
    )
    return f"""
{LILY_GREEN}  ╦  ╦═╗╦  ╦ ╦╦ ╦╦ ╦╦╔╦╗╔═╗{RESET}
{LILY_GREEN}  ║  ║ ║║  ╚╦╝║║║║║ ║║ ║ ║╣{RESET}
{LILY_GREEN}  ╩═╝╩ ╩╩═╝ ╩ ╚╩╝╚╩╝╩ ╩ ╚═╝{RESET}
{SPRING_PINK}       Bringing Spring to Python.{RESET}
{LILY_WHITE}       {application_name} v{application_version}{RESET}
{DIM}       Litestar + {server_name}  •  {endpoint}{RESET}
"""


def print_banner(
    application_name: str,
    application_version: str,
    host: str | None,
    port: int | None,
    *,
    server_name: str = "Uvicorn",
) -> None:
    """向 stderr 输出彩色 Banner，避免 stdout 缓冲改变启动信息顺序。"""
    print(
        render_banner(
            application_name,
            application_version,
            host,
            port,
            server_name=server_name,
        ),
        file=sys.stderr,
        flush=True,
    )


__all__ = ["print_banner", "render_banner", "server_url"]
