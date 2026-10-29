"""外部 Protobuf v3 最小客户端；先生成 external_plugin_pb2.py，再安装 websockets。"""
import argparse
import asyncio
import logging
import uuid


async def connect(endpoint, token, plugin_id, output_card=False):
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
        if output_card:
            registration.min_minor = registration.max_minor = 2
            registration.capabilities.extend(["ui", "output_cards_v1"])
            registration.output_cards.add(id="console", title="SDK 控制台", subtitle="按卡片消费定向消息")
            registration.output_endpoints.add(card_id="console", receipt_mode="completed")
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
            if envelope.HasField("request") and envelope.request.HasField("output_delivery"):
                delivery = envelope.request.output_delivery
                logging.info("卡片 %s 消费消息 %s: %s", delivery.card_id, delivery.message_id,
                             delivery.message.document)
                acknowledgement = protocol.Envelope(major=3, minor=2, request_id=envelope.request_id)
                acknowledgement.response.output_delivery.SetInParent()
                await socket.send(acknowledgement.SerializeToString())
                if delivery.operation != "preview":
                    receipt = protocol.Envelope(major=3, minor=2, request_id=str(uuid.uuid4()))
                    receipt.request.output_receipt.CopyFrom(delivery)
                    receipt.request.output_receipt.status = "completed"
                    await socket.send(receipt.SerializeToString())


def main():
    """从参数读取连接设置；令牌仅用于请求头。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="ws://127.0.0.1:38601/api/v3/ws")
    parser.add_argument("--token", required=True)
    parser.add_argument("--id", default="example.python-sdk")
    parser.add_argument("--output-card", action="store_true", help="声明并消费独立控制台输出卡片")
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        asyncio.run(connect(arguments.endpoint, arguments.token, arguments.id, arguments.output_card))
    except KeyboardInterrupt:
        pass
    except Exception:
        logging.exception("外部插件客户端结束")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
