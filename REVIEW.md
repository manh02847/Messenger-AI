# Rà soát dự án — 26/10/2026

Rà soát từ bản `08b8535`, tập trung vào nhận/gửi tin, phạm vi chat, người dùng
nhắn thủ công, ngữ cảnh, chọn model/Search/thinking, xử lý lỗi, ảnh, lưu trạng
thái, cấu hình và hướng dẫn triển khai. Kết quả dưới đây phân biệt lỗi đã sửa
với phần còn nên phát triển; không phải chứng nhận toàn bộ hệ thống an toàn
hoặc luôn kết nối được Messenger.

## Lỗi đã sửa trong đợt này

| Mức | Lỗi trước sửa | Hành vi sau sửa |
|---|---|---|
| Cao | HTTP 200 nhưng JSON hỏng, nội dung trống/chỉ có suy luận hoặc Google `MALFORMED_RESPONSE` làm dừng cả lượt, không xoay model | Phân loại lỗi phản hồi tạm thời, xoay ngay model tiếp theo; hết chuỗi thì bot giữ lượt và retry theo giới hạn hiện có |
| Cao | Groq/Cloudflare chữ có thể nhận nội dung từ phản hồi có `finish_reason` khác `stop` | Mọi nguồn tương thích đều kiểm tra trạng thái hoàn tất; không gửi nội dung lọc/tool call/bản bị cắt |
| Cao | `allowlist` chỉ kiểm tra ID, có thể cho nhóm hoặc loại chat chưa xác định đi qua | Chặn trước khi lưu lịch sử, tải ảnh hoặc gọi AI ở cả hai chế độ phạm vi |
| Vừa | Auto trên Gemma bỏ sót bài toán không có từ khóa/câu không dấu; câu “thế à” kế tiếp vẫn thừa hưởng mức cao | Xét câu mới trước, nhận thêm dữ kiện số và câu không dấu, chỉ mang độ khó từ ngữ cảnh sang câu hỏi tiếp phù hợp |
| Vừa | Gemini auto giữ mức trung bình ngay cả với lời chào/cảm thán rõ ràng | Dùng mức tối thiểu cho các lượt này; các câu hỏi khác giữ cơ chế động, lựa chọn `on`/`off` được giữ nguyên |
| Vừa | `latest`, task và revision giữ dữ liệu của từng chat đã kết thúc trong RAM suốt phiên | Dọn khi worker kết thúc, giữ đúng tin mới đến trong lúc tắt typing; chống trùng và pause vẫn nằm trong SQLite |

Lỗi key/quyền/cấu hình, nội dung bị chặn và hết `max_completion_tokens` vẫn
dừng, không bị gom thành lỗi để spam vô hạn. Retry vẫn tính từng request vào
ngân sách, tuân thủ thời gian nghỉ nguồn và hủy khi bạn nhắn thủ công. Chưa rõ
kết quả gửi Messenger vẫn không tự gửi lại.

Việc phân biệt lỗi Google dựa trên [FinishReason của generateContent](https://ai.google.dev/api/generate-content#FinishReason).
Các mã mới/chưa được xử lý vẫn bị từ chối thay vì gửi phần trả lời chưa hoàn tất.

## Kiểm chứng

- Trước sửa: 1.103 kiểm thử offline đạt. Các ca bổ sung tái hiện được lỗi
  phản hồi hỏng, lọt nhóm trong allowlist, auto thinking và dữ liệu RAM còn giữ.
- Sau sửa: 1.222 kiểm thử offline đạt; Ruff E4/E7/E9/F và `git diff --check` đạt.
- Có kiểm tra luân chuyển model chữ/ảnh, retry khi chỉ có một model, đếm ngân
  sách từng request, từ chối nội dung bị lọc/bị cắt, dữ liệu riêng không lọt
  vào lỗi, 30 chat hoàn tất giải phóng RAM, chống trùng vẫn hoạt động và tin
  đến lúc tắt typing vẫn được trả lời.
- Không đăng nhập/gửi Messenger, không kết nối SSH hoặc đổi service/config
  trên VPS. Các kiểm thử offline mô phỏng đường truyền, không thay thế kiểm
  tra tài khoản Messenger thật.

Thử 4 request Google thật, dùng payload từ code mới, `auto`, tắt Search,
`max_completion_tokens=4096`. Đề cầu có bốn người mất 1/2/7/13 phút, tối đa hai
người một lượt, một đèn pin; đáp án tối ưu đã được tính độc lập là 20 phút.

| Model | Tình huống | Mức gửi lên API | Token suy luận thực tế | Thời gian | Kết quả |
|---|---|---|---:|---:|---|
| Gemma 4 26B A4B | Bài cầu hỏi tự nhiên | high | 1.055 | 30,78 giây | 20, đúng |
| Gemma 4 26B A4B | “thế à” sau bài cầu | minimal | 0 | 8,22 giây | Có câu trả lời hoàn chỉnh |
| Gemini 3.5 Flash Lite | Bài cầu hỏi tự nhiên | medium | 2.840 | 15,13 giây | 20, đúng |
| Gemini 3.5 Flash Lite | “thế à” sau bài cầu | minimal | 0 | 7,61 giây | Có câu trả lời hoàn chỉnh |

“0” là trường hợp API không có trường thoughts và tổng token bằng đầu vào +
đầu ra. Không yêu cầu hoặc ghi nội dung suy luận. Đây là mẫu nhỏ, không suy
ra tỷ lệ đúng hay tốc độ ổn định. Thời gian trên là request độc lập, chưa
gồm gom tin/gửi Messenger và không chạy toàn chuỗi fallback. Đặc biệt, lượt
Gemma 30,78 giây có thể vượt ngân sách chờ Gemma 30 giây khi đứng trong chuỗi
có Gemini; kết quả đúng không bảo đảm lượt đó được dùng trong mọi cấu hình.

Auto trên Gemma vẫn dùng quy tắc tại bot vì [API của nó chỉ bật/tắt thinking](https://ai.google.dev/gemma/docs/core/gemma_on_gemini_api#thinking).
Không coi bản sửa là khả năng tự phân loại đúng mọi câu hỏi hoặc lỗi chính tả.

## Nên bổ sung tiếp

1. **Giữ lượt chờ qua restart.** `ReplyBot.pending`, câu mới nhất và ảnh đang
   chờ hiện ở RAM. Restart khi đang hết quota sẽ mất lượt đó. Cần bảng lượt
   chờ riêng với revision/trạng thái gửi, chỉ khôi phục lượt chưa gửi, hủy
   khi người dùng đã trả lời; không phát lại outbox `unknown`. Với ảnh cần
   quyết định riêng cách lưu tham chiếu/khóa, không tự ghi dữ liệu ảnh riêng tư.
2. **Dọn dữ liệu định kỳ khi chạy lâu.** `State.prune()` hiện chỉ được gọi
   lúc khởi động trong CLI. `seen`, outbox, pause và bộ đếm cũ có thể tăng khi
   chạy liên tục. Nên có lịch dọn hàng giờ, giữ dữ liệu cần cho lượt chờ và
   tính giới hạn. Hiện `retention_days` chưa phải thời hạn xóa tức thời.
3. **Tên chủ tài khoản trong nhường trả lời.** `handoff.py` còn nhận câu gọi
   tên “Mạnh” cố định, preview/log cũng nhắc tên này. Với acc thứ hai tên
   khác, persona riêng chưa thay đổi được quy tắc đó. Nên thêm tên/cách gọi
   được cấu hình riêng; yêu cầu dừng chung vẫn hoạt động như hiện tại.
4. **Lệnh xem trạng thái vận hành.** Nên có trạng thái từng model, lần lỗi
   gần nhất, thời gian chờ, ngân sách còn lại và số lượt pending. Có thể lưu
   token input/output/thinking dạng số, không lưu suy luận, cookie hay nội
   dung chat vào log chẩn đoán. Hiện `features --show` chủ yếu cho biết cấu
   hình, không chứng minh lượt vừa rồi thực sự dùng bao nhiêu thinking.
5. **CI trên GitHub.** Chưa có workflow chạy bộ kiểm thử/lint mỗi lần push
   hoặc PR. Nên dùng Python được hỗ trợ, chỉ test offline, không cấp API key
   hay cookie thật. Các kết quả trên được chạy trong môi trường phát triển.
6. **Phục hồi service theo loại lỗi.** Mẫu service dùng `Restart=on-abnormal`;
   CLI thường thoát mã 1 khi gặp lỗi vận hành nên trường hợp đó chưa tự chạy
   lại. Nên tách lỗi tạm thời và lỗi đăng nhập/cấu hình trước khi thay chính
   sách restart, tránh tạo vòng đăng nhập lỗi liên tục. Tham khảo
   [quy tắc Restart của systemd](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html#Restart=).

## Dữ liệu riêng và lịch sử Git

`config.json`, `secrets.json`, `persona.local.txt`, `data/` và file môi trường
được bỏ qua bởi Git; không có các file đó trong thay đổi của đợt rà soát.
Quét các mẫu key phổ biến và cookie phiên trên các blob lịch sử hiện có
không phát hiện giá trị khớp; đây không phải bằng chứng mọi dạng bí mật đều
đã được loại trừ.

Bản persona từng đưa lên trước khi rút gọn vẫn có trong lịch sử Git, ví dụ
commit `de1aa71`. Đưa nội dung mới sang `persona.local.txt` chỉ ngăn commit
mới, không xóa bản cũ. Đợt này không viết lại lịch sử nhánh; nếu muốn xóa
thông tin cũ cần xử lý lịch sử và các bản clone/fork riêng.

## Áp dụng cho hai acc

Bản sửa không thêm dependency hoặc đổi schema, model, key, persona hay giới
hạn đã lưu. Cập nhật code và restart cả hai system service trên VPS:

```bash
git -C /root/messenger-ai-bot pull --ff-only &&
git -C /root/messenger-ai-bot-2 pull --ff-only &&
systemctl restart messenger-ai messenger-ai-2
```

Xem kết quả sau restart:

```bash
journalctl -u messenger-ai -u messenger-ai-2 -n 40 --no-pager
```
