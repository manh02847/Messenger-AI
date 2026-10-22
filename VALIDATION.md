# Kiểm tra bản 1.0.0 — 22/10/2026

Đã kiểm tra trên Linux x86-64, Python 3.12:

- 33 bài test offline: đạt.
- Kiểm tra cú pháp và lint: đạt.
- Wheel Messenger 2.3.4: kiểm đúng SHA-256 của bản phát hành.
- Binary E2EE Linux x86-64 thật: kiểm đúng SHA-256, chạy được và trả hợp lệ cho RPC `hello`.
- Giao thức bridge phiên bản 1 và các hàm `newClient`, `connect`, `connectE2EE`, `isConnected`, `events`: đạt.

Các tình huống được kiểm tra bằng mô phỏng: danh sách cuộc trò chuyện, hai tuyến E2EE/tin thường, chống trùng qua khởi động lại, gộp tin, đổi tin khi AI đang soạn, người dùng tự nhắn, echo đến trước kết quả gửi, timeout/trạng thái gửi chưa rõ, xem trước không gửi, chuyển người dùng xử lý, giới hạn lượt gửi và gọi AI, HTTP 401/429, ẩn lỗi chứa thông tin nhạy cảm, chỉ lấy câu trả lời cuối.

Chưa thực hiện vì chưa có thông tin cấu hình của bạn:

- Gọi Groq bằng API key thật.
- Đăng nhập Messenger bằng phiên tài khoản của bạn.
- Gửi/nhận thật, khôi phục thiết bị E2EE sau khi có tin thật hoặc thử mất mạng với Facebook.
- Cài/running thực tế trên Windows, macOS hoặc Linux ARM64.

Không có tin nhắn thật nào được gửi trong quá trình chuẩn bị gói này. Chạy `check-ai`, `discover` và `run --dry-run` tại máy của bạn để kiểm tra tiếp trước khi dùng `--live`.
