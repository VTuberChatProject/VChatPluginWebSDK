# v3.1 手机与远程界面契约

首个 `Envelope` 固定为 major 3、minor 0，登记 `min_minor=1/max_minor=1`。
登记响应的 `minor` 用于后续所有请求、响应和通知。能力分别为 `remote-ui`、
`remote-send`、`remote-media`，权限与已登记插件身份及连接代次一起校验。
v3.0 插件继续使用原有消息、转换和事件回放协议。

## 同步

`Request.remote.subscribe` 创建原子订阅并冻结快照。快照 `RemoteTransfer`
可能先于 `Response.remote.subscribed` 到达，客户端应从发出请求起接收通知。
每块最大 256 KiB，按 transfer_id/index/count 收齐后解码为 `RemoteUpdate`，
完整内容最大 64 MiB。新快照原子替换内存列表，增量应用 upserts/removed_ids，
最后按完整 order 重排；列表与 PC 相同，最多 500 条。

每次 PC 启动生成新 epoch，投影变化递增 revision。增量的 base_revision 必须
等于客户端当前 revision。epoch 改变、分块缺失、revision 缺口、队列溢出均触发
重新连接和全量订阅。手机切后台关闭连接，保留内存视图并标记离线；回前台重新订阅。
正文、图片、草稿和待决发送均只在手机内存中存在。

## 发送

`Request.remote.send { operation_id, document }` 使用 PC 接受请求时的当前角色，
复用桌面本地消息流水线。各端草稿独立。响应为
`Response.remote.send { found, epoch, operation_id, message, identity }`。
同一设备 ID 和操作 ID 在 PC 进程内幂等；相同内容返回原回执，内容改变返回 conflict。
请求回执丢失时，用 `Request.remote.query { operation_id }` 查询。
PC 重启导致 epoch 改变时，由用户确认重发。发送回执受本次进程数量预算约束。

## 媒体

投影中的头像和图片 source 使用 `vchat-resource:<resource_id>`。真实文件路径和
PC 回环媒体 URL 留在宿主边界。`Request.remote.media_read` 指定 resource_id、
offset 和 max_bytes，响应提供 offset/total_size/mime/data/eof。分块最大 256 KiB，
媒体最大 16 MiB，访问与消息共用 Bearer 鉴权连接。

上传使用 `Request.remote.upload`，首块 upload_id 为空且 offset 为 0；随后使用
服务器返回的 upload_id，并保持 offset 连续。最后一块 finish=true，返回 image。
将此 image 放入待发送 Document，即可使用签发资源引用。单张图片最大 16 MiB，
支持 PNG/JPEG/GIF/WebP；PC 复用桌面解码限制和原子归档。未完成上传绑定连接代次，
断线或闲置 120 秒后回收；每连接最多 4 个，全局最多 16 个并发上传。

## 可运行示例

```sh
python Tools/generate.py
python target/python/remote-client.py --token YOUR_TOKEN --text "来自手机的消息" --image photo.png
```

示例维护有界内存同步视图，持续消费通知，并支持图片上传与当前角色发送。
