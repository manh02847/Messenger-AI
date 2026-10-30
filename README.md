# Bot AI trả lời Messenger cá nhân

Bot nhận **tin văn bản mới** trên Messenger cá nhân, dùng AI để soạn rồi trả lời trong cuộc trò chuyện đó. Có thể bật thêm **đọc ảnh gửi mới** bằng model hỗ trợ thị giác. Có ngữ cảnh riêng cho từng người và tự nhường khi bạn nhắn thủ công.

Có thể bật **AI thả cảm xúc theo ngữ cảnh** và **tóm tắt phần cuộc gọi AI đã nghe rồi gửi cho chính mình**. Hai tính năng có công tắc riêng, mặc định chưa bật khi cập nhật.

Hỗ trợ **NVIDIA NIM, Google AI Studio, Cloudflare Workers AI và Groq**. Bot chạy bằng dòng lệnh trên máy tính/VPS; GitHub chỉ lưu mã nguồn. Dùng API hosted nên VPS không cần GPU.

- **Đã cài bot:** xem [lệnh thường dùng](#1-lệnh-thường-dùng) và [kiểm tra nguồn/model](#2-kiểm-tra-ai-nguồn-và-model).
- **Cài lần đầu:** bắt đầu từ [cài đặt](#3-cài-đặt-lần-đầu), sau đó chọn phạm vi rep và chạy thử.
- **AI trong cuộc gọi Chrome máy tính:** xem [Call Lab](experimental/CALL_LAB.md). Relay đã thử với Google thật; người dùng xác nhận cầu nối 0.1.1 hoạt động trên Chrome Windows. Các phần mới ở bản VPS cần kiểm tra riêng.
- **Gọi AI chạy hoàn toàn trên Ubuntu VPS:** xem [cài Chrome, âm thanh ảo và tự nhận cuộc gọi](deploy/CALL_VPS.md). Bản 0.5.0 cho chọn thời gian chờ để bạn nghe trước, mặc định 25 giây; cần đăng nhập Facebook và kiểm tra cuộc gọi trên VPS trước khi bật tự động.

## 1. Lệnh thường dùng

Các lệnh Linux bên dưới chạy trong thư mục bot:

```bash
cd ~/messenger-ai-bot
```

### Cập nhật bot

Nếu cài **system service bằng root** theo mục 6:

```bash
systemctl stop messenger-ai
git pull --ff-only
python3 setup_bot.py
systemctl start messenger-ai
```

Nếu chạy trực tiếp trên terminal, nhấn **Ctrl+C** để dừng trước khi cập nhật, rồi chạy lại `run --live`. `setup_bot.py` cập nhật thư viện/bridge; thay đổi chỉ có README thì không cần chạy lại bot.

`git pull` giữ cấu hình riêng, cookie và dữ liệu trong `config.json`, `secrets.json`, `data/`. Nó **không tự đổi model hoặc bật nguồn AI mới**. Nếu bạn đã sửa `persona.txt` hay mã nguồn, cần lưu/xử lý thay đổi đó trước khi pull; không dùng reset để xóa chỉnh sửa chưa lưu.

### Quản lý bot chạy nền

| Việc cần làm | Lệnh |
|---|---|
| Xem trạng thái | `systemctl status messenger-ai` |
| Xem log trực tiếp | `journalctl -u messenger-ai -f` |
| Dừng bot | `systemctl stop messenger-ai` |
| Bật bot | `systemctl start messenger-ai` |
| Áp dụng cấu hình/persona mới | `systemctl restart messenger-ai` |

Các lệnh trên dành cho **system service**. Nếu đã cài **user service**, thêm `--user` vào `systemctl` và `journalctl`. Hai loại service được cài ở vị trí khác nhau; chọn đúng loại đã cài. Nếu chưa có service, xem [chạy nền trên VPS](#6-chạy-nền-trên-vps).

### AI tự chọn cảm xúc

```bash
.venv/bin/python -m messenger_ai reactions auto
systemctl restart messenger-ai
```

Model chọn theo câu mới và ngữ cảnh: không thả, thả rồi trả lời, hoặc chỉ thả để xác nhận/kết chuyện. Có các cảm xúc thích, tim, vui, ngạc nhiên và buồn; hướng dẫn chọn thận trọng, không dùng để nhận lời hoặc xác nhận giao dịch thay chủ tài khoản. Nội dung chữ vẫn theo persona, không tự thêm emoji. Quyết định nằm trong cùng lượt gọi AI, không gọi thêm một model chỉ để chọn react.

`chat-ai` cho xem lựa chọn dự kiến mà không kết nối Messenger. Cảm xúc chỉ tác động đúng tin mới nhất trong chat riêng đã được phép, không tác động nhóm hoặc tin của chính bạn. Bot vẫn nhường khi bạn nhắn thủ công. Nếu lệnh react lỗi/chưa rõ kết quả, không tự thả lại và dùng câu trả lời chữ dự phòng. Việc gửi lệnh thành công chưa thay thế việc kiểm tra cảm xúc đã hiển thị trên Messenger.

```bash
.venv/bin/python -m messenger_ai reactions off
```

Đổi cấu hình xong restart service tương ứng. Với acc 2, chạy trong `~/messenger-ai-bot-2` và dùng `systemctl restart messenger-ai-2`.

### Tóm tắt cuộc gọi rồi gửi tin

Trên VPS đã cài gọi AI, chọn thư mục bot sẽ **nhận thông báo cho chính tài khoản đó**:

```bash
cd ~/messenger-ai-bot
.venv/bin/python setup_call_vps.py install --call-summaries
systemctl restart messenger-ai
```

Sau khi phần AI tham gia cuộc gọi kết thúc, host tạo bản tóm tắt ngắn và bot nhắn vào cuộc trò chuyện **với chính mình**. Không gửi bản tóm tắt cho người gọi. Chỉ nhận dạng lời nói khi bật tính năng này, không ghi file âm thanh. Bản tóm tắt dựa vào phần AI nghe, có thể thiếu khi nhường người thật hoặc nhận dạng sai.

Mặc định dùng `gemini-3.5-flash-lite`, một request Google bổ sung sau mỗi phiên có lời người gọi; tính vào quota/phí project Google, tách bộ đếm của bot text. Đổi bằng `--summary-model MÃ_MODEL`. Host và bot nhắn tin đều cần chạy, bot phải ở chế độ gửi thật. Không cần reload tiện ích chỉ để bật hai tính năng Python này; giữ các lựa chọn giọng, persona, chờ tự nhận và mã kết nối hiện có.

Tắt tóm tắt **các cuộc gọi mới**:

```bash
.venv/bin/python setup_call_vps.py install --no-call-summaries
```

Chi tiết acc 2, bản chờ gửi, lỗi và dữ liệu tạm: [hướng dẫn tóm tắt cuộc gọi](deploy/CALL_VPS.md#tóm-tắt-sau-gọi-và-gửi-cho-chính-mình).

## 2. Kiểm tra AI, nguồn và model

### Thử API và thử hội thoại

```bash
.venv/bin/python -m messenger_ai check-ai
```

`check-ai` gọi thử theo thứ tự nguồn đang cấu hình, in **nguồn/model thực sự trả lời** và thời gian. Nếu nguồn đầu lỗi, nó có thể dùng nguồn sau; thành công không có nghĩa tất cả nguồn đều hoạt động.

```bash
.venv/bin/python -m messenger_ai chat-ai
```

`chat-ai` dùng cùng chuỗi nguồn và persona như bot (ưu tiên `persona.local.txt` nếu có) để thử nhiều lượt, kể cả viết tắt/sai chính tả. Gõ `/context` để xem lượng ngữ cảnh, `/reset` để bắt đầu lại, `/quit` để thoát. Lịch sử thử chỉ giữ trong RAM, không đọc lịch sử Messenger.

Hai lệnh trên **không kết nối hoặc gửi Messenger**, nhưng có gọi API và tiêu thụ quota thật. Chúng dùng chung bộ đếm thử cục bộ, tách với bộ đếm của bot đang rep.

Để kiểm tra **riêng NVIDIA**, không chuyển sang nguồn khác:

```bash
.venv/bin/python -m messenger_ai check-nvidia
```

Để kiểm tra chuỗi đọc ảnh, dùng `check-vision`; thêm `--all` để thử riêng từng model. Xem [bật đọc ảnh](#đọc-ảnh-trên-messenger). `check-ai` và `chat-ai` chỉ thử tin chữ, không chứng minh model đọc được ảnh.

### Xem nguồn đang bật và thứ tự model

```bash
.venv/bin/python -m messenger_ai providers
```

Lệnh chỉ đọc cấu hình, in cờ **BẬT/TẮT**, model chữ/ảnh đã lưu và hai chuỗi thực sự đang dùng; không đọc/in key hay gọi API. Nguồn tắt được bỏ qua ở cả hai chuỗi.

Bot thử model từ trên xuống đến khi có câu trả lời, theo `text_models` cho chữ và `vision_models` cho ảnh. Cài mới chỉ bật Groq; các nguồn khác cần chọn model/key rồi bật. Không có nhà cung cấp nào bắt buộc phải làm nguồn cuối.

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

Trong các lệnh tiếp theo, thay `.venv/bin/python` bằng `.venv\Scripts\python.exe`. Phần systemd chỉ dành cho Linux.

</details>

### Bước 2: Nhập API key và cookie Facebook

Chọn nguồn khi cài: mặc định [Groq](https://console.groq.com/keys), hoặc truyền `--provider cloudflare`, `--provider google`, `--provider nvidia`. Các nguồn khác có thể thêm ở mục 4.

Với Groq:

```bash
.venv/bin/python -m messenger_ai configure
```

Với Cloudflare, không cần key Groq:

```bash
.venv/bin/python -m messenger_ai configure --provider cloudflare
```

Lệnh hỏi thông tin AI của nguồn được chọn và **cookie Facebook**, ẩn key/cookie khi nhập. Sau khi kiểm tra định dạng, lệnh lưu `secrets.json` và `config.json`; chưa gọi API hay đăng nhập Messenger. Cấu hình lại bằng `configure` không có cờ giữ nguyên cờ nguồn và thứ tự model, kể cả khi tất cả nguồn đang tắt; Enter để giữ thông tin cũ. `--provider` cấu hình và bật nguồn được nêu.

Nếu đã có một bản bot trên cùng VPS, có thể dùng lại riêng phần AI bằng `configure --copy-ai-from THU_MUC_BOT_CU`; xem phần thêm acc ở mục 6.

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

Mọi lệnh chạy trong đúng thư mục bot. Sau khi thay đổi nguồn hoặc model, khởi động lại đúng service để áp dụng.

### Bật/tắt nguồn: cùng một lệnh cho cả bốn bên

```bash
.venv/bin/python -m messenger_ai providers
```

| Việc cần làm | Lệnh |
|---|---|
| Chỉ dùng Google | `.venv/bin/python -m messenger_ai providers only google` |
| Chỉ dùng NVIDIA | `.venv/bin/python -m messenger_ai providers only nvidia` |
| Chỉ dùng Groq | `.venv/bin/python -m messenger_ai providers only groq` |
| Chỉ dùng Cloudflare | `.venv/bin/python -m messenger_ai providers only cloudflare` |
| Bật thêm NVIDIA và Groq | `.venv/bin/python -m messenger_ai providers enable nvidia groq` |
| Tắt NVIDIA và Cloudflare | `.venv/bin/python -m messenger_ai providers disable nvidia cloudflare` |
| Chỉ giữ Google và Groq | `.venv/bin/python -m messenger_ai providers only google groq` |

`only` chỉ bật các nguồn được nêu; `enable` bật thêm, `disable` tắt các nguồn được nêu. Cờ dùng chung cho chữ và ảnh. Các lệnh này **giữ nguyên toàn bộ model, thứ tự và key**, không hỏi lại key/cookie hoặc gọi API. Nguồn bật cần có ít nhất một model đã chọn và thông tin kết nối hợp lệ; nguồn đang tắt không bị gọi hoặc yêu cầu key.

Có thể tắt toàn bộ nguồn: bot tiếp tục nhận tin nhưng không gọi AI/gửi phản hồi. Bật lại sẽ dùng các model đã lưu. Nếu nguồn chỉ có model ảnh thì chỉ xử lý ảnh; muốn rep chữ cần chọn thêm model chữ.

### Nhập key và chọn model bằng lệnh chung

`configure-ai` dùng được cho Google, NVIDIA, Groq và Cloudflare. Có thể truyền một hoặc nhiều model của cùng nguồn; ví dụ dưới đây là các lựa chọn độc lập, chỉ chạy dòng của nguồn muốn cấu hình:

```bash
.venv/bin/python -m messenger_ai configure-ai google --models gemini-3.8-flash gemini-3.6-flash gemini-3.5-flash-lite gemini-3.1-flash-lite
.venv/bin/python -m messenger_ai configure-ai nvidia --model google/gemma-4-31b-it
.venv/bin/python -m messenger_ai configure-ai groq --model openai/gpt-oss-120b
.venv/bin/python -m messenger_ai configure-ai cloudflare --model @cf/qwen/qwen3.8-27b
```

Lệnh lưu model/key và bật nguồn được chọn, dùng cùng bộ xử lý cấu hình cho cả bốn bên. Ở dòng key, Enter giữ key cũ. Thêm `--keep-key` để dùng key hiện có mà không hỏi/ghi lại key. Nếu không truyền `--models`, lệnh hỏi để bạn nhập mã trực tiếp; Enter giữ danh sách đang hiển thị. Nguồn chưa có model hiển thị mẫu của chương trình. Thứ tự thực tế được in ra sau khi lưu.

Key và mã model lấy tại [NVIDIA API Catalog](https://build.nvidia.com/), [Google AI Studio](https://aistudio.google.com/apikey), [Groq Console](https://console.groq.com/) hoặc [Cloudflare REST API](https://developers.cloudflare.com/workers-ai/get-started/rest-api/). Cloudflare cần thêm Account ID. NVIDIA nhận mã `hãng/tên-model`, không nhập URL. Google nhận **mã API tự chọn**, kể cả model mới chưa có trong mẫu; không bị khóa vào danh sách cố định. Nhập `gemini-3.8-flash`, không nhập tên hiển thị `Gemini 3.8 Flash`, tiền tố `models/` hoặc URL.

### Tự đổi model Google

**Cách dễ nhất:** chạy lệnh ngắn rồi dán mã model khi được hỏi:

```bash
.venv/bin/python -m messenger_ai configure-ai google
```

Nhập một mã như `gemini-3.8-flash`, hoặc nhiều mã như `gemini-3.8-flash gemini-3.6-flash gemini-3.5-flash-lite gemini-3.1-flash-lite`. Có thể dùng dấu phẩy thay dấu cách; thứ tự nhập là thứ tự thử. Nhấn Enter không nhập gì để giữ danh sách hiện tại. Chế độ này tự dùng key đã lưu nếu có, không hỏi lại cookie. Muốn nhập lại key thì thêm `--edit-key`; chưa có key sẽ được hỏi để nhập.

Đổi chuỗi ảnh cũng theo cách nhập trực tiếp, dùng key đã cấu hình:

```bash
.venv/bin/python -m messenger_ai configure-vision google
```

Chỉ dán mã model, không cần thêm `google:`. Enter giữ các model ảnh Google đang lưu; nếu chưa có thì hiện các model chữ Google để bạn chọn. Lệnh chọn chuỗi ảnh của nguồn này; model chữ được giữ. Thay `google` bằng `nvidia`, `groq` hoặc `cloudflare` để cấu hình tương tự cho nguồn khác. Dùng `providers` để xem/bật/tắt nguồn; restart service đúng acc sau khi đổi model.

Lấy mã model mà API trả về cho key hiện có:

```bash
.venv/bin/python -m messenger_ai list-models google
```

Lệnh chỉ đọc [Google Models API](https://ai.google.dev/api/models), lấy đủ các trang và in mã có `generateContent`; không gửi persona, ảnh hay nội dung chat, không thay cấu hình hoặc bật thêm nguồn. Có tên trong danh sách chưa chứng minh model có quota, miễn phí, hỗ trợ ảnh hoặc tạo được câu trả lời; chọn model trả lời chữ/hiểu ảnh phù hợp, tránh các model chuyên TTS, embedding hoặc tạo ảnh.

Đổi model chữ theo thứ tự bạn muốn, dùng lại key cũ:

```bash
.venv/bin/python -m messenger_ai configure-ai google --keep-key --models gemini-3.8-flash gemini-3.6-flash gemini-3.5-flash-lite gemini-3.1-flash-lite
.venv/bin/python -m messenger_ai providers only google
```

Đổi riêng chuỗi đọc ảnh, cũng nhập thủ công theo thứ tự:

```bash
.venv/bin/python -m messenger_ai configure-vision --chain google:gemini-3.8-flash google:gemini-3.6-flash
```

Để dùng một model, giữ đúng một mã sau `--models` hoặc `--chain`. Có thể đổi sang mã khác từ `list-models` bất cứ lúc nào, không phải sửa code. Sau khi lưu, chạy `check-ai`, `check-vision --all` nếu có dùng ảnh, rồi restart service đúng acc. Chỉ bật Google thì retry/fallback cũng chỉ dùng các model Google đã chọn.

Mẫu Google ưu tiên **Gemini 3.8 Flash → Gemini 3.6 Flash → Gemini 3.5 Flash-Lite → Gemini 3.1 Flash-Lite** cho chữ; mẫu ảnh dùng 3.8 Flash → 3.6 Flash trước các nguồn khác. Các model Google trong mẫu có Free Tier cho đầu vào/đầu ra theo bảng giá Google ngày 25/10/2026; không đưa Argon vào mẫu vì model đó chỉ có trả phí. Đây là mẫu khi cấu hình nguồn chưa có model hoặc gọi `configure-vision --chain` không kèm danh sách. **`git pull` không ghi đè model đã lưu**; muốn thay cấu hình hiện có thì chạy các lệnh trên. Bot không tự theo dõi catalog để đổi model.

**Có Free Tier cho model chưa đủ để bảo đảm tài khoản không bị tính phí.** Phải dùng key thuộc project đang hiển thị **Free Tier**; key thuộc project Paid Tier/Tier 1 áp dụng bảng giá Paid Tier, kể cả gọi Flash có cột Free Tier. Bot không kiểm tra được tier/số dư của project từ key hoặc từ `list-models`. Xem [Google Pricing](https://ai.google.dev/gemini-api/docs/pricing) và [Google Billing](https://ai.google.dev/gemini-api/docs/billing).

Với nhu cầu dùng miễn phí, giữ suy luận tự động và tắt Search cho chuỗi Gemini 3 ở trên:

```bash
.venv/bin/python -m messenger_ai features --reasoning auto --search off
```

Google Search trên các Gemini 3 này yêu cầu Paid Tier theo bảng giá hiện tại. Quota Search miễn phí nằm trong Paid Tier không làm token đầu vào/đầu ra thành miễn phí. Nếu đã có `model_features`, kiểm tra `features --show` và đặt tra cứu `off` ở từng model đang dùng; lựa chọn riêng vẫn ưu tiên hơn lệnh chung. Nếu cần tra cứu với Free Tier, Gemini 2.5 Flash có hạn mức grounding miễn phí riêng; phải tự chọn model đó và kiểm tra quota hiện có. Không bật billing/chuyển tier chỉ để dùng mẫu này.

Nếu AI Studio báo **Prepay credits depleted / No credits**, cần kiểm tra billing/số dư của project trước. Đổi model hoặc retry không bổ sung số dư và không đưa project trả phí về Free Tier. Muốn đổi key sau khi chọn đúng project, dùng `configure-ai google --edit-key`; không dán key vào chat/GitHub.

Lệnh cũ `configure-google`, `configure-nvidia`, `configure-google --only` và `--disable` vẫn được chuyển vào cùng bộ xử lý. `--fallback` / `--no-fallback` của Groq/Cloudflare chỉ bật/tắt cờ nguồn còn lại; nên dùng `providers` để quản lý thống nhất.

`upgrade-chat` đổi các model chữ Groq/Cloudflare đã cấu hình sang Qwen3.8, giữ model nguồn khác và cờ bật/tắt. Lệnh nâng ngân sách cục bộ lên ít nhất 1000 lần gọi/ngày và 1000 lượt rep/chat/ngày, không cấp thêm quota API.

### Bật, tắt hoặc tự động suy luận và tra cứu

Chạy lệnh ngắn, rồi nhập **on**, **off** hoặc **auto** ở hai câu hỏi. Có thể nhập `bật`/`tắt`/`tự động`; Enter giữ lựa chọn hiện tại:

```bash
.venv/bin/python -m messenger_ai features
```

| Chế độ | Suy luận | Tra cứu web |
|---|---|---|
| `off` | Tắt nếu model cho phép; model luôn suy luận dùng mức thấp nhất | Không gắn công cụ tìm kiếm |
| `on` | Bật suy luận sâu theo API của model | Yêu cầu model dùng Google Search xác minh thông tin thực tế |
| `auto` | Gemini tự phân bổ suy nghĩ trong ngân sách phù hợp; API chỉ có công tắc/mức cố định dùng quy tắc tại bot để chọn theo câu hỏi | Câu cần thông tin mới/kiểm chứng tự chọn model Search đang bật; model dùng công cụ tìm khi cần |

Hai lựa chọn áp dụng cho cả chữ và ảnh, **theo đúng nguồn/model của từng lần thử**. Không có lượt gọi AI riêng để phân loại câu hỏi. Cấu hình cũ không có hai trường mới mặc định `off`/`off`, chưa tự bật Search. Lưu bằng `features` không gọi API, không đổi model, cờ nguồn, key/cookie, persona, lịch sử hoặc bộ đếm.

Đặt nhanh suy luận tự động và tắt Search cho nhu cầu chat miễn phí, hoặc chỉ xem trạng thái mà không lưu:

```bash
.venv/bin/python -m messenger_ai features --reasoning auto --search off
.venv/bin/python -m messenger_ai features --show
```

Có thể chỉnh riêng từng **nguồn:model**, hoặc bỏ lựa chọn riêng để dùng lại mặc định chung:

```bash
.venv/bin/python -m messenger_ai features --model google:gemini-3.8-flash
.venv/bin/python -m messenger_ai features --model google:gemini-3.8-flash --reasoning off --search off
.venv/bin/python -m messenger_ai features --model google:gemini-3.8-flash --reset
```

Lựa chọn riêng lưu trong `model_features`; đổi chế độ chung không xóa chúng. `--show --model nguồn:model` xem khả năng/mức có hiệu lực, kể cả model chưa được chọn. Chỉ đặt lựa chọn không bật thêm nguồn; cờ `provider_enabled` vẫn quyết định nguồn có được gọi hay không. Cấu hình AI sao chép sang acc khác bao gồm cả hai chế độ và lựa chọn riêng.

Khả năng đã được đối chiếu cho các model đang dùng:

| Nguồn/model | Điều khiển suy luận | Tra cứu đã tích hợp |
|---|---|---|
| Google Gemini 3.8 Flash, 3.6 Flash và các Gemini 3 được nhận diện; Argon cho người tự chọn trả phí | `thinkingLevel`; `auto` dùng mức cân bằng và cơ chế suy nghĩ động của model | Google Search ở các model đã xác minh hỗ trợ |
| Google Gemini 2.5 Pro/Flash/Flash-Lite | `thinkingBudget`; `auto` dùng ngân sách động; Pro không tắt hẳn | Google Search |
| Google Gemma 4 31B/26B | `high` hoặc `minimal`; auto chọn theo câu hỏi | Google Search qua Gemini API |
| NVIDIA Google Gemma 4 31B/26B | `enable_thinking`; auto chọn theo câu hỏi | Chưa tích hợp |
| Groq GPT-OSS 20B/120B, Qwen 3.8 27B | Mức được API hỗ trợ; GPT-OSS không tắt hẳn | Chưa tích hợp |
| Cloudflare Qwen 3.8 27B | `low`/`medium`/`xhigh`; không có mức tắt hẳn được xác minh | Chưa tích hợp |
| Cloudflare Qwen3-30B-A3B cũ | Công tắc mềm `/think` và `/no_think`; hiệu lực còn tùy template của nguồn | Chưa tích hợp |

Tên tự nhập chưa được nhận diện vẫn dùng mặc định của API, không đoán/gửi tham số reasoning hoặc công cụ không hỗ trợ; `features --show` ghi rõ giới hạn đó. Model chưa hỗ trợ Search có thể yêu cầu chuyển câu cần kiểm chứng sang model Search đã bật trong cùng danh sách. Nếu không có model Search, bot dùng giới hạn không tra cứu. Không tự gọi nhà cung cấp ngoài danh sách đang bật.

`auto` xét câu mới nhất trước: lời chào/cảm thán rõ ràng như “chào bạn”, “thế à”, “ok cảm ơn” dùng mức suy luận tối thiểu, kể cả sau một bài khó. Các câu hỏi thực chất trên Gemini vẫn dùng cơ chế động ở mức/ngân sách trong bảng. Với Gemma và API chỉ hỗ trợ bật/tắt/mức cố định, bot dùng quy tắc tại máy: nhận tiếng Việt không dấu, bài toán có nhiều dữ kiện số và câu hỏi tiếp như “nếu đổi 13 thành 14?”. Chủ đề cũ không tự làm mọi câu sau thành khó. Đây vẫn là quy tắc gần đúng, chưa phải bộ phân loại ngữ nghĩa; không bảo đảm nhận đúng mọi bài toán, lỗi gõ hoặc hàm ý. `on` vẫn ép suy luận sâu, `off` giữ mức tối thiểu; không tự đổi lựa chọn đã lưu.

Google quyết định việc thực thi Search: **bật/auto không có nghĩa mọi lượt đều phát sinh tìm kiếm**. Bot dùng metadata grounding để xác nhận việc tra cứu, **không tự nối mục Nguồn, gợi ý Google Search hoặc đống link redirect vào tin nhắn**. Prompt yêu cầu trả lời tự nhiên; chỉ đưa link/nguồn trong nội dung khi người nhắn yêu cầu. Link model viết trong câu trả lời vẫn được giữ. Log ghi `tra cứu thực tế=có/không` và số nguồn, không in câu tìm kiếm, HTML, API key hoặc nội dung chat. Lỗi quyền/billing/cấu hình Search được báo rõ và không âm thầm thử lại cùng request với công cụ bị gỡ bỏ.

Suy luận/tra cứu cần thêm thời gian: lượt thực sự dùng chế độ này có deadline **45 giây/model**, cả chuỗi **90 giây**, nhóm Google chữ tối đa **60 giây** (Gemma tối đa 30 giây khi có Gemini dự phòng). Khi tự chọn chuỗi Search, mỗi model được thử tối đa **30 giây** để còn thời gian cho model Search tiếp theo; thời gian cả nhóm/cả lượt vẫn bị giới hạn như trên. Lượt cơ bản giữ giới hạn cũ. Quá tải/timeout vẫn đi theo cơ chế giữ câu chờ; không bỏ giới hạn thời gian để retry liên tục trong một request.

Ngân sách sinh vẫn là `max_completion_tokens` đang cấu hình, gồm cả suy luận; câu quá khó có thể hết ngân sách và bot không gửi bản bị cắt. Không tự tăng token hoặc quota. Một request vẫn tính một lượt ở bộ đếm cục bộ, nhưng **token suy luận và truy vấn Google Search có cách tính quota/phí riêng của nhà cung cấp**. Xem [Google thinking](https://ai.google.dev/gemini-api/docs/generate-content/thinking), [Google Search](https://ai.google.dev/gemini-api/docs/generate-content/google-search), [Groq reasoning](https://console.groq.com/docs/reasoning) và [Cloudflare Qwen](https://developers.cloudflare.com/workers-ai/models/qwen3.8-27b/).

Chạy `chat-ai`, hỏi một câu cần thông tin hiện tại rồi kiểm tra dòng `tra cứu thực tế=có` trong log; restart service đúng acc để áp dụng cho Messenger. `check-ai` chỉ hỏi chào nên `auto` có thể không tìm kiếm; các lệnh thử không gửi Messenger.

Hai Gemma 4 trên **nguồn Google** hỗ trợ `googleSearch` theo [hướng dẫn Gemma qua Gemini API](https://ai.google.dev/gemma/docs/core/gemma_on_gemini_api#google-search); khả năng này không tự áp dụng cho Gemma chạy ở NVIDIA. Muốn chỉ cho hai model này tự tra cứu, giữ Search chung `off` và đặt riêng:

```bash
.venv/bin/python -m messenger_ai features --model google:gemma-4-31b-it --search auto
.venv/bin/python -m messenger_ai features --model google:gemma-4-26b-a4b-it --search auto
```

Bot tự chọn model theo câu hỏi, cho cả chữ và ảnh:

- **Chat thường:** theo thứ tự model đã cấu hình. Ví dụ Flash đứng trước thì thử Flash trước.
- **Câu nhận ra ngay cần tra:** thời tiết, tin tức, giá, tỷ giá, lịch, phiên bản mới, yêu cầu tìm/kiểm tra… đi thẳng tới các model Search đã bật `on`/`auto`, giữ thứ tự tương đối. Ví dụ “bình ga 1 bình nhiêu ta” hoặc “tìm thử xem nào” cũng được nhận diện. Không gọi Flash trước cho các câu này.
- **Câu ngoài bộ từ khóa:** model đang trả lời tự xét ý nghĩa và ngữ cảnh. Khi cần xác minh thông tin công khai, model có thể gửi yêu cầu nội bộ để bot chuyển sang Search thay vì trả “không có công cụ tra cứu”. Model hỗ trợ Search được yêu cầu tra thật; model chưa hỗ trợ chỉ yêu cầu chuyển, không được tự gắn công cụ không tương thích. Cách này dùng thêm một lượt gọi model đầu **khi có chuyển sang Search**; chat trả lời bình thường vẫn chỉ một lượt, không gọi API phân loại riêng cho mỗi tin.
- **Câu hỏi tiếp:** đọc ngữ cảnh người nhắn gần đây, nên sau câu hỏi thời tiết, “còn ngày mai thì sao?” vẫn đi tới Search. “Thế à”, “ừ”, “ok”, lời rủ và chuyện cá nhân dùng chat thường. “Nay ngày gì”, thứ/ngày và giờ hiện tại dùng mốc thời gian máy chủ theo giờ Việt Nam được cung cấp ở mỗi request, không cần Search.
- **Nguồn Search quá tải/hết quota:** thử model Search kế tiếp, rồi giữ câu chờ theo cơ chế retry. Không chuyển câu cần dữ liệu mới sang model tắt Search chỉ để có câu trả lời. Các cuộc chat thường vẫn dùng được Flash khỏe trong khi nguồn Search đang nghỉ.

Nhận diện kết hợp quy tắc nhanh với quyết định của model, vẫn có thể bỏ sót hoặc chọn sai. Khi đã chuyển sang Search, bot kiểm tra metadata thực tế: không có dữ liệu Search thì bỏ bản nháp đó, thử model Search khác hoặc giữ câu chờ. Yêu cầu nội bộ không được gửi lên Messenger hay lưu thành câu trả lời. Bot nhớ quyết định chuyển của tối đa 128 ngữ cảnh bằng mã băm trong RAM để retry cùng câu không phải hỏi lại Flash; tin mới/đổi ngữ cảnh được xét lại. Không tự bật nguồn/model, đổi key hoặc gửi dữ liệu riêng vào truy vấn. Lỗi nội dung bị chặn/câu trả lời bị cắt vẫn dừng như trước.

Lượt cần Search ở Gemma gửi câu hỏi hiện tại kèm yêu cầu gọi công cụ; khi có lịch sử thì gửi ngữ cảnh có gắn nhãn cùng câu hỏi để hiểu câu hỏi tiếp ngắn. Nhắc model hiểu cách viết tắt như “1 bình nhiêu” là hỏi giá theo ngữ cảnh, tìm giá tham khảo và nói rõ phạm vi nếu thiếu loại/khu vực. Persona và ảnh hiện tại vẫn được cung cấp; lịch sử cũ là dữ liệu có thể sai, không phải chỉ dẫn hệ thống hoặc nguồn xác minh. Chat thường và model khác dùng cách gửi lịch sử vốn có.

Các lựa chọn `features` vẫn áp dụng: `off` không cho model đó tra cứu; `on`/`auto` mới được tự chọn vào chuỗi Search. Lựa chọn riêng từng model ưu tiên hơn mặc định chung. `features --show` hiển thị model Search có thể dùng; danh sách chữ và ảnh vẫn được xét riêng khi trả lời. Không tự bật Search sau `git pull`, không đổi key hay ghi lại thứ tự model trong file cấu hình. Khi thử bằng `chat-ai`, hỏi “thời tiết Hà Nội hôm nay” rồi “còn ngày mai thì sao?”, kiểm tra dòng `Tự chọn model tra cứu`, model thực sự trả lời và `tra cứu thực tế=có`.

Khả năng gọi được Search không xác nhận project thuộc Free Tier hay chứng minh một lượt thử không phát sinh phí. Hướng dẫn Gemma hiện có ví dụ Search trong khi bảng giá Gemma vẫn ghi `Not available`; cần kiểm tra billing/quota thực tế của project. Tooltip `Default` có nhiều model cùng nhóm không có nghĩa mỗi model được một hạn mức Search riêng.

### Ba trường quản lý nguồn trong config.json

Ví dụ phần nguồn, với Google đang bật và NVIDIA đang tắt:

```json
{
  "provider_enabled": {
    "nvidia": false,
    "google": true,
    "groq": false,
    "cloudflare": false
  },
  "text_models": [
    "nvidia:google/gemma-4-31b-it",
    "google:gemini-3.8-flash",
    "google:gemini-3.6-flash"
  ],
  "vision_models": [
    "google:gemini-3.8-flash",
    "nvidia:google/gemma-4-31b-it"
  ]
}
```

Có thể sửa trực tiếp các cờ true/false hoặc thứ tự hai danh sách, giữ các thiết lập khác trong file rồi restart bot. Model có trong danh sách nhưng nguồn tắt sẽ không được gọi. Model chữ và ảnh được chọn riêng; model đọc ảnh phải hỗ trợ thị giác.

Cấu hình cũ vẫn được đọc theo đúng thứ tự đang dùng. Lần đầu lưu cấu hình nguồn bằng lệnh mới, chương trình đổi sang ba trường trên và tạo `config.before-providers.bak` riêng tư, không ghi đè bản sao đã có. Key vẫn ở `secrets.json`; persona, lịch sử và các giới hạn được giữ. Không thêm lại các trường nguồn cũ như `ai_provider` hoặc `ai_fallback` vào file đã chuyển.

<details>
<summary>Khi một nguồn lỗi, bot chuyển nguồn như thế nào?</summary>

- Bot chuyển nguồn khi gặp lỗi khả dụng như mạng, timeout, quota hoặc phản hồi API hỏng/trống; nguồn lỗi được tạm bỏ qua trong các lượt sau. Lỗi cấu hình, nội dung bị chặn hoặc câu trả lời chạm giới hạn token cần xử lý riêng, không thử vô hạn.
- **NVIDIA:** một lần thử/lượt, tối đa 12 giây. HTTP 202 đang xếp hàng được bỏ qua, không polling. HTTP 401/403 cho nguồn nghỉ 600 giây rồi thử nguồn sau.
- **Google:** mỗi model thử một request trong chuỗi nhiều model; lỗi tạm thời chuyển ngay sang model kế tiếp. Nếu chỉ cấu hình một model, lỗi 500/502/503/504 trả về nhanh được thử lại một lần trong deadline. Lượt cơ bản cả nhóm tối đa 20 giây; Gemma dùng chung 10 giây khi có Flash. Suy luận/Search dùng deadline riêng ở trên. Khi model đang trả lời yêu cầu chuyển sang Search, thời gian Google đã dùng vẫn bị trừ, không mở lại ngân sách 60 giây mới. Key/quyền sai hoặc HTTP 400 cần sửa cấu hình.
- **Groq/Cloudflare khi có nhiều model:** mỗi model thử một request/vòng rồi chuyển tiếp khi gặp lỗi tạm thời.
- **Thời gian nghỉ:** lỗi mạng, timeout, HTTP 408/5xx hoặc model không trả kết quả Search mặc định 1 giây, không cộng dồn backoff. HTTP 429 không có chỉ dẫn nghỉ 60 giây; có `Retry-After`/Google `RetryInfo` thì dùng mốc đó, kể cả khi ngắn hơn 60 giây. Hết quota ngày chờ reset khi API có thông tin. Model khác đang sẵn sàng được thử ngay, không chờ hết thời gian nghỉ của model lỗi.
- Khi có nhiều nguồn/model, mỗi vòng thử bị giới hạn **60 giây**. Khi hết thời gian hoặc tất cả nguồn đang nghỉ vì lỗi tạm thời, bot giữ lượt chờ và thử vòng sau theo thời gian nghỉ, nếu `ai_retry_enabled: true`.
- Trạng thái nghỉ nguồn nằm trong RAM; bộ đếm gọi AI cục bộ lưu trên đĩa. Restart không làm mới quota API. Mỗi lần retry/chuyển sang gọi nguồn khác đều tính một lần gọi AI.

</details>

### Giữ câu chờ khi AI quá tải hoặc hết quota

Mặc định **bật** (`ai_retry_enabled: true` trong `config.json`). Chỉ dùng một nhà cung cấp vẫn có cơ chế này: bot thử các model đang bật, rồi giữ lượt chờ nếu gặp lỗi mạng, timeout, HTTP 408/429/5xx hoặc NVIDIA còn xếp hàng. Không cần người nhắn gửi thêm để kích hoạt lại.

Model lỗi được chuyển tiếp ngay; hết một vòng lỗi tạm thời thì chờ tới model sẵn sàng sớm nhất và thử tiếp, tối thiểu **1 giây**, không tăng dần 5–60 giây. Bot vẫn tuân thủ `Retry-After`, reset quota và `minimum_ai_interval_seconds` đã cấu hình. Mặc định khoảng cách gọi cùng model là 6 giây; nếu muốn vòng retry nhanh hơn, giảm trường đó xuống 1 rồi restart. Model lỗi còn chờ khoảng cách riêng được bỏ qua để thử model khác sẵn sàng. Các chat dùng chung trạng thái nghỉ nguồn; khi chờ, bot tắt trạng thái đang nhập và bật lại lúc thực sự tạo phản hồi.

Mỗi request thật vẫn tính vào ngân sách AI. Hết ngân sách cục bộ hoặc giới hạn rep/chat/ngày thì giữ lượt tới ngày mới theo giờ Việt Nam; quota nhà cung cấp dùng thời gian reset của bên đó nếu API có chỉ dẫn. Không tự tăng/reset giới hạn. Lỗi key/quyền/model không tồn tại, HTTP 400, nội dung bị chặn hoặc câu trả lời chạm giới hạn token không được gọi lại vô hạn.

HTTP 200 vẫn có thể chứa phản hồi hỏng. JSON sai cấu trúc, nội dung trống/chỉ có suy luận, thiếu trạng thái hoàn tất và các lỗi Google `MALFORMED_RESPONSE`/`MALFORMED_FUNCTION_CALL`/`OTHER` được chuyển model và giữ lượt để thử lại, mặc định nghỉ 1 giây nếu cả chuỗi lỗi. Không gửi phần nháp đó. Groq/Cloudflare cũng phải trả `finish_reason=stop` mới được gửi; nội dung bị lọc hoặc yêu cầu gọi tool chưa xử lý không được coi là câu trả lời hoàn chỉnh. `check-ai`/`chat-ai` vẫn thử hữu hạn, không chạy vòng retry của bot Messenger.

Tin **đã được nhận khi còn mới** không bị bỏ chỉ vì chờ vượt `max_message_age_seconds`. Tin mới trong cùng chat thay lượt đang chờ bằng ngữ cảnh mới nhất; các lần gọi lỗi không thêm tin nháp vào lịch sử. Bạn tự rep hoặc người nhắn yêu cầu dừng thì hủy lượt chờ và nhường như cũ. Lượt gửi Messenger chưa rõ kết quả vẫn không tự gửi lại để tránh trùng.

Lượt chờ và ảnh đã xử lý hiện nằm **trong RAM của phiên bot**: dừng/restart sẽ xóa lượt chờ, không tự đọc lại lịch sử để phục hồi. `check-ai`, `check-vision` và `chat-ai` vẫn là lệnh thử hữu hạn; `run --dry-run` có thể giữ lượt/gọi lại API nhưng không gửi Messenger. Đặt `ai_retry_enabled: false` rồi restart nếu muốn bỏ lượt sau vòng lỗi như trước.

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

Mã trên chỉ minh họa; thay bằng kết quả thật, có thể là `e2ee:...` hoặc `thread:...`. Không mặc định lấy số trong URL Messenger `/e2ee/t/...` làm mã cho bot. `allowlist` chỉ rep các **chat riêng đã xác định** trong `allowed_threads`; nhóm và loại chưa xác định vẫn bị bỏ qua dù lỡ thêm ID. Để bỏ một mã, xóa nó khỏi danh sách trong `config.json`.

### Xem trước, sau đó gửi thật

Không chạy đồng thời bot, service hoặc `discover` trong cùng thư mục. Nếu service đang chạy, dừng trước khi thử: `systemctl stop messenger-ai` với system service, hoặc thêm `--user` nếu đã cài user service.

```bash
.venv/bin/python -m messenger_ai run --dry-run
```

Nhờ gửi **tin mới** để xem bản nháp. Chế độ này kết nối Messenger và gọi AI nhưng chưa gửi câu trả lời. Nhấn **Ctrl+C**, rồi bật gửi thật:

```bash
.venv/bin/python -m messenger_ai run --live
```

`--live` chỉ áp dụng cho lần chạy hiện tại; `run` không có cờ thì theo `dry_run` trong cấu hình. Dừng bằng **Ctrl+C**. Muốn chạy nền, dừng phiên terminal này rồi làm tiếp mục 6.

## 6. Chạy nền trên VPS

### Đang dùng root trên VPS: cài system service

Dùng mẫu **[deploy/messenger-ai-system.service](deploy/messenger-ai-system.service)** khi đăng nhập bằng root. Mẫu giả định bot ở **`/root/messenger-ai-bot`**; nếu khác đường dẫn, sửa `WorkingDirectory` và `ExecStart`. Sau khi cấu hình, chạy thử và dừng phiên terminal của bot:

```bash
cp deploy/messenger-ai-system.service /etc/systemd/system/messenger-ai.service
systemctl daemon-reload
systemctl enable --now messenger-ai
journalctl -u messenger-ai -f
```

System service chạy cùng hệ thống và tiếp tục sau khi đóng SSH, không cần user bus hoặc lingering. Quản lý bằng `systemctl`/`journalctl` **không có `--user`**.

<details>
<summary>Tài khoản Linux thường: dùng user service nếu đã có user bus</summary>

Mẫu **[deploy/messenger-ai.service](deploy/messenger-ai.service)** dành cho `systemd --user`, giả định repo ở `~/messenger-ai-bot`:

```bash
mkdir -p ~/.config/systemd/user
cp deploy/messenger-ai.service ~/.config/systemd/user/messenger-ai.service
systemctl --user daemon-reload
sudo loginctl enable-linger "$(whoami)"
systemctl --user enable --now messenger-ai
journalctl --user -u messenger-ai -f
```

Lingering cho phép user service tiếp tục chạy sau khi đóng SSH. Nếu `systemctl --user` báo `Failed to connect to bus: No medium found`, phiên hiện tại chưa truy cập được user bus. Với phiên root, dùng phần system service phía trên.

</details>

Cả hai mẫu đều chạy **`run --live`**, tức gửi thật dù `config.json` còn `dry_run: true`. Ctrl+C trong màn hình xem log chỉ dừng xem log; tắt bot bằng `systemctl stop TEN_SERVICE` (thêm `--user` cho user service). Khi chuyển loại service, dừng và bỏ bật tự động của loại cũ trước; không chạy hai service cho cùng thư mục.

Với aaPanel/Supervisor, đặt thư mục làm việc là thư mục repo và lệnh `.venv/bin/python -m messenger_ai run --live`; chỉ dùng một trình quản lý tiến trình.

### Thêm một acc Messenger trên cùng VPS

Mỗi acc dùng một thư mục và service riêng. Ví dụ bot đầu ở `~/messenger-ai-bot`, bản thứ hai ở `~/messenger-ai-bot-2`:

```bash
git clone https://github.com/manh02847/Messenger-AI.git ~/messenger-ai-bot-2
cd ~/messenger-ai-bot-2
python3 setup_bot.py
.venv/bin/python -m messenger_ai configure --copy-ai-from ../messenger-ai-bot
```

Nếu đã tạo bản thứ hai, vào thư mục đó và `git pull --ff-only`, rồi chạy lệnh cấu hình cuối. Lệnh lấy thứ tự nguồn/model, các key AI và giới hạn đầu vào/đầu ra/ngân sách gọi AI. **Chỉ hỏi cookie của acc thứ hai**, bắt buộc nhập mới; không dùng cookie của bản nguồn hoặc nhấn Enter để giữ cookie cũ.

Không sao chép người nhận, phạm vi rep, persona, lịch sử, file khóa hoặc thiết bị E2EE. Bot nguồn được đọc để lấy AI, không bị chỉnh sửa/dừng. Với bản mới, chọn lại phạm vi rồi thử:

```bash
.venv/bin/python -m messenger_ai scope all_private
.venv/bin/python -m messenger_ai check-ai
.venv/bin/python -m messenger_ai run --dry-run
```

Khi đã thử xong, Ctrl+C để dừng xem trước. Dừng cả phiên `run --live` trên terminal nếu còn mở, để tránh trùng tiến trình.

Nếu lần cài user service đầu tiên đã thất bại vì thiếu bus, dọn đúng file nháp và symlink bật tự động của acc thứ hai trước khi cài system service:

```bash
rm -f ~/.config/systemd/user/default.target.wants/messenger-ai-2.service
rm -f ~/.config/systemd/user/messenger-ai-2.service
```

Nếu user service đã chạy thành công trước đó, dừng và disable bằng đúng user manager trước khi chuyển.

Với **phiên root**, tạo system service thứ hai để gửi thật:

```bash
sed 's/messenger-ai-bot/messenger-ai-bot-2/g' deploy/messenger-ai-system.service > /etc/systemd/system/messenger-ai-2.service
systemctl daemon-reload
systemctl enable --now messenger-ai-2
journalctl -u messenger-ai-2 -f
```

Quản lý acc thứ hai bằng `systemctl ... messenger-ai-2`. Nếu dùng tài khoản Linux thường/user service, dùng mẫu user ở trên và đổi đường dẫn sang `messenger-ai-bot-2`.

Mỗi bot có bộ đếm cục bộ riêng, nhưng nếu dùng chung API key thì vẫn dùng chung quota của nhà cung cấp. Không chép cả thư mục `data/` hoặc `secrets.json` giữa hai acc. Nếu hai bot có nhắn nhau, dùng phạm vi `allowlist` loại cuộc chat giữa hai acc để tránh tự rep qua lại.

## 7. Ngữ cảnh, giọng trả lời và nhường bạn rep

### Đọc ảnh trên Messenger

Mặc định **tắt**, cần chọn model có hỗ trợ ảnh. Nhận ảnh mới trong chat thường và E2EE; dùng chung persona đang chọn, ngữ cảnh, phạm vi được rep và cơ chế nhường khi bạn nhắn. Gửi ảnh rồi nhắn câu hỏi ngay sau trong thời gian gom tin sẽ được xử lý cùng lượt. Tin chỉ có ảnh cũng có thể được nhận xét ngắn.

Cập nhật thư viện bằng `python3 setup_bot.py` khi đã dừng bot. Nếu đã có key các nguồn và muốn **tự chuyển model khi quá tải/hết quota**, bật mẫu sau:

```bash
.venv/bin/python -m messenger_ai configure-vision --chain
.venv/bin/python -m messenger_ai check-vision
```

Mẫu ưu tiên theo thứ tự dưới, chỉ thêm nguồn **đang bật và đã có key**, in rõ nguồn bị bỏ qua. Dùng key hiện có, không hỏi lại cookie/key. Mẫu không bật lại nguồn bạn đã tắt bằng `providers`. Model trong mẫu được đặt cố định; bot không tự lấy model từ catalog.

| Thứ tự | Nguồn | Model |
|---|---|---|
| 1 | Google | `gemini-3.8-flash` |
| 2 | Google | `gemini-3.6-flash` |
| 3 | NVIDIA | `google/gemma-4-31b-it` |
| 4 | Groq | `qwen/qwen3.8-27b` |
| 5 | Cloudflare | `@cf/qwen/qwen3.8-27b` |

Bot thử từ trên xuống, dừng ngay khi một model trả lời được. Lỗi mạng, timeout, HTTP 202/408/429/5xx hoặc model/quyền truy cập chưa sẵn sàng sẽ chuyển tiếp. Model lỗi được tạm nghỉ, tôn trọng `Retry-After`; hết thời gian nghỉ thì lại được thử theo thứ tự ưu tiên. Log ghi nguồn lỗi và model thực sự đã đọc ảnh.

Với nhiều model, mỗi vòng chờ tối đa **45 giây**, mỗi model tối đa **10 giây**, riêng NVIDIA **6 giây** để còn thời gian thử nguồn khác. Mỗi model thử một request/vòng. Khi hết thời gian hoặc mọi nguồn đều lỗi/nghỉ tạm thời, giữ ảnh đã xử lý và câu hỏi trong RAM để thử vòng sau theo cơ chế trên. HTTP 400 do cấu hình, nội dung bị chặn hoặc phản hồi hỏng/bị cắt cần xử lý riêng.

Muốn **tự chọn model/thứ tự**, ghi rõ danh sách (tối đa 12 mục, không trùng); ví dụ:

```bash
.venv/bin/python -m messenger_ai configure-vision --chain \
  google:gemini-3.8-flash \
  groq:qwen/qwen3.8-27b \
  nvidia:google/gemma-4-31b-it
```

Danh sách tự chọn yêu cầu đủ key tương ứng và bật các nguồn được nêu, theo cờ chung cho cả chữ/ảnh; thiếu key sẽ báo lỗi trước khi lưu. Chuyển về **một model ảnh** bằng lệnh cũ; ví dụ NVIDIA:

```bash
.venv/bin/python -m messenger_ai configure-vision nvidia --model google/gemma-4-31b-it
```

Khi cấu hình một nguồn, ở dòng API key nhấn Enter để dùng key hiện có. Chế độ này giữ deadline **30 giây/lượt**. `configure-vision` không gọi API hay đổi danh sách model chữ; nguồn được chọn sẽ được bật bằng cờ chung, nên các model chữ đã lưu của nguồn đó cũng có thể chạy. Cấu hình một nguồn trước đây vẫn chạy như cũ sau `git pull`, chỉ xoay nhiều model khi bạn bật `--chain`.

`check-vision` gửi một ô màu đỏ tạo tại máy qua chuỗi, in model trả lời thực tế và thời gian; thành công chỉ chứng minh một model đã trả lời. Để thử **riêng tất cả model** dù model đầu đã chạy được:

```bash
.venv/bin/python -m messenger_ai check-vision --all
```

Mỗi model trong `--all` dùng một lượt gọi thử, có thể chờ đến 30 giây/model. Nếu có model lỗi, lệnh vẫn thử các model còn lại rồi báo tổng số lỗi; model nhận sai màu cần bạn tự đối chiếu. Hai chế độ dùng bộ đếm thử `ai-check.sqlite3`, không đăng nhập/gửi Messenger. Khởi động lại bot sau khi cấu hình xong.

Có thể thay `nvidia` bằng `google`, `groq` hoặc `cloudflare` và nhập mã model thị giác tương ứng. Google cho nhập mã API thủ công, không giới hạn vào mẫu; NVIDIA cho nhập dạng `hãng/model`. Tên đúng định dạng chưa chứng minh model hỗ trợ ảnh hoặc key có quyền truy cập, nên luôn chạy `check-vision`. Nếu cần, xem [NVIDIA Gemma 4](https://docs.api.nvidia.com/nim/reference/google-gemma-4-31b-it-infer), [Google đọc ảnh](https://ai.google.dev/gemini-api/docs/generate-content/image-understanding), [Groq Vision](https://console.groq.com/docs/vision) và [Cloudflare OpenAI-compatible API](https://developers.cloudflare.com/workers-ai/configuration/open-ai-compatibility/).

Lượt có ảnh gọi thẳng model thị giác để tạo câu trả lời, không gọi thêm model chữ để viết lại. **Mỗi request khi chuyển model đều tính một lượt gọi AI**, dùng chung ngân sách live với tin chữ; có tin mới làm bỏ bản nháp rồi tạo lại thì vẫn tốn lượt cho request đã gọi. Các model được thử nhận cùng ảnh đã xử lý, persona và ngữ cảnh. Ảnh dùng thêm token đầu vào theo nhà cung cấp, không nằm trong 3500 ký tự lịch sử chữ.

- Tối đa **hai ảnh gần nhất** trong một lượt gom tin; mỗi ảnh tối đa **8 MiB**, **20 triệu pixel**. Hỗ trợ JPG/PNG/WebP tĩnh, thu nhỏ cạnh dài tối đa **1600 px**, chuyển JPEG và bỏ metadata trước khi gửi tới AI. Chữ quá nhỏ/mờ có thể đọc sai.
- Ảnh được gửi tới các nguồn thị giác trong danh sách đã chọn theo thứ tự cần thử. Khi lỗi tải/định dạng, bot báo chưa đọc được ảnh; lỗi API khả dụng thì thử model ảnh tiếp theo. Nếu tất cả lỗi tạm thời, giữ lượt/ảnh trong RAM để thử lại, không tải ảnh lại ở mỗi lần gọi AI.
- Bộ tải chỉ lấy URL ảnh từ host Meta được phép; ảnh E2EE tải và giải mã qua bridge đang có. Bridge dùng file tạm riêng khi giải mã và tự dọn. Bot không lưu URL ký, khóa giải mã hoặc dữ liệu ảnh trong SQLite; chỉ lưu dấu có ảnh và phần trả lời bằng chữ làm ngữ cảnh.
- Metadata kích thước ảnh E2EE có thể thiếu hoặc không chính xác. Bot dùng giới hạn tải cứng 8 MiB cho bridge và kiểm tra SHA-256 của dữ liệu nhận được, không bắt số byte phải bằng metadata. Khi tải/xử lý thất bại, log có mã lỗi cố định để phân biệt thiếu dữ liệu, lỗi HTTP, giải mã, timeout và thư viện ảnh; không in nguyên lỗi máy chủ chứa URL ký/khóa.
- Sau khi trả lời, bot không giữ ảnh gốc cho các lượt tiếp theo. Nếu cần xem lại chi tiết, gửi lại ảnh kèm câu hỏi. Ảnh trích dẫn từ tin cũ, sticker/GIF động, video, file và ghi âm chưa được đọc.
- Khi đọc ảnh đang tắt, tin chỉ có ảnh được bỏ qua; tin có chú thích vẫn xử lý phần chữ và đánh dấu ảnh chưa được cung cấp. `run --dry-run` có thể tải ảnh/gọi AI nếu đã bật, nhưng không gửi tin hay phát trạng thái đang nhập.

Tắt đọc ảnh và giữ các key/model chữ:

```bash
.venv/bin/python -m messenger_ai configure-vision --disable
```

Mỗi acc có cấu hình riêng; thực hiện trong đúng thư mục bot. Sau đó khởi động lại đúng service.

### Trạng thái đang nhập

Khi chạy gửi thật, bot báo **đang nhập** lúc AI bắt đầu soạn và làm mới khoảng **4 giây/lần** trong lúc chờ, kể cả khi chuyển nguồn AI. Bot gửi tín hiệu tắt khi gửi xong, gặp lỗi, dừng hoặc bạn tự nhắn/yêu cầu nhường. Hỗ trợ cả chat thường và E2EE qua kết nối hiện có.

`run --dry-run`, `check-ai` và `chat-ai` không phát trạng thái này. Tín hiệu đang nhập không gọi thêm AI, không tốn token; nếu cập nhật trạng thái lỗi, bot vẫn tiếp tục xử lý câu trả lời. Việc nhìn thấy dấu đang nhập phụ thuộc Messenger phía người nhận.

### Bot nhớ những gì?

- Mỗi cuộc trò chuyện có lịch sử riêng, gồm tin người kia và câu trả lời của bot; tin bạn tự nhắn cũng được lưu làm ngữ cảnh.
- Mặc định giữ tối đa **12 tin tổng hai phía**; mỗi lượt lấy tối đa **3500 ký tự lịch sử**, cộng persona đang dùng. Mỗi tin đầu vào được giới hạn **1200 ký tự**.
- Ưu tiên các tin gần nhất còn nguyên nội dung; bỏ câu trả lời đầu ngữ cảnh nếu câu hỏi tương ứng đã bị loại. Không lấy riêng phần đuôi của tin cũ chỉ để lấp đủ giới hạn. Nếu riêng tin mới nhất vượt ngân sách lịch sử, chỉ lấy phần đầu của tin đó.
- Nếu hai tin liên tiếp trong một chat cách nhau **từ 1 giờ**, lượt tiếp theo bắt đầu ngữ cảnh mới. Điều chỉnh `history_idle_seconds` trong `config.json`; đặt `0` để tắt. Quy tắc cũng áp dụng sau restart và cho `chat-ai`. Dữ liệu cũ vẫn được giữ theo giới hạn lưu trữ, nhưng không gửi qua ranh giới này.
- Tin cũ được bỏ dần theo giới hạn, nên ngữ cảnh không phình vô hạn. Bot không đọc lại toàn bộ lịch sử Messenger và không reset trắng sau mỗi lần API hết quota.
- Lịch sử bot nằm trong `data/`; dữ liệu quá hạn mặc định **7 ngày** được dọn khi khởi động. `chat-ai` là cuộc trò chuyện thử riêng trong RAM.
- Khi một lượt đã kết thúc, bot giải phóng đối tượng tin nhắn/ảnh, task và bộ đếm sửa đổi của chat khỏi RAM. Lịch sử, chống gửi trùng và thời gian nhường trong SQLite vẫn được giữ theo quy tắc ở trên.

Mỗi request kèm một hướng dẫn ngắn để đối chiếu persona, phân biệt chủ tài khoản với người nhắn và không coi câu trả lời cũ của bot là sự thật đã xác minh. Hướng dẫn áp dụng cả khi có `persona.local.txt`, thêm một ít token đầu vào; không gọi AI riêng để tóm tắt hoặc đánh giá lịch sử. Đây là hướng dẫn cho model, không bảo đảm mọi câu trả lời đều đúng.

### Reset ngữ cảnh của một cuộc trò chuyện

Khi bot cứ lặp lại cách hiểu sai, có thể xóa riêng ngữ cảnh chat đó. Dùng mã đã lấy từ `discover`, thay `e2ee:222@msgr` trong ví dụ bằng mã thật; không dùng trực tiếp số trên thanh địa chỉ Messenger.

Dừng bot trong đúng thư mục trước, rồi chạy lệnh reset và bật lại. Ví dụ với system service:

```bash
systemctl stop messenger-ai
.venv/bin/python -m messenger_ai reset-context "e2ee:222@msgr"
systemctl start messenger-ai
```

Với acc thứ hai, chạy trong `~/messenger-ai-bot-2` và thay tên service thành `messenger-ai-2`. Nếu dùng user service, thêm `--user` vào lệnh `systemctl`. Nếu chạy trực tiếp, dừng bằng `Ctrl+C`, reset rồi chạy lại `run --live`.

Lệnh chỉ xóa các tin làm ngữ cảnh trong chat đã chọn. Dữ liệu chống gửi trùng, outbox, thời gian nhường, quota, persona và các chat khác được giữ; không xóa tin trên Messenger. Nếu bot/discover còn chạy trong thư mục, lệnh từ chối để tránh gửi bản nháp từ ngữ cảnh cũ. Chế độ xem trước dùng dữ liệu riêng:

```bash
.venv/bin/python -m messenger_ai reset-context "e2ee:222@msgr" --preview
```

Trong `chat-ai`, dùng `/reset` để xóa ngữ cảnh thử trong RAM. Sửa persona vẫn cần khởi động lại bot để đọc bản mới.

### Khi bạn nhắn thủ công

Bot nhường **300 giây (5 phút)** trong cuộc trò chuyện đó, tính lại từ tin thủ công mới nhất. Bản nháp đang soạn bị bỏ khi nhận được tin bạn nhắn. Hết thời gian nhường, bot chỉ rep khi có **tin mới tiếp theo**, không trả lời bù các tin đã bỏ qua.

Một số yêu cầu rõ ràng như “Mạnh tự rep đi” hoặc “Đừng trả lời nữa” cũng kích hoạt nhường; đây là nhận diện theo mẫu, không hiểu mọi cách diễn đạt. AI không tự dừng cuộc trò chuyện chỉ bằng mã `[[HANDOFF]]`.

Bot gom các tin đến sát nhau trong **2,5 giây**. Khi có thêm tin trong lúc AI đang soạn, bản nháp cũ được bỏ để xử lý ngữ cảnh mới. Nếu yêu cầu gửi đã ra mạng thì không bảo đảm thu hồi kịp. Lượt gửi không rõ thành công được ghi nhận và tạm dừng chat, không tự gửi lại.

### Chỉnh cách nói, bỏ icon

**[persona.txt](persona.txt)** là mẫu chung công khai, không chứa hồ sơ cá nhân. Bản rút gọn khoảng **3.100 ký tự**, giữ cách nói tự nhiên, không icon, hiểu ngữ cảnh/lỗi gõ, không bịa hay nhận lời thay chủ tài khoản.

Muốn tùy chỉnh tên, xưng hô hoặc thông tin riêng, tạo **`persona.local.txt` ngay trên máy chạy bot**. Trên Linux:

```bash
cp -n persona.txt persona.local.txt
chmod 600 persona.local.txt
nano persona.local.txt
```

`cp -n` giữ nguyên file riêng nếu đã có. Khi file này tồn tại, bot dùng **toàn bộ nội dung của nó thay cho** `persona.txt`; không nối hai bản. Quy tắc này áp dụng cho `run` (cả chữ/ảnh), `check-ai`, `check-nvidia`, `check-vision` và `chat-ai`. File riêng rỗng/không đọc được sẽ báo lỗi để sửa, không âm thầm dùng mẫu chung. Bỏ file riêng nếu muốn quay lại mẫu chung.

Git bỏ qua `persona.local.txt`, nên chỉnh riêng không gây xung đột khi pull và không được thêm bằng `git add` thông thường. Persona đang dùng vẫn được gửi tới nhà cung cấp AI mỗi lượt; giới hạn lịch sử không cắt ngắn persona. Không đưa mật khẩu, cookie hoặc API key vào prompt.

Xóa thông tin khỏi bản hiện tại **không xóa các commit cũ**. Nội dung đã từng công khai vẫn có thể còn trong lịch sử Git hoặc các bản sao.

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
| `provider_enabled` | Chỉ Groq bật | Cờ true/false cho từng nguồn, dùng chung cho chữ và ảnh |
| `text_models` | `["groq:openai/gpt-oss-120b"]` | Danh sách model chữ theo thứ tự; bỏ qua nguồn tắt |
| `vision_models` | `[]` | Danh sách model ảnh theo thứ tự; rỗng là tắt ảnh; bỏ qua nguồn tắt |
| `reply_prefix` | `""` | Tiền tố thêm trước câu trả lời |
| `debounce_seconds` | `2.5` | Thời gian gom tin đến liên tiếp |
| `reply_cooldown_seconds` | `8` | Khoảng cách tối thiểu giữa hai lượt gửi cùng chat |
| `manual_pause_seconds` | `300` | Thời gian nhường khi bạn tự nhắn/yêu cầu dừng hoặc gửi chưa rõ kết quả |
| `max_message_age_seconds` | `120` | Lọc tuổi tin khi mới nhận; lượt đã nhận được giữ khi bật retry |
| `history_messages` | `12` | Số tin tối đa trong ngữ cảnh, tổng hai phía |
| `history_char_limit` | `3500` | Tổng ký tự lịch sử lấy cho mỗi lượt |
| `history_idle_seconds` | `3600` | Bắt đầu ngữ cảnh mới khi hai tin cách nhau từ mức này; `0` tắt |
| `input_char_limit` | `1200` | Giới hạn ký tự mỗi tin đưa vào ngữ cảnh |
| `output_char_limit` | `4000` | Giới hạn ký tự câu trả lời, chưa tính tiền tố |
| `max_completion_tokens` | `4096` | Ngân sách token cho một lần tạo phản hồi; có thể gồm suy luận |
| `max_ai_calls_per_day` | `150` | Tổng lần gọi AI/ngày, tính cả retry và chuyển nguồn |
| `ai_retry_enabled` | `true` | Giữ lượt chờ và thử lại khi AI lỗi tạm thời; tắt nếu muốn bỏ lượt lỗi |
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
| `Unit messenger-ai.service not loaded` | Kiểm tra đã cài system hay user service rồi dùng đúng lệnh; system service không có `--user`. Chưa cài thì làm mục 6 |
| `Failed to connect to bus: No medium found` | Lệnh `--user` chưa truy cập được user bus. Với root trên VPS, dùng mẫu system service ở mục 6 |
| `Đang có một bot/discover chạy trong thư mục này` | Dừng service hoặc phiên terminal cũ rồi chạy lại. Không xóa `data/bot.lock` để ép chạy hai phiên |
| `allowed_threads đang rỗng` | Dùng `scope all_private`, hoặc `discover` rồi `allow` mã đã xác minh |
| Thiếu key Groq khi cài acc thứ hai | Chạy `configure --copy-ai-from ../messenger-ai-bot` để dùng lại AI, nhập cookie riêng; hoặc `configure --provider cloudflare` nếu chọn Cloudflare |
| Không có `config.json` sau khi cấu hình lỗi | Chạy `configure` thành công trước khi dùng `scope`, `check-ai` hoặc bật service |
| `FACEBOOK_COOKIE` đang ghi đè acc mới | Gỡ cookie acc khác khỏi biến môi trường/session/service; nếu dùng shell Linux có thể `unset FACEBOOK_COOKIE` rồi cấu hình lại |
| Có nhận tin nhưng không rep | Kiểm tra `--live`, phạm vi rep, thời gian nhường, tin có văn bản và còn quota. Bot chỉ xử lý tin mới |
| `check-ai` thành công nhưng không phải nguồn muốn thử | Đọc nguồn/model in ra; lệnh có fallback. NVIDIA có `check-nvidia` để thử riêng |
| Gửi ảnh mà bot không nhận | Bật `configure-vision`, chạy `check-vision`, khởi động lại đúng bot; ảnh chỉ có trước khi bật không được đọc bù |
| Bot báo chưa đọc được ảnh | Xem mã lỗi của bộ tải trong log theo hướng dẫn dưới; chưa thể kết luận là lỗi định dạng hay model |
| Nguồn chữ còn dùng được nhưng đọc ảnh lỗi | Thử `check-vision --all` để tìm model ảnh lỗi; bật `configure-vision --chain` để dự phòng nhiều nguồn |
| NVIDIA HTTP 401/403 / `Authorization failed` | Kiểm tra key, tài khoản và quyền gọi model. Đọc được danh sách model chưa chứng minh có quyền inference |
| Google HTTP 500/503 | Trong chuỗi, chuyển ngay sang model kế; hết vòng lỗi tạm thời thì giữ câu và thử lại khi bật `ai_retry_enabled`. Không tăng dần backoff |
| HTTP 429 | Chạm giới hạn API hoặc tần suất. Xem quota/dashboard và thời gian chờ; restart không cấp thêm quota |
| Hết ngân sách gọi AI cục bộ | Kiểm tra `max_ai_calls_per_day`; retry cũng được tính. Tăng nếu phù hợp, quota API vẫn áp dụng |
| `Câu trả lời chạm max_completion_tokens` | Là giới hạn của một lần tạo phản hồi. Dùng `tune-chat` nếu cấu hình cũ thấp; không đồng nghĩa hết quota ngày |
| Tất cả nguồn đang lỗi/nghỉ | Bật ai_retry_enabled để giữ lượt và tự thử lại; xem thời gian nghỉ trong log. Key/cấu hình sai cần sửa trước |
| Cookie/phiên Facebook hết hạn hoặc checkpoint | Đăng nhập Facebook bình thường, xử lý xác minh rồi nhập cookie mới bằng `configure` |
| Bridge lỗi checksum/phiên bản | Dừng bot, chạy `doctor`; tải lại tài sản đã ghim qua `setup_bot.py`, không dùng binary không khớp checksum |
| Git không cho pull vì có sửa cục bộ | Lưu lại và xử lý thay đổi của bạn trước; không reset xóa cấu hình/persona đang cần |

Nếu đọc ảnh lỗi, gửi một ảnh mới rồi lấy riêng dòng log đã ẩn dữ liệu riêng tư (system service acc 1):

```bash
journalctl -u messenger-ai -n 80 --no-pager | grep -F 'Không tải/xử lý được ảnh:'
```

Acc 2 thay tên unit bằng `messenger-ai-2`; user service thêm `--user` vào `journalctl`.

| Mã lỗi ảnh | Ý nghĩa / bước tiếp |
|---|---|
| `IMAGE_DECODER_MISSING` | Chạy lại `python3 setup_bot.py` trong đúng thư mục rồi restart |
| `E2EE_PATH_MISSING`, `E2EE_KEY_INVALID`, `E2EE_HASH_INVALID` | Sự kiện bridge thiếu metadata cần tải/giải mã; giữ mã lỗi để kiểm tra bridge, chưa liên quan model |
| `E2EE_NOT_READY`, `E2EE_SESSION_FAILED` | Kết nối/phiên tải media E2EE chưa sẵn sàng; thử kết nối lại đúng bot và gửi ảnh mới |
| `MEDIA_HTTP_403`, `MEDIA_HTTP_404`, `MEDIA_HTTP_410` | Máy chủ từ chối/không còn ảnh; thử gửi ảnh mới, kiểm tra kết nối media nếu lặp lại |
| `MEDIA_TIMEOUT`, `MEDIA_NETWORK_FAILED` | Kiểm tra kết nối VPS tới máy chủ ảnh |
| `E2EE_HASH_MISMATCH`, `E2EE_DECRYPT_FAILED` | Không xác minh/giải mã được dữ liệu; bot không đưa ảnh đó cho AI |
| `IMAGE_DECODE_FAILED`, `IMAGE_FORMAT_UNSUPPORTED`, `IMAGE_PIXEL_LIMIT`, `IMAGE_TOO_LARGE` | Kiểm tra dữ liệu/định dạng và giới hạn ảnh |

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
- Chỉ xử lý tin mới nhận khi chạy; ảnh cần bật nguồn thị giác riêng. Sticker, video, file và ghi âm chưa được AI đọc. Không bảo đảm nhận đủ tin trong lúc mất mạng.
- Nội dung cùng một phần lịch sử được gửi tới nhà cung cấp AI được thử. `data/` chứa lịch sử và trạng thái/khóa thiết bị E2EE, chưa mã hóa ở tầng ứng dụng; bảo vệ máy chạy và không chia sẻ thư mục này. Không chạy hai máy dùng chung bản sao thiết bị E2EE.
- Hạn mức, model và điều kiện sử dụng phụ thuộc từng dịch vụ; xem dashboard/tài liệu hiện hành, không coi free tier là không giới hạn.

Tài liệu dự án: [rà soát dự án và các việc còn nên bổ sung](REVIEW.md), [kết quả kiểm tra và phạm vi xác minh](VALIDATION.md), [thành phần bên thứ ba](THIRD_PARTY.md), [system service cho root](deploy/messenger-ai-system.service), [user service](deploy/messenger-ai.service).

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
