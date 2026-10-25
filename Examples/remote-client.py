"""v3.1 远程界面示例：内存同步、按 PC 当前角色发送及分块上传图片。"""
import argparse
import asyncio
import logging
import pathlib
import uuid

CHUNK_BYTES = 256 * 1024
MAX_TRANSFER = 64 * 1024 * 1024


class RemoteClient:
    """一个连接持有一份内存投影；版本缺口终止会话，由调用方重连。"""
    def __init__(self, protocol, socket):
        self.protocol, self.socket = protocol, socket
        self.minor = 0
        self.epoch, self.revision = None, 0
        self.records, self.order = {}, []
        self.transfer = None

    def update(self, frame):
        """限制分块长度和总量，收齐后一次提交同步结果。"""
        if not frame.count or frame.count > MAX_TRANSFER // CHUNK_BYTES:
            raise RuntimeError("同步分块数量无效")
        if len(frame.data) > CHUNK_BYTES:
            raise RuntimeError("同步分块过大")
        if frame.index == 0:
            self.transfer = (frame.transfer_id, frame.count, [], 0)
        if self.transfer is None:
            raise RuntimeError("同步分块起点丢失")
        transfer_id, count, chunks, size = self.transfer
        if transfer_id != frame.transfer_id or count != frame.count or frame.index != len(chunks):
            raise RuntimeError("同步分块顺序无效")
        if size + len(frame.data) > MAX_TRANSFER:
            raise RuntimeError("同步内容超过 64 MiB")
        chunks.append(frame.data)
        self.transfer = (transfer_id, count, chunks, size + len(frame.data))
        if len(chunks) != count:
            return
        update = self.protocol.RemoteUpdate.FromString(b"".join(chunks))
        if update.snapshot:
            self.records.clear()
        elif self.epoch != frame.epoch or self.revision != update.base_revision:
            raise RuntimeError("同步版本缺口，需要重新订阅")
        for record_id in update.removed_ids:
            self.records.pop(record_id, None)
        for record in update.upserts:
            self.records[record.message.id] = record
        self.order = list(update.order)
        self.epoch, self.revision = frame.epoch, frame.revision
        self.transfer = None
        logging.info("同步完成，记录 %d 条，修订 %d", len(self.order), self.revision)

    async def exchange(self, request):
        """接收请求回执期间持续应用提前到达的快照和增量。"""
        envelope = self.protocol.Envelope(major=3, minor=self.minor, request_id=str(uuid.uuid4()))
        envelope.request.CopyFrom(request)
        await self.socket.send(envelope.SerializeToString())
        while True:
            data = await asyncio.wait_for(self.socket.recv(), 30)
            if not isinstance(data, bytes):
                raise RuntimeError("协议需要 Binary 数据帧")
            packet = self.protocol.Envelope.FromString(data)
            if packet.HasField("remote_transfer"):
                self.update(packet.remote_transfer)
            if packet.request_id == envelope.request_id:
                if packet.response.HasField("error"):
                    raise RuntimeError(f"{packet.response.error.code}: {packet.response.error.message}")
                return packet.response

    async def upload(self, path):
        """图片驻留内存，完成后使用 PC 签发的资源引用发送。"""
        if path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("图片超过 16 MiB")
        data, upload_id = path.read_bytes(), ""
        if not data:
            raise ValueError("图片为空")
        for offset in range(0, len(data), CHUNK_BYTES):
            request = self.protocol.Request()
            request.remote.upload.CopyFrom(self.protocol.RemoteUpload(
                upload_id=upload_id, name=path.name, offset=offset,
                data=data[offset:offset + CHUNK_BYTES], finish=offset + CHUNK_BYTES >= len(data)))
            result = (await self.exchange(request)).remote.upload
            upload_id = result.upload_id
        return result.image


async def run(arguments):
    """登记、同步并可选发送内容，随后持续处理远程更新。"""
    import external_plugin_pb2 as protocol
    from websockets.asyncio.client import connect
    async with connect(arguments.endpoint, additional_headers={"Authorization": f"Bearer {arguments.token}"},
                       max_size=4 * 1024 * 1024) as socket:
        client = RemoteClient(protocol, socket)
        request = protocol.Request()
        request.register.CopyFrom(protocol.Register(
            id=arguments.id, name="远程界面示例", min_minor=1, max_minor=1,
            capabilities=["remote-ui", "remote-send", "remote-media"]))
        registration = (await client.exchange(request)).register
        client.minor = registration.minor
        request = protocol.Request()
        request.remote.subscribe.SetInParent()
        await client.exchange(request)
        if arguments.text or arguments.image:
            document = protocol.Document(version=1)
            paragraph = document.paragraphs.add()
            if arguments.text:
                paragraph.segments.add(text=arguments.text)
            if arguments.image:
                paragraph.segments.add().image.CopyFrom(await client.upload(arguments.image))
            request = protocol.Request()
            request.remote.send.CopyFrom(protocol.RemoteSend(operation_id=str(uuid.uuid4()), document=document))
            result = (await client.exchange(request)).remote.send
            logging.info("发送已确认，消息 ID=%s", result.message.id)
        async for data in socket:
            packet = protocol.Envelope.FromString(data)
            if packet.HasField("remote_transfer"):
                client.update(packet.remote_transfer)


def main():
    """令牌用于升级请求头，日志只记录状态和消息 ID。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="ws://127.0.0.1:38601/api/v3/ws")
    parser.add_argument("--token", required=True)
    parser.add_argument("--id", default="example.remote-mobile")
    parser.add_argument("--text")
    parser.add_argument("--image", type=pathlib.Path)
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        asyncio.run(run(arguments))
    except KeyboardInterrupt:
        pass
    except Exception:
        logging.exception("远程界面会话结束")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
