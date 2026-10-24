"""外部 Protobuf v3 最小客户端；先生成 external_plugin_pb2.py，再安装 websockets。"""
import argparse
import asyncio
import logging
import uuid


async def connect(endpoint, token, plugin_id):
    """登记后投递一条结构化消息，并接收强类型响应和事件。"""
    import external_plugin_pb2 as protocol
    from websockets.asyncio.client import connect as websocket_connect

    async with websocket_connect(endpoint, additional_headers={"Authorization": f"Bearer {token}"},
                                 max_size=4 * 1024 * 1024) as socket:
        register = protocol.Envelope(major=3, minor=0, request_id="register-1")
        registration = register.request.register
        registration.id = plugin_id
        registration.name = "Protobuf SDK 示例"
        registration.capabilities.extend(["messages", "events"])
        await socket.send(register.SerializeToString())
        result = protocol.Envelope.FromString(await socket.recv())
        if result.response.WhichOneof("body") == "error":
            raise RuntimeError(result.response.error.message)
        if result.response.WhichOneof("body") != "register":
            raise RuntimeError("宿主返回了错误的登记响应类型")
        logging.info("登记成功: %s", result.response.register.plugin_id)
        message = protocol.Envelope(major=3, minor=result.response.register.minor,
                                    request_id=str(uuid.uuid4()))
        incoming = message.request.messages_incoming
        incoming.username = "SDK 示例"
        incoming.source_message_id = str(uuid.uuid4())
        incoming.document.version = 1
        incoming.document.paragraphs.add().segments.add(text="你好，Protobuf v3")
        await socket.send(message.SerializeToString())
        async for data in socket:
            if not isinstance(data, bytes):
                raise RuntimeError("宿主数据帧需要为 Binary")
            envelope = protocol.Envelope.FromString(data)
            logging.info("收到 %s: %s", envelope.WhichOneof("body"), envelope)


def main():
    """从参数读取连接设置；令牌仅用于请求头。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="ws://127.0.0.1:38601/api/v3/ws")
    parser.add_argument("--token", required=True)
    parser.add_argument("--id", default="example.python-sdk")
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        asyncio.run(connect(arguments.endpoint, arguments.token, arguments.id))
    except KeyboardInterrupt:
        pass
    except Exception:
        logging.exception("外部插件客户端结束")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
