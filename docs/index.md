# LilyWhite 文档

春が来た。这里从第一个接口一直写到配置、生命周期和运维接口。

## 用法

- [快速上手](getting-started.md)：运行仓库示例，或者从零写一个带 HTTP 接口的应用。
- [入口与应用生命周期](application.md)：`@LilywhiteMain`、启动参数、Banner、入口钩子和 ASGI。
- [业务分层与依赖注入](business.md)：Controller、WebSocket、Service、Repository、Component、`@configuration` / `@bean` 和 AST 发现。
- [多实例与 Qualifier](qualifier.md)：多个数据库 Engine、HTTP Client 和同 Interface 实现的命名注入。
- [配置](configuration.md)：YAML、命令行覆盖、声明式分组、字段约束和跨字段校验。
- [运维接口与响应](operations.md)：健康检查、请求指标、SSE 日志流和统一响应工具。

第一次使用，按“快速上手 → 业务分层与依赖注入 → 配置”的顺序读就很顺。

## 仓库结构

```text
lilywhite/          框架本体
  app/              入口、ASGI、DI、静态发现和生命周期
  controller/       Controller、统一结果、SSE 和 HTTP 中间件
  services/         通用 Service、结果模型和 @service
  storage/          @repository 和后端解析
  domain/           通用类型
  observability/    日志历史和异步订阅
  utils/            @component、注册表、任务、时钟和随机源
  config.py         配置模型和 YAML 加载
  logger.py         Loguru 配置
  health.py         组件健康状态
  metrics.py        请求指标
  banner.py         东方主题彩色 Banner

example/            可直接运行的问候示例
  application.py    @LilywhiteMain 入口类
  __main__.py       命令行启动
  controller/       HTTP 与 WebSocket Controller
  services/         问候 Service
  store/            Repository 接口与内存 Adapter

docs/               详细用法
tests/              行为测试与配置测试
```

业务目录名不属于框架协议。`controller/`、`web/`、`services/`、`logic/`、`store/` 都可以，框架找的是 LilyWhite 装饰器。

## 开发

本地检查、构建和测试命令见[开发文档](development.md)。
