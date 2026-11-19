# 开发

## 安装开发环境

```bash
uv sync --locked
```

## 行为测试

```bash
uv run pytest tests -q
```

测试覆盖公开入口、真实 HTTP/WebSocket 请求、构造器注入、AST 静态发现、配置校验、Banner 和生命周期。

## Lint、格式和类型

```bash
uv run ruff check lilywhite example tests
uv run ruff format --check lilywhite example tests
uv run mypy
```

需要应用格式化时：

```bash
uv run ruff format lilywhite example tests
```

## 构建

```bash
uv build
uvx twine check dist/*
```

`uv build` 生成源码包和 wheel，发行包里只有 `lilywhite` 框架本体。`example/`、`tests/` 和 `docs/` 留在源码仓库中，不作为业务代码装进框架包。

## 真实启动验证

```bash
uv run python -m example --config config.example.yaml --host 127.0.0.1 --port 8000
```

再请求：

```bash
curl --fail http://127.0.0.1:8000/api/v1/greetings/Lily
curl --fail http://127.0.0.1:8000/healthz
```

## CI

推送到 `main` 和 Pull Request 都会运行测试、Ruff、格式检查、Mypy、构建和 Twine 检查。发布 GitHub Release 时，工作流还会校验 `vX.Y.Z` 标签与 `pyproject.toml` 版本一致，再通过 Trusted Publishing 发布到 PyPI。
