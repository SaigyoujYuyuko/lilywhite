# LilyWhite 文档

春が来た。这里从第一个接口一直写到配置、生命周期和运维接口。

## 用法

- [快速上手](getting-started.md)：运行仓库示例，或者从零写一个带 HTTP 接口的应用。
- [入口与应用生命周期](application.md)：`@LilywhiteMain`、启动参数、Banner、入口钩子和 ASGI。
- [业务分层与依赖注入](business.md)：Controller、中间件、WebSocket、Service、Repository、Component、`@configuration` / `@bean` 和 AST 发现。
- [多实例与 Qualifier](qualifier.md)：多个数据库 Engine、HTTP Client 和同 Interface 实现的命名注入。
- [托管注册表](managed-registries.md)：业务类与函数装饰器的声明式 AST 静态发现。
- [数据库事务](transactions.md)：请求级 AsyncSession、UnitOfWork、多 Repository 和后台任务。
- [大型项目组织与资源管理](large-projects.md)：模块边界、生命周期、第三方适配、可选依赖和多应用。
- [性能基准](performance.md)：DI 缓存对比、规模化启动、请求延迟和资源回收。
- [配置](configuration.md)：YAML、命令行覆盖、声明式分组、字段约束和跨字段校验。
- [运维接口与响应](operations.md)：健康检查、请求指标、全局异常处理、HTTP 响应、流式响应和 SSE 日志流。

第一次使用，按“快速上手 → 业务分层与依赖注入 → 配置”的顺序读就很顺。

## 仓库结构

```text
lilywhite/          框架本体
  app/              入口、ASGI、DI、静态发现和生命周期
  decorators/       业务分层、HTTP、配置与事务装饰器
  http/             HTTP 响应、内置运维入口和中间件
  observability/    健康、指标、日志订阅及其查询用例
  websocket/        WebSocket 客户端
  utils/            @component、注册表、任务、时钟和随机源
  config.py         配置模型和 YAML 加载
  transaction.py    事务上下文与 UnitOfWork
  logger.py         Loguru 配置
  banner.py         东方主题彩色 Banner

example/            可直接运行的问候示例
  application.py    @LilywhiteMain 入口类
  __main__.py       命令行启动
  controller/       HTTP 与 WebSocket Controller
  services/         问候 Service
  store/            Repository 接口与内存 Adapter
  modules/          identity、billing、catalog 模块化单体

benchmarks/         DI 与规模化基准
docs/               详细用法
tests/              行为、并发、故障与事务测试
```

业务目录名不属于框架协议。`controller/`、`web/`、`services/`、`logic/`、`store/` 都可以，框架找的是 LilyWhite 装饰器。

## 开发

本地检查、构建和测试命令见[开发文档](development.md)。
