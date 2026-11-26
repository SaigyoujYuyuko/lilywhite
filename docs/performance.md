# 性能基准与缓存决策

基准脚本在 `benchmarks/`。它们关闭控制台日志，避免把 DEBUG 输出误算成 DI 开销；结果使用 JSON，便于保存和比较。

```powershell
uv run python benchmarks/di_benchmark.py --calls 5000 --output .local/di-after.json
uv run python benchmarks/scale_benchmark.py --modules 100 --requests 1000 --concurrency 100 --output .local/scale.json
uv run python -m benchmarks.server_benchmark --requests 1000 --concurrency 100 --rounds 2 --output .local/server.json
uv run python -m benchmarks.file_benchmark --sizes 65536,1048576,8388608 --requests 100 --concurrency 20 --rounds 2 --output .local/file.json
uv run python -m benchmarks.batch_benchmark --files 128 --file-size 16384 --requests 100 --concurrency 20 --rounds 2 --output .local/batch.json
```

`.local/` 只保存本机结果，不进入 Git。下面是 2026-11-21 在同一台 Windows、Python 3.15.2 环境得到的一次样本，不是跨机器性能承诺。

## 构造器元数据缓存

基准每次解析都创建 `Root → Middle → Leaf` 三层 Transient，避免 Singleton 或 Scoped 命中掩盖构造器成本。缓存前后各执行 5,000 次。

| 指标 | 缓存前 | 缓存后 |
| --- | ---: | ---: |
| 总耗时 | 0.5306 s | 0.1902 s |
| 每秒解析 | 9,424 | 26,289 |
| 平均延迟 | 0.1058 ms | 0.0378 ms |
| P50 | 0.0685 ms | 0.0247 ms |
| P95 | 0.1579 ms | 0.0643 ms |
| P99 | 0.3412 ms | 0.1445 ms |

这次样本中，缓存后吞吐约为 **2.79 倍**，P50 下降约 **64%**。独立的 `signature()` / `get_type_hints()` 微基准也保留在输出里；这两个微基准本身没有被加速，收益来自容器不再重复调用它们。

缓存策略随之确定：

- Bean 工厂在注册时读取并保存依赖元数据。
- 普通构造器在当前容器首次依赖图校验时读取并缓存。
- 缓存按容器隔离，不使用进程级全局缓存；Qualifier、条件装配和多应用测试均保持独立。
- 对只创建一次的 Singleton，收益很小；主要改善 Scoped 首次解析和大量 Transient 解析。

## 已绑定依赖快速路径

`_prepare()` 对已完成首次校验的依赖键直接复用容器内绑定，不再重复筛选 Repository 注册表。首次解析仍执行完整的条件装配、Qualifier 和候选冲突检查。

2026-11-24 在同一环境顺序执行修改前后基准，每次解析仍创建三层 Transient，共 20,000 次：

| 指标 | 优化前 | 优化后 |
| --- | ---: | ---: |
| 总耗时 | 0.8297 s | 0.6940 s |
| 每秒解析 | 24,104 | 28,818 |
| 平均延迟 | 0.0412 ms | 0.0345 ms |
| P50 | 0.0319 ms | 0.0284 ms |
| P95 | 0.0797 ms | 0.0491 ms |
| P99 | 0.1250 ms | 0.0800 ms |

这次顺序 A/B 样本中，吞吐提升约 **19.6%**，P50 下降约 **11%**。并行运行的基准会争抢 CPU，因此不用于结论。

## 规模化启动

100 个独立业务 Service 模块的一次样本：

| 阶段 | 耗时 |
| --- | ---: |
| AST 扫描 | 1.1570 s |
| 精确模块导入 | 0.9185 s |
| 100 个 Singleton 预创建 | 0.00093 s |

启动成本主要在文件扫描和 Python 导入，不在空对象构造。不要通过推迟所有 Singleton 来掩盖导入问题；先用这里的分阶段数据定位。

## 业务发现结果复用

业务包过去会在依赖容器装配和 Controller 发现时各执行一次完整 AST 扫描。现在 `ApplicationRuntime` 持有当前应用自己的 `BusinessDiscovery`，容器与 HTTP 装配共享同一份模块列表；`import_modules()` 幂等，第二次调用直接复用已经完成的导入。

这个缓存只存在于单个 Runtime，不跨应用共享，也不让不同配置或测试包互相污染。回归测试会创建真实业务 Controller、连续生成两个 ASGI 应用并发起请求，同时断言 `scan_decorated_modules()` 总共只调用一次。Windows 文件缓存与后台进程会让本地启动时间波动较大，因此这里记录结构变化，不承诺固定提速百分比。

## 真实 Uvicorn 网络请求

`server_benchmark.py` 为每种实现启动独立的 Uvicorn 进程，由另一个进程中的 HTTPX 客户端通过 HTTP/1.1 over TCP 发请求。两个应用具有相同的 Controller 行为、Scoped 资源、Transient 依赖、指标中间件和 CORS。每轮分别执行 1,000 个顺序请求和 1,000 个并发请求，并发上限为 100；两轮交替实现顺序，进程启动与预热不计入请求耗时。

2026-11-26 在 Windows、Python 3.15.2 环境的两轮算术平均：

| 实现与场景 | 吞吐 | 平均延迟 | P50 |
| --- | ---: | ---: | ---: |
| LilyWhite 顺序 | 657/s | 1.517 ms | 1.211 ms |
| 原生 Litestar 顺序 | 669/s | 1.482 ms | 1.249 ms |
| LilyWhite 并发 | 536/s | 177.986 ms | 119.469 ms |
| 原生 Litestar 并发 | 519/s | 184.384 ms | 119.290 ms |

这组真实网络结果中两种实现很接近，没有显示出稳定的 LilyWhite 额外吞吐损耗。HTTPX 客户端与回环网络会占用本机资源，因此它不是专业压测器的极限吞吐测试，也不能与下面的直接 ASGI 数字直接比较。需要测量服务器饱和点时，应在另一台机器使用 `wrk` 或 `oha` 压测。

## 文件下载与 AyaFileIO

`file_benchmark.py` 对比 LilyWhite `FileIO` 的 AyaFileIO 实现与 Litestar 原生 `File`。两边读取同一个随机文件，使用相同 64 KiB 分块、Content-Length 和 Uvicorn 配置；客户端流式消费并校验完整字节数，不把整个文件保存在内存。每种尺寸执行两轮，每轮包含 100 个顺序请求和 100 个并发请求，并发上限为 20。

2026-11-26 在 Windows、Python 3.15.2 环境的两轮平均载荷吞吐：

| 文件与场景 | AyaFileIO | Litestar File |
| --- | ---: | ---: |
| 64 KiB 顺序 | 32.11 MiB/s | 29.40 MiB/s |
| 64 KiB 并发 | 21.66 MiB/s | 28.51 MiB/s |
| 1 MiB 顺序 | 208.01 MiB/s | 155.84 MiB/s |
| 1 MiB 并发 | 255.41 MiB/s | 227.11 MiB/s |
| 8 MiB 顺序 | 303.13 MiB/s | 208.13 MiB/s |
| 8 MiB 并发 | 420.83 MiB/s | 318.50 MiB/s |

这组样本里，AyaFileIO 在 1 MiB 和 8 MiB 的顺序、并发场景均领先；8 MiB 分别约为 1.46 倍和 1.32 倍。64 KiB 并发结果受单次运行波动影响较大，不作为稳定领先或落后结论。吞吐包含完整 HTTP 链路，不是纯磁盘读取速度；不同磁盘、操作系统和分块大小仍需重新测量。

### `aopen()` 是否更快

同一文件基准还直接比较了普通 `open()` 与 `aopen()`，两者使用完全相同的 `read_at` 分块逻辑。另一组两轮平均结果：

| 文件与场景 | 普通 `open()` | `aopen()` |
| --- | ---: | ---: |
| 1 MiB 顺序 | 244.52 MiB/s | 211.88 MiB/s |
| 1 MiB 并发 | 235.50 MiB/s | 258.68 MiB/s |
| 8 MiB 顺序 | 308.44 MiB/s | 301.78 MiB/s |
| 8 MiB 并发 | 437.26 MiB/s | 442.95 MiB/s |

本地温缓存单文件没有稳定的 `aopen()` 优势；8 MiB 并发的细小差异不足以跑赢噪声。它的合适场景是慢存储或同时打开大量文件，不应把 LilyWhite 默认 `FileIO.stream()` 改成始终使用 `aopen()`。

### 批量文件读取

`batch_benchmark.py` 让每次 HTTP 请求完整读取一组文件，并返回文件数与总字节数进行校验。这里的 MiB/s 计算的是实际读取的文件字节数，不是较小的 JSON 响应体。对照包括 `read_bytes_many`、`gather + open`、`gather + aopen` 和串行 `open`。

| 每请求文件布局与场景 | `read_bytes_many` | 并发 `open` | 并发 `aopen` | 串行 `open` |
| --- | ---: | ---: | ---: | ---: |
| 32 × 64 KiB，顺序 | 464.64 MiB/s | 482.45 MiB/s | 342.13 MiB/s | 207.68 MiB/s |
| 128 × 16 KiB，顺序 | 270.08 MiB/s | 258.52 MiB/s | 140.25 MiB/s | 66.65 MiB/s |
| 128 × 16 KiB，并发 | 263.78 MiB/s | 250.15 MiB/s | 159.47 MiB/s | 219.16 MiB/s |

128 个小文件的顺序批量读取中，`read_bytes_many` 约为串行的 4.05 倍，也略高于手写并发 `open`。32 个文件时手写并发略快，说明原生批量 API 不是所有布局下都必然最高吞吐，但它用一次调用提供有序结果和并发上限，避免了手写任务管理。外层 HTTP 并发会让多个串行请求彼此重叠，因此不能用并发组证明单个请求内部的串行读取同样优秀。

## 请求与资源回收

请求基准使用真实 Litestar ASGI 调用链，并分别创建 LilyWhite 与原生 Litestar 应用。两边使用相同的路由、Scoped 资源和 Transient 下游对象；原生对照组通过 `Provide`、类型注入和异步生成器依赖完成资源清理，不是空路由。每组 1,000 个请求，并发组最多同时执行 100 个。

2026-11-26 在本机顺序执行的一组样本：

| 实现与场景 | 吞吐 | 平均 | P50 | P95 | P99 |
| --- | ---: | ---: | ---: | ---: | ---: |
| LilyWhite 顺序 | 7,714/s | 0.1237 ms | 0.1123 ms | 0.1704 ms | 0.3703 ms |
| 原生 Litestar 顺序 | 5,950/s | 0.1640 ms | 0.1506 ms | 0.2121 ms | 0.5139 ms |
| LilyWhite 并发 | 8,601/s | 5.8437 ms | 5.8365 ms | 8.3198 ms | 8.8709 ms |
| 原生 Litestar 并发 | 7,510/s | 8.2810 ms | 8.0781 ms | 11.8201 ms | 12.2795 ms |

这组样本说明当前 DI 路径在该场景没有表现出额外吞吐损失，但不能据此承诺所有路由都比原生 Litestar 更快。并发延迟包含信号量排队时间，不能与顺序延迟直接当作纯处理耗时比较；需要继续优化时应保留同机、同脚本的对照数据。

两组持续请求都使用 `tracemalloc` 观察内存，并各自在顺序、并发、持续三组中创建和关闭 3,000 个资源，结束后活跃数均为 0。单次内存差值不等于长期泄漏结论；需要长期部署验证时，用同一脚本扩大 `--requests` 并观察多轮趋势。

启动、并发请求、流异常、客户端断开、取消、后台异常和关闭回滚由常规 pytest 与 CI 持续回归；性能数字作为本地可重复基准，不设容易受 CI 负载影响的硬阈值。
