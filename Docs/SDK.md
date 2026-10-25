# 外部插件开发协议

外部插件连接 VChat `/api/v3/ws`，使用 Bearer 请求头认证，以 Binary WebSocket 帧交换 `external_plugin.proto` 定义的 Protobuf v3 `Envelope`。

1. 首条请求为 `register`，声明插件 ID、展示信息和 capabilities。
2. 登记响应确认 plugin_id、协商的 minor 版本；后续信封使用该版本。
3. `message_types_register` 注册消息类型；`messages_incoming` 和 `messages_send` 投递结构化消息。
4. 宿主通过 event 投递事件，`last_event_id` 用于断线重连续传。客户端应按收到的事件顺序处理。
5. transform 请求须按 request_id 返回对应结果；超时由宿主隔离处理。

每个请求使用唯一 request_id，失败检查 response.error。来源身份由连接登记决定。心跳由 WebSocket 协议层维护；客户端支持 Ping/Pong。单帧上限 4 MiB。

Python/C++ 示例及生成命令见 [README](../README.md)。Native ABI 插件使用 [NativeSDK](https://github.com/VTuberChatProject/VChatPluginNativeSDK)。宿主行为参考 [插件系统设计](https://github.com/VTuberChatProject/VChatRev/blob/main/Docs/PluginSystemDesign.md)。

v3.1 远程界面扩展见 [手机协议](Remote.md)：消息快照、完整增量、当前角色发送及媒体分块均使用既有鉴权 WebSocket。
