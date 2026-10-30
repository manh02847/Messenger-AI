# Gọi AI chạy hoàn toàn trên Ubuntu VPS

Chrome, phiên Facebook, thiết bị âm thanh ảo và Google Live relay cùng chạy trên VPS. Máy Windows/điện thoại chỉ mở màn hình từ xa để đăng nhập và cấu hình; sau khi kiểm tra và bật tự động, có thể đóng máy cá nhân. Không chuyển tiếng cuộc gọi qua máy cá nhân nữa.

**Đây là bản triển khai đầu tiên cần thử trên VPS thật.** Người dùng đã xác nhận cầu nối Chrome trên Windows hoạt động ở bản 0.1.1. Bản 0.2.0 bổ sung desktop Ubuntu và nhận cuộc gọi tự động; phần mới đã kiểm thử offline/mô phỏng, chưa được cài hoặc kiểm chứng với Facebook trên VPS trong môi trường phát triển.

**Bản hiện tại: 0.5.0.** Có thời gian chờ trước khi AI tự nhận để ưu tiên bạn nghe trước, mặc định 25 giây và chỉnh được trong popup. Tiếp tục giữ kết thúc theo yêu cầu, lựa chọn giọng, lời chào, làm mới Facebook sau cuộc gọi, nhường người thật và persona riêng. Các thao tác phụ thuộc nhãn giao diện Facebook vẫn cần kiểm tra trên VPS sau cập nhật.

Cấu hình khởi đầu dự kiến: 2 vCPU, khoảng 4 GB RAM cho một phiên Chrome với một tài khoản. Đây là đánh giá theo cấu hình, chưa phải số đo tải thật. Bộ cài giới hạn service ở 2500 MB để dành RAM cho hệ thống và bot text. Chưa tự thêm swap.

## 1. Cài bằng root trên VPS

Nếu lệnh `call-lab` cũ vẫn chạy trên terminal thì bấm **Ctrl+C** ở terminal đó trước để giải phóng cổng 8765. Không dừng service bot nhắn tin.

Trong thư mục acc 1 đã có key Google:

```bash
cd ~/messenger-ai-bot
git pull --ff-only
.venv/bin/python setup_call_vps.py install
```

Cũng có thể chạy từ `~/messenger-ai-bot-2` nếu muốn lấy key Google của thư mục đó. Chỉ cài **một host gọi** trong bản này; thư mục nguồn chỉ cung cấp key, tài khoản nhận cuộc gọi là Facebook bạn đăng nhập trong Chrome VPS.

Bộ cài hỗ trợ Ubuntu/Debian **x86-64**, systemd, Python 3.11+. Nó cài Google Chrome stable, TigerVNC, Openbox, PulseAudio và noVNC; tạo user riêng `messenger-call`, venv riêng và system service `messenger-ai-call`.

Cuối quá trình, terminal hiện hai thông tin cần giữ riêng:

- **Mật khẩu noVNC:** 8 ký tự do bộ cài tạo, dùng vào màn hình từ xa; khác mật khẩu SSH của VPS.
- **Mã kết nối:** dán vào tiện ích Chrome VPS; không phải Google API key. Mã được giữ qua các lần restart service.

Key Google được lấy từ `GEMINI_API_KEY` hoặc `google_api_key` trong `secrets.json` của thư mục nguồn. Chỉ key Google được chuyển vào cấu hình riêng; không lấy cookie Facebook, persona hoặc lịch sử của bot text. Nếu cần đổi key khi cài lại, thêm `--update-key`. Cấu hình hiện có giữ model và mã kết nối nếu không yêu cầu đổi.

## 2. Mở màn hình VPS để đăng nhập

Trên **Windows**, mở PowerShell và dùng tài khoản/IP SSH thật của VPS:

```powershell
ssh -N -L 6080:127.0.0.1:6080 USER_SSH@IP_VPS
```

Nhập mật khẩu SSH như bình thường. Cửa sổ đứng im sau đăng nhập là đúng. Nếu cổng 6080 trên máy đang bị ứng dụng khác dùng, đổi vế đầu thành `16080`, rồi mở cổng đó ở URL bên dưới.

Mở Chrome **trên máy Windows** tới:

```text
http://127.0.0.1:6080/vnc.html
```

Bấm **Connect**, nhập mật khẩu **noVNC** do bộ cài in ra. Đây là màn hình của Chrome đang chạy trên VPS. Đăng nhập Facebook bằng tài khoản thử trong màn hình này; bạn tự nhập mật khẩu, OTP và xử lý xác minh nếu có. Khi phiên hết hạn cần vào lại để đăng nhập/xác minh. Không chuyển cookie bằng cách dán vào source.

Relay 8765, VNC 5977 và noVNC 6080 đều chỉ nghe loopback. Không mở các cổng này ra Internet. SSH tunnel 6080 phục vụ việc điều khiển màn hình, không cần giữ nó sau khi đã cấu hình xong.

## 3. Cài tiện ích trên Chrome của VPS

**Thao tác trong màn hình noVNC**, không phải Chrome Windows:

1. Vào `chrome://extensions`, bật **Developer mode**.
2. Chọn **Load unpacked**, nhập/chọn thư mục:

```text
/opt/messenger-ai-call/app/experimental/call-lab-extension
```

3. Kiểm tra phiên bản **0.5.0**. Cho phép tiện ích chạy trên Facebook/Messenger nếu Chrome hỏi; chỉ giữ một bản tiện ích đang bật.
4. Ghim tiện ích. Tải lại trang Facebook trước khi tạo cuộc gọi mới.
5. Mở tiện ích, địa chỉ giữ `ws://127.0.0.1:8765`, dán mã kết nối từ bộ cài. Có thể tắt **Nghe giọng AI trên máy này** vì VPS không cần phát loa để bạn nghe qua noVNC.

Google Chrome mới không được giả định hỗ trợ `--load-extension` qua dòng lệnh. Vì vậy bước Load unpacked được thực hiện trong giao diện Chrome và lưu theo profile riêng.

## 4. Thử một cuộc gọi rồi bật tự động

1. Trước tiên **giữ tự động tắt**. Từ tài khoản khác gọi tới tài khoản Facebook trên VPS; nhận bằng noVNC.
2. Nếu Chrome hỏi quyền micro, chọn **Allow / Cho phép**. VPS không cần mic vật lý: bộ cài tạo mic ảo **Messenger_Virtual_Mic**, chọn mic này hoặc Default trỏ tới mic này trong cài đặt micro của Chrome/Messenger. Máy Windows không cần cấp micro cho noVNC. Tiếng người gọi được lấy trực tiếp từ luồng cuộc gọi, tiếng AI thay track gửi; mic ảo im lặng giúp Messenger mở kết nối ban đầu.
3. Bấm **Bật AI cho cuộc gọi này**. Nghe/kiểm tra từ điện thoại hoặc máy của người gọi, vì noVNC trong cấu hình này không truyền tiếng desktop về máy bạn.
4. Sau khi tiếng hai chiều hoạt động, kết thúc cuộc gọi thử.
5. Trong tiện ích, tích **Tự nhận cuộc gọi thoại và bật AI**, đặt **Chờ trước khi AI nhận (giây)** rồi bấm **Lưu chế độ tự động**. Mặc định **25 giây**, nhận số nguyên **0–90**; `0` là nhận ngay khi Google sẵn sàng.
6. Gọi thử lần nữa. Google được khởi tạo song song với thời gian chờ; chưa nhận hoặc nối âm thanh khi đang chờ. Hết thời gian, chỉ bấm nhận khi Google đã sẵn sàng và thông báo vẫn là đúng lượt gọi đó. Sau đó tự tìm cửa sổ gọi và nối âm thanh.
7. Khi bước 6 đã hoạt động, có thể đóng tab noVNC và cửa sổ SSH/Windows. VPS vẫn giữ Chrome và âm thanh chạy.

**Dừng AI** cũng tắt chế độ tự động. Tự động mặc định tắt khi mới cài; lựa chọn đã lưu cùng mã kết nối nằm trong profile Chrome riêng, nên có thể được khôi phục khi Chrome khởi động lại. Mật khẩu noVNC và Google key không được đưa vào tiện ích.

Nhận diện tự động hiện dựa trên nút nhận/từ chối và thông báo cuộc gọi đến bằng tiếng Việt/Anh. Nó bỏ qua nút không khớp, yêu cầu kết bạn, tin nhắn thường, video và nhóm có nhãn nhận diện được; nếu giao diện Facebook thay đổi có thể không tự nhận. Đây chưa phải API xác nhận loại cuộc gọi, nên chưa bảo đảm phân biệt mọi giao diện nhóm. Chỉ dùng cho thử cuộc gọi riêng; chưa hỗ trợ cuộc gọi nhóm/video. Không có chức năng tự gọi ra.

Nếu Google lỗi trước khi nhận, không bấm nhận cuộc gọi. Không retry liên tục cùng một thông báo đến. Nếu nhiều cửa sổ cùng có cuộc gọi, không tự chọn tùy ý. Sau khi nhận, nếu chưa tìm được kết nối sau khoảng 25 giây thì dừng thử; kiểm tra cuộc gọi trên noVNC.

Thời gian chờ tính từ lúc tiện ích nhận thông báo cuộc gọi trên VPS, không phải lúc người gọi bắt đầu bấm gọi. Google khởi tạo chậm hơn mốc này thì tiếp tục chờ Google; không cộng lại toàn bộ thời gian đã chọn. Trong khi chờ, tiện ích kiểm tra khoảng mỗi giây và kiểm tra lại trước khi nhận. Nếu thông báo mất, đổi lượt gọi hoặc đã thấy cuộc gọi được người thật nhận trên VPS, hủy phiên chờ mà không cúp cuộc gọi của người thật. Nhận trên điện thoại cần Facebook đồng bộ trạng thái về VPS; chưa bảo đảm tránh mọi race khi trạng thái này cập nhật chậm.

Lựa chọn được lưu qua lần mở Chrome/service worker sau, áp dụng cho lượt gọi mới. Cấu hình tự nhận cũ chưa có mục này dùng mặc định 25 giây. **Dừng AI**, bỏ chọn tự động rồi lưu, hoặc **Nhường người thật** đều hủy lượt chờ; Nhường giữ tự nhận cho các lượt sau. Gọi thủ công rồi bấm Bật AI không phải chờ thêm mốc tự nhận này.

Không dựa vào một số giây đổ chuông cố định của Messenger để canh sát cuối: chưa xác nhận được mốc thống nhất từ Meta, và người gọi có thể tự ngắt sớm. Thử một cuộc không ai nhận trên thiết bị của bạn để chọn thời gian có khoảng đệm phù hợp. Nếu thử được chuông kéo dài khoảng 60 giây, có thể đặt 45–50 giây; đây là ví dụ theo kết quả thử, không phải giới hạn được Messenger bảo đảm.

Cuộc gọi do AI **tự nhận** sẽ được kết thúc khi phiên AI dừng nếu nút kết thúc khớp và phiên vẫn đúng; nếu Facebook đổi nút thì cần vào noVNC kết thúc thủ công. Cuộc gọi bạn tự nhận rồi bật AI thủ công vẫn trả micro khi dừng, theo cách cũ. Không tự nối lại giữa một cuộc gọi khi Google mất kết nối.

Mỗi phiên VPS mặc định **600 giây (10 phút)**. Dùng Google/Gemini 3.8 Live; vẫn tiêu thụ quota/phí của project Google, tách khỏi bộ đếm ngày của bot text. Persona riêng là lựa chọn ở mục dưới; cuộc gọi không bật Search.

AI mở đầu bằng “Xin chào, mình là trợ lý AI đang hỗ trợ chủ tài khoản. Xin hỏi bạn gọi có việc gì thế ạ?”, với hướng dẫn nói nhẹ nhàng, lịch sự và tự nhiên. Chỉ giới thiệu khi bắt đầu cuộc gọi. Sau đó trả lời trực tiếp, không kèm lại danh xưng khi trả lời thông thường, hỏi lại hoặc chào kết chuyện. Chỉ xác nhận ngắn gọn vai trò khi người gọi hỏi trực tiếp về danh tính hoặc có phải AI không. Câu hỏi về chủ tài khoản không được coi là câu hỏi về danh tính AI; chưa có thông tin thì nói chưa biết. Quy tắc cách nói được đặt sau persona để tránh mẫu trả lời riêng ép giới thiệu lại mỗi lượt. Lời chào được nạp từ relay khi mở phiên mới; thay đổi phần này cần cập nhật host bằng `setup_call_vps.py install`, không cần đổi persona hoặc mã kết nối.

Cuộc gọi ưu tiên tiếng Việt xuyên suốt, phát âm rõ và tốc độ vừa phải. AI được yêu cầu chỉ đổi ngôn ngữ khi người gọi yêu cầu rõ ràng; nếu nghe lời nói không rõ thì hỏi lại bằng tiếng Việt, không đoán nội dung/ngôn ngữ từ tiếng nền. Đây là hướng dẫn cho model, không khóa cứng nhận dạng hay giọng phát ra. Theo [tài liệu Live API](https://ai.google.dev/gemini-api/docs/live-api/capabilities#change-voice-and-language), native audio tự chọn ngôn ngữ và không hỗ trợ đặt mã ngôn ngữ trực tiếp; không thêm `languageCode` vào cấu hình để tránh tham số không được hỗ trợ. Nếu tiếng vẫn nghe lạ hoặc méo sau cập nhật, cần nghe đoạn âm thanh mẫu để phân biệt lỗi ngôn ngữ với chất lượng tiếng/đường truyền.

## Chọn giọng nói

Trong thư mục nguồn trên VPS, cập nhật rồi chọn tên giọng:

```bash
cd ~/messenger-ai-bot
git pull --ff-only
.venv/bin/python setup_call_vps.py install --voice Aoede
```

Bộ cài lưu lựa chọn và khởi động lại host gọi; áp dụng từ cuộc gọi mới. Các lần cập nhật không có `--voice` giữ giọng đã chọn. Cấu hình cũ chưa chọn giọng tiếp tục dùng mặc định của Google. Không cần đổi mã kết nối hoặc reload tiện ích chỉ để đổi giọng.

Một số giọng có thể thử; mô tả là phong cách trong [danh sách giọng Google](https://ai.google.dev/gemini-api/docs/speech-generation#prebuilt-voices), không phải cam kết về giọng vùng miền tiếng Việt:

| Tên để nhập | Phong cách |
|---|---|
| `Aoede` | Thoải mái |
| `Puck` | Vui tươi |
| `Kore` | Dứt khoát |
| `Achernar` | Nhẹ nhàng |
| `Sulafat` | Ấm áp |

Hỗ trợ 30 tên giọng có sẵn của Google. Nghe trước trong **Google AI Studio → Stream** rồi nhập đúng tên, phân biệt chữ hoa/thường. Việc chọn giọng điều chỉnh chất giọng phát ra; hướng dẫn ưu tiên tiếng Việt vẫn giữ như trên. Chưa hỗ trợ tạo/nhân bản giọng riêng hoặc chọn giọng bằng popup.

Đổi lại mặc định:

```bash
.venv/bin/python setup_call_vps.py install --voice default
```

## Tóm tắt sau gọi và gửi cho chính mình

Trong thư mục bot nhắn tin đã có cấu hình, chạy:

```bash
cd ~/messenger-ai-bot
git pull --ff-only
.venv/bin/python setup_call_vps.py install --call-summaries
systemctl restart messenger-ai
```

Bộ cài chọn chính tài khoản Facebook đã cấu hình trong thư mục này làm nơi nhận. Khi bot nhắn tin kết nối lại, nó đối chiếu ID tài khoản thật; không khớp thì dừng gửi báo cáo. Host gọi không nhận cookie Facebook của bot nhắn tin. Muốn chọn acc 2 làm nơi nhận, chạy lệnh cài trên trong `~/messenger-ai-bot-2`, rồi restart `messenger-ai-2`. Vẫn chỉ có một host gọi; tính năng này không tự biết tài khoản Chrome VPS có trùng tài khoản bot nhắn tin hay không, nên chọn đúng thư mục nhận mong muốn.

Khi phần AI tham gia cuộc gọi kết thúc (gác máy, dừng/nhường AI hoặc kết nối mất), host tóm tắt nội dung chính, yêu cầu người gọi và mốc hẹn đã nói rõ. Bot gửi vào cuộc trò chuyện **với chính mình** của tài khoản nhận, qua E2EE. Không gửi cho người gọi, không lấy đích gửi từ lời nói trong cuộc gọi. Nếu không nhận dạng được lời người gọi thì không tạo báo cáo chỉ có lời chào. Khi nhường người thật, bản tóm tắt chỉ có phần AI đã nghe, không tiếp tục nghe cuộc gọi của người thật.

Mặc định dùng `gemini-3.5-flash-lite`, thêm một request Google sau mỗi phiên có nội dung. Đổi model bằng `--summary-model MÃ_MODEL`. Tóm tắt chạy riêng sau gọi để không giữ cuộc gọi mới chờ. Quota/phí thuộc project Google, không qua bộ đếm ngày của bot text. Nếu nguồn tóm tắt lỗi, gửi báo cáo ghi rõ chưa tóm tắt được và kèm trích đoạn lời người gọi được nhận dạng; không tự bịa một bản tổng kết.

Nhận dạng input/output chỉ bật khi đã chọn `--call-summaries`. Không ghi âm; bản nhận dạng đầy đủ chỉ giữ trong RAM, tối đa 24.000 ký tự gần nhất và 200 lượt, báo rõ nếu rút bớt. Tóm tắt/trích đoạn dự phòng được xếp vào hộp gửi riêng trên VPS, không log nội dung. Hộp nằm dưới `/var/spool/messenger-ai-call`, chỉ user host và nhóm của bot nhận đọc/ghi được. Bot gửi thật thì xóa bản tạm sau khi xác nhận ID tin; chạy preview thì giữ chờ và chưa gửi.

Khi gửi chưa rõ kết quả, giữ file `.unknown.json`; nếu process dừng giữa lúc gửi, có thể còn `.sending.json`. Không tự gửi lại các bản này để tránh trùng. Bạn có thể mở bản riêng để đọc lại khi cần. Nếu chưa thấy thông báo, kiểm tra log `messenger-ai-call` và service bot nhận; kiểm tra bot không ở preview, ID tài khoản còn khớp và thư mục hộp gửi đọc được. Chức năng nhắn cho chính mình và cảm xúc vẫn cần thử với Facebook thật sau cập nhật; kiểm thử offline không xác nhận server luôn chấp nhận.

Tắt nhận dạng/tóm tắt cuộc gọi mới (các báo cáo cũ đang chờ vẫn được bot xử lý):

```bash
.venv/bin/python setup_call_vps.py install --no-call-summaries
```

Chạy lại `install` không có cờ tóm tắt giữ lựa chọn đã lưu. Hai tính năng react/tóm tắt chỉ sửa Python: không cần đổi phiên bản tiện ích 0.5.0, giọng, persona hoặc chế độ chờ người thật. Nếu đã sửa file persona nguồn, vẫn dùng `--persona` như phần riêng bên dưới để cập nhật bản sao.

## Yêu cầu AI kết thúc cuộc gọi

Khi AI đang nghe trong cuộc gọi, model hiểu ý định kết thúc qua toàn bộ hội thoại và lượt mới nhất rồi dùng công cụ `end_call`. Có thể nói rõ như **“ngắt cuộc gọi đi”**, nói ngắn **“ok ngắt đi”**, **“cúp đi”**, hoặc chào kết chuyện **“ok thôi nhá”**, **“ừ thế nhé”** sau khi đã hỏi xong. Không cần đọc nguyên một mẫu câu hoặc nhắc từ “máy/cuộc gọi”. Tiện ích vẫn kiểm tra đúng phiên, đúng cửa sổ và kết nối âm thanh trước khi bấm nút kết thúc. Tính năng hoạt động với cả cuộc gọi AI tự nhận và cuộc gọi bạn đã bật AI thủ công. Tự nhận cuộc gọi sau vẫn giữ theo lựa chọn đã lưu.

Câu **“đừng ngắt”**, **“ok thôi, nói tiếp đi”**, **“bạn có tự cúp máy được không?”**, giả định, trích dẫn hoặc chỉ bỏ một chủ đề thì chưa phải muốn cúp. **“Ok”** sau câu trả lời thông thường là xác nhận đã hiểu; sau câu hỏi xác nhận kết thúc cuộc gọi thì có thể là đồng ý cúp. Nếu đang nói về việc ngắt nhạc/việc khác thì không dùng lệnh kết thúc cuộc gọi. Câu chào tạm biệt có ý kết chuyện được phép kết thúc; không còn quy tắc chặn mọi câu chào tạm biệt như bản đầu 0.4.0. Chỉ hỏi lại khi ý định thực sự chưa rõ. Đây là phân loại của model và không bảo đảm tuyệt đối khi model nghe nhầm âm thanh.

Nếu nút kết thúc không khớp, phiên đã đổi hoặc lệnh quá hạn thì báo chưa thực hiện được; không báo thành công khi chưa có kết quả từ tiện ích. Không dùng bản chép lời hoặc nội dung AI nói ra làm lệnh cúp. Không bổ sung quyền Chrome hoặc lưu âm thanh/lời nói trong log.

Cần cập nhật **cả host và tiện ích**: chạy `git pull --ff-only`, `.venv/bin/python setup_call_vps.py install`, rồi trong Chrome VPS mở `chrome://extensions`, Reload tiện ích, xác nhận **0.5.0** và tải lại Facebook. Host chỉ khai báo công cụ kết thúc khi tiện ích báo hỗ trợ; bản tiện ích cũ tiếp tục hoạt động theo cách cũ.

Các điều chỉnh cách nói/hiểu ý hoặc đổi giọng chỉ cần cập nhật host rồi mở cuộc gọi mới. Riêng thời gian chờ tự nhận ở **0.5.0** cần Reload tiện ích như trên để nạp mã mới.

Đã thử Google/Gemini 3.8 Live với 20 tình huống chữ có ngữ cảnh, 4 mẫu giọng nói tổng hợp và 1 hội thoại nhiều lượt liên tục: câu kết thúc rút gọn, phủ định, xác nhận “ok”, hỏi khả năng, giả định/trích dẫn, đổi chủ đề, ngắt việc khác và hỏi thông tin chủ tài khoản; các mẫu đều được xử lý đúng và không giới thiệu lại ở lượt thông thường. Giọng “ok thôi nhá”/“ok ngắt đi” tạo lệnh, giọng muốn nói tiếp không tạo lệnh. Chưa kiểm tra thao tác bấm cúp trên Facebook thật sau thay đổi; thử lại một cuộc gọi trên VPS để xác nhận nhãn nút đang dùng. Cơ chế dùng [function calling của Live API](https://ai.google.dev/gemini-api/docs/live-api/tools#function-calling).

## Dọn cửa sổ gọi, nhường và gọi ra

Từ 0.3.0, khi trang gọi hiện màn hình kết thúc/đánh giá như “Bạn thấy chất lượng cuộc gọi như thế nào?”, tiện ích kiểm tra không còn kết nối âm thanh rồi dọn trang gọi. Nó giữ ít nhất một trang Facebook/Messenger chính, không đóng trang chủ, không bấm đánh giá sao và không bấm Gọi lại. Tab đang chuyển trang, đang có cuộc gọi hoặc đã đổi `call_id` không bị dọn theo sự kiện cũ. Nếu còn một tab Facebook duy nhất thì giữ lại.

Từ 0.3.2, sau khi dọn cửa sổ gọi, tiện ích chờ thêm khoảng 1,5 giây rồi tải lại **một** trang Facebook/Messenger chính để làm mới phiên nhận cuộc gọi. Đóng trực tiếp cửa sổ đang được AI xử lý cũng lên lịch tải lại. Tự nhận vẫn giữ theo lựa chọn đã lưu và được nạp lại khi trang tải xong. Nếu có cuộc gọi đến, gọi ra, peer đang kết nối, tab đang điều hướng hoặc chưa kiểm tra được trạng thái thì bỏ lần tải lại đó. Chuyển người thật trên thiết bị khác không kích hoạt tải lại. Không tải lại định kỳ khi đang để máy nghỉ hoặc đang gọi.

Phần theo dõi cuộc gọi đến giữ nguyên mã của thông báo đang rung khi tiện ích khôi phục. Trước đây việc bật lại cùng chế độ theo dõi đã tạo mã mới, khiến sự kiện vừa đánh thức tiện ích không còn khớp; cuộc gọi đó có thể bị bỏ qua. Bản sửa có kiểm thử mô phỏng khôi phục worker với cuộc gọi đầu tiên. Sau cập nhật, nên để nghỉ 3–5 phút rồi thử gọi một lần; kết quả thật còn phụ thuộc phiên Facebook, giao diện và thời gian Google sẵn sàng.

| Tình huống | Hành vi |
|---|---|
| Có cuộc gọi mới trong lúc AI đang xử lý một cuộc gọi | Giữ cuộc gọi hiện tại, không tự nhảy sang cuộc khác. |
| Bạn bấm **Nhường người thật, giữ cuộc gọi** | Dừng nghe/nói bằng AI, không bấm cúp máy, giữ lựa chọn tự nhận cho cuộc gọi sau. |
| Messenger báo rõ cuộc gọi đã trả lời trên thiết bị khác | AI nhường mà không cúp cuộc gọi; chỉ dọn trang cũ khi trang đó đã kết thúc và không còn peer đang gọi. |
| Bạn tham gia từ điện thoại nhưng VPS vẫn còn trong cuộc gọi, không có thông báo chuyển thiết bị | AI chưa biết chắc bạn là chủ tài khoản và có thể tiếp tục trả lời; dùng nút Nhường để dừng AI. Không dùng nhận diện giọng chủ tài khoản. |
| Bạn gọi ra trong Chrome của VPS | Không tự bật AI cho cuộc gọi ra. Có thể bấm **Bật AI cho cuộc gọi này** sau khi cuộc gọi kết nối và không có phiên AI khác đang chạy. |
| Bạn gọi ra trên điện thoại/máy khác | Tiện ích trên VPS không có luồng âm thanh của cuộc gọi đó, không tự chèn AI vào. |

Nhường chỉ dừng AI: noVNC vẫn không chuyển micro máy cá nhân tới VPS. Muốn nói tiếp, thiết bị của bạn phải đang tham gia/được Messenger chuyển cuộc gọi. **Dừng AI** tiếp tục có nghĩa tắt tự động; với cuộc gọi AI đã tự nhận, nó còn thử kết thúc cuộc gọi như mục trước.

## Persona riêng cho cuộc gọi

Mặc định cuộc gọi dùng lời hướng dẫn chung. Muốn dùng cách nói/thông tin trong persona của acc đang đăng nhập ở **Chrome VPS**, chọn rõ file khi cài/cập nhật:

```bash
cd ~/messenger-ai-bot
git pull --ff-only
.venv/bin/python setup_call_vps.py install --persona persona.local.txt
```

Nếu cần dùng persona của acc 2 đang nằm ở thư mục khác, thay đường dẫn sau `--persona`, ví dụ `/root/messenger-ai-bot-2/persona.local.txt`. Không tự đoán persona theo key API hoặc tài khoản Facebook. File phải tồn tại, mã hóa UTF-8, từ 1 đến 12000 ký tự.

**Nội dung file đã chọn được gửi tới Google trong mỗi phiên gọi.** Bộ cài tạo bản sao riêng 0600 tại `/var/lib/messenger-ai-call/call-persona.local.txt`, không đưa vào repo hoặc tiện ích. Chỉ chọn thông tin bạn muốn AI sử dụng cho cuộc gọi. Các chỉ dẫn giới thiệu là AI và không tự nhận lời thay chủ tài khoản vẫn được giữ.

Sau lần chọn đầu, chạy install không có `--persona` sẽ giữ lựa chọn hiện tại. Sửa file persona nguồn cần chạy lại install với `--persona` để cập nhật bản sao. Hoặc sửa trực tiếp bản sao riêng trên VPS rồi restart `messenger-ai-call` để nạp lại. Không in persona vào log.

Muốn ngừng dùng persona riêng:

```bash
.venv/bin/python setup_call_vps.py install --no-persona
```

Cờ này ngừng gửi persona trong phiên mới và dùng mẫu chung; không xóa bản sao riêng khỏi VPS. Lịch sử/ngữ cảnh cuộc gọi vẫn mới cho từng phiên, không lấy lịch sử nhắn tin hoặc lịch sử người khác. Chế độ suy luận/Search của bot text không tự áp dụng cho gọi.

## Quản lý

```bash
systemctl status messenger-ai-call
journalctl -u messenger-ai-call -n 60 --no-pager
```

| Việc | Lệnh trong thư mục repo, bằng root |
|---|---|
| Dừng Chrome/relay/desktop gọi | `systemctl stop messenger-ai-call` |
| Bật lại | `systemctl start messenger-ai-call` |
| Khởi động lại | `systemctl restart messenger-ai-call` |
| Tắt tự khởi động theo VPS | `systemctl disable --now messenger-ai-call` |
| Xem lại mã kết nối | `.venv/bin/python setup_call_vps.py token` |
| Đặt mật khẩu noVNC mới | `.venv/bin/python setup_call_vps.py password` |

Mã kết nối được in khi cài hoặc khi bạn chủ động dùng lệnh `token`, không in vào journal lúc khởi động. Mật khẩu noVNC không đọc lại được; dùng lệnh `password` để tạo mật khẩu mới.

Muốn cập nhật code/tiện ích hoặc chọn model và thời gian khác:

```bash
cd ~/messenger-ai-bot
git pull --ff-only
.venv/bin/python setup_call_vps.py install --model gemini-3.1-flash-live-preview --max-seconds 600
```

Không truyền các tùy chọn trên nếu muốn giữ model/thời gian hiện có. Bộ cài cập nhật bản sao riêng trong `/opt`, giữ profile/cấu hình trong `/var/lib`, rồi restart **chỉ** service gọi. Nếu Chrome yêu cầu, vào noVNC → `chrome://extensions` bấm Reload tiện ích sau cập nhật và gọi lại từ trang Facebook đã reload. Chỉ `git pull` chưa cập nhật bản sao host đang chạy.

Bot nhắn tin `messenger-ai` và `messenger-ai-2` có cấu hình/service riêng, bộ cài không stop hoặc thay cookie/persona của chúng. Host gọi có thể đăng nhập lại cùng tài khoản hoặc tài khoản khác trong Chrome VPS.

## Kiểm tra lỗi

- **Bộ cài báo cổng 8765 đang dùng:** Ctrl+C relay `call-lab` cũ tại terminal đang chạy nó. Không dùng lệnh kill toàn bộ Python.
- **noVNC không mở:** kiểm tra SSH tunnel đang chạy trên máy bạn, service đang active; không dùng IP VPS kèm cổng 6080 trực tiếp.
- **Service khởi động lại rồi failed:** xem journal phía trên. Kiểm tra gói Chrome/TigerVNC/PulseAudio, quyền file và RAM. Bộ cài không tắt sandbox Chrome; không thêm `--no-sandbox` để che lỗi.
- **Chưa đăng nhập/đòi xác minh:** xử lý thủ công trong Chrome VPS. Không tự vượt xác minh.
- **Không tự nhận:** kiểm tra phiên bản 0.3.0, đã Lưu tự động, Facebook đăng nhập và chỉ một tab/cửa sổ gọi. Vào noVNC xem nút/thông báo đang hiển thị; vẫn có thể nhận rồi bật AI thủ công.
- **Nhận rồi im lặng:** kiểm tra quyền micro ở Chrome VPS, model/key/quota, trạng thái tiện ích. Kết thúc cuộc gọi, thử lại bước thủ công trước; tránh bật auto khi lượt thủ công chưa hoạt động.
- **Chrome báo không có mic:** cập nhật repo rồi chạy lại `.venv/bin/python setup_call_vps.py install` để cập nhật bản sao trong `/opt` và restart Chrome. Bản sửa tạo source riêng `call_input` với tên **Messenger_Virtual_Mic**, vì Chrome bỏ qua nguồn monitor của loa khi liệt kê mic. Trong Chrome VPS, kiểm tra `chrome://settings/content/microphone`, chọn mic ảo và cho phép Facebook. Nguồn monitor của loa và mic vẫn tách nhau để tránh vọng tiếng.
- **Một thành phần chết:** supervisor dừng các tiến trình liên quan và systemd thử lại; giới hạn 5 lần khởi động trong 120 giây. Sửa lỗi rồi chạy `systemctl reset-failed messenger-ai-call` và `systemctl start messenger-ai-call`.

Code public không chứa tài khoản Facebook, API key, mật khẩu noVNC hoặc mã kết nối thật. Desktop/profile/cấu hình nằm trên VPS, cần giữ riêng như cookie bot.

Kiểm tra source âm thanh bằng root (service phải đang chạy):

```bash
runuser -u messenger-call -- env XDG_RUNTIME_DIR=/run/messenger-ai-call PULSE_SERVER=unix:/run/messenger-ai-call/pulse/native pactl list short sources
```

Cần có dòng tên `call_input`. Lệnh không in key, cookie hoặc mật khẩu. Nếu thiếu dòng đó, gửi trạng thái service/journal để kiểm tra bước khởi tạo PulseAudio.

Tham khảo: [TigerVNC Xvnc](https://tigervnc.org/doc/Xvnc.html), [noVNC](https://github.com/novnc/noVNC), [systemd services](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html), [Chrome trên Linux](https://support.google.com/chrome/a/answer/7100626).
