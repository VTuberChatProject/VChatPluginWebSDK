# InternalPlugin SDK

ABI 主版本为 1，协议主版本为 1。Rust 使用 `vchat-plugin-api`，C/C++ 使用
`internal_plugin.h` 和 `internal_plugin.proto`；生成器由 `protoc-bin-vendored = 3.2.0`
锁定为 Protobuf 31.1。字段编号保留兼容性，新增 ABI 表字段通过 `struct_size` 协商。

动态库导出 `vchat_internal_plugin_get_api`，worker 复制函数表。`create` 接收稳定的
HostApi 地址与 JSON 配置；输出独立实例地址。每个插件代次在独立 worker 进程执行，生命周期及 invoke 串行运行。宿主服务通过内部 IPC 同步转发到主进程。
请求缓冲区在本次调用内有效。插件通过 write 回调复制响应，宿主释放宿主缓冲区，插件释放插件对象。
各 ABI 函数捕获 panic/异常，禁止异常穿过 ABI 边界。单响应最大 16 MiB。

invoke 接收 PluginRequest 并返回 PluginResponse。`transform` 的 payload_json 保存共享
消息 JSON；文档采用 Paragraph/Segment/TextStyle/Image 结构化字段，extra_json 保留未知扩展；
`ui.command` 同时携带文档、修订号和选区，返回 edit 时宿主核对 expected_revision。
`ui.settings` 接收配置字段。UI 字段 kind 使用 text、number、switch、enum、color。
`transform` 和 `event` 同时携带结构化 message（包含 document 与消息来源、身份、时序、状态、message_type、avatar_url）；
`config.changed` 通知配置变化，payload_json 保留版本扩展入口。转换结果优先使用 edit.replacement，
payload_json 可返回共享消息 JSON。Rust 用 document_to_proto/document_from_proto/message_to_proto 转换。

HostApi.invoke 接收 HostRequest：runtime.paths 返回本代次包根目录、资源目录与持久化数据目录；log 记录日志；config 写回 JSON 配置；config.set 更新并投递配置变更事件；message.post 投递消息；message.types.register 注册消息类型；
event.subscribe 注册订阅；ui.register 注册 UiContribution；frontend.register 声明一个可接收消息的前端；frontend.message 投递前端消息；frontend.receipt 提交前端回执；
frontend.clear 清空当前前端显示，与 frontend.message、frontend.receipt 共用 frontend 权限。
ui.window.* 请求宿主创建、更新或关闭 NanaUI 窗口。`web.route.register` 使用 `web` 权限注册整组 HTTP/WS 路由，重复或重叠的 method/path 会被拒绝，插件停用时路由与连接一并清理。示例：

```json
{"version":1,"routes":[{"kind":"http","method":"GET","path":"/example/*","operation":"example.http"},{"kind":"websocket","method":"GET","path":"/example-ws","operation":"example.ws"}]}
```

HTTP 路由调用插件的 operation，payload 包含 version、method、path、query、headers 和 byte-array body；PluginResponse 的 status、content_type、no_store、body 生成 HTTP 响应。WebSocket 由 WebService 建立和关闭，插件依次收到 `<operation>.open`、`<operation>.message`、`<operation>.close` 调用，payload 带 connection_id、path、query、preview 和 data。候选插件的 `start` 阶段同步校验路由冲突，校验失败会回滚热更新；成功路由在代次提交时切换。`websocket.send` 按 connection_id 单播，`websocket.broadcast` 向本插件频道广播原始 JSON；广播消息不会进入其他插件频道。两者 payload 使用 `{ "connection_id": "...", "data": ..., "preview": false }`，广播可省略 connection_id。

权限分别使用 messages、events、ui、frontend、web；所有新增服务的 payload_json 必须是有效 JSON，服务事件仍按插件代次排队。
回调线程安全，宿主将事件入队。插件必须复制暂存的请求。HostContext 和 generation 随实例固定。

剧本投递的 `message` 操作在既有 `frontend_id`、`batch_id`、`message` 外携带 `run_id` 和递增的 `generation`。宿主按批次立即替换显示，NanaDialogue 的完成回执由 UI 实际逐字呈现结束后提交。`clear` 操作携带 `frontend_id`、`message_id`、`batch_id`、`run_id`、`generation`，插件通过 `frontend.clear` 转交宿主。宿主过滤已退休批次的显示更新、完成回执和异步失败；普通消息继续沿用原有投递格式。

quiesce 成功表示插件的后台线程、任务和宿主回调全部结束。resume 重新启用实例。
save_state 输出 StateSnapshot（插件 ID、非零格式版本、状态字节），restore_state 负责版本迁移。
热更新先创建候选进程并预加载包内库，暂停旧实例，导出快照，在暂存宿主上下文中恢复候选实例。
候选 start 成功后持久化新包引用，再切换活动代次和 UI；失败回收候选并 resume 旧实例。
暂存实例的消息投递按顺序缓存，提交后释放；失败候选事件丢弃。
消息类型注册同样进入代次事务队列，声明先于该类型消息投递，候选失败时丢弃注册。
宿主 `reload` 沿用配置；`reload_with_config(id, manifest, path, values)` 将新配置送入候选实例，
迁移成功时提交配置，失败时保留原配置。配置、代次和事件暂存共用事务锁。
新实例提交后清理旧进程，清理失败时强制结束并记录日志。
调用超过 5 秒、IPC 断开或插件崩溃时，宿主终止并回收进程，撤销该插件的 UI 与路由，用户通过设置手动重启。
独立进程提供故障隔离；插件继续拥有当前用户的操作系统访问权限。

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

## `.vcplug` 打包与资源

`.vcplug` 是标准 ZIP，单包对应一个平台与架构，布局为：

```text
manifest.json
bin/<入口动态库及配套原生依赖>
resources/<网页、媒体、默认配置、主题等>
```

清单示例（入口文件名按目标平台生成）：

```json
{"package_version":1,"entry":"bin/example.dll","id":"example.counter","version":"1.0.0","platform":"windows","architecture":"x86_64","abi_version":1,"protocol_version":1,"capabilities":["ui","messages","events"]}
```

`entry` 为包内 `bin/` 下相对路径。平台使用 Rust OS 名称（windows、linux、macos），架构使用 x86_64、aarch64 等 Rust 目标架构名。插件 ID 用 ASCII 字母、数字、点、下划线、连字符表示。打包工具校验清单、入口与包内路径，加载器验证 ZIP 完整性并限制解压规模。

```powershell
cargo build --locked -p vchat-example-plugin -p vchat-echolive-config-plugin -p vchat-nana-dialogue-plugin
cargo run --locked -p vchat-internal-plugin --bin vchat-plugin-pack -- builtin . target/debug target/debug
cargo run --locked -p vchat-internal-plugin --bin vchat-plugin-pack -- pack target/plugin-stage target/example.vcplug
```

插件在 `create` 中通过 `HostRequest.service = "runtime.paths"` 查询：

```json
{"package_root":"/当前代次包目录","resources_root":"/当前代次包目录/resources","data_root":"/插件持久化数据目录"}
```

Rust 使用 `unsafe { vchat_plugin_api::runtime::runtime_paths(&host) }`；C/C++ 使用现有 HostApi 回调解析同一 JSON。资源路径随代次变化，配置与可写数据独立持久化。每个进程只加载对应包内动态库；Linux 原生依赖使用 `$ORIGIN` 或 worker 搜索环境，macOS 使用 `@loader_path/@rpath`，Windows 依赖与入口放在同一目录。

应用导入后按插件 ID 与包 SHA-256 保存受控副本。更新采用候选进程、状态快照迁移和暂存宿主事件；数据库保存成功后提交活动代次，失败恢复旧实例。成功更新关闭该插件原有 WebSocket 连接，客户端重新连接后重新触发 open。

C++ 示例安装 Protobuf 31.1 后运行 `cmake -S Plugins -B target/cpp-plugin` 并构建。指定 `-DCMAKE_PREFIX_PATH=<Protobuf31.1安装目录>`、`-DVCHAT_PROTOC=<protoc31.1可执行文件>`；Windows 静态 Protobuf 使用 `-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded`。将产出的库放入 `bin/`，使用对应 `entry` 生成插件包。

## 已验证的命令

```powershell
cargo +stable build --locked -p vchat-internal-plugin --bin vchat-plugin-worker
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
迁移测试验证计数连续，故障测试覆盖 start/restore 回滚、事件顺序、进程超时隔离、权限与配置暂存。
三平台 CI 的 cpp-plugin 工作流构建固定 Protobuf 31.1，执行同一 C++ 动态库测试。
