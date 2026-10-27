# Thử Gemini Live trong cuộc gọi Messenger

**Đây là bản thử. Chưa xác minh cuộc gọi Messenger thật hoặc tiện ích trong Chrome thật ở môi trường phát triển.** Relay đã gọi Google thật thành công bằng âm thanh mẫu; các kiểm thử mô phỏng kiểm tra đường âm thanh và thao tác trả micro. Bước còn lại là thử tiện ích trên máy đang mở Facebook của bạn.

Bạn tự gọi/nhận cuộc gọi trong Chrome, rồi bấm **Bật AI cho cuộc gọi này**. Tiện ích lấy tiếng người bên kia, gửi qua relay đến Gemini Live và dùng tiếng AI thay micro của bạn. Bấm **Dừng AI** để trở lại nói bằng micro. Tiện ích không tự nhận cuộc gọi hoặc gọi cho ai.

Từ **0.1.1**, có thể mở tiện ích ở tab Facebook chính: nó tự tìm cuộc gọi đã kết nối trong các tab/cửa sổ Facebook và Messenger, kể cả cửa sổ gọi riêng. Chỉ bật khi tìm thấy đúng một cuộc gọi; nếu có nhiều cuộc gọi hoặc nhiều kết nối âm thanh thì báo để bạn xử lý trước. Việc tìm chỉ chạy khi bấm Bật AI, không gửi âm thanh hay mở Google trong bước tìm.

## 1. Chạy relay trên VPS

Dùng thư mục bot đã có key Google, ví dụ acc 2:

```bash
cd ~/messenger-ai-bot-2
git pull --ff-only
.venv/bin/python -m pip install -r requirements-call-lab.txt
.venv/bin/python -m messenger_ai call-lab
```

Nếu dùng thư mục acc 1, thay dòng đầu bằng `cd ~/messenger-ai-bot`. Chỉ chạy **một relay** trên cổng 8765; thư mục này cung cấp key Google, không quyết định tài khoản Facebook đang gọi. Facebook dùng tài khoản đang đăng nhập trong Chrome.

Giữ terminal này mở. Lệnh in ra:

```text
Địa chỉ trong tiện ích: ws://127.0.0.1:8765
Mã kết nối riêng cho lần chạy này: ...
```

Copy **mã kết nối** để dán vào tiện ích. Mã đổi khi chạy lại relay; đây không phải Google API key.

Relay đọc `GEMINI_API_KEY` hoặc `google_api_key` trong `secrets.json` của thư mục bot. Nếu báo thiếu key, chạy `.venv/bin/python -m messenger_ai configure-ai google --edit-key` để cấu hình Google trước. Relay không đọc persona, lịch sử Messenger hay cookie Facebook; phiên thử dùng lời hướng dẫn AI riêng, có câu mở đầu tự giới thiệu là trợ lý AI.

Relay chạy riêng với service trả lời tin nhắn, không cần dừng hoặc restart `messenger-ai`/`messenger-ai-2` để bật gọi thử. Nó chỉ nghe trên `127.0.0.1`; **không cần mở cổng 8765 trên firewall VPS**.

## 2. Nối máy Windows với VPS

Trên **máy Windows đang mở Chrome**, mở thêm PowerShell/terminal và dùng cùng tài khoản, IP, key SSH bạn vẫn dùng để vào VPS, thêm chuyển tiếp cổng:

```powershell
ssh -N -L 8765:127.0.0.1:8765 USER_SSH@IP_VPS
```

Thay `USER_SSH` và `IP_VPS` bằng thông tin thật. Nếu bình thường dùng file `.pem`, giữ tham số đó, ví dụ:

```powershell
ssh -i "C:\duong-dan\key.pem" -N -L 8765:127.0.0.1:8765 USER_SSH@IP_VPS
```

Giữ cửa sổ này mở; kết nối thành công thường không in gì. Prompt `root@...` trên VPS không có nghĩa tài khoản SSH phải là root; dùng tài khoản SSH thực tế của bạn.

Nếu relay và Chrome cùng một máy thì bỏ bước SSH tunnel.

## 3. Cài tiện ích trên Chrome máy tính

1. Mở [repo Messenger-AI](https://github.com/manh02847/Messenger-AI), chọn **Code → Download ZIP**, giải nén trên máy Windows. Nếu đã clone repo trên máy này thì cập nhật bản đó.
2. Vào `chrome://extensions`, bật **Developer mode / Chế độ dành cho nhà phát triển**.
3. Chọn **Load unpacked / Tải tiện ích đã giải nén** và chọn đúng thư mục `Messenger-AI-main/experimental/call-lab-extension` có file `manifest.json`.
4. Ghim tiện ích **Messenger AI — Call Lab** để dễ mở.
5. **Kết thúc cuộc gọi cũ, tải lại trang Facebook/Messenger rồi gọi lại.** Tiện ích cần được nạp trước khi trang tạo kết nối cuộc gọi.

Nếu đang dùng **0.1.0**: tải ZIP mới trên **máy Windows**, thay các file trong thư mục tiện ích cũ, vào `chrome://extensions` bấm **Reload / Tải lại** của Messenger AI — Call Lab và kiểm tra phiên bản **0.1.1**. Nếu giải nén sang thư mục mới, dùng Load unpacked chọn thư mục mới và tắt bản cũ để chỉ giữ một bản đang bật. Sau đó kết thúc cửa sổ gọi cũ, reload Facebook và gọi lại. Cập nhật file trên VPS không cập nhật thư mục tiện ích đã cài trên Windows.

Cho phép quyền truy cập các trang Facebook/Messenger nếu Chrome hỏi sau cập nhật. Quyền host được giới hạn ở các domain đã hỗ trợ để tìm cửa sổ gọi; không cần quyền đọc toàn bộ tab hoặc cookie. [Tài liệu quyền tab của Chrome](https://developer.chrome.com/docs/extensions/reference/api/tabs#permissions).

Không dán Google API key hay cookie vào tiện ích. API key nằm ở VPS; tiện ích chỉ cần mã kết nối của relay. Mã này được giữ trong bộ nhớ phiên của Chrome, không lưu bằng `storage.local` hoặc đưa vào mã trang Facebook.

## 4. Thử cuộc gọi

1. Dùng tài khoản thử, tự gọi/nhận một cuộc gọi thoại thông thường bằng Chrome.
2. Bấm vào trang cuộc gọi để trình duyệt cho phép phát âm thanh.
3. Mở tiện ích ngay ở **tab Facebook chính** hoặc trang gọi. Bản 0.1.1 tự tìm cửa sổ đang có cuộc gọi đã kết nối.
4. Giữ địa chỉ `ws://127.0.0.1:8765`, dán **mã kết nối** từ bước 1, rồi bấm **Bật AI cho cuộc gọi này**.
5. Chờ trạng thái “AI đang nghe và nói…”. Người bên kia sẽ nghe lời giới thiệu AI rồi có thể nói chuyện. Kết nối Google lần đầu có thể mất nhiều giây.
6. Bấm **Dừng AI** để lấy lại micro. `Ctrl+C` ở VPS dừng relay; đóng tunnel cũng ngắt phiên. Nếu micro chưa hoạt động lại, kết thúc rồi gọi lại.

Mục **Nghe giọng AI trên máy này** giúp bạn nghe phần AI trả lời; có thể bỏ chọn trước khi bật. Dùng tai nghe khi thử để hạn chế tiếng vọng. Trong lúc AI hoạt động, dùng nút **Dừng AI** để tiếp quản; nút tắt micro của Facebook có thể vẫn điều khiển track micro cũ.

Khi bật, tiếng người gọi được gửi đến **Google Gemini API**. Phần mềm không ghi âm hoặc lưu bản chép lời vào file. Phiên mới mở lại ngữ cảnh mới, không dùng ngữ cảnh của bot trả lời tin nhắn.

## Model và thời gian thử

Mặc định: `gemini-3.8-live`, tối đa **180 giây mỗi phiên**, tính cả thời gian kết nối. Có thể thử model khác bằng cách dừng relay rồi chạy:

```bash
.venv/bin/python -m messenger_ai call-lab --model gemini-3.1-flash-live-preview
```

Hoặc:

```bash
.venv/bin/python -m messenger_ai call-lab --model gemini-2.5-flash-native-audio-latest --max-seconds 300
```

`--max-seconds` nhận từ 15 đến 900 giây. Không tự xoay model hoặc nối lại cuộc gọi khi lỗi: tiện ích dừng AI và khôi phục micro; bạn chủ động bật lại. Không dùng Extended Thinking trong mẫu vì thử nghiệm trước có lượt không hoàn thành được câu trả lời.

Live gọi API trực tiếp, dùng quota của project Google và **không qua bộ đếm ngày của bot text**. Có quota hiển thị không đồng nghĩa miễn phí/vô hạn; kiểm tra tier và hạn mức project của bạn. Phiên thử không bật Search, không gửi cấu hình suy luận của bot text và không đọc `persona.local.txt`.

## Nếu chưa chạy được

| Hiện tượng | Cách kiểm tra |
|---|---|
| “Chưa thấy cuộc gọi” | Kiểm tra tiện ích là 0.1.1, cho phép truy cập Facebook/Messenger, kết thúc cửa sổ gọi cũ và reload Facebook rồi gọi lại; đợi bên kia nhận để cuộc gọi kết nối. Có thể mở tiện ích ở tab Facebook chính. Nếu vẫn lỗi, có thể Facebook dùng frame/worker hoặc cơ chế WebRTC bản thử chưa bắt được. |
| “Chưa gắn được tiện ích vào cửa sổ gọi” | Cập nhật/reload tiện ích, kết thúc cửa sổ gọi cũ, reload Facebook rồi mở cuộc gọi mới. |
| “Có nhiều cuộc gọi hoặc luồng âm thanh” | Chỉ giữ một cuộc gọi thoại trong tất cả cửa sổ Facebook/Messenger. Bản thử cần đúng một kết nối WebRTC với một track gửi và một track nhận âm thanh. |
| “Không vào được relay” | Giữ lệnh `call-lab` và SSH tunnel chạy; tunnel phải mở trên máy đang chạy Chrome. Kiểm tra cùng cổng 8765. |
| “Mã kết nối chưa đúng” | Copy lại mã từ lần chạy relay hiện tại. Không dùng API key Google. |
| Google chưa chấp nhận/ngắt phiên | Kiểm tra key có quyền dùng model Live, quota, mạng VPS; thử một model trong danh sách ở trên. |
| Lỗi cho phép âm thanh | Bấm vào trang cuộc gọi, rồi bật lại AI. |
| Hết thời gian hoặc mất mạng | AI dừng; kiểm tra micro rồi bấm bật lại nếu muốn mở phiên mới. |
| Đã bật nhưng bên kia không nghe | Kiểm tra trạng thái cuộc gọi, nút tắt tiếng và quyền âm thanh; bấm Dừng AI trước. Nếu vẫn lỗi, kết thúc và gọi lại. |

Bản thử chỉ hỗ trợ Chrome máy tính với cuộc gọi đã nhận thủ công, một cặp track âm thanh ở trang chính. Chưa có tự nhận cuộc gọi, cuộc gọi nhóm, điện thoại, gửi video hoặc tích hợp trực tiếp với service Messenger. Facebook có thể đổi cách tạo kết nối khiến tiện ích không thấy cuộc gọi.

## Phạm vi kiểm chứng

- Python relay: xác thực Origin/mã kết nối, một phiên đồng thời, gate trước khi bật âm thanh, PCM hai chiều, ngắt lời, timeout, đóng kết nối, lọc suy luận/bản chép lời và thông báo lỗi không lộ key.
- Node: 25 ca kiểm tra mã PCM, resampling, lấy track người gọi, trả micro, bấm Dừng lúc khởi tạo, bấm Bật hai lần, sự kiện muộn từ phiên cũ và tìm cuộc gọi ở cửa sổ riêng. Kiểm tra nhiều cuộc gọi bị từ chối, tab cũ lỗi không che cuộc gọi hợp lệ, tab ngoài domain không được hỏi và hủy lúc đang tìm không mở relay. Đây là mô phỏng API trình duyệt.
- Google thật qua relay: Gemini 3.8 Live nhận 48 khung âm thanh mẫu và trả âm thanh; không dùng dữ liệu người gọi, persona hoặc cookie thật.
- Có fixture Chromium/WebRTC dùng hai trang và tiếng mẫu, nhưng **chưa chạy được ở môi trường phát triển** vì runtime chặn socket IPC của Chrome (`Operation not permitted`). Chưa xác nhận giao diện tiện ích, WebRTC trong Chrome thật hoặc cuộc gọi Facebook thật.

Nếu máy phát triển có Node, Playwright và Chromium hỗ trợ tiện ích, có thể chạy fixture cục bộ (không đăng nhập/gọi Facebook và không gọi Google):

```bash
CALL_LAB_CHROME=/duong/dan/chromium .venv/bin/python -m pytest -q tests/test_call_lab_browser.py
```

Nếu Node không tìm thấy Playwright, đặt `NODE_PATH` tới thư mục `node_modules` đã cài Playwright. Dùng Chromium hỗ trợ nạp tiện ích qua tham số khởi chạy; Chrome/Edge thương mại có thể không hỗ trợ cách nạp này.

Tham khảo: [Gemini Live API](https://ai.google.dev/gemini-api/docs/live-api), [Chrome content scripts](https://developer.chrome.com/docs/extensions/develop/concepts/content-scripts), [WebSocket trong service worker](https://developer.chrome.com/docs/extensions/how-to/web-platform/websockets), [Playwright extensions](https://playwright.dev/docs/chrome-extensions).
