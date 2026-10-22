# Bot AI trả lời Messenger cá nhân

Bot nhận tin nhắn mới bằng tài khoản Messenger cá nhân, gửi nội dung cùng một phần ngữ cảnh sang Groq và trả lời trong đúng cuộc trò chuyện được chọn.

Nền kết nối: **fbchat-v2 2.3.4**. Model mặc định: **openai/gpt-oss-120b trên Groq**. Bạn có thể đổi model trong `config.json`.

## Bắt đầu nhanh

Cần máy Windows hoặc VPS Linux có Python **3.11 trở lên** và truy cập được GitHub, Facebook, Groq. Không chạy trực tiếp trên iPhone. Lần cài đầu tải thêm các thư viện Python và bridge. Trình cài tự chọn bridge tương ứng với hệ điều hành/CPU và kiểm tra checksum đã ghim.

### 1. Cài đặt

Có thể tải từ GitHub hoặc giải nén ZIP. Bản này dùng dòng lệnh, chưa có giao diện web. GitHub lưu mã nguồn; bot chạy trên VPS hoặc máy tính của bạn.

**Ubuntu/Debian:**

```bash
sudo apt update
sudo apt install -y git python3 python3-venv
git clone https://github.com/manh02847/Messenger-AI.git ~/messenger-ai-bot
cd ~/messenger-ai-bot
python3 setup_bot.py
```

**Windows:** tải ZIP qua nút **Code → Download ZIP** của repo rồi giải nén. Cài Python 3.11+ từ https://www.python.org/downloads/ và bật tùy chọn thêm Python vào PATH. Mở PowerShell trong thư mục chứa `setup_bot.py`:

```powershell
py -3 setup_bot.py
```

Nếu Ubuntu đang có Python cũ hơn 3.11, cần cài Python 3.11+ trước. Trình cài không thay Python hệ thống.

Các lệnh bên dưới dùng `.venv/bin/python` trên Linux. Trên Windows, thay bằng `.venv\Scripts\python.exe`.

### 2. Lấy API key và nhập phiên đăng nhập

Tạo API key tại **https://console.groq.com/keys**. Dùng gói Free để thử; quota thực tế xem trong tài khoản Groq của bạn.

```bash
.venv/bin/python -m messenger_ai configure
```

Lệnh hỏi API key Groq và cookie Facebook, ẩn nội dung khi gõ/dán. Thông tin được ghi vào `secrets.json` trên máy chạy bot. Bạn cũng có thể dùng biến môi trường `GROQ_API_KEY` và `FACEBOOK_COOKIE`.

Cookie là chuỗi dạng:

```text
c_user=ID_TAI_KHOAN; xs=GIA_TRI_PHIEN; ...
```

Lấy cookie của **chính tài khoản bạn đăng nhập** trên máy tính: mở Facebook → F12 → Network → tải lại trang → chọn yêu cầu tới `www.facebook.com` → Request Headers → sao chép giá trị `Cookie`. Không sao chép cả dòng `Cookie:`. Nếu trình duyệt không hiển thị trường này, kiểm tra phiên đăng nhập trong công cụ nhà phát triển; không cần cài extension lấy cookie từ người lạ.

Cookie có quyền truy cập tài khoản. Không đưa `secrets.json`, thư mục `data`, cookie hay API key lên GitHub hoặc gửi vào chat. Nếu cookie hết hạn/checkpoint, đăng nhập Facebook bình thường rồi chạy lại `configure` với cookie mới. Bot không tự giải CAPTCHA hoặc vượt checkpoint.

### 3. Kiểm tra riêng AI

```bash
.venv/bin/python -m messenger_ai check-ai
```

Lệnh này gọi Groq với một câu chào mẫu. Không mở kết nối hoặc gửi tin lên Messenger. API key sai/hết quota sẽ có thông báo, không in key ra màn hình.

Để thử hội thoại nhiều lượt với đúng model và persona đang cấu hình:

```bash
.venv/bin/python -m messenger_ai chat-ai
```

Gõ các câu viết tắt/sai chính tả trực tiếp trên terminal. `/context` xem số tin và ký tự trong ngữ cảnh, `/reset` bắt đầu cuộc trò chuyện thử mới, `/quit` thoát. Cả câu hỏi và câu trả lời thử được gửi sang Groq, nhưng không kết nối Messenger và không đọc lịch sử Messenger. Ngữ cảnh thử chỉ giữ trong RAM đến lúc thoát; số lượt gọi vẫn tính quota và dùng chung bộ đếm cục bộ của `check-ai`.

Nếu đang dùng bản cũ với giới hạn 768 token, dừng bot rồi cập nhật cấu hình:

```bash
git pull --ff-only
.venv/bin/python -m messenger_ai tune-chat
```

Lệnh này bỏ tiền tố icon và nâng `max_completion_tokens` lên 4096 và `output_char_limit` lên ít nhất 4000 ký tự, giữ các cấu hình khác. Bản cũ giới hạn văn bản 500 ký tự nên có thể cắt giữa câu, ngay cả khi model đã trả lời đầy đủ. Giới hạn này áp dụng cho **mỗi lần tạo câu trả lời**, gồm cả suy luận; không phải quota còn lại của tài khoản. Thông báo chạm giới hạn này không đồng nghĩa hết quota API. Giới hạn cao hơn cho phép model dùng nhiều token hơn; không đảm bảo mọi câu trả lời đều hoàn thành hoặc chất lượng tốt hơn. Quota thật vẫn có thể bị chạm riêng và thường báo HTTP 429. Khởi động lại bot sau khi chỉnh.

### 4. Chọn phạm vi tự rep

Để tự rep **tất cả chat riêng, bỏ qua group**, không cần lấy từng ID:

```bash
.venv/bin/python -m messenger_ai scope all_private
```

Khởi động lại bot sau khi đổi phạm vi. Chế độ này xử lý tin văn bản mới ở các chat riêng mà kết nối Messenger nhận được, kể cả người chưa nằm trong `allowed_threads`. Nhóm, kênh và loại chat chưa xác định bị bỏ qua trước khi lưu nội dung hoặc gọi AI. Không tự nhắn trước, không rep lại lịch sử cũ. Ngữ cảnh vẫn tách riêng cho từng cuộc trò chuyện; bạn tự nhắn thì bot vẫn nhường 5 phút.

Nhận diện E2EE dựa trên JID chat riêng `@msgr`; `@g.us` là nhóm. Với tin thường, bot kiểm tra `threadType` do bridge cung cấp. Nếu bridge thiếu thông tin loại chat, bot bỏ qua tin đó. Một chat riêng có thể dùng ID người kia trong JID, nhưng mã `/e2ee/t/...` trên website không được mặc định coi là cùng ID; không dùng việc ID chat trùng ID người gửi để phân biệt nhóm.

Để quay lại chỉ rep danh sách đã chọn:

```bash
.venv/bin/python -m messenger_ai scope allowlist
```

Cấu hình cũ giữ chế độ `allowlist` cho đến khi chạy lệnh đổi phạm vi. Với chế độ này, lấy mã người được rep bằng:


```bash
.venv/bin/python -m messenger_ai discover
```

Nhờ đúng người bạn muốn thử gửi **một tin mới**. Màn hình sẽ in mã cuộc trò chuyện và ID người gửi, không in nội dung tin nhắn. Ví dụ:

```text
Mã cuộc trò chuyện: e2ee:123456789@msgr | người gửi: 123456789
```

Đối chiếu người vừa nhắn và mã hiển thị. Nhấn **Ctrl+C** để dừng `discover`, rồi thêm **đúng mã đã xác minh**:

```bash
.venv/bin/python -m messenger_ai allow "e2ee:123456789@msgr"
```

Đây là số minh họa, phải thay bằng kết quả thật. Tin chưa mã hóa có thể dùng mã `thread:...`. Nếu cùng một cuộc trò chuyện đổi kiểu mã hóa, dùng `discover` để xác minh mã mới. Trong chế độ `allowlist`, bot không trả lời ngoài danh sách. Bot không tự thêm bạn bè hoặc tự chọn theo tên. Không chạy đồng thời hai phiên bot/discover dùng chung thư mục.

### 5. Xem trước rồi bật trả lời

Xem trước với tin **mới**, có gọi Groq nhưng chưa gửi lên Messenger:

```bash
.venv/bin/python -m messenger_ai run --dry-run
```

Khi muốn bot gửi thật, dừng bằng Ctrl+C rồi chạy:

```bash
.venv/bin/python -m messenger_ai run --live
```

Mặc định `config.json` có `dry_run: true`. Cờ `--live` chỉ áp dụng cho lần chạy hiện tại. Bạn có thể chỉnh `dry_run` thành `false` để lệnh `run` mặc định gửi thật.

Không yêu cầu người kia nhắn lệnh hoặc tag bot; khi có tin văn bản mới thuộc phạm vi đã chọn, bot sẽ tự xử lý. Tắt bot bằng **Ctrl+C**. Khi bạn tự nhắn trong cuộc trò chuyện đó, bot tạm nhường **5 phút**; sau đó chỉ phản hồi khi có **tin mới tiếp theo**.

## Những gì đã có

- Gửi/nhận qua kết nối mã hóa đầu cuối E2EE và tuyến nhắn tin thường do thư viện hỗ trợ.
- Hai phạm vi: tất cả chat riêng (loại nhóm) hoặc danh sách chọn trước; mặc định danh sách rỗng.
- Gom các tin đến sát nhau trong 2,5 giây; câu trả lời dùng ngữ cảnh của riêng cuộc trò chuyện.
- Nếu có tin mới trong lúc AI đang soạn, bỏ bản nháp cũ và soạn lại theo ngữ cảnh mới.
- Phát hiện bạn nhắn thủ công cả khi đang chờ AI; bot không tiếp tục gửi bản nháp đó.
- Nhận diện tin phản hồi của chính bot để không tự đối thoại hoặc tự kích hoạt chế độ nhường.
- Lưu ID tin đã xử lý để hạn chế rep trùng sau khi khởi động lại.
- Nếu gửi bị timeout hoặc không biết có thành công không, ghi nhận trạng thái chưa rõ, tạm dừng cuộc trò chuyện và không tự gửi lại tin đó.
- Giới hạn số lần gọi AI, số lần gửi trong ngày và độ dài ngữ cảnh; xử lý HTTP 429 từ Groq với thời gian chờ hữu hạn.
- Giữ trạng thái thiết bị E2EE tại máy chạy để tái sử dụng phiên. Không tự thay thiết bị mỗi lần mở lại.
- Chỉ lấy câu trả lời cuối từ Groq; không gửi trường suy luận của model.

## Chỉnh giọng nói và hành vi

Sửa **`persona.txt`** để thay cách xưng hô, độ dài và các thông tin bot được phép biết. Mặc định hỗ trợ Mạnh, xưng mình/bạn, trả lời ngắn và được hướng dẫn không thêm emoji. Khi người nhắn hỏi có phải bot hay không, bot được hướng dẫn nói rõ là trợ lý tự động. Mặc định `reply_prefix` là chuỗi rỗng. Nếu đã cài bản cũ, đổi `reply_prefix` trong `config.json` thành `""` rồi khởi động lại để bỏ icon robot; `git pull` không sửa cấu hình riêng của bạn.

Các tùy chọn chính trong `config.json`:

| Tùy chọn | Mặc định | Ý nghĩa |
|---|---:|---|
| `reply_scope` | `allowlist` | `all_private`: tất cả chat riêng, loại nhóm; `allowlist`: chỉ danh sách |
| `allowed_threads` | `[]` | Mã xác minh qua discover; chỉ dùng khi phạm vi là `allowlist` |
| `dry_run` | `true` | Chỉ in bản nháp khi chưa dùng `--live` |
| `debounce_seconds` | `2.5` | Chờ để gom tin liên tiếp |
| `reply_cooldown_seconds` | `8` | Khoảng cách tối thiểu giữa hai lượt gửi cùng cuộc trò chuyện |
| `manual_pause_seconds` | `300` | Nhường sau khi bạn tự nhắn, yêu cầu dừng rõ ràng hoặc gửi chưa rõ kết quả |
| `history_messages` | `12` | Tối đa số tin trong ngữ cảnh cục bộ |
| `history_char_limit` | `3500` | Tổng ký tự lịch sử gửi sang AI mỗi lượt |
| `input_char_limit` | `1200` | Tối đa ký tự của mỗi tin đưa vào ngữ cảnh |
| `output_char_limit` | `4000` | Tối đa ký tự trả lời, chưa tính tiền tố |
| `max_completion_tokens` | `4096` | Giới hạn token mỗi phản hồi, gồm token suy luận của model |
| `max_ai_calls_per_day` | `150` | Số lần gọi AI cục bộ/ngày, tính cả thử lại |
| `max_replies_per_thread_per_day` | `60` | Số lượt gửi/cố gửi trên mỗi cuộc trò chuyện/ngày |
| `max_message_age_seconds` | `120` | Bỏ tin quá cũ, không soạn trả lời hàng loạt lịch sử |
| `retention_days` | `7` | Dọn dữ liệu cũ khi khởi động bot |

Mốc ngày của bộ giới hạn cục bộ tính theo **giờ Việt Nam**. Quota của nhà cung cấp vẫn áp dụng riêng; bot có thể chạm giới hạn token của Groq trước khi đạt số lượt ở bảng này. Mỗi lần thử lại API cũng tính một lần gọi. Xem trước và gửi thật dùng hai kho ngữ cảnh/bộ đếm cục bộ riêng; bản nháp chưa gửi không được ghi giả thành tin đã gửi.

AI không còn tự tạm dừng cuộc trò chuyện bằng `[[HANDOFF]]`. Nếu model vẫn trả mã này, bot đổi thành câu hỏi làm rõ và tiếp tục nhận tin mới. Chỉ một số mẫu yêu cầu rõ ràng được ứng dụng nhận diện để nhường, ví dụ `Cho mình gặp Mạnh nhé`, `Mạnh tự rep đi`, `Đừng trả lời nữa` (có thể không dấu). Đây là bộ mẫu giới hạn, không nhận diện mọi cách diễn đạt. Khi bạn tự nhắn, cơ chế nhường 5 phút vẫn hoạt động. Câu hỏi cần quyết định riêng thì AI được hướng dẫn giải thích rằng không quyết định thay được.

Đổi cấu hình hoặc persona thì khởi động lại bot. Nếu đổi sang model khác, kiểm tra bằng `check-ai` trước; tên model và hỗ trợ API có thể thay đổi.

## Chạy nền trên VPS Linux

Bot tự nối lại lỗi mạng theo cơ chế của fbchat-v2. Nếu cần quản lý tiến trình bằng systemd, có mẫu **`deploy/messenger-ai.service`**. Mẫu giả định bot nằm ở `~/messenger-ai-bot` và máy đã có phiên `systemd --user`:

```bash
mkdir -p ~/.config/systemd/user
cp deploy/messenger-ai.service ~/.config/systemd/user/messenger-ai.service
systemctl --user daemon-reload
systemctl --user enable --now messenger-ai
journalctl --user -u messenger-ai -f
```

Mẫu service chạy **gửi thật** và yêu cầu bạn đã cấu hình API/cookie/người nhận, thử xem trước rồi. Muốn service tiếp tục chạy sau khi SSH logout, quản trị viên VPS cần bật lingering cho tài khoản chạy service. Nếu dùng aaPanel/Supervisor thì đặt thư mục chạy là thư mục bot, lệnh `.venv/bin/python -m messenger_ai run --live`; không chạy thêm systemd cùng lúc.

Bật lingering cho tài khoản đang đăng nhập:

```bash
sudo loginctl enable-linger "$(whoami)"
```

Quản lý service:

```bash
systemctl --user status messenger-ai
systemctl --user stop messenger-ai
systemctl --user start messenger-ai
```

Cập nhật mã nguồn sau này (dừng bot trước, giữ nguyên `secrets.json`, `config.json` và `data/`):

```bash
cd ~/messenger-ai-bot
systemctl --user stop messenger-ai
git pull --ff-only
python3 setup_bot.py
systemctl --user start messenger-ai
```

Nếu bạn đã sửa `persona.txt` hoặc mã nguồn, Git có thể yêu cầu xử lý thay đổi cục bộ trước khi cập nhật. Không dùng reset để xóa các chỉnh sửa chưa lưu.

Nếu phiên Facebook không hợp lệ, bot cần bạn cập nhật cookie. Mẫu systemd chỉ tự khởi động lại khi tiến trình bị kết thúc bất thường, không lặp đăng nhập liên tục khi chương trình báo lỗi cấu hình/xác thực.

## Giới hạn thực tế

- Cần kiểm tra thật với tài khoản của bạn. Bộ kiểm tra offline không chứng minh Facebook sẽ chấp nhận phiên đăng nhập hoặc kết nối luôn ổn định.
- Đây là kết nối tài khoản cá nhân không chính thức. Facebook có thể thay giao thức hoặc yêu cầu đăng nhập/checkpoint. Không có cam kết tránh hạn chế tài khoản.
- Bản đầu xử lý **văn bản**. Tin chỉ có ảnh, sticker, file hoặc ghi âm không được gửi vào AI để đoán nội dung.
- Chỉ xử lý tin mới khi bot chạy. Không tự trả lời bù tin cũ sau lúc offline, và không cam kết nhận đủ tin trong lúc mất mạng.
- Tin thủ công đến trước khi bắt đầu gửi có thể ngăn bản nháp. Nếu một yêu cầu gửi đã được truyền ra mạng thì không thể bảo đảm thu hồi kịp.
- Nội dung và một phần lịch sử của người được chọn được gửi tới Groq. Cookie và API key trong cấu hình không được chèn vào prompt của model. Cân nhắc quyền riêng tư của nội dung chat và người tham gia trước khi dùng dịch vụ AI bên ngoài.
- `data` chứa lịch sử chat giới hạn và khóa/phiên thiết bị E2EE, lưu cục bộ chưa mã hóa ở tầng ứng dụng. Trên Linux, thư mục được giới hạn quyền; vẫn cần bảo vệ tài khoản máy chạy. Không chia sẻ `data` khi gửi log nhờ hỗ trợ.

## Kiểm tra và khắc phục

```bash
.venv/bin/python -m messenger_ai doctor
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

`doctor` xác minh checksum, phiên bản thư viện và giao thức RPC với **binary bridge thật** mà không đăng nhập Facebook. Các test mô phỏng dịch vụ bên ngoài và kiểm tra luồng nhận/gửi, danh sách được rep, chống trùng, nhường người dùng, gửi chưa rõ kết quả, giới hạn API và quyền riêng tư của log.

| Hiện tượng | Xử lý |
|---|---|
| `allowed_threads đang rỗng` | Chạy discover rồi allow, hoặc `scope all_private` để rep tất cả chat riêng |
| Không thấy bot gửi | Kiểm tra chế độ xem trước, tin nhắn mới, danh sách, thời gian nhường và quota |
| `Groq từ chối API key` | Tạo/kiểm tra key trên Groq rồi configure lại |
| `HTTP 429` | Chạm quota. Giảm ngữ cảnh/tần suất và chờ quota phục hồi |
| `Câu trả lời chạm max_completion_tokens` | Chạy `tune-chat` nếu đang dùng mức 768 cũ; không phải thông báo hết quota API. Mức cao hơn có thể tiêu tốn quota nhanh hơn |
| Facebook/checkpoint | Đăng nhập trên trình duyệt bình thường, xử lý yêu cầu của Facebook và cập nhật cookie |
| Bridge checksum sai | Không dùng file đó. Xóa đúng tệp trong `bin` rồi chạy setup_bot.py để tải lại bản ghim |
| Đổi máy và mất phiên E2EE | Dừng các phiên cũ; cấu hình lại trên máy mới. Không chạy hai máy dùng chung bản sao thiết bị |

## Nguồn

- fbchat-v2: https://github.com/m008v/fbchat-v2
- Bản ghim: https://github.com/m008v/fbchat-v2/releases/tag/v2.3.4
- Groq: https://console.groq.com/docs/quickstart
- Hạn mức Groq: https://console.groq.com/docs/rate-limits
- Tài sản upstream được kiểm SHA-256 theo `assets.json`; phần nguồn tương ứng và giấy phép xem `THIRD_PARTY.md`.
