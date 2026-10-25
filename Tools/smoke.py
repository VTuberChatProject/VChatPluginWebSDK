"""验证生成的 v3 类型及真实宿主登记、消息与事件交互。"""
import argparse
import asyncio
import logging
import pathlib
import sys
import uuid


async def exchange(protocol, endpoint, token):
    """发送独立请求并确认 Binary 信封的实际交互。"""
    from websockets.asyncio.client import connect
    async with connect(endpoint, additional_headers={'Authorization': f'Bearer {token}'}) as socket:
        request = protocol.Envelope(major=3, request_id='register')
        request.request.register.id = 'example.web-sdk-smoke'
        request.request.register.name = 'WebSDK smoke'
        request.request.register.capabilities.extend(['messages', 'events'])
        await socket.send(request.SerializeToString())
        reply = protocol.Envelope.FromString(await asyncio.wait_for(socket.recv(), 10))
        if not reply.response.HasField('register'):
            raise RuntimeError(f'登记失败: {reply}')
        message = protocol.Envelope(major=3, request_id='incoming')
        message.request.messages_incoming.source_message_id = str(uuid.uuid4())
        message.request.messages_incoming.username = 'SDK 验证'
        message.request.messages_incoming.document.version = 1
        message.request.messages_incoming.document.paragraphs.add().segments.add(text='跨仓库协议验证 👋')
        await socket.send(message.SerializeToString())
        accepted = event = False
        while not (accepted and event):
            reply = protocol.Envelope.FromString(await asyncio.wait_for(socket.recv(), 10))
            if reply.HasField('response') and reply.response.HasField('error'):
                raise RuntimeError(str(reply.response.error))
            accepted |= reply.request_id == 'incoming' and reply.response.HasField('accepted_message')
            event |= reply.HasField('event')
        logging.info('真实宿主登记、消息与事件验证通过')


def main():
    """默认验证离线往返；提供 endpoint 时连接真实宿主。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generated', type=pathlib.Path, default=pathlib.Path(__file__).resolve().parents[1] / 'target/python')
    parser.add_argument('--endpoint')
    parser.add_argument('--token')
    arguments = parser.parse_args()
    sys.path.insert(0, str(arguments.generated.resolve()))
    import external_plugin_pb2 as protocol
    value = protocol.Envelope(major=3, request_id='offline-中文')
    value.request.register.id = 'example.offline'
    assert protocol.Envelope.FromString(value.SerializeToString()) == value
    logging.info('Protobuf v3 离线往返通过')
    if arguments.endpoint:
        if not arguments.token:
            parser.error('--endpoint 需要 --token')
        asyncio.run(exchange(protocol, arguments.endpoint, arguments.token))


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    try:
        main()
    except Exception:
        logging.exception('WebSDK 验证失败')
        raise SystemExit(1)
