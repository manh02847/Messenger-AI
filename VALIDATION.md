# Kiểm tra bản 1.0.0 — 23/10/2026

Đã kiểm tra trên Linux x86-64, Python 3.12:

- 186 bài test offline: đạt (gồm thời gian riêng cho Flash, Google retry, chuyển model/nguồn dự phòng, nâng giới hạn, trạng thái đang nhập và persona riêng).
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

## Hoàn tác thử nghiệm ChatGPT web

Dùng Git hoàn tác sáu commit thử nghiệm, khôi phục tuyến AI và CLI của bản
`7dedcb6`. Gỡ adapter trình duyệt, nhập cookie, các lệnh web, dependency và các
kiểm thử riêng của thử nghiệm. Chỉ thêm tương thích config cũ: bỏ cờ
`chatgpt_web` khi đọc và xóa cờ đó khỏi file sau khi xác thực config hợp lệ.

136 kiểm thử offline và Ruff đạt. 4 ca bổ sung kiểm tra cờ cũ true/false không
bật lại nguồn web, giữ nguyên các nguồn/cấu hình/bí mật/ngữ cảnh, và không ghi
lại config sai. Chưa triển khai hay khởi động lại service trên VPS người dùng.


## NVIDIA NIM thử nghiệm

- Toàn bộ 162 kiểm thử offline và Ruff đạt. Thêm 26 ca kiểm tra payload/endpoint,
  max_tokens và tắt thinking, bảo toàn ngữ cảnh, lọc suy luận/phản hồi chưa xong,
  không retry lặp, timeout hủy request, chuyển nguồn đúng thứ tự, dùng chung
  ngân sách, cấu hình giữ keys/scope/các nguồn cũ và check NVIDIA không fallback.
- Model NVIDIA nhập thủ công, không whitelist danh sách hay tự đổi sang model
  NVIDIA khác. Kiểm tra cấu hình tự chọn và không gửi tham số Gemma cho model khác.
- Đã gọi thật endpoint NVIDIA từ môi trường này: catalog trả HTTP 200 và có model
  `google/gemma-4-31b-it`. Gọi chat completion bằng key đọc từ ảnh nhận HTTP 403,
  phản hồi "Authorization failed"; chưa có câu trả lời nên chưa đo chất lượng
  hoặc tốc độ inference. Không suy ra key trong ảnh có quyền inference từ việc
  model xuất hiện trong catalog.
- Chưa thử thành công adapter với key nhập trực tiếp trên VPS, chưa triển khai
  hay xác nhận Messenger→NVIDIA→Messenger thật. Không lưu key đọc từ ảnh vào repo.

## Trạng thái đang nhập

- 178 kiểm thử offline và Ruff đạt. Thêm 16 ca cho tín hiệu đang nhập: xuất hiện
  trong lúc chờ AI, làm mới định kỳ không dùng thêm ngân sách AI, tắt sau khi gửi,
  lỗi AI/gửi hoặc kết quả chưa rõ; nhường thủ công/yêu cầu dừng tắt ngay khi AI
  còn chờ, hủy worker và đóng bot vẫn dọn trạng thái. Tin mới đến trong lúc
  dọn trạng thái vẫn được xử lý, không cần thêm một tin khác để kích hoạt lại.
- Xem trước không phát tín hiệu. Lỗi/timeout cập nhật trạng thái không chặn câu
  trả lời hoặc lộ nội dung lỗi; chờ cập nhật có giới hạn. Đóng bot vẫn cho lượt
  gửi đang chạy hoàn thành, không tự gửi lại.
- Kiểm tra serializer BridgeActions thật của wheel 2.3.4 với bridge mô phỏng:
  E2EE gọi sendE2EETyping, chat thường gọi sendTypingIndicator và giữ threadType
  từ sự kiện. Dùng bridge/thiết bị E2EE đang có, không tạo phiên mới.
- Binary Linux x86-64 đã ghim nhận diện cả hai RPC typing trong thử nghiệm không
  tạo client: trả đúng lỗi client not initialised, không phải unknown method;
  không đăng nhập, không tạo thiết bị hoặc kết nối Facebook.
- Đối chiếu [mã nguồn typing của bridge 2.3.4](https://github.com/m008v/fbchat-v2/blob/aa7abd0386ef1d4cabf8ce592d0f2cf308d8f4f6/bridge-e2ee/bridge/messages.go).
  Chưa đăng nhập Facebook hoặc xác nhận dấu đang nhập hiển thị trên Messenger
  thật; cần cập nhật và thử tại VPS của người dùng.

## Rút gọn persona và hỗ trợ bản riêng trên máy chạy

- Persona công khai giảm từ 8655 xuống 3132 ký tự, bỏ hồ sơ/sở thích và tên riêng,
  giữ cách xưng hô, ngữ cảnh, ví dụ lỗi gõ, giới hạn quyền hạn và bảo mật. Không
  đo token theo từng model hoặc khẳng định chất lượng hội thoại qua test offline.
- Bot ưu tiên persona.local.txt nếu có, dùng thay toàn bộ mẫu công khai cho run,
  check-ai, check-nvidia và chat-ai. Git bỏ qua file riêng; đọc không sửa nội dung
  file và không tự nối hai persona khiến prompt dài trở lại.
- 186 kiểm thử offline và Ruff đạt. Thêm 8 ca kiểm tra dùng mẫu chung, ưu tiên
  bản riêng kể cả khi thiếu mẫu chung, UTF-8 BOM, giữ nguyên file, lỗi file riêng
  rỗng/sai mã hóa/không phải file, và check-ai/chat-ai không in persona. Mở rộng
  kiểm tra NVIDIA riêng để xác nhận cũng nhận persona.local.txt.
- Kiểm tra cú pháp khối lệnh README và quy tắc Git bỏ qua persona.local.txt đạt.
  Nội dung đã commit trước đây vẫn còn trong lịch sử Git; lần cập nhật này không
  viết lại lịch sử hoặc đổi chế độ công khai của repo.
