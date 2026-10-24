<!-- ABI 2 与外部协议 v3 的开发、验证及分发说明。 -->
# 插件 SDK

完整契约见 [插件系统设计](../../Docs/PluginSystemDesign.md)。外部插件通过 WebSocket Protobuf v3 接入，内部插件通过结构化 C ABI 2 接入独立 worker。
主程序内嵌与开发动态库同源的接口实现。插件发行通过宿主注入的函数表工作，SDK 独立构建和发布。
版本分别管理：外部协议 v3、C ABI 2、私有 IPC 2、内部业务模型 1。`PluginRequest.protocol_version` 对应 `BUSINESS_MODEL_VERSION=1`（`PROTOCOL_VERSION` 为其别名），C 使用 `VC_MODEL_VERSION`；插件加载兼容性依据清单 ABI 与平台。

## 外部插件

在「设置 → 拓展 → 基础设置」启用接口并复制统一令牌。默认地址为 `ws://127.0.0.1:38601/api/v3/ws`，升级请求携带 `Authorization: Bearer <令牌>`。
监听设置、接口开关和令牌轮换沿用应用设置；变更后重新连接登记。协议来源为 [external_plugin.proto](../../Adapter/HttpPlugin/external_plugin.proto)。
每个 WebSocket Binary 消息承载一个 Envelope。首条请求在 15 秒内发送 register，信封 major=3、minor=0，登记中 min_minor/max_minor 声明支持范围，当前为 0。

```text
major: 3 minor: 0 request_id: "register-1"
request { register {
  id: "example.remote" name: "远程插件" version: "2.0.0"
  capabilities: "messages" capabilities: "events" capabilities: "transform"
  min_minor: 0 max_minor: 0
} }
```

上例为 Protobuf TextFormat 的可读表示；线上发送生成类型编码后的字节。Response 使用相同 request_id，Event 使用稳定 event_id 和空 request_id。

| 操作 | 方向与权限 | 数据 |
| --- | --- | --- |
| register | 插件 → 宿主 | 身份资料、版本范围、能力、可选配置网页/输出卡片/游标；返回身份、代次和版本 |
| message-types.register | 插件 → 宿主，messages | 稳定 ID 和名称的完整列表；空列表移除声明 |
| messages.incoming | 插件 → 宿主，messages | 强类型 MessageInput，按来源自动转发策略入队 |
| messages.send | 插件 → 宿主，messages | 强类型 MessageInput，直接入队 |
| event | 宿主 → 插件，events | 稳定事件 ID、种类、完整 Message 和专用扩展 |
| transform | 宿主 → 插件，transform | Message 与当前 Document，返回替换 Document |

MessageInput 提交文档、用户名、可选来源消息 ID/时间、插件内 type_id、头像 URL 和 origin_ids；宿主生成可信来源与消息身份。
文档的段落、片段、样式、图片、注音、速度与停顿均为结构化字段，extra_json 用于扩展。头像沿用 HTTP/HTTPS 校验和宿主缓存。
类型先注册再投递；类型暂停仍接收和排队，解除后按原顺序调度。输出卡片最多两个操作，随会话登记，根路径按当前 WebService 地址解析。
事件 FIFO，保留最近 1000 条；重连提交 last_event_id，历史过期返回 history_expired。Ping 间隔 15 秒，45 秒失联回收。
写入与外部转换限 3 秒，登记和应用处理限 15 秒，单消息最大 4 MiB。同方向待决 request_id 唯一，迟到响应丢弃。

业务边界额外读取至多 1 字节以识别超限，发送 Close 1009 并限时 1 秒等待回执。更大帧由传输硬上限在分配前拒绝；底层错误使读取流终止，宿主尽力发送 1009 后立即回收连接、代次及待决请求，客户端也可能观察到 TCP reset 或 EOF。

Rust 客户端可使用 `vchat_http_plugin::wire::proto` 与 encode/decode；encode_request/encode_response/decode_value 提供宿主模型转换。
Python 示例使用标准生成代码和 websockets：

```powershell
python -m pip install protobuf grpcio-tools websockets
python -m grpc_tools.protoc -I Adapter/HttpPlugin --python_out=Core/Tools Adapter/HttpPlugin/external_plugin.proto
python Core/Tools/sdk-client.py --token <令牌>
```

独立 SDK 中协议与示例位于根目录，生成参数改用 `-I . --python_out=. external_plugin.proto`。
C++ 外部示例 sdk-client.cpp 依赖 Boost.Beast 和生成代码，参数为 `<host> <port> <token>`。

## 内部 C ABI

公共头文件为 VCPluginInterface.h，ABI 主版本为 2。插件导出 vchat_internal_plugin_get_api，返回稳定只读 PluginApi 表。
worker 校验版本、结构大小和函数表，向 create 注入实例级 HostApi。宿主服务通过该表转发到主程序。
Rust 使用 vchat-plugin-api 的 abi/sdk 模块，默认构建包含业务模型及 C ABI 封装，Protobuf 编解码由宿主启用 host-protocol 特性。
proto 模块保留拥有型业务模型命名，默认构建通过结构化视图交换这些数据。

| SDK 方法 | 用途 |
| --- | --- |
| sdk::read_request / read_host_request | 深拷贝结构化输入，检查版本、长度及嵌套预算 |
| sdk::with_request / with_host_request | 在同步闭包期间保持嵌套视图有效 |
| sdk::write_response / write_snapshot | 同步向回复 sink 复制结果或快照 |
| sdk::call_host | 调用注入表并复制宿主响应 |
| runtime::runtime_paths | 读取当前包、资源、持久化数据与共享 Assets 目录 |

ABI 使用固定宽度整数、自然对齐、UTF-8 字符串、带布局信息的集合和不透明上下文。输入借用到函数返回，回复由 sink 同步深拷贝。
各侧管理各自内存，插件对象由 destroy 释放。合法带 sink 调用恰好回复一次；状态码和函数返回值传播失败。
调用总量上限 16 MiB，深度上限 64。panic/异常在插件内部捕获；生命周期与 invoke 串行，后台线程可调用宿主。
标准消息、文档、UI 与服务数据通过 C 结构传递，配置、表单 schema 和自定义操作保留用途明确的 JSON。
宿主权限为 messages、events、ui、frontend、web；runtime.paths/log 面向全部实例。现有消息类型、前端、窗口与 Web 路由服务继续提供。
编辑提交检查 expected_revision，路由整组校验冲突，剧本回执保留 run_id/batch_id/message_id/generation，过滤退休批次。

## SDK 构建与调试

```powershell
# Unix 使用 bash Core/Tools/package-sdk.sh
./Core/Tools/package-sdk.ps1
cargo build --locked --release -p vchat-plugin-api --features sdk-dev
cargo build --locked -p vchat-example-plugin
cmake -S Plugins -B target/cpp-plugin -DVCHAT_SDK=<头文件目录>
cmake --build target/cpp-plugin --config Release
```

SDK 输出在 target/dist/VCPluginSDK-<os>-<arch>/，包含头文件、开发库、可独立构建的源码、协议、示例和测试宿主。
开发库为 VCPluginInterface.dll、libVCPluginInterface.so 或 libVCPluginInterface.dylib，与主程序静态编译的接口实现同源。
测试宿主显式装载开发库并解析导出；导出接口提供版本查询、创建及销毁宿主，由调用方注入后端。
最小测试宿主使用无需业务服务即可启动的 C++ 示例，验证真实动态加载与 create/start/quiesce/save/resume/destroy：

```powershell
python Core/Tools/sdk-host.py --library <SDK目录>/VCPluginInterface.dll --plugin <C++示例动态库>
```

业务回调、状态迁移及隔离由真实 worker 集成测试覆盖。正式插件仅使用头文件或静态封装，并通过注入函数表取得接口。

## 插件包与生命周期

.vcplug 为 ZIP，包含 manifest.json、bin/ 下入口与自身原生依赖、resources/ 下资源。清单版本为 2，ABI 为 2：

```json
{"package_version":2,"entry":"bin/example.dll","id":"example.counter","name":"示例计数插件","author":"VChat Contributors","description":"消息与状态迁移示例","version":"2.0.0","platform":"windows","architecture":"x86_64","abi_version":2,"capabilities":["ui","messages","events"]}
```

打包检查入口、平台、架构、路径、压缩内容与原生依赖，拒绝携带或依赖 VCPluginInterface 开发库。
Linux 原生依赖使用 $ORIGIN，macOS 使用 @loader_path/@rpath，Windows 放在同一 bin/。

```powershell
cargo run --locked -p vchat-internal-plugin --bin vchat-plugin-pack -- pack target/plugin-stage target/example.vcplug
cargo build --locked -p vchat-echolive-config-plugin -p vchat-nana-dialogue-plugin -p vchat-vtypewriter-plugin
cargo run --locked -p vchat-internal-plugin --bin vchat-plugin-pack -- builtin . target/debug target/debug
```

每代独立解压并运行，data_root 长期保留，resources_root 随代次切换，assets_root 随 data-dir 移动。
更新先创建候选、暂停旧实例、导出/迁移快照并启动候选。消息、类型、UI、前端与路由暂存，持久化提交成功后切换代次。
失败时丢弃候选并恢复旧实例；quiesce 排空后台线程、任务与回调。5 秒超时、IPC 断开或崩溃回收对应 worker，设置页可手动重启。
候选文件/网络副作用由插件负责；准备阶段校验与注册，实际输出留到活动业务调用。

## 迁移与验证

外部 JSON v2 客户端更新到 v3 路径、Binary 与强类型字段。内部 ABI 1 插件升级 SDK、签名和清单并重新构建。
旧配置与安装记录停用保留；导入同 ID 新包后恢复使用。C++ 内部插件移除 Protobuf 生成/链接，Rust 内部插件改用 SDK 视图方法。

```powershell
cargo test --locked -p vchat-plugin-api -p vchat-http-plugin -p vchat-internal-plugin
cargo test --locked --workspace
cargo clippy --locked --workspace --all-targets -- -D warnings
```

跨平台 CI 验证布局、实际 C++ 动态库、开发 SDK 和正式 worker。主程序在仓库外以空数据目录验证独立运行，插件单独构建、打包与安装。
