# Kiểm tra bản 1.0.0 — 22/10/2026

Đã kiểm tra trên Linux x86-64, Python 3.12:

- 76 bài test offline: đạt (gồm chế độ rep tất cả chat riêng).
- Kiểm tra cú pháp và lint: đạt.
- Wheel Messenger 2.3.4: kiểm đúng SHA-256 của bản phát hành.
- Binary E2EE Linux x86-64 thật: kiểm đúng SHA-256, chạy được và trả hợp lệ cho RPC `hello`.
- Giao thức bridge phiên bản 1 và các hàm `newClient`, `connect`, `connectE2EE`, `isConnected`, `events`: đạt.

Các tình huống được kiểm tra bằng mô phỏng: danh sách cuộc trò chuyện, hai tuyến E2EE/tin thường, chống trùng qua khởi động lại, gộp tin, đổi tin khi AI đang soạn, người dùng tự nhắn, echo đến trước kết quả gửi, timeout/trạng thái gửi chưa rõ, xem trước không gửi, chuyển người dùng xử lý, giới hạn lượt gửi và gọi AI, HTTP 401/429, ẩn lỗi chứa thông tin nhạy cảm, chỉ lấy câu trả lời cuối.

Bản cập nhật kiểm tra thêm: model trả nhầm HANDOFF cho “đang lag gì thế” không tạm dừng; tin tiếp theo vẫn được xử lý; yêu cầu dừng rõ ràng hủy bản nháp; chat-ai giữ cả hai vai hội thoại và reset ngữ cảnh; giới hạn ký tự vẫn giữ tin mới nhất; tune-chat giữ nguyên người nhận, các cấu hình khác và bí mật đăng nhập.

Các test này kiểm tra hành vi phần mềm, không đo khả năng hiểu tiếng lóng/sai chính tả của model. Chưa có thử nghiệm API thật để so sánh chất lượng model hoặc xác nhận 2048 token đủ cho mọi lượt.

Chưa thực hiện vì chưa có thông tin cấu hình của bạn:

- Gọi Groq bằng API key thật.
- Đăng nhập Messenger bằng phiên tài khoản của bạn.
- Gửi/nhận thật, khôi phục thiết bị E2EE sau khi có tin thật hoặc thử mất mạng với Facebook.
- Cài/running thực tế trên Windows, macOS hoặc Linux ARM64.

Không có tin nhắn thật nào được gửi trong quá trình chuẩn bị gói này. Chạy `check-ai`, `discover` và `run --dry-run` tại máy của bạn để kiểm tra tiếp trước khi dùng `--live`.

## Phạm vi tất cả chat riêng

Kiểm tra thêm: nhận chat riêng E2EE và các threadType 1/7/10/13/15; chặn nhóm E2EE, nhóm thường, broadcast, loại thiếu/không biết/sai kiểu; chặn nhóm kể cả khi ID đã nằm trong allowlist. Danh sách rỗng vẫn nhận chat riêng ở chế độ all_private, ngữ cảnh tách theo chat, tin thủ công hủy bản nháp. Đổi scope giữ các cấu hình khác và không chạm secrets.json. Cấu hình cũ vẫn mặc định allowlist.

Đối chiếu schema với nguồn đúng phiên bản bridge 2.3.4:

- [Bridge events.go](https://github.com/m008v/fbchat-v2/blob/aa7abd0386ef1d4cabf8ce592d0f2cf308d8f4f6/bridge-e2ee/bridge/events.go): E2EE chatJid lấy từ e.Info.Chat; tin thường có threadType, mặc định 0 nếu không có cache metadata.
- [whatsmeow JID](https://github.com/tulir/whatsmeow/blob/0057a822e79a/types/jid.go) và [message source](https://github.com/tulir/whatsmeow/blob/0057a822e79a/message.go): MessengerServer là msgr; nhóm dùng g.us, broadcast được phân loại nhóm. Bot chỉ nhận JID số hợp lệ thuộc msgr trong chế độ all_private.
- [mautrix-meta ThreadType](https://github.com/mautrix/meta/blob/cea2e38c9107be591bcd1b7a6562ccc72400ce23/pkg/messagix/table/enums.go): chỉ nhận các loại one-to-one của người dùng, loại AI_BOT không được tự rep.

Chưa thử chế độ all_private với tài khoản thật. Việc nhận tin từ tin nhắn chờ hoặc từng loại hội thoại phụ thuộc những sự kiện bridge thực sự cung cấp; bot bỏ qua nếu không xác định được chat riêng.
