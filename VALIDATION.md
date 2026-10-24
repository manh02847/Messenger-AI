# Kiểm tra bản 1.0.0 — 23/10/2026

Đã kiểm tra trên Linux x86-64, Python 3.12:

- 203 bài test offline: đạt (gồm thời gian riêng cho Flash, Google retry, chuyển model/nguồn dự phòng, nâng giới hạn, trạng thái đang nhập, persona riêng và cài thêm acc).
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

## Cài nguồn chính từ đầu và dùng lại AI cho acc thứ hai

- Sửa configure bắt buộc Groq: cài mới có thể chọn --provider cloudflare; khi
  cập nhật cookie, configure giữ nguồn/model hiện tại. Không lưu file mới nếu
  thiếu key, Account ID hoặc cookie không đúng định dạng.
- Thêm configure --copy-ai-from THU_MUC: chỉ lấy các thiết lập AI và key đã biết,
  bắt buộc nhập cookie riêng. Không chép danh sách/phạm vi người nhận, persona,
  lịch sử, khóa tiến trình hay thiết bị E2EE; không ghi vào thư mục nguồn.
- 203 kiểm thử offline đạt, gồm 17 ca mới: khởi tạo Groq/Cloudflare, tạo config
  để dùng scope tiếp, giữ model Cloudflare khi thay cookie, cấu hình thiếu không
  ghi file, dùng lại cả chuỗi NVIDIA/Google/Cloudflare/Groq, giữ nguyên dữ liệu
  nguồn/đích, từ chối nguồn sai và phát hiện FACEBOOK_COOKIE ghi đè cookie mới.
- Ruff với bộ quy tắc E4/E7/E9/F đạt; cú pháp shell/Python và 31 ví dụ CLI trong
  README đạt. Chưa đăng nhập hoặc gửi Messenger thật bằng acc thứ hai, chưa
  triển khai/khởi động lại tiến trình trên VPS người dùng.

## System service cho phiên root trên VPS

- Thêm deploy/messenger-ai-system.service với User=root, đường dẫn /root,
  WantedBy=multi-user.target và các thiết lập dừng/khởi động lại như mẫu user.
  README dùng đúng lệnh systemctl/journalctl cho từng loại manager, có hướng
  dẫn riêng cho lỗi user bus và acc thứ hai.
- Kiểm tra cả mẫu acc đầu và bản thay đường dẫn sang messenger-ai-bot-2:
  systemd-analyze verify trên systemd 255 đạt. Khi kiểm tra, thay ExecStart và
  WorkingDirectory bằng đường dẫn tồn tại trong môi trường kiểm tra; xác minh
  riêng đường dẫn /root trong mẫu gốc bằng parser. Không khởi động service.
- Các khối lệnh shell/Python, liên kết nội bộ trong README và git diff --check
  đạt. Không sửa mã bot; không chạy lại 203 test offline của commit trước.
  Chưa cài service hoặc kiểm tra bus trên VPS người dùng.

## Hạn chế ngữ cảnh dẫn lệch và reset riêng từng chat

- Giữ các tin gần nhất còn nguyên nội dung trong giới hạn tin/ký tự; bỏ câu
  trả lời đứng đầu khi câu hỏi trước nó đã bị loại, thay vì gửi mảnh đuôi tin.
  Tin mới nhất vượt ngân sách lịch sử được lấy phần đầu để vẫn có đầu vào.
- Thêm history_idle_seconds, mặc định 3600 giây, 0 là tắt. Ngữ cảnh không vượt
  qua khoảng cách giữa hai tin từ mức này; hội thoại đang nhắn liên tục vẫn
  giữ lịch sử dù đã kéo dài nhiều giờ. Áp dụng trên dữ liệu có sẵn sau restart,
  không cần migration, và dùng chung cách chọn lịch sử với chat-ai.
- Mỗi nguồn nhận persona đầy đủ cùng hướng dẫn phân biệt chủ tài khoản/người
  nhắn, đối chiếu thông tin và không coi câu trả lời cũ của bot là chứng cứ.
  Áp dụng cả persona.local.txt; không sửa file riêng, tự suy diễn giới tính hay
  gọi AI thêm để tóm tắt. Hướng dẫn thêm vào có tiêu thụ token đầu vào.
- reset-context chỉ xóa messages của mã chat được chọn trong state.sqlite3,
  hoặc preview.sqlite3 khi có --preview. Yêu cầu dừng bot/discover bằng khóa
  tiến trình sẵn có; giữ seen/outbox, cooldown, thời gian nhường, giới hạn,
  persona, cookie, thiết bị E2EE, các chat và thư mục acc khác.
- Toàn bộ 227 kiểm thử offline đạt, thêm 24 ca cho giới hạn trọn tin, ranh
  giới im lặng, cấu hình cũ/sai, tích hợp lượt trả lời và chat-ai, reset từng
  chat/chế độ, khóa tiến trình, CLI và payload của bốn nhà cung cấp. Cập nhật
  kiểm tra configure --copy-ai-from để giữ thiết lập thời gian ngữ cảnh.
- Ruff với E4/E7/E9/F, cú pháp 37 khối lệnh và liên kết cục bộ README, CLI help
  và git diff --check đạt. Không gọi AI/Facebook thật, không triển khai hay
  reset dữ liệu trên VPS người dùng. Các test xác nhận cơ chế chọn lịch sử và
  request; không chứng minh model sẽ luôn làm đúng hoặc hết bịa.

## Đọc ảnh Messenger với model thị giác được chọn riêng

- Thêm configure-vision và check-vision; nguồn/model ảnh do người dùng chọn
  thủ công, mặc định tắt. Tái sử dụng key của NVIDIA/Google/Groq/Cloudflare,
  giữ model/chuỗi fallback chữ. Lệnh cấu hình xác minh định dạng/quyền lưu
  file cục bộ, chưa xác minh quyền inference; check-vision gửi ô màu đỏ tạo
  tại máy để người dùng kiểm tra câu trả lời, không đăng nhập Messenger.
- Nhận attachments type=image theo schema upstream 2.3.4 ở cả sự kiện thường
  và E2EE. Gom ảnh mới với câu hỏi mới trong cùng lượt, dùng tối đa hai ảnh
  gần nhất. Bộ lọc phạm vi/nhóm, tuổi tin, chống trùng, thời gian nhường và
  giới hạn gửi chạy trước khi tải ảnh. Nguồn ảnh dùng chung bộ đếm AI live,
  mỗi lượt thử một request, deadline 30 giây và HTTP read timeout 25 giây;
  không fallback qua nguồn chỉ hỗ trợ chữ.
- Giới hạn mỗi ảnh 8 MiB/20 triệu pixel; Pillow 13.0.0 đọc JPG/PNG/WebP tĩnh,
  thu nhỏ 1600 px, xoay theo EXIF rồi chuyển JPEG bỏ metadata, tối đa 1 MiB
  dữ liệu nén trước base64. Tải thường giới hạn streaming và kiểm tra host
  Meta ở từng redirect, không gửi cookie/key. Tải E2EE dùng BridgeActions
  downloadE2EEMedia với khóa/hash/size từ sự kiện; yêu cầu size dương để giới
  hạn cứng file tạm của bridge. Không lưu URL ký/khóa/ảnh vào SQLite.
- Giữ ảnh đã xử lý trong RAM cho lượt đang chờ; tin mới làm bỏ bản nháp có
  thể tái sử dụng ảnh đó. Xóa khi lượt kết thúc/nhường/dừng; không giữ ảnh cho
  các lượt sau. Ảnh lỗi tải/định dạng trả câu báo chưa mở được; lỗi API bỏ
  lượt, không gọi model chữ để bịa. Tin chỉ có ảnh khi chưa bật được bỏ qua.
- Sửa race khi tin mới đến lúc lần gửi trước đang chờ xác nhận: câu trả lời
  cũ có thể được lưu sau câu hỏi mới. Ngữ cảnh dùng cho lần gọi tiếp đặt lại
  câu hỏi đang chờ ở cuối, kể cả khi giới hạn chỉ một tin; ảnh mới không bị
  ghép nhầm với ảnh của lượt đã gửi.
- Toàn bộ 294 kiểm thử offline đạt (67 ca mới): payload ảnh thực tế của cả
  bốn giao thức, persona riêng, quota/timeout/lỗi không retry ảnh, parser và
  giới hạn bytes/pixel/EXIF/transparency/host/redirect, action serializer thật
  trong wheel 2.3.4, gom tin, cô lập chat, lỗi tải, nhường thủ công, thay nháp,
  ảnh đến khi đang gửi, cấu hình/CLI/check-vision và đóng client. Kiểm tra
  configure --copy-ai-from có lấy các thiết lập nguồn/model ảnh riêng.
- Ruff E4/E7/E9/F, cú pháp 39 khối lệnh README, liên kết cục bộ, CLI help và
  git diff --check đạt. Binary Linux amd64 ghim SHA-256 qua doctor; gọi hai
  RPC downloadMedia/downloadE2EEMedia không có client trả client not initialised,
  chứng minh handler tồn tại, không phải thử tải/giải mã ảnh Facebook thật.
- Đối chiếu [schema sự kiện](https://github.com/m008v/fbchat-v2/blob/aa7abd0386ef1d4cabf8ce592d0f2cf308d8f4f6/bridge-e2ee/bridge/events.go)
  và [cách tải media](https://github.com/m008v/fbchat-v2/blob/aa7abd0386ef1d4cabf8ce592d0f2cf308d8f4f6/bridge-e2ee/bridge/media.go),
  tài liệu ảnh chính thức của NVIDIA/Gemini/Groq/Cloudflare được dẫn trong README.
  Chưa gọi AI thật, chưa đăng nhập/tải ảnh từ Messenger, chưa triển khai trên
  VPS người dùng hoặc đo chất lượng OCR/chi phí thực tế. Cần chạy check-vision
  bằng key trên VPS và thử gửi ảnh mới trước khi kết luận luồng thật hoạt động.

## Tải ảnh E2EE thiếu metadata kích thước và chẩn đoán lỗi ảnh

- Ảnh người dùng cung cấp cho thấy bot trả câu báo tải/xử lý thất bại, chưa
  có log chỉ ra nguyên nhân cụ thể. Không kết luận ảnh sai định dạng hoặc
  model không hỗ trợ ảnh từ câu báo cũ.
- Bỏ yêu cầu metadata fileSize dương và so khớp tuyệt đối số byte đã tải.
  Trong bridge 2.3.4 đang ghim, tham số fileSize chỉ đặt giới hạn file tạm;
  truyền cố định 8 MiB để vẫn giới hạn cứng khi metadata vắng/sai số. Giữ
  kiểm tra dung lượng thực tế và bổ sung SHA-256 plaintext sau khi SDK đã
  kiểm tra hash/giải mã. Ảnh thiếu đường dẫn/khóa/hash vẫn bị từ chối.
- Đối chiếu [DownloadE2EEMedia và boundedMediaFile](https://github.com/m008v/fbchat-v2/blob/aa7abd0386ef1d4cabf8ce592d0f2cf308d8f4f6/bridge-e2ee/bridge/media.go)
  cùng [download-to-file.go của whatsmeow được ghim](https://github.com/tulir/whatsmeow/blob/0057a822e79a/download-to-file.go):
  bridge dùng fileSize cho cap file tạm, tải qua DownloadMediaWithPathToFile
  không truyền expected length; whatsmeow kiểm tra SHA-256 trên plaintext.
- ImageError giữ mã và mô tả từ danh sách cố định: phân biệt metadata, phiên
  E2EE, HTTP 403/404/410, timeout, decode, pixel/dung lượng và thiếu Pillow.
  Lỗi đã phân loại không còn bị đổi thành một lỗi chung ở adapter. Ngoại lệ
  máy chủ chỉ dùng để chọn mã, không in nguyên URL ký/khóa/nội dung lỗi.
  Câu báo gửi qua Messenger không còn khuyên đổi JPG/PNG khi chưa rõ nguyên
  nhân. README có lệnh lấy riêng dòng log bộ tải và bảng giải thích mã.
- Toàn bộ 316 test offline đạt: bổ sung 23 ca cho metadata size 0/không khớp,
  cap RPC/bytes thực tế, hash sai, HTTP/bridge exception được ẩn, thông tin
  metadata thiếu và thiếu decoder; bỏ ca cũ coi size 0 là lỗi. Test worker
  kiểm tra mã cụ thể xuất hiện trong log mà không gọi AI để đoán ảnh lỗi.
- Ruff E4/E7/E9/F, cú pháp 40 khối lệnh README và git diff --check đạt. Không
  gọi Facebook/AI thật, không sửa dữ liệu hoặc triển khai trên VPS. Chưa
  xác nhận nguyên nhân thực tế của hai ảnh thất bại; nếu vẫn lỗi sau cập
  nhật cần mã log mới từ VPS để tiếp tục chẩn đoán.
