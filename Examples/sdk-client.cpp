// 外部 Protobuf v3 客户端：依赖 Boost.Beast 与生成的 external_plugin.pb.h。
#include <boost/asio/connect.hpp>
#include <boost/beast/core.hpp>
#include <boost/beast/websocket.hpp>
#include <iostream>
#include <stdexcept>
#include "external_plugin.pb.h"

// 建立明文 WebSocket 连接，登记并读取强类型响应；生产环境按部署需求使用 TLS。
int main(int argc, char** argv) {
    if (argc != 4) {
        std::cerr << "usage: sdk-client <host> <port> <token>\n";
        return 2;
    }
    try {
        namespace net = boost::asio;
        namespace ws = boost::beast::websocket;
        net::io_context context;
        net::ip::tcp::resolver resolver(context);
        ws::stream<boost::beast::tcp_stream> socket(context);
        boost::beast::get_lowest_layer(socket).expires_after(std::chrono::seconds(15));
        boost::beast::get_lowest_layer(socket).connect(resolver.resolve(argv[1], argv[2]));
        socket.set_option(ws::stream_base::timeout::suggested(boost::beast::role_type::client));
        socket.set_option(ws::stream_base::decorator([&](ws::request_type& request) {
            request.set(boost::beast::http::field::authorization, std::string("Bearer ") + argv[3]);
        }));
        socket.read_message_max(4 * 1024 * 1024);
        socket.handshake(std::string(argv[1]) + ":" + argv[2], "/api/v3/ws");
        vchat::external::v3::Envelope envelope;
        envelope.set_major(3);
        envelope.set_request_id("register-1");
        auto* registration = envelope.mutable_request()->mutable_register_();
        registration->set_id("example.cpp-sdk");
        registration->set_name("C++ SDK 示例");
        registration->add_capabilities("events");
        std::string bytes;
        if (!envelope.SerializeToString(&bytes)) throw std::runtime_error("登记编码失败");
        socket.binary(true);
        socket.write(net::buffer(bytes));
        boost::beast::flat_buffer buffer;
        socket.read(buffer);
        bytes = boost::beast::buffers_to_string(buffer.data());
        if (!socket.got_binary() || !envelope.ParseFromString(bytes))
            throw std::runtime_error("登记响应格式无效");
        if (envelope.response().has_error()) throw std::runtime_error(envelope.response().error().message());
        if (!envelope.response().has_register_()) throw std::runtime_error("登记响应类型无效");
        std::cout << envelope.response().register_().DebugString();
        socket.close(ws::close_code::normal);
    } catch (const std::exception& error) {
        std::cerr << "SDK 客户端失败: " << error.what() << '\n';
        return 1;
    }
}
