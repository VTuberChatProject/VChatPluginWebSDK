# VChat Plugin Web SDK

面向外部插件开发的 Protobuf v3 契约与 Python/C++ WebSocket 示例。默认端点为 `ws://127.0.0.1:38601/api/v3/ws`，Bearer 令牌通过请求头传递。

## Python

安装 Python 3.10+、protoc，然后执行：

```sh
python -m pip install -r requirements.txt
python Tools/generate.py
python Tools/smoke.py
python target/python/sdk-client.py --endpoint ws://127.0.0.1:38601/api/v3/ws --token YOUR_TOKEN
python Tools/smoke.py --endpoint ws://127.0.0.1:38601/api/v3/ws --token YOUR_TOKEN
```

## C++

安装 CMake、Protobuf 和 Boost.System 开发包：

```sh
cmake -S Examples -B target/cpp
cmake --build target/cpp --config Release
# 使用平台对应的可执行文件路径
./target/cpp/vchat_web_client 127.0.0.1 38601 YOUR_TOKEN
```

[开发说明](Docs/SDK.md) 描述 Binary 帧、登记、事件和转换约定。主程序维护自己的协议副本，跨仓库集成 CI 对照契约并验证真实交互。

## 迁移来源

从 `VTuberChatProject/VChatRev` 提交 `985c2a1ae3717f6918cb6030b6dd755d01edff9a` 提取协议、客户端及相关文档历史；路径重映射后的提交保留原作者、日期和说明。许可证见 [LICENSE](LICENSE)。
