# Bot AI trả lời Messenger cá nhân

Bot nhận **tin văn bản mới** trên Messenger cá nhân, dùng AI để soạn rồi trả lời trong cuộc trò chuyện đó. Có ngữ cảnh riêng cho từng người và tự nhường khi bạn nhắn thủ công.

Hỗ trợ **NVIDIA NIM, Google AI Studio, Cloudflare Workers AI và Groq**. Bot chạy bằng dòng lệnh trên máy tính/VPS; GitHub chỉ lưu mã nguồn. Dùng API hosted nên VPS không cần GPU.

- **Đã cài bot:** xem [lệnh thường dùng](#1-lệnh-thường-dùng) và [kiểm tra nguồn/model](#2-kiểm-tra-ai-nguồn-và-model).
- **Cài lần đầu:** bắt đầu từ [cài đặt](#3-cài-đặt-lần-đầu), sau đó chọn phạm vi rep và chạy thử.

## 1. Lệnh thường dùng

Các lệnh Linux bên dưới chạy trong thư mục bot:

```bash
cd ~/messenger-ai-bot
```

### Cập nhật bot

Nếu đang dùng service theo README này:

```bash
systemctl --user stop messenger-ai
git pull --ff-only
python3 setup_bot.py
systemctl --user start messenger-ai
```

Nếu chạy trực tiếp trên terminal, nhấn **Ctrl+C** để dừng trước khi cập nhật, rồi chạy lại `run --live`. `setup_bot.py` cập nhật thư viện/bridge; thay đổi chỉ có README thì không cần chạy lại bot.

`git pull` giữ cấu hình riêng, cookie và dữ liệu trong `config.json`, `secrets.json`, `data/`. Nó **không tự đổi model hoặc bật nguồn AI mới**. Nếu bạn đã sửa `persona.txt` hay mã nguồn, cần lưu/xử lý thay đổi đó trước khi pull; không dùng reset để xóa chỉnh sửa chưa lưu.

### Quản lý bot chạy nền

| Việc cần làm | Lệnh |
|---|---|
| Xem trạng thái | `systemctl --user status messenger-ai` |
| Xem log trực tiếp | `journalctl --user -u messenger-ai -f` |
| Dừng bot | `systemctl --user stop messenger-ai` |
| Bật bot | `systemctl --user start messenger-ai` |
| Áp dụng cấu hình/persona mới | `systemctl --user restart messenger-ai` |

README dùng **user service**, nên các lệnh có `--user`. Nếu chưa cài service, xem [chạy nền trên VPS](#6-chạy-nền-trên-vps).

## 2. Kiểm tra AI, nguồn và model

### Thử API và thử hội thoại

```bash
.venv/bin/python -m messenger_ai check-ai
```

`check-ai` gọi thử theo thứ tự nguồn đang cấu hình, in **nguồn/model thực sự trả lời** và thời gian. Nếu nguồn đầu lỗi, nó có thể dùng nguồn sau; thành công không có nghĩa tất cả nguồn đều hoạt động.

```bash
.venv/bin/python -m messenger_ai chat-ai
```

`chat-ai` dùng cùng chuỗi nguồn và `persona.txt` như bot để thử nhiều lượt, kể cả viết tắt/sai chính tả. Gõ `/context` để xem lượng ngữ cảnh, `/reset` để bắt đầu lại, `/quit` để thoát. Lịch sử thử chỉ giữ trong RAM, không đọc lịch sử Messenger.

Hai lệnh trên **không kết nối hoặc gửi Messenger**, nhưng có gọi API và tiêu thụ quota thật. Chúng dùng chung bộ đếm thử cục bộ, tách với bộ đếm của bot đang rep.

Để kiểm tra **riêng NVIDIA**, không chuyển sang nguồn khác:

```bash
.venv/bin/python -m messenger_ai check-nvidia
```

### Xem toàn bộ thứ tự nguồn/model đang bật

Sao chép cả khối sau vào terminal Linux:

```bash
.venv/bin/python - <<'PY'
from messenger_ai.ai import provider_configs
from messenger_ai.config import Settings, load_secrets

for index, (_, config, _) in enumerate(provider_configs(load_secrets(), Settings.load()), 1):
    print(f"{index}. {config.ai_provider}: {config.model}")
PY
```

Khối này chỉ đọc cấu hình và kiểm tra định dạng thông tin kết nối; **không gọi API, không in key**. Nó không thể xác nhận key còn quota hoặc model có quyền truy cập.

Thứ tự chung:

| Ưu tiên | Nguồn được thử |
|---|---|
| 1 | NVIDIA với model bạn tự chọn, nếu đã bật |
| 2 | Các model Google, theo thứ tự trong `google_models` |
| 3 | Nguồn chính: Groq hoặc Cloudflare |
| 4 | Nguồn còn lại trong Groq/Cloudflare, nếu `ai_fallback: true` |

Ví dụ **NVIDIA → Google → Cloudflare → Groq** chỉ đúng khi đã bật NVIDIA/Google, chọn Cloudflare làm chính và bật dự phòng Groq. Nếu chọn Groq làm chính thì hai nguồn cuối đổi chỗ. Cài mới mặc định **chỉ có Groq**, các nguồn khác cần cấu hình thêm.

Bot thử lần lượt đến khi có câu trả lời; không gọi nhiều model song song rồi ghép nội dung. Các nguồn được thử nhận cùng persona/ngữ cảnh trong giới hạn cấu hình.

## 3. Cài đặt lần đầu

### Bước 1: Cài chương trình

Cần **Python 3.11+** và kết nối tới GitHub, Facebook, các nhà cung cấp AI bạn dùng. Nền kết nối Messenger là **fbchat-v2 2.3.4**, hỗ trợ tuyến tin thường và E2EE theo thư viện.

Ubuntu/Debian:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv
git clone https://github.com/manh02847/Messenger-AI.git ~/messenger-ai-bot
cd ~/messenger-ai-bot
python3 setup_bot.py
```

Nếu Python hệ thống thấp hơn 3.11, cài Python 3.11+ trước; trình cài không thay Python hệ thống. Lần đầu sẽ tải thư viện và bridge đúng hệ điều hành/CPU, kiểm tra checksum rồi tạo `.venv`.

<details>
<summary>Cài trên Windows</summary>

Tải ZIP qua **Code → Download ZIP** rồi giải nén. Cài [Python 3.11+](https://www.python.org/downloads/) và bật tùy chọn thêm Python vào PATH. Mở PowerShell trong thư mục chứa `setup_bot.py`:

```powershell
py -3 setup_bot.py
```

Trong các lệnh tiếp theo, thay `.venv/bin/python` bằng `.venv\Scripts\python.exe`. Phần systemd chỉ dành cho Linux; khối Python xem thứ tự nguồn ở trên dùng cú pháp shell Linux.

</details>

### Bước 2: Nhập API key và cookie Facebook

Luồng cài ban đầu dùng key [Groq](https://console.groq.com/keys). Có thể thêm các nguồn khác ở mục 4.

```bash
.venv/bin/python -m messenger_ai configure
```

Lệnh hỏi **Groq API key** và **cookie Facebook**, ẩn ký tự khi nhập, lưu vào `secrets.json` và tạo `config.json` nếu chưa có. Nhấn Enter để giữ giá trị cũ khi cấu hình lại.

Cookie cần có dạng:

```text
c_user=ID_TAI_KHOAN; xs=GIA_TRI_PHIEN; ...
```

Lấy từ chính tài khoản Facebook của bạn trên trình duyệt máy tính:

1. Mở Facebook → **F12 → Network**, tải lại trang.
2. Chọn một yêu cầu tới `www.facebook.com` → **Request Headers**.
3. Sao chép **giá trị bên phải `Cookie`**, không lấy cả headers hoặc chữ `Cookie:`.
4. Dán trực tiếp vào lời nhắc trên máy chạy bot.

Cookie cho phép truy cập tài khoản. Không đăng cookie/API key, `secrets.json` hoặc `data/` lên GitHub hay gửi vào chat. Cookie hết hạn thì đăng nhập Facebook bình thường và chạy lại `configure`.

### Bước 3: Thử rồi bật rep

Chạy `check-ai`, chọn [nguồn AI](#4-thêm-nguồn-và-chọn-model) nếu cần, rồi làm theo [chọn phạm vi rep và chạy thử](#5-chọn-phạm-vi-rep-và-chạy-thử). Cài xong **chưa tự gửi tin**: mặc định danh sách được rep rỗng và `dry_run: true`.

## 4. Thêm nguồn và chọn model

Chạy các lệnh trong thư mục bot. Lệnh cấu hình chỉ lưu thiết lập; sau khi kiểm tra, **khởi động lại bot để áp dụng**. Key cũ có thể giữ bằng Enter. Dùng dashboard của từng bên để xem quota thực tế; thêm nguồn không làm tăng hạn mức của từng tài khoản.

### NVIDIA NIM: tự nhập model

Lấy key và mã model ở [NVIDIA API Catalog](https://build.nvidia.com/), sau đó:

```bash
.venv/bin/python -m messenger_ai configure-nvidia
.venv/bin/python -m messenger_ai check-nvidia
```

Bạn tự chọn **một model** dạng `hãng/tên-model`, không nhập cả URL. Lệnh gợi ý `google/gemma-4-31b-it` khi chưa chọn; không có danh sách khóa sẵn và không tự xoay các model NVIDIA. Có thể chỉ định model ngay trong lệnh:

```bash
.venv/bin/python -m messenger_ai configure-nvidia --model google/gemma-4-31b-it
```

Model cần hỗ trợ chat completions trên endpoint NVIDIA. Tên đúng định dạng chưa đảm bảo tài khoản có quyền gọi, nên dùng `check-nvidia` để xác nhận riêng. NVIDIA được đặt trước các nguồn cũ, giữ nguyên cấu hình của chúng.

Tắt NVIDIA, giữ key:

```bash
.venv/bin/python -m messenger_ai configure-nvidia --disable
```

### Google AI Studio: chọn danh sách model

Tạo key ở [Google AI Studio](https://aistudio.google.com/apikey):

```bash
.venv/bin/python -m messenger_ai configure-google
.venv/bin/python -m messenger_ai check-ai
```

Mặc định thêm các model theo thứ tự:

1. `gemma-4-31b-it`
2. `gemma-4-26b-a4b-it`
3. `gemini-3.5-flash-lite`
4. `gemini-3.1-flash-lite`

Để chỉ dùng một phần hoặc đổi thứ tự, chọn trong bốn model được hỗ trợ ở trên:

```bash
.venv/bin/python -m messenger_ai configure-google --models gemma-4-31b-it gemini-3.5-flash-lite
```

Tắt Google, giữ key:

```bash
.venv/bin/python -m messenger_ai configure-google --disable
```

Google đứng sau NVIDIA và trước Groq/Cloudflare. `check-ai` có thể được nguồn khác trả lời; luôn đọc tên nguồn/model trong kết quả. Nhiều model Google có thể dùng chung quota, nên không cộng chúng thành số lượt được bảo đảm.

### Groq và Cloudflare: nguồn chính và dự phòng

Chọn Groq làm chính:

```bash
.venv/bin/python -m messenger_ai configure-ai groq
```

Chọn Cloudflare làm chính:

```bash
.venv/bin/python -m messenger_ai configure-ai cloudflare
```

Cloudflare cần **Account ID** và **Workers AI API token** của đúng tài khoản, lấy theo [hướng dẫn REST API](https://developers.cloudflare.com/workers-ai/get-started/rest-api/). Bot vẫn chạy trên VPS; chỉ phần tạo câu trả lời dùng Workers AI.

Để dùng **Cloudflare chính, Groq dự phòng**, nhập key Groq trước nếu chưa có rồi bật dự phòng:

```bash
.venv/bin/python -m messenger_ai configure-ai groq --no-fallback
.venv/bin/python -m messenger_ai configure-ai cloudflare --fallback
```

Nếu đã có đủ thông tin hai bên, chỉ cần dòng thứ hai. Đổi sang **Groq chính, Cloudflare dự phòng** bằng `configure-ai groq --fallback`. Tắt dự phòng bằng `--no-fallback` với nguồn chính muốn giữ. Không có cờ này thì trạng thái dự phòng hiện tại được giữ nguyên.

| Nguồn | Model do `configure-ai` chọn | Model do `upgrade-chat` chọn |
|---|---|---|
| Groq | `openai/gpt-oss-120b` | `qwen/qwen3.8-27b` |
| Cloudflare | `@cf/qwen/qwen3-30b-a3b-fp8` | `@cf/qwen/qwen3.8-27b` |

Muốn dùng các model Qwen3.8 ở bảng và nâng ngân sách cục bộ:

```bash
.venv/bin/python -m messenger_ai upgrade-chat
.venv/bin/python -m messenger_ai check-ai
```

`upgrade-chat` đổi model chính và model Groq/Cloudflare dự phòng nếu đã bật; giữ NVIDIA, Google và thứ tự nguồn. Nó nâng lên **ít nhất 1000 lần gọi AI/ngày cho toàn bot** và **1000 lượt rep/chat/ngày**, giữ mức cao hơn bạn đã đặt. Đây là giới hạn cục bộ, không cấp thêm quota API. Khi NVIDIA/Google trả lời trước, model Qwen chưa cần được gọi.

**Lưu ý:** chạy lại `configure-ai` sẽ chọn lại model mặc định ở cột giữa. Muốn giữ Qwen3.8 thì chạy `upgrade-chat` sau đó, hoặc sửa đúng trường model trong `config.json` rồi kiểm tra.

<details>
<summary>Khi một nguồn lỗi, bot chuyển nguồn như thế nào?</summary>

- Bot chuyển nguồn khi gặp lỗi khả dụng như mạng, timeout hoặc quota; nguồn lỗi được tạm bỏ qua trong các lượt sau. Không phải mọi lỗi đều được chuyển: lỗi cấu hình, nội dung sai định dạng, bị cắt/chặn hoặc hết ngân sách cục bộ có thể dừng lượt đó.
- **NVIDIA:** một lần thử/lượt, tối đa 12 giây. HTTP 202 đang xếp hàng được bỏ qua, không polling. HTTP 401/403 cho nguồn nghỉ 600 giây rồi thử nguồn sau; 429 nghỉ ít nhất 60 giây và tôn trọng `Retry-After`.
- **Google:** cả nhóm dùng tối đa 20 giây/lượt. Khi có Flash trong danh sách, các Gemma dùng chung tối đa 10 giây để còn thời gian thử Flash. Lỗi 500/502/503/504 trả về nhanh có thể được thử lại một lần; lỗi chậm, timeout và 429 chuyển tiếp luôn. Key/quyền sai hoặc HTTP 400 cần sửa cấu hình, không tự chuyển để bỏ qua lỗi đó.
- **Groq/Cloudflare khi có nhiều nguồn:** mỗi bên thử một lần/lượt. HTTP 429 cho nguồn nghỉ ít nhất 5 phút; lỗi dịch vụ ít nhất 1 phút, lỗi mạng mặc định 5 phút; tôn trọng thời gian chờ dài hơn từ API.
- Khi có nhiều nguồn/model, toàn chuỗi bị giới hạn **60 giây/lượt**. Nếu hết thời gian hoặc tất cả nguồn đang nghỉ, bot bỏ lượt và chờ **tin mới**, không tự rep bù tin cũ.
- Trạng thái nghỉ nguồn nằm trong RAM; bộ đếm gọi AI cục bộ lưu trên đĩa. Restart không làm mới quota API. Mỗi lần retry/chuyển sang gọi nguồn khác đều tính một lần gọi AI.

</details>

## 5. Chọn phạm vi rep và chạy thử

### Rep tất cả chat riêng, bỏ qua nhóm

```bash
.venv/bin/python -m messenger_ai scope all_private
```

Không cần thêm từng ID. Chế độ này chỉ xử lý chat được kết nối xác định là riêng; bỏ qua nhóm và loại chat chưa xác định. Chỉ phản hồi **tin văn bản mới** nhận được khi bot chạy, không tự nhắn trước hoặc rep lại lịch sử.

### Hoặc chỉ rep người bạn chọn

Dừng bot đang chạy trước, rồi:

```bash
.venv/bin/python -m messenger_ai scope allowlist
.venv/bin/python -m messenger_ai discover
```

Nhờ đúng người muốn thử gửi một tin mới. `discover` in mã cuộc trò chuyện và ID người gửi, không in nội dung. Đối chiếu đúng người, nhấn **Ctrl+C**, rồi thêm mã vừa xác minh:

```bash
.venv/bin/python -m messenger_ai allow "e2ee:123456789@msgr"
```

Mã trên chỉ minh họa; thay bằng kết quả thật, có thể là `e2ee:...` hoặc `thread:...`. Không mặc định lấy số trong URL Messenger `/e2ee/t/...` làm mã cho bot. `allowlist` chỉ rep các cuộc trò chuyện trong `allowed_threads`; để bỏ một mã, xóa nó khỏi danh sách trong `config.json`.

### Xem trước, sau đó gửi thật

Không chạy đồng thời bot, service hoặc `discover` trong cùng thư mục. Nếu service đang chạy, dừng bằng `systemctl --user stop messenger-ai` trước khi thử:

```bash
.venv/bin/python -m messenger_ai run --dry-run
```

Nhờ gửi **tin mới** để xem bản nháp. Chế độ này kết nối Messenger và gọi AI nhưng chưa gửi câu trả lời. Nhấn **Ctrl+C**, rồi bật gửi thật:

```bash
.venv/bin/python -m messenger_ai run --live
```

`--live` chỉ áp dụng cho lần chạy hiện tại; `run` không có cờ thì theo `dry_run` trong cấu hình. Dừng bằng **Ctrl+C**. Muốn chạy nền, dừng phiên terminal này rồi làm tiếp mục 6.

## 6. Chạy nền trên VPS

Mẫu service giả định repo ở **`~/messenger-ai-bot`** và VPS có `systemd --user`. Nếu dùng đường dẫn khác, sửa `WorkingDirectory` và `ExecStart` trong file service.

Sau khi cấu hình và chạy thử thành công:

```bash
mkdir -p ~/.config/systemd/user
cp deploy/messenger-ai.service ~/.config/systemd/user/messenger-ai.service
systemctl --user daemon-reload
sudo loginctl enable-linger "$(whoami)"
systemctl --user enable --now messenger-ai
journalctl --user -u messenger-ai -f
```

Service này chạy **`run --live`**, tức gửi thật dù `config.json` còn `dry_run: true`. Lingering cho phép service tiếp tục chạy sau khi đóng SSH. Nhấn Ctrl+C ở màn hình xem log chỉ dừng xem log; muốn tắt bot dùng `systemctl --user stop messenger-ai`.

Nếu bạn đã cài kiểu **system service** trước đây, quản lý bằng `systemctl` không có `--user`. Chọn đúng service đã cài, không chạy cả hai. Với aaPanel/Supervisor, đặt thư mục làm việc là thư mục repo và lệnh `.venv/bin/python -m messenger_ai run --live`; chỉ dùng một trình quản lý tiến trình.

## 7. Ngữ cảnh, giọng trả lời và nhường bạn rep

### Trạng thái đang nhập

Khi chạy gửi thật, bot báo **đang nhập** lúc AI bắt đầu soạn và làm mới khoảng **4 giây/lần** trong lúc chờ, kể cả khi chuyển nguồn AI. Bot gửi tín hiệu tắt khi gửi xong, gặp lỗi, dừng hoặc bạn tự nhắn/yêu cầu nhường. Hỗ trợ cả chat thường và E2EE qua kết nối hiện có.

`run --dry-run`, `check-ai` và `chat-ai` không phát trạng thái này. Tín hiệu đang nhập không gọi thêm AI, không tốn token; nếu cập nhật trạng thái lỗi, bot vẫn tiếp tục xử lý câu trả lời. Việc nhìn thấy dấu đang nhập phụ thuộc Messenger phía người nhận.

### Bot nhớ những gì?

- Mỗi cuộc trò chuyện có lịch sử riêng, gồm tin người kia và câu trả lời của bot; tin bạn tự nhắn cũng được lưu làm ngữ cảnh.
- Mặc định giữ tối đa **12 tin tổng hai phía**; mỗi lượt lấy tối đa **3500 ký tự lịch sử**, cộng chỉ dẫn trong `persona.txt`. Mỗi tin đầu vào được giới hạn **1200 ký tự**.
- Tin cũ được bỏ dần theo giới hạn, nên ngữ cảnh không phình vô hạn. Bot không đọc lại toàn bộ lịch sử Messenger và không reset trắng sau mỗi lần API hết quota.
- Lịch sử bot nằm trong `data/`; dữ liệu quá hạn mặc định **7 ngày** được dọn khi khởi động. `chat-ai` là cuộc trò chuyện thử riêng trong RAM.

### Khi bạn nhắn thủ công

Bot nhường **300 giây (5 phút)** trong cuộc trò chuyện đó, tính lại từ tin thủ công mới nhất. Bản nháp đang soạn bị bỏ khi nhận được tin bạn nhắn. Hết thời gian nhường, bot chỉ rep khi có **tin mới tiếp theo**, không trả lời bù các tin đã bỏ qua.

Một số yêu cầu rõ ràng như “Mạnh tự rep đi” hoặc “Đừng trả lời nữa” cũng kích hoạt nhường; đây là nhận diện theo mẫu, không hiểu mọi cách diễn đạt. AI không tự dừng cuộc trò chuyện chỉ bằng mã `[[HANDOFF]]`.

Bot gom các tin đến sát nhau trong **2,5 giây**. Khi có thêm tin trong lúc AI đang soạn, bản nháp cũ được bỏ để xử lý ngữ cảnh mới. Nếu yêu cầu gửi đã ra mạng thì không bảo đảm thu hồi kịp. Lượt gửi không rõ thành công được ghi nhận và tạm dừng chat, không tự gửi lại.

### Chỉnh cách nói, bỏ icon

Sửa **[persona.txt](persona.txt)** để đổi xưng hô, độ dài và thông tin AI được biết. Mặc định hướng dẫn nói tự nhiên, không thêm emoji, không bịa Mạnh đang làm gì và nói rõ là trợ lý tự động nếu được hỏi.

`reply_prefix` mặc định rỗng. Với cấu hình cũ còn icon hoặc mức 768 token/500 ký tự:

```bash
.venv/bin/python -m messenger_ai tune-chat
```

Lệnh xóa tiền tố, nâng `max_completion_tokens` lên ít nhất **4096**, `output_char_limit` lên ít nhất **4000**; không đổi model hoặc quota API. Hướng dẫn persona không bảo đảm model luôn làm đúng; dùng `chat-ai` để thử câu thực tế. Khởi động lại bot sau khi sửa persona hoặc cấu hình.

## 8. Các thiết lập chính

Sửa `config.json`, đối chiếu [config.example.json](config.example.json). Bảng là **mặc định cài mới**; cấu hình hiện tại có thể khác, `git pull` không ghi đè chúng.

| Trường | Mặc định | Ý nghĩa |
|---|---|---|
| `reply_scope` | `"allowlist"` | `all_private`: tất cả chat riêng; `allowlist`: chỉ danh sách |
| `allowed_threads` | `[]` | Mã cuộc trò chuyện đã xác minh bằng `discover` |
| `dry_run` | `true` | Xem trước nếu không có cờ `--live` |
| `nvidia_model` | `""` | Model NVIDIA tự chọn; rỗng là tắt |
| `google_models` | `[]` | Danh sách model Google theo thứ tự; rỗng là tắt |
| `ai_provider` | `"groq"` | Nguồn chính trong hai bên `groq` / `cloudflare` |
| `model` | `"openai/gpt-oss-120b"` | Model của nguồn chính |
| `ai_fallback` | `false` | Bật nguồn Groq/Cloudflare còn lại làm dự phòng |
| `fallback_model` | `""` | Model nguồn dự phòng; rỗng dùng mặc định của nguồn đó |
| `reply_prefix` | `""` | Tiền tố thêm trước câu trả lời |
| `debounce_seconds` | `2.5` | Thời gian gom tin đến liên tiếp |
| `reply_cooldown_seconds` | `8` | Khoảng cách tối thiểu giữa hai lượt gửi cùng chat |
| `manual_pause_seconds` | `300` | Thời gian nhường khi bạn tự nhắn/yêu cầu dừng hoặc gửi chưa rõ kết quả |
| `max_message_age_seconds` | `120` | Bỏ tin quá cũ; không rep bù lịch sử |
| `history_messages` | `12` | Số tin tối đa trong ngữ cảnh, tổng hai phía |
| `history_char_limit` | `3500` | Tổng ký tự lịch sử lấy cho mỗi lượt |
| `input_char_limit` | `1200` | Giới hạn ký tự mỗi tin đưa vào ngữ cảnh |
| `output_char_limit` | `4000` | Giới hạn ký tự câu trả lời, chưa tính tiền tố |
| `max_completion_tokens` | `4096` | Ngân sách token cho một lần tạo phản hồi; có thể gồm suy luận |
| `max_ai_calls_per_day` | `150` | Tổng lần gọi AI/ngày, tính cả retry và chuyển nguồn |
| `max_replies_per_thread_per_day` | `1000` | Lượt gửi/cố gửi tối đa mỗi chat/ngày |
| `minimum_ai_interval_seconds` | `6` | Khoảng cách tối thiểu giữa các lần bắt đầu gọi cùng model/nguồn |
| `retention_days` | `7` | Dọn dữ liệu cũ khi khởi động |

**Ký tự, token và quota là ba giới hạn khác nhau.** `max_completion_tokens` là ngân sách cho từng lần tạo câu trả lời, không phải token còn lại trong ngày. Nâng nó không tăng quota tài khoản. Số token đầu vào phụ thuộc persona, lịch sử và cách model chia token; không bằng số ký tự.

Bộ đếm cục bộ theo **ngày giờ Việt Nam**, còn quota API theo quy định từng nhà cung cấp. Ví dụ `configure-ai cloudflare --daily-limit 1000` chỉ nâng giới hạn gọi cục bộ. Xem trước và gửi thật có lịch sử/bộ đếm riêng; cả hai vẫn dùng quota của cùng API key.

<details>
<summary>Thông tin bí mật và biến môi trường</summary>

Key/cookie lưu trong `secrets.json` với quyền riêng tư trên Linux. Có thể dùng các biến môi trường sau; giá trị môi trường được ưu tiên hơn file:

| Nguồn | Biến môi trường |
|---|---|
| Facebook | `FACEBOOK_COOKIE` |
| NVIDIA | `NVIDIA_API_KEY` |
| Google | `GEMINI_API_KEY` |
| Groq | `GROQ_API_KEY` |
| Cloudflare | `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` |

Biến chỉ đặt trong phiên SSH chưa chắc được truyền vào systemd; `secrets.json` do lệnh cấu hình lưu có thể dùng trực tiếp với service. Không đưa giá trị bí mật vào README, lệnh công khai hoặc log hỗ trợ.

</details>

## 9. Xử lý lỗi thường gặp

| Hiện tượng | Kiểm tra/cách xử lý |
|---|---|
| `Unit messenger-ai.service not loaded` | Nếu cài theo README, dùng `systemctl --user ...`. Nếu chưa có service, làm mục 6 |
| `Đang có một bot/discover chạy trong thư mục này` | Dừng service hoặc phiên terminal cũ rồi chạy lại. Không xóa `data/bot.lock` để ép chạy hai phiên |
| `allowed_threads đang rỗng` | Dùng `scope all_private`, hoặc `discover` rồi `allow` mã đã xác minh |
| Có nhận tin nhưng không rep | Kiểm tra `--live`, phạm vi rep, thời gian nhường, tin có văn bản và còn quota. Bot chỉ xử lý tin mới |
| `check-ai` thành công nhưng không phải nguồn muốn thử | Đọc nguồn/model in ra; lệnh có fallback. NVIDIA có `check-nvidia` để thử riêng |
| NVIDIA HTTP 401/403 / `Authorization failed` | Kiểm tra key, tài khoản và quyền gọi model. Đọc được danh sách model chưa chứng minh có quyền inference |
| Google HTTP 500/503 | Bot retry hữu hạn rồi chuyển theo thứ tự. Kiểm tra log và nguồn sau; không retry vô hạn |
| HTTP 429 | Chạm giới hạn API hoặc tần suất. Xem quota/dashboard và thời gian chờ; restart không cấp thêm quota |
| Hết ngân sách gọi AI cục bộ | Kiểm tra `max_ai_calls_per_day`; retry cũng được tính. Tăng nếu phù hợp, quota API vẫn áp dụng |
| `Câu trả lời chạm max_completion_tokens` | Là giới hạn của một lần tạo phản hồi. Dùng `tune-chat` nếu cấu hình cũ thấp; không đồng nghĩa hết quota ngày |
| Tất cả nguồn đang lỗi/nghỉ | Bot bỏ lượt, chờ tin mới sau khi nguồn phục hồi; không tự gửi bù |
| Cookie/phiên Facebook hết hạn hoặc checkpoint | Đăng nhập Facebook bình thường, xử lý xác minh rồi nhập cookie mới bằng `configure` |
| Bridge lỗi checksum/phiên bản | Dừng bot, chạy `doctor`; tải lại tài sản đã ghim qua `setup_bot.py`, không dùng binary không khớp checksum |
| Git không cho pull vì có sửa cục bộ | Lưu lại và xử lý thay đổi của bạn trước; không reset xóa cấu hình/persona đang cần |

Tìm tiến trình bot/discover còn chạy trên Linux:

```bash
pgrep -af 'python.*-m messenger_ai (run|discover)'
```

Kiểm tra thư viện, checksum và giao thức bridge mà không đăng nhập Facebook/gọi AI:

```bash
.venv/bin/python -m messenger_ai doctor
```

Phần thử nghiệm ChatGPT web đã được gỡ. Không cần cookie ChatGPT; tùy chọn `chatgpt_web` cũ được tự bỏ khi nạp cấu hình.

## 10. Giới hạn và tài liệu

- Kết nối Messenger cá nhân là **không chính thức**. Facebook có thể đổi giao thức hoặc yêu cầu xác minh; bot không tự vượt CAPTCHA/checkpoint. Kiểm tra offline không chứng minh tài khoản thực tế luôn kết nối được.
- Chỉ xử lý văn bản mới nhận khi chạy; tin chỉ có ảnh, sticker, file, ghi âm không được AI đọc. Không bảo đảm nhận đủ tin trong lúc mất mạng.
- Nội dung cùng một phần lịch sử được gửi tới nhà cung cấp AI được thử. `data/` chứa lịch sử và trạng thái/khóa thiết bị E2EE, chưa mã hóa ở tầng ứng dụng; bảo vệ máy chạy và không chia sẻ thư mục này. Không chạy hai máy dùng chung bản sao thiết bị E2EE.
- Hạn mức, model và điều kiện sử dụng phụ thuộc từng dịch vụ; xem dashboard/tài liệu hiện hành, không coi free tier là không giới hạn.

Tài liệu dự án: [kết quả kiểm tra và phạm vi xác minh](VALIDATION.md), [thành phần bên thứ ba](THIRD_PARTY.md), [service mẫu](deploy/messenger-ai.service).

Tài liệu nhà cung cấp:

- [fbchat-v2 v2.3.4](https://github.com/m008v/fbchat-v2/releases/tag/v2.3.4)
- [NVIDIA NIM API](https://docs.api.nvidia.com/nim/docs/product)
- [Google Gemini API và hạn mức](https://ai.google.dev/gemini-api/docs/rate-limits)
- [Groq API](https://console.groq.com/docs/quickstart) · [hạn mức Groq](https://console.groq.com/docs/rate-limits)
- [Cloudflare Workers AI REST API](https://developers.cloudflare.com/workers-ai/get-started/rest-api/) · [giá và hạn mức](https://developers.cloudflare.com/workers-ai/platform/pricing/)

Để chạy bộ kiểm tra offline dành cho phát triển:

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```
