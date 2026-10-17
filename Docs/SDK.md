# InternalPlugin SDK

ABI 主版本为 1，协议主版本为 1。Rust 使用 `vchat-plugin-api`，C/C++ 使用
`internal_plugin.h` 和 `internal_plugin.proto`；生成器由 `protoc-bin-vendored = 3.2.0`
锁定为 Protobuf 31.1。字段编号保留兼容性，新增 ABI 表字段通过 `struct_size` 协商。

动态库导出 `vchat_internal_plugin_get_api`，宿主复制函数表。`create` 接收稳定的
HostApi 地址与 JSON 配置；输出独立实例地址。每个生命周期及 invoke 在实例专用线程串行运行。
请求缓冲区在本次调用内有效。插件通过 write 回调复制响应，宿主释放宿主缓冲区，插件释放插件对象。
各 ABI 函数捕获 panic/异常，禁止异常穿过 ABI 边界。单响应最大 16 MiB。

invoke 接收 PluginRequest 并返回 PluginResponse。`transform` 的 payload_json 保存共享
消息 JSON；文档采用 Paragraph/Segment/TextStyle/Image 结构化字段，extra_json 保留未知扩展；
`ui.command` 同时携带文档、修订号和选区，返回 edit 时宿主核对 expected_revision。
`ui.settings` 接收配置字段。UI 字段 kind 使用 text、number、switch、enum、color。
`transform` 和 `event` 同时携带结构化 message（包含 document 与消息来源、身份、时序、状态、message_type、avatar_url）；
`config.changed` 通知配置变化，payload_json 保留版本扩展入口。转换结果优先使用 edit.replacement，
payload_json 可返回共享消息 JSON。Rust 用 document_to_proto/document_from_proto/message_to_proto 转换。

HostApi.invoke 接收 HostRequest：log 记录日志；config 写回 JSON 配置；config.set 更新并投递配置变更事件；message.post 投递消息；message.types.register 注册消息类型；
event.subscribe 注册订阅；ui.register 注册 UiContribution；frontend.register 声明一个可接收消息的前端；frontend.message 投递前端消息；frontend.receipt 提交前端回执；
ui.window.* 请求宿主创建、更新或关闭 NanaUI 窗口。权限分别使用 messages、events、ui、frontend；所有新增服务的 payload_json 必须是有效 JSON，服务事件仍按插件代次排队。
回调线程安全，宿主将事件入队。插件必须复制暂存的请求。HostContext 和 generation 随实例固定。

quiesce 成功表示插件的后台线程、任务和宿主回调全部结束。resume 重新启用实例。
save_state 输出 StateSnapshot（插件 ID、非零格式版本、状态字节），restore_state 负责版本迁移。
热更新先预加载库，暂停旧实例，导出快照，在暂存宿主上下文中恢复候选实例。start 成功才切换
活动代次和 UI；失败销毁候选并 resume 旧实例。暂存实例的消息投递按顺序缓存，提交后释放；失败候选事件丢弃。
消息类型注册同样进入代次事务队列，声明先于该类型消息投递，候选失败时丢弃注册。
宿主 `reload` 沿用配置；`reload_with_config(id, manifest, path, values)` 将新配置送入候选实例，
迁移成功时提交配置，失败时保留原配置。配置、代次和事件暂存共用事务锁。
新实例提交后，旧实例清理返回普通错误时记录警告并保留旧库，热更新仍返回成功；
超时停用实例并返回 Timeout，宿主可以提示重启恢复。
调用超过 5 秒时宿主停用实例并保留库、上下文和对象到进程退出，保证后台引用的地址有效。
插件作者负责内存安全；进程内动态库的访问权限等同于应用进程。

## 消息类型与暂停

HTTP 插件使用 `POST /api/v1/message-types`，携带 `Authorization: Bearer <插件令牌>`；
InternalPlugin 使用 `HostRequest.service = "message.types.register"`，将相同 JSON 写入 `payload_json`。
两者需要 `messages` 权限，并以完整列表替换当前插件声明；空列表移除声明，既有积压消息和暂停设置继续保留。
版本必须为 1，ID 和中文名称必须非空，ID 在同一插件内唯一且应长期稳定。

```json
{"version":1,"types":[{"id":"remote","label":"远程消息"},{"id":"danmaku","label":"弹幕消息"}]}
```

声明成功后，在 `message.post`、HTTP incoming/send 的消息 JSON 中填写可选 `message_type`：

```json
{"source_id":"internal:example.counter","source_message_id":"1","message_type":"remote","username":"示例插件","document":{"version":1,"revision":0,"paragraphs":[{"segments":[{"text":"远程消息","style":{}}]}]}}
```

提交只填写插件内类型 ID。宿主从凭据或 HostContext 取得插件身份，生成
`message_type: {plugin_kind, plugin_id, type_id}`，并用于共享消息、插件事件和 Protobuf Message 的字段 11。
显式提交未声明的 ID 会返回错误；旧插件省略字段时归入该插件的“未分类消息”。
InternalPlugin 的宿主回调同步校验声明：未声明 ID 返回 `STATUS_ERROR`；注册成功后立即可按该 ID 投递。
每个实例持有独立类型缓存，候选完整替换声明后仍保留事务隔离，迁移失败时旧实例继续使用原声明。
宿主启动前通过 `InternalPluginManager::seed_message_types(id, types)` 注入持久化声明，旧声明即可在首次投递时使用；
热更新自动复制活动实例声明，之后由候选注册请求更新自己的缓存。
类型暂停继续接收和转换消息，调度跳过该类型；解除暂停后积压消息按原始顺序参与播放。
Rust 示例在启用启动或后台投递时先注册 `remote`，再投递相应消息。

## 接收者头像

HTTP incoming/send 和 InternalPlugin `message.post` 的消息 JSON 支持可选 `avatar_url`：

```json
{"source_id":"internal:example.counter","username":"示例插件","avatar_url":"https://example.com/avatar.png","document":{"version":1,"revision":0,"paragraphs":[{"segments":[{"text":"带头像的消息","style":{}}]}]}}
```

链接支持 HTTP/HTTPS，随消息保存并保留至转发、重试、插件事件和转换请求。Protobuf `Message` 追加可选字段 `avatar_url = 12`，省略字段的既有插件与历史记录继续兼容。客户端在后台加载图片，同一链接共享本次会话缓存，图片缺失、加载中或失败时显示姓名首个字素。建议提供直接图片链接或同源重定向；下载上限为 8 MiB，超时 5 秒。GIF 显示首帧缩略图。自己的头像由设置页的本地图片选择器管理。

Rust 示例：`cargo build -p vchat-example-plugin`，读取 target/debug 的动态库。
C++ 示例：安装 Protobuf 31.1，运行 `cmake -S Plugins -B target/cpp-plugin` 后构建。
指定 `-DCMAKE_PREFIX_PATH=<Protobuf31.1安装目录>`，`-DVCHAT_PROTOC=<protoc31.1可执行文件>`；
Windows 静态 Protobuf 使用 `-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded`，依赖及 SDK 统一 C++17。
构建后执行 `cargo test -p vchat-internal-plugin cpp_actual -- --ignored` 验证 C++ 动态库和状态迁移。
按平台修改 example.internal.json 的 platform 与 architecture；清单用于校验加载目标。

## 已验证的命令

```powershell
cargo +stable test -p vchat-plugin-api -p vchat-internal-plugin
cargo +stable clippy -p vchat-plugin-api -p vchat-internal-plugin -p vchat-example-plugin --all-targets -- -D warnings
git clone --depth 1 --branch v31.1 https://github.com/protocolbuffers/protobuf.git target/protobuf-src
cmake -S target/protobuf-src -B target/protobuf-clean -DCMAKE_CXX_STANDARD=17 -Dprotobuf_BUILD_TESTS=OFF -Dprotobuf_BUILD_SHARED_LIBS=OFF -Dprotobuf_BUILD_PROTOC_BINARIES=OFF -Dprotobuf_BUILD_LIBUPB=OFF -DCMAKE_INSTALL_PREFIX=<安装目录>
cmake --build target/protobuf-clean --config Release --parallel 8 --target install
cmake -S Plugins -B target/cpp-plugin -DCMAKE_PREFIX_PATH=<安装目录> -DVCHAT_PROTOC=<vendored protoc31.1路径> -DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded
cmake --build target/cpp-plugin --config Release --parallel 4
$env:VCHAT_CPP_TEST_LIBRARY = '<C++示例动态库路径>'
cargo +stable test -p vchat-internal-plugin cpp_actual -- --ignored
```

Windows x86_64 已验证 Rust DLL、C++ MSVC DLL、ABI 布局与中文/emoji Protobuf 交换；
迁移测试验证计数连续，故障测试验证 start/restore 回滚、旧事件顺序、超时隔离、权限与配置暂存。
三平台 CI 的 cpp-plugin 工作流构建固定 Protobuf 31.1，执行同一 C++ 动态库测试。
