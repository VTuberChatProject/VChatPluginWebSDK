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

## v3.2 输出卡片

预览使用 `operation=preview`，目标由 Host 当前连线选择；插件回复请求接收后跳过正式完成回执。

登记时设置 `min_minor=2/max_minor=2`、能力 `ui/output_cards_v1`，同时提供 `output_cards` 及 `output_endpoints`。端点使用对应卡片的 `card_id`，实时输出的 `receipt_mode` 为 `completed`，归档输出为 `accepted`。旧登记缺省端点集合；用户连线从空集合开始。

宿主 `request.output_delivery` 携带 `frontend_id/plugin_id/card_id/message_id/batch_id/session_generation`、结构化消息及 `operation`（`message` 或 `clear`）。剧本另带 `run_id/generation`。插件回复同请求编号的 `response.output_delivery`，消费完成后发送独立请求 `request.output_receipt`，原样回传定位与代次字段，填写 `status=completed/accepted`；失败填写 `failed/error`。宿主验证当前会话、端点归属及活动批次。

运行 `python target/python/sdk-client.py --token YOUR_TOKEN --output-card`，即可登记控制台输出卡片。画布连接来源后，示例消费定向消息并回传完成确认。同插件各卡片分别维护状态和回执，用户修改连线作用于随后接纳的新消息。
