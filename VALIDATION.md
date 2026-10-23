# Kiểm tra bản 1.0.0 — 22/10/2026

Đã kiểm tra trên Linux x86-64, Python 3.12:

- 132 bài test offline: đạt (gồm thời gian riêng cho Flash, Google retry, chuyển model/nguồn dự phòng và nâng giới hạn).
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

## Nâng độ dài câu trả lời

Nâng mặc định lên 4096 token tạo câu trả lời (gồm suy luận) và 4000 ký tự văn bản thay cho 500. Lệnh tune-chat cập nhật cấu hình cũ, giữ mức ký tự cao hơn nếu đã đặt. Kiểm tra hồi quy 76 test offline đạt; chưa đo token thực tế hay gọi API thật. Đầu vào giữ nguyên giới hạn lịch sử để không tăng tiêu hao ngoài yêu cầu.

## Cloudflare Workers AI

81 test offline đạt. Kiểm tra endpoint/account, token dùng đúng nhà cung cấp, max_tokens cho Cloudflare, không gửi tham số riêng của Groq, lọc suy luận, lỗi 403 không lộ token và không tự fallback. Lệnh configure-ai giữ cookie, scope và các giới hạn khác; nhập Account ID sai không ghi đè cấu hình. Kiểm tra đổi lại Groq và giữ key Cloudflare. Lệnh cấu hình chỉ xác minh định dạng, không gọi API hay Messenger.

Chưa có Account ID/API token Cloudflare nên chưa thử endpoint thật hoặc chất lượng tiếng Việt. Người dùng chạy check-ai/chat-ai tại VPS để xác nhận trước khi chạy bot. Không coi test mô phỏng là xác nhận quota hay số lượt/ngày thực tế.

## Tự chuyển hai nhà cung cấp

91 test offline đạt. Kiểm tra 429 chuyển sang nguồn thứ hai với cùng lịch sử; mỗi request trừ ngân sách chung; Retry-After 3600 giây ngăn thử lại nguồn lỗi trong thời gian chờ; hết thời gian thì thử lại. Hai nguồn cùng lỗi không gọi liên tục. Lỗi auth/cấu hình và giới hạn cục bộ không bị che bởi fallback. Kiểm tra 408, 503, lỗi mạng được phân loại chuyển nguồn, không lộ phản hồi lỗi. CLI yêu cầu đủ hai key trước khi lưu, hỗ trợ bật/tắt fallback; đóng cả hai client khi dừng.

Chưa chạy hai API thật hoặc kiểm tra giọng model khi đổi nguồn. Nguồn giao thức lỗi Cloudflare: https://developers.cloudflare.com/workers-ai/platform/errors/ (408 timeout, 429 quota/capacity).

## Qwen3.8 và giới hạn 1000

96 test offline và lint đạt. Kiểm tra request Qwen3.8 trên cả Groq/Cloudflare dùng max_completion_tokens và reasoning_effort low; chỉ Groq nhận reasoning_format hidden. Không gửi include_reasoning hoặc /no_think cho model này. Phản hồi mô phỏng chỉ kiểm tra bot lấy nội dung cuối, không chứng minh model hiểu sai chính tả.

Kiểm tra upgrade-chat nâng giới hạn từng chat và số lần gọi chung lên ít nhất 1000/ngày, đổi model chính/dự phòng đang bật, giữ mức giới hạn cao hơn và cấu hình khác. Chạy lại không đổi kết quả, không sửa secrets.json. Không gọi API thật hoặc đo chất lượng, độ trễ, quota thực tế; cần chạy check-ai/chat-ai trên VPS trước khi khởi động lại bot.

## Google AI Studio và danh sách model ưu tiên

117 test offline đạt. Thêm kiểm tra giao thức generateContent cho cả bốn model, giữ system instruction và hai vai hội thoại, gửi key bằng header đúng host, không đặt key trong URL. Loại phần thought, chặn phản hồi bị cắt/chặn/chỉ có suy luận. Kiểm tra luân chuyển bốn model Google đến Groq khi 429, cùng lịch sử và ngân sách, giữ thứ tự, bỏ qua model đang nghỉ, dừng ngay khi một model trả lời. HTTP 404 của model nghỉ một giờ; 400/401/403 dừng và không lộ body lỗi/key. Kiểm tra RetryInfo và QuotaFailure ngày theo múi giờ Pacific. Lệnh cấu hình giữ nguồn cũ/cookie/giới hạn, lưu key 0600, tắt nguồn không xóa key và từ chối cấu hình trùng/sai/thiếu key trước khi ghi.

Chưa có Google API key nên chưa gọi API thật, xác minh quyền của từng model, đo chất lượng tiếng Việt hoặc xác nhận quota chia sẻ. check-ai dùng tuyến ưu tiên và báo model thực sự trả lời, không xác nhận toàn bộ nguồn. Lệnh configure-google không bật thanh toán hay thay ngân sách cục bộ. Giới hạn thời gian toàn tuyến là 60 giây, tránh chờ lần lượt quá lâu khi nhiều dịch vụ mất kết nối.

## Retry Google và giảm thời gian chờ khi dịch vụ lỗi

129 test offline và lint đạt. Kiểm tra lỗi 500/503 nhanh được thử thêm đúng một lần với cùng request, mỗi lần trừ ngân sách; lỗi tiếp diễn thì chuyển nguồn. Không retry 429, lỗi mạng/timeout, lỗi trả về chậm hoặc Retry-After/RetryInfo yêu cầu chờ lâu. Kiểm tra cạn ngân sách sau lần đầu ngăn request thứ hai. Request Google có read timeout 8 giây và connect timeout 4 giây; hạn model 12 giây, cả nhóm Google 20 giây. Kiểm tra hạn tổng hủy request đang chờ, bỏ qua Google còn lại và tới nguồn dự phòng; hủy tác vụ từ ngoài không biến thành retry. Các deadline được thu nhỏ trong test để kiểm tra cơ chế hủy thực, không cần đợi 12/20 giây.

Thay đổi dựa trên log người dùng có Google chờ 25 giây trước khi chuyển Cloudflare. Chưa đo độ trễ API thật sau sửa; timeout ngắn có thể bỏ qua phản hồi hợp lệ chậm. Không thay thứ tự model, persona, phạm vi chat, giới hạn cục bộ hoặc thời gian nhường.

## Dành thời gian cho Flash

132 test offline và lint đạt. Sửa trường hợp hai Gemma dùng hết 20 giây Google khiến Flash bị bỏ qua: khi có Flash, hai Gemma dùng chung tối đa 10 giây; phần còn lại của 20 giây dành cho các model Google tiếp theo. Kiểm tra request Gemma treo bị hủy và Gemini 3.5 Flash Lite thực sự được gọi/trả lời; kiểm tra cả trường hợp Gemma đầu đã lỗi mạng rồi Gemma thứ hai treo. Nếu Flash cũng treo thì hạn Google vẫn có hiệu lực, hủy request và chuyển Groq. Không gọi model còn lại sau khi có câu trả lời thành công, vẫn tính ngân sách từng request. Các test timeout dùng thời gian thu nhỏ; chưa đo với API thật. Lỗi auth/cấu hình, quota và giới hạn cục bộ vẫn được giữ nguyên.


### ChatGPT web / chat tạm thời

- Toàn bộ 143 kiểm thử offline và Ruff đều đạt.
- 11 ca bổ sung kiểm tra giới hạn/ngăn trộn ngữ cảnh, tạo tab tạm mới mỗi lượt,
  chặn gửi khi chưa xác nhận đăng nhập/chế độ tạm, đóng tab khi hủy/lỗi,
  không trả phản hồi đang stream hoặc gửi lại khi không chắc, ngân sách cục bộ,
  giữ thứ tự API dự phòng, cấu hình không đụng secrets và lệnh check web không
  fallback API. Các bài adapter dùng browser giả lập, không phải headless live.
- Đã gửi prompt tổng hợp thật trên ChatGPT web với `temporary-chat=true`; giao
  diện xác nhận không xuất hiện trong lịch sử. Nhận được phản hồi cho ngữ cảnh
  “tí đi choei k” → “Bạn định đi đâu, mấy giờ?” → “ra hồ ngồi tí thôi, 8h”, không emoji.
- Chưa test adapter Playwright với tài khoản thật, chưa test headless trên VPS,
  chưa triển khai hay xác nhận luồng Messenger→ChatGPT→Messenger thật.


### Nhập cookie trên Ubuntu không có desktop

- Toàn bộ 154 kiểm thử offline và Ruff đều đạt. Thêm kiểm tra Cookie header,
  cookie phiên chia phần, JSON export, lọc domain, lỗi không lộ bí mật, headless,
  giữ profile cũ khi kiểm tra thất bại và backup profile khi thay thành công.
- Lệnh `import-chatgpt-cookie` nhập ẩn qua terminal hoặc đọc `--file`; kiểm tra
  phiên mới trước khi đổi profile, không sửa key API/phạm vi Messenger.
- Chưa có cookie tài khoản người dùng trên VPS để kiểm tra đăng nhập thật bằng
  cookie. Các bài bổ sung dùng dữ liệu và browser giả lập.


### Khóa tiến trình và thông báo lỗi CLI web

- Toàn bộ 158 kiểm thử offline và Ruff đều đạt.
- Nhập cookie kiểm tra khóa trước khi hỏi bí mật; check web cũng giữ khóa để tránh
  tranh profile với bot. 4 ca bổ sung kiểm tra hai hành vi này, thông báo
  ProviderUnavailable được hiển thị và lỗi không tin cậy vẫn không lộ dữ liệu.
- Ghi nhận lệnh `systemctl stop` của người dùng báo system service không tồn tại;
  hướng dẫn kiểm tra user service và phiên chạy tay. Chưa truy cập VPS để xác
  định tiến trình thực tế hoặc thử cookie thật.


### Định dạng cookie copy từ DevTools

- Toàn bộ 165 kiểm thử offline và Ruff đều đạt.
- 7 ca bổ sung kiểm tra dấu chấm phẩy thừa/cuối chuỗi, dấu nháy bao ngoài, BOM,
  nhãn Cookie và xuống dòng giữa cặp; vẫn từ chối ngắt dòng giữa giá trị token.
- Chỉ dùng cookie giả để kiểm thử parser. Không trích xuất hay sử dụng giá trị
  đăng nhập trong ảnh người dùng, chưa xác định nguyên nhân chính xác trên VPS.


### Nhận cookie dài qua terminal Linux

- Tái hiện trên pseudo-terminal thật: getpass cũ nhận 4095 byte từ cookie giả
  dài 10098 byte. Lỗi cắt dòng có thể làm mất dấu = của cookie cuối.
- Thay ô nhập cookie bằng noncanonical hidden input, đọc theo khối tối đa 64 KiB,
  hỗ trợ bracketed paste, khôi phục terminal khi thành công/hủy/lỗi và không
  echo nội dung. Chỉ in độ dài byte sau khi xác nhận.
- Toàn bộ 171 kiểm thử offline và Ruff đều đạt. 6 ca bổ sung chạy với PTY thật:
  nhận đủ cookie dài, paste chia khối/nhiều dòng, từ chối quá 64 KiB, Ctrl+C,
  UTF-8 lỗi và không có terminal. Không dùng cookie tài khoản thật.
- Đây là lỗi nhập đã tái hiện được ở local, chưa kết luận là nguyên nhân duy
  nhất của lỗi người dùng hoặc xác nhận đăng nhập trên VPS.
