# Kết quả kiểm tra

## Chờ người thật trước khi AI nhận — tiện ích 0.5.0, 28/10/2026

- Thêm mục **Chờ trước khi AI nhận (giây)** trong popup, mặc định **25**, nhận số nguyên **0–90**. Lưu cùng chế độ tự nhận trong profile Chrome; cấu hình cũ chưa có mục này dùng 25 giây. `0` giữ cách nhận ngay khi Google sẵn sàng. Bật AI thủ công không bị trì hoãn theo cấu hình tự nhận.
- Đếm từ lúc background nhận thông báo trên VPS bằng đồng hồ đơn điệu. Chuẩn bị Google song song, chưa nhận/nối âm thanh hoặc gửi `ready` trước khi cả deadline và Google đều sẵn sàng. Google chậm hơn mốc chờ thì không cộng thêm cả mốc đó. Kiểm tra khoảng mỗi giây và kiểm tra lại ngay trước thao tác nhận: vẫn đúng nonce, một thông báo đến và chưa thấy cuộc gọi đã được người thật nhận.
- Thông báo mất, người thật nhận trên VPS, Dừng AI, Nhường hoặc tắt tự động đều hủy lượt chờ, đóng phiên relay và dọn timer; không cúp cuộc gọi của người thật. Nhường và mất thông báo giữ lựa chọn tự động cho lượt sau. Lượt gọi mới thay lượt cũ khi đang chờ có deadline riêng; event hoặc timer cũ không tự bật AI vào lượt mới.
- **87 kiểm thử relay/VPS/tiện ích đạt, 1 fixture Chrome thật bỏ qua**. Thêm **21 tình huống Node** với thời gian mô phỏng: deadline chính xác, khôi phục 25 giây từ cấu hình cũ, lưu/khôi phục 45 giây, giới hạn 90 giây, Google sẵn sàng trước/sau deadline, nhận trên VPS/thiết bị khác, caller ngắt, hủy bằng ba thao tác, đổi nonce, nhận sát mốc, giá trị sai, bắt đầu thủ công và lưu form popup không ghi đè giá trị đang sửa khi polling. Các kiểm thử audio/peer/control hiện có tiếp tục đạt.
- Cú pháp JS, manifest và `git diff --check` đạt. Giữ quyền `storage` và tập host permission hiện có. Không gọi Google hoặc thực hiện cuộc gọi Facebook thật trong đợt này. Chưa kiểm chứng thời gian đổ chuông thực tế, chất lượng đồng bộ giữa các thiết bị hoặc thao tác nhận trên VPS sau thay đổi; Facebook đồng bộ chậm vẫn có thể gây race. Không tuyên bố một mốc đổ chuông cố định của Messenger.
- Cần cập nhật host để chép tiện ích mới, Reload **0.5.0** trên Chrome VPS rồi tải lại Facebook. Hướng dẫn và giới hạn trong [deploy/CALL_VPS.md](deploy/CALL_VPS.md).

## Chọn giọng gọi và lưu trên VPS — 27/10/2026

- Thêm `--voice NAME` cho bộ cài host VPS và lệnh `call-lab`, với 30 tên giọng có sẵn trong tài liệu Google. Cấu hình cũ chưa chọn giọng tiếp tục dùng mặc định; cập nhật không truyền cờ giữ lựa chọn, `--voice default` xóa lựa chọn riêng. Host truyền giọng vào `generationConfig.speechConfig.voiceConfig.prebuiltVoiceConfig.voiceName` khi mở phiên mới. Tiện ích vẫn ở 0.4.0.
- **86 kiểm thử relay/VPS đạt**: bổ sung trường hợp âm thanh hai chiều với giọng đã chọn, giữ giọng khi cập nhật/đổi persona, đổi và khôi phục mặc định, đọc cấu hình cũ, từ chối giọng sai trước khi đọc key. Wrapper kiểm tra JS cũng đạt; fixture Chrome thật vẫn bỏ qua. Lint, CLI help và `git diff --check` đạt.
- **5 lượt Google thật đạt:** Gemini 3.8 Live với `Aoede`, `Puck`, `Kore`; Gemini 3.1 Flash Live Preview với `Puck`; Gemini 2.5 Flash Native Audio với `Kore`. Tất cả chấp nhận setup có tên giọng, trả PCM 24 kHz và transcript có lời chào tiếng Việt. Các lượt này kiểm tra API chấp nhận lựa chọn và trả âm thanh, chưa đánh giá cảm nhận chất giọng hoặc giọng vùng miền.
- Chỉ dùng lời chào công khai, key nhập ẩn trong bộ nhớ; không gửi persona, âm thanh người dùng hoặc cookie. Chưa triển khai lên VPS hoặc thử giọng đã chọn qua cuộc gọi Facebook thật. Hướng dẫn đổi giọng và khôi phục mặc định nằm trong [deploy/CALL_VPS.md](deploy/CALL_VPS.md#chọn-giọng-nói).

## Hiểu câu kết chuyện theo ngữ cảnh, giảm giới thiệu lặp — 27/10/2026

- Bỏ ràng buộc cũ yêu cầu phải nói rõ việc cúp và chặn mọi câu tạm biệt. Hướng dẫn model đọc cả hội thoại: yêu cầu rút gọn như “ok ngắt đi” và lời kết chuyện “ok thôi nhá” có thể gọi `end_call`; không yêu cầu đúng mẫu hoặc đủ từ “máy/cuộc gọi”. Phân biệt “ok” xác nhận đã hiểu với đồng ý kết thúc, phủ định/muốn nói tiếp, đổi chủ đề và ngắt việc khác. Cập nhật cả mô tả function và ý nghĩa đối số để không giữ hạn chế cũ ở schema.
- Thêm quy tắc cách nói sau persona trong setup, ưu tiên trả lời thẳng và không kèm lại danh xưng mỗi lượt. Câu hỏi thông tin chủ tài khoản không bị coi là hỏi danh tính AI; hỏi trực tiếp có phải AI vẫn được trả lời trung thực. Giữ nguyên lời chào đầu cuộc gọi do người dùng chọn. Không thêm bộ từ khóa, sửa đường âm thanh, thay model hoặc đổi giao thức/phiên bản tiện ích 0.4.0.
- **78 kiểm thử relay/VPS/tiện ích đạt, 1 fixture Chrome bỏ qua**, lint và `git diff --check` đạt. Không thêm test chỉ so khớp câu prompt; giữ kiểm tra giao thức và thử hành vi bằng model thật.
- **Google thật / Gemini 3.8 Live:** 20 tình huống chữ có lịch sử đều đạt: 8 tình huống muốn kết thúc, 12 tình huống giữ cuộc gọi/trả lời. Bao gồm câu rút gọn, chào kết chuyện, ngữ cảnh đang hỏi cách cúp, “ok” theo hai ngữ cảnh, phủ định, yêu cầu nói tiếp, trích dẫn/giả định, ngắt nhạc, đổi chủ đề và hỏi thông tin chủ tài khoản. Các lượt thông thường không lặp danh xưng trong transcript, kể cả hồ sơ tổng hợp cố tình yêu cầu giới thiệu mỗi câu.
- **4 mẫu giọng nói tổng hợp đạt:** “ok thôi nhá”, “ok ngắt đi” tạo lệnh đúng; “thôi đừng ngắt, mình muốn hỏi thêm”, “ok thôi, nói tiếp đi” không tạo lệnh. Kiểm nội dung speech bằng output transcription, chuyển 24 kHz thành 16 kHz và gửi realtime sau lịch sử hỏi/đáp. **1 hội thoại thật với model qua nhiều lượt liên tục đạt:** giữ lời chào ban đầu, hỏi thông tin chủ tài khoản không giới thiệu lại, hỏi có phải AI được xác nhận trung thực, sau đó “ok thôi nhá” tạo lệnh kết thúc. Không bấm cúp Messenger trong các probe này.
- Chỉ gửi câu/hồ sơ tổng hợp công khai và dùng key trong bộ nhớ; không đọc hoặc gửi persona, âm thanh hoặc cookie thật của người dùng. Chưa xác nhận thao tác cúp trên Facebook thật sau thay đổi; các mẫu đạt không bảo đảm không nhận nhầm mọi giọng/nhiễu. Cập nhật host rồi mở cuộc gọi mới để nạp hướng dẫn mới.

## Kết thúc cuộc gọi theo yêu cầu — 0.4.0, 27/10/2026

- Thêm công cụ Live API `end_call`, chỉ khai báo khi tiện ích xác nhận hỗ trợ. Yêu cầu model chỉ dùng cho yêu cầu cúp ngay, không dùng cho phủ định, hỏi khả năng, giả định, trích dẫn, chào tạm biệt đơn thuần hoặc câu nghe không rõ. Hướng dẫn được thêm sau persona đã chọn; không đọc thêm hồ sơ hoặc lịch sử.
- Relay yêu cầu trình duyệt đã sẵn sàng và đã nhận audio, xác thực tên/đối số, chống trùng tool id, dùng request id riêng và hạn 5 giây. Chỉ báo thành công cho Google sau kết quả từ tiện ích; lỗi/timeout không tự báo đã cúp. Bản chép lời, text và inline function part không được biến thành lệnh điều khiển. Tiện ích cũ không được cấp công cụ này.
- Chrome kiểm tra phiên đang chạy, call id, URL và điều hướng; content kiểm tra lại peer âm thanh đúng phiên, thời hạn và nút kết thúc duy nhất. Lệnh cũ hoặc lookup trả muộn không tác động phiên mới; kiểm tra thất bại không dừng AI. Thành công kết thúc cả gọi thủ công/tự nhận và giữ chế độ tự nhận cho lần sau. Không tăng quyền Chrome, không đưa token, Google tool id hoặc nội dung lời nói vào page command/log.
- **1.300 kiểm thử offline đạt, 1 fixture Chrome bỏ qua**. Thêm các ca thương lượng khả năng, điều khiển trước ready/audio, đối số sai, request trùng/quá hạn, ack sai/đến muộn, giữ phiên khi nút không khớp, cúp thủ công/tự nhận, đổi call id/peer/session và lookup trả muộn. Node dùng track tổng hợp có `readyState=live` để phản ánh MediaStreamTrack thật. Lint, cú pháp JS/manifest và `git diff --check` đạt.
- **Google thật / Gemini 3.8 Live:** 9 câu bằng chữ đạt (4 yêu cầu kết thúc, 5 câu phủ định/hỏi/giả định/chào tạm biệt); 2 mẫu giọng nói tổng hợp đạt: yêu cầu ngắt tạo function call đúng đối số/id, câu “đừng ngắt cuộc gọi, mình còn muốn nói” không tạo lệnh. Hai mẫu speech được kiểm nội dung bằng output transcription trước khi chuyển 24 kHz thành 16 kHz để gửi thử. Chỉ dùng system công khai và câu cố định, key nhập ẩn trong bộ nhớ; không gửi persona, âm thanh hoặc cookie thật của người dùng. Không thực thi công cụ lên Messenger trong thử API.
- Chưa bấm kết thúc trong cuộc gọi Facebook thật sau sửa. Phân loại 11 mẫu không bảo đảm không nhận nhầm mọi giọng nói/nhiễu; nhãn nút Facebook khác vẫn có thể làm thao tác thất bại. Căn cứ giao thức: [Live tools](https://ai.google.dev/gemini-api/docs/live-api/tools), [WebSocket toolCall/toolResponse](https://ai.google.dev/api/live).

## Ưu tiên tiếng Việt và hỏi lại khi nghe mơ hồ — 27/10/2026

- Bổ sung system instruction giữ tiếng Việt trong suốt cuộc gọi, chỉ đổi khi người gọi yêu cầu rõ; phát âm rõ và tốc độ vừa phải. Với lời nói chưa hiểu thì hỏi lại bằng tiếng Việt, không tự đoán nội dung/ngôn ngữ từ đoạn ngắn hoặc tiếng nền; chờ khi chỉ có im lặng/tiếng nền. Giữ nguyên câu chào người dùng đã chọn và thêm hướng dẫn đọc rõ tiếng Việt.
- Dùng hướng dẫn cho model theo [Live API capabilities](https://ai.google.dev/gemini-api/docs/live-api/capabilities#change-voice-and-language). Native audio tự chọn ngôn ngữ, không hỗ trợ đặt mã ngôn ngữ trực tiếp; không thêm `languageCode` vào request. Không đổi model, voice, sample rate, persona, quyền tiện ích hoặc phiên bản 0.3.2.
- **57 kiểm thử relay/VPS/tiện ích đạt, 1 fixture Chrome bỏ qua**, lint và `git diff --check` đạt. Bộ Node kiểm tra PCM/resample và luồng âm thanh mô phỏng cũng chạy trong wrapper. Môi trường kiểm thử được bổ sung dependency `websockets==16.0` đã khai báo, sau khi lượt chạy đầu báo thiếu thư viện.
- Không gọi Google thật hoặc gửi dữ liệu cá nhân trong đợt này. Chưa có đoạn âm thanh của trường hợp người dùng mô tả nên chưa xác định đó là tự đổi ngôn ngữ, phát âm lạ hay tiếng bị méo. Kiểm thử offline không đánh giá chất giọng, khả năng nhận tiếng Việt hoặc mức cải thiện của hướng dẫn mới.

## Lời chào lịch sự theo lựa chọn — 27/10/2026

- Đặt lời chào đầu cuộc gọi thành “Xin chào, mình là trợ lý AI đang hỗ trợ chủ tài khoản. Xin hỏi bạn gọi có việc gì thế ạ?”, kèm hướng dẫn giọng nhẹ nhàng, lịch sự và tự nhiên. Giữ chỉ dẫn giới thiệu một lần và không tự thêm tên người. Không đổi persona, cơ chế nhận cuộc gọi hay phiên bản tiện ích 0.3.2.
- **36 kiểm thử relay đạt**, lint Python và `git diff --check` đạt. Không gọi Google hoặc thực hiện cuộc gọi thật trong đợt sửa lời chào; chất giọng và mức độ làm theo cần nghe lại trên VPS.

## Làm mới Facebook sau cuộc gọi và giữ lượt gọi đầu — 0.3.2, 27/10/2026

- Sau khi xác nhận màn hình kết thúc không còn peer âm thanh và dọn cửa sổ gọi, chờ thêm 1,5 giây rồi tải lại một trang Facebook/Messenger chính. Đóng trực tiếp cửa sổ AI đang xử lý cũng lên lịch làm mới. Giữ chế độ tự nhận, đăng ký lại theo dõi khi trang tải xong; không thêm quyền hoặc tải lại định kỳ.
- Kiểm tra trạng thái peer, nút gọi/rung, URL và điều hướng trước khi tải lại. Hủy khi có sự kiện cuộc gọi mới, phiên AI mới, peer đang hoạt động, cửa sổ đang kết nối, trạng thái chưa biết hoặc chuyển người thật trên thiết bị khác. Nút chấp nhận kết bạn không bị coi là cuộc gọi; cuộc gọi nhóm/video vẫn chặn tải lại dù không thuộc loại tự nhận.
- Sửa `watch(true)` gọi lại đã xóa nonce của thông báo đang rung. Khi worker khôi phục chế độ đã lưu trong lúc xử lý sự kiện đầu, nonce mới khiến sự kiện cũ không khớp và bị bỏ qua. Giữ nguyên watcher/nonce khi chế độ không thay đổi. Có ca dùng cả production incoming watcher và background để mô phỏng lần gọi đầu đánh thức worker; không cần gọi lần hai để mở Google trong ca này. Cơ sở về vòng đời worker: [Chrome extension service worker lifecycle](https://developer.chrome.com/docs/extensions/develop/concepts/service-workers/lifecycle).
- Toàn bộ **1.279 kiểm thử Python đạt, 1 fixture Chrome bỏ qua**; sau lượt rà cuối, chạy lại **57 kiểm thử liên quan đạt** và **85 ca Node đạt**. Các ca mới kiểm tra khôi phục lần đầu, một lần reload, giữ tự nhận sau tải trang, hủy khi bận/đổi trang, đóng trực tiếp và chuyển người thật. Cú pháp JS/manifest, lint và `git diff --check` đạt.
- Đây là kiểm thử offline/mô phỏng, không gửi cuộc gọi hay dữ liệu cá nhân thật. Chưa xác nhận lỗi người dùng thấy chỉ do nonce; mạng Facebook, thay đổi DOM hoặc Google sẵn sàng chậm vẫn có thể làm lỡ cuộc gọi. Cần cập nhật tiện ích rồi để nghỉ 3–5 phút và thử gọi một lần trên VPS thật.

## Thống nhất lời giới thiệu cuộc gọi — 0.3.1, 27/10/2026

- Bỏ lời giới thiệu cũ “AI đang thử nghiệm” trong system instruction và yêu cầu lời chào. Dùng câu mở đầu “Mình là trợ lý AI, đang nghe bạn đây”, yêu cầu giữ vai trò AI khi có persona và chỉ nhắc lại vai trò khi được hỏi. Không thay dữ liệu persona riêng hoặc cách chọn file.
- Đổi tên/tiêu đề tiện ích thành Messenger AI — Cuộc gọi, bỏ nhãn phiên thử trong trạng thái hiển thị. Không đổi cơ chế nhận/dừng cuộc gọi, dọn tab, nhường người thật hoặc quyền truy cập của tiện ích.
- **57 kiểm thử relay/VPS/tiện ích đạt, 1 fixture Chrome bỏ qua**; lint Python, cú pháp JavaScript, manifest và `git diff --check` đạt. Không gọi Google thật hoặc gửi persona thật trong đợt này; chưa xác nhận cách model phát âm/làm theo lời chào mới trên cuộc gọi thật.

## Dọn trang gọi, nhường người thật và persona — 0.3.0, 27/10/2026

- Dọn trang gọi có màn hình kết thúc/đánh giá bằng nhãn Việt/Anh, sau khi xác nhận không còn peer âm thanh. Giữ trang Facebook chính, kiểm tra lại trạng thái và `call_id` trước khi đóng; không đóng tab đang điều hướng/đã dùng cho cuộc gọi mới, không bấm sao hoặc gọi lại.
- Nút Nhường dừng AI mà không bấm cúp hoặc tắt tự nhận cho lần sau. Chỉ tự nhường theo thông báo rõ về thiết bị khác; không suy đoán chủ tài khoản theo giọng. Sự kiện peer cũ kết thúc không bấm cúp cuộc gọi mới. Cuộc gọi ra vẫn chỉ bật AI thủ công khi có âm thanh ở Chrome của host.
- Persona riêng chỉ dùng khi chọn file qua `--persona`; giới hạn UTF-8/12000 ký tự, bản sao 0600 ngoài repo, nội dung được gửi Google trong setup mỗi phiên. Không đọc persona/lịch sử bot text mặc định, không in vào log/repr. `--no-persona` trở về mẫu chung; giữ lựa chọn cũ khi cập nhật không chỉ định lại.
- **1.279 kiểm thử offline đạt, 1 fixture Chrome bỏ qua**. Node **63 ca mô phỏng đạt**, gồm trường hợp màn hình như ảnh, cuộc gọi mới trong tab cũ, giữ tab chính, hủy dọn khi có peer, nhường không cúp và giữ tự động. Python thêm ca chọn/tắt persona, file hỏng/quá dài và ẩn nội dung trong repr. Ruff, cú pháp JS/manifest và `git diff --check` đạt.
- Không gọi Google thật với persona riêng, không đọc file persona thật của người dùng trong đợt này. Chưa xác minh DOM dọn/nhường trên Chrome Facebook thật ở VPS sau sửa; nhãn giao diện khác có thể cần cập nhật. Ảnh người dùng chỉ được dùng để nhận diện màn hình đánh giá, không lưu URL phòng/nonce thật vào repo.

## Mic ảo xuất hiện trong Chrome VPS — 27/10/2026

- Sửa cấu hình chỉ có hai null-sink và chọn `call_microphone.monitor` làm mic mặc định. Chromium lọc nguồn monitor khi liệt kê đầu vào và từ chối mặc định dạng monitor; thêm `module-remap-source` trên monitor im lặng để tạo source riêng `call_input`, tên **Messenger_Virtual_Mic**. Cả `PULSE_SOURCE` và default-source dùng source này; nguồn loa vẫn tách riêng.
- Kiểm tra hồi quy bảo đảm source remap trỏ vào monitor im lặng, có tên hiển thị và không dùng monitor loa làm mic. Bộ kiểm thử VPS/relay và lint đạt; chưa kiểm chứng mic này trong Chrome/PulseAudio thật ở môi trường phát triển. Cần cập nhật host bằng bộ cài rồi kiểm tra danh sách source và mic trong Chrome VPS.
- Căn cứ: [Chromium PulseAudio input enumeration và tham số mặc định](https://chromium.googlesource.com/chromium/src.git/+/1c3ae392e0134f2abfb5a4b650b4705c493d9a29/media/audio/pulse/audio_manager_pulse.cc), [PulseAudio remap source](https://github.com/pulseaudio/pulseaudio/blob/master/src/modules/module-remap-source.c).

## Chrome và âm thanh chạy trên Ubuntu VPS — 0.2.0, 27/10/2026

- Người dùng xác nhận bản cầu nối Chrome Windows 0.1.1 hoạt động. Đây là xác nhận từ người dùng, không phải cuộc gọi do môi trường phát triển thực hiện.
- Thêm bộ cài Ubuntu/Debian x86-64 và service riêng: user không phải root, desktop TigerVNC/Openbox, PulseAudio với micro im lặng tách loa, noVNC loopback và Chrome profile riêng. Chỉ sao chép key Google; giữ token qua restart, cấu hình 0600, không lấy Facebook cookie/persona/lịch sử từ bot text.
- Tự nhận mặc định tắt, phải bật và lưu trong tiện ích. Khởi tạo Google trước khi nhận; xác minh lại nonce của thông báo đang hiện, từ chối nhiều cuộc gọi, nhận diện nhãn Việt/Anh và bỏ qua các nút khác. Dừng AI hủy warmup và thao tác lưu bật tự động còn chờ. Trạng thái bật/tắt được lưu trong profile riêng. Kết thúc tự động chỉ thử nút kết thúc đúng phiên đã nối; UI không khớp cần thao tác thủ công.
- **1.274 kiểm thử offline đạt, 1 fixture Chrome bỏ qua**; Node có **44 ca** mô phỏng codec, cầu nối, lựa chọn cửa sổ, nhận diện thông báo và chế độ tự động. Kiểm tra supervisor bằng subprocess thật: một worker chết thì worker còn lại được dừng/reap và relay đóng. Không gọi Google hoặc Facebook trong các kiểm thử mới.
- Ruff, cú pháp JS/manifest, `systemd-analyze verify` và `git diff --check` đạt. Bộ cài mới chưa chạy apt/cài Chrome trên VPS thật trong môi trường phát triển. Chưa xác minh Chrome/PulseAudio trên VPS hoặc DOM nút nhận cuộc gọi Facebook thật ở bản 0.2.0; vẫn cần thử một cuộc gọi thủ công rồi tự động trên VPS sau đăng nhập. Không tuyên bố tự động nhận mọi biến thể giao diện, phân biệt mọi cuộc gọi nhóm hoặc đã triển khai thành công.
- Hướng dẫn cài, đăng nhập qua màn hình từ xa và giới hạn: [deploy/CALL_VPS.md](deploy/CALL_VPS.md).

## Tìm cửa sổ cuộc gọi — Call Lab 0.1.1, 27/10/2026

- Sửa trường hợp bấm tiện ích ở trang Facebook chính trong khi cuộc gọi nằm ở cửa sổ popup: tìm các tab Facebook/Messenger ở tất cả cửa sổ, hỏi trạng thái WebRTC rồi chỉ chọn một cuộc gọi đã kết nối. Nếu có nhiều cuộc gọi/kết nối thì dừng trước khi mở relay/Google.
- Quyền host chỉ gồm các domain Facebook/Messenger đã hỗ trợ và loopback; không yêu cầu quyền đọc toàn bộ tab, cookie hoặc debugger. Không dùng URL phòng, tiêu đề hay tên người gọi để quyết định; các URL thật trong ảnh người dùng không được lưu vào repo.
- Thêm 7 ca Node cho cửa sổ gọi riêng, từ chối nhiều cuộc gọi, bỏ qua tab ngoài domain, tab cũ mất content script và hủy lúc đang tìm. Tổng **25 ca Node đạt**; **1.259 kiểm thử offline đạt, 1 fixture Chrome bỏ qua**, Ruff và `git diff --check` đạt. Fixture Chromium được bổ sung cửa sổ gọi riêng và trang chủ không có cuộc gọi, nhưng chưa chạy được trong runtime hiện tại; chưa xác minh âm thanh Messenger thật sau sửa.
- Cập nhật tiện ích trên máy Windows lên 0.1.1, reload tiện ích và mở cuộc gọi mới sau khi reload Facebook. Mã Python relay không đổi.

## Call Lab thử nghiệm — 27/10/2026

- **1.259 kiểm thử offline đạt, 1 kiểm thử Chrome được bỏ qua** vì chưa bật fixture riêng; Ruff E4/E7/E9/F và `git diff --check` đạt.

- Thêm relay chỉ nghe loopback và tiện ích Chrome bật theo từng cuộc gọi đã nhận thủ công. Không thay nguồn/model/config/persona hoặc service của bot text.
- Kiểm thử mới cho Origin/token, một phiên đồng thời, trạng thái sẵn sàng, PCM hai chiều, ngắt lời, timeout, dọn kết nối và lỗi không lộ key. Node có 18 ca mô phỏng PCM, resampling, track người gọi, trả micro, khởi tạo bị hủy và sự kiện muộn từ phiên cũ.
- Google thật qua relay, chỉ dùng lời giới thiệu AI công khai làm âm thanh mẫu: Gemini 3.8 Live kết nối/setup 12,93 giây; lời chào 3,80 giây âm thanh; gửi vào 48 khung PCM 16 kHz (4,80 giây, gồm một giây im lặng); nhận thêm 4,24 giây âm thanh trả lời. Không đọc persona/cookie, không dùng dữ liệu cuộc gọi thật. Một ca không đánh giá được độ chính xác hoặc độ trễ trong cuộc gọi thực tế.
- Fixture Chromium/WebRTC chưa chạy được: runtime từ chối socket IPC khi Chrome khởi động (`Operation not permitted`). Kiểm thử này cần bật riêng bằng `CALL_LAB_CHROME`; các ca Node mô phỏng không thay thế nó. Chưa thử tiện ích bằng Chrome thật hoặc đăng nhập/gọi Messenger thật, chưa triển khai lên VPS.
- Cách cài và giới hạn nằm trong [experimental/CALL_LAB.md](experimental/CALL_LAB.md).

## Rà soát tổng thể — 26/10/2026

- **1.222 kiểm thử offline đạt**, tăng 119 ca so với bản trước đợt rà soát;
  Ruff E4/E7/E9/F và `git diff --check` đạt.
- Bổ sung ca tái hiện và hồi quy cho phản hồi API hỏng/trống, Google lỗi
  giao thức dù HTTP 200, luân chuyển cả chữ/ảnh, retry với một model, giữ
  giới hạn request và phân biệt nội dung bị chặn/cắt với lỗi tạm thời.
- Chặn nhóm/loại chưa xác định trong cả allowlist và all_private trước
  lịch sử/AI; thu hồi dữ liệu RAM của lượt đã kết thúc, giữ chống trùng,
  pause và tin mới đến lúc đang dọn typing.
- Auto thinking nhận câu không dấu/bài toán nhiều số/câu hỏi tiếp, hạ mức
  cho lời chào/cảm thán và không lấy chủ đề khó cũ áp vào câu mới không liên
  quan. Vẫn là quy tắc gần đúng với API không có thinking động.
- Bốn request Google thật sau sửa: hai model giải đúng một bài cầu; câu
  “thế à” dùng mức minimal và không có token suy luận. Số liệu, giới hạn
  thử nghiệm và các việc còn cần bổ sung nằm trong [REVIEW.md](REVIEW.md).
- Chưa đăng nhập/gửi Messenger hoặc triển khai trên VPS trong đợt này.

Các mục dưới là nhật ký kiểm tra các bản cũ; số lượng test và mô tả hành vi
ở từng mục phản ánh thời điểm ghi, không thay thế kết quả mới nhất ở trên.

## Kiểm tra bản 1.0.0 — 23/10/2026

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

## Xoay nhiều model đọc ảnh — 25/10/2026

- Thêm vision_models và configure-vision --chain. Mẫu gồm Gemini 3.5
  Flash-Lite, Gemini 3.1 Flash-Lite, NVIDIA Gemma 4 31B, Qwen 3.8 qua Groq
  và Cloudflare; chỉ thêm nguồn đã có key, in rõ nguồn thiếu key. Có thể
  nhập danh sách nguồn:model thủ công để chọn thứ tự; kiểm tra toàn bộ cấu
  hình/key trước khi ghi file, không gọi API hoặc sửa secrets khi bật chuỗi.
- Cấu hình một nguồn cũ giữ nguyên; mặc định vẫn tắt. Chọn lại một nguồn
  hoặc --disable gỡ chuỗi. configure --copy-ai-from sao chép đúng thứ tự
  model ảnh và vẫn yêu cầu cookie riêng, không lấy persona/thiết bị/lịch sử.
- Chuỗi ảnh tách khỏi chuỗi chữ. Từng model nhận cùng ảnh đã xử lý, persona
  và ngữ cảnh; dừng khi có câu trả lời. Mỗi model thử một request; timeout,
  mạng, quá tải/quota và model/quyền truy cập chưa sẵn sàng được chuyển tiếp.
  Tạm nghỉ model lỗi và tôn trọng Retry-After/quota ngày Google. Khi nguồn
  phục hồi, lại thử theo thứ tự ưu tiên. Lỗi nội dung/cấu hình 400, dữ liệu
  phản hồi hỏng/bị cắt hoặc hết ngân sách cục bộ dừng lượt.
- Với nhiều model, deadline 45 giây toàn chuỗi, 10 giây mỗi model, NVIDIA
  6 giây. Request đang chờ được hủy khi hết thời gian; không polling hoặc
  retry chạy nền. Mỗi request được tính vào cùng ngân sách AI live. Khi
  tất cả nguồn lỗi/nghỉ, bỏ lượt và chờ tin mới. Lượt ảnh chỉ tải media một
  lần dù chuyển nguồn nhiều lần, tối đa một tin trả lời.
- check-vision mặc định thử chuỗi đến model đầu trả lời được; --all thử
  từng model kể cả sau thành công/lỗi, in câu trả lời, thời gian và tổng
  số lỗi. Dùng ảnh ô đỏ và bộ đếm ai-check.sqlite3; không đăng nhập/gửi
  Messenger. Model trả sai màu cần người dùng đối chiếu kết quả.
- 370 kiểm thử offline đạt, gồm 54 ca bổ sung cho payload ảnh/ngữ cảnh/
  persona giữ nguyên qua cả năm model, HTTP/quota/cooldown/phục hồi, timeout
  và hủy request, ngân sách cục bộ, dừng khi nội dung lỗi, cô lập chuỗi chữ,
  CLI/cấu hình cũ/danh sách thủ công, thử tất cả model và đóng client.
  Tích hợp worker với HTTP mô phỏng kiểm tra tải một lần, tính đủ hai lượt
  gọi và chỉ gửi một hoặc không gửi phản hồi khi các nguồn đều thất bại.
- Ruff E4/E7/E9/F, CLI help, git diff --check và cú pháp 43 khối Bash trong
  README đạt; Python heredoc được kiểm tra AST, liên kết file cục bộ hợp lệ.
  Không gọi AI/Facebook thật, không triển khai hoặc sửa dữ liệu trên VPS.
  Cần chạy check-vision trên VPS và gửi ảnh mới để xác minh luồng thực tế.

## Chỉ dùng Google cho chữ và ảnh — 25/10/2026

- Thêm configure-google --only [--models ...]. Google có thể là nguồn chữ
  chính, không bắt buộc Groq/Cloudflare ở cuối chuỗi và không gọi trùng model
  Google đầu tiên. Lệnh tắt NVIDIA/dự phòng Groq/Cloudflare; ảnh đang bật
  chỉ giữ model Google; có --models thì áp dụng cùng danh sách, ảnh đang
  tắt được giữ tắt. Không có --models thì giữ thứ tự Google riêng từng chuỗi.
  Key nguồn
  khác vẫn được giữ để bật lại sau. Không thay cookie, persona, lịch sử
  hoặc các giới hạn; xác minh key/cấu hình trước khi ghi.
- Không cho tắt Google khi đó là nguồn chính mà chưa chọn nguồn khác.
  Cập nhật cookie ở chế độ Google hỏi đúng key Google, không hỏi key Groq.
  Cấu hình chế độ nguồn bổ sung cũ và các nguồn còn lại giữ cách hoạt động.
- 385 kiểm thử offline đạt, thêm 15 ca cho đổi từ chuỗi ảnh/nguồn đơn/ảnh
  tắt, thiếu key nguồn khác, bảo toàn dữ liệu và key, lỗi cấu hình không
  ghi dở, đổi cookie, CLI và HTTP thực tế qua MockTransport cho cả chữ/ảnh.
  Khi Google chính lỗi và model sau thành công hoặc cả hai đều lỗi, mọi
  request đều chỉ tới generativelanguage.googleapis.com, không gọi nguồn khác.
- Ruff E4/E7/E9/F, git diff --check, CLI help và cú pháp 44 khối Bash README
  đạt. Không gọi API/Facebook thật, không triển khai hoặc đổi cấu hình VPS.

## Thống nhất bật/tắt nhà cung cấp — 25/10/2026

- Cấu hình nguồn mới chỉ gồm provider_enabled, text_models và vision_models.
  Cờ true/false của từng nhà cung cấp lọc cả chữ/ảnh trước khi xác minh thông
  tin kết nối hoặc tạo HTTP client; không còn nguồn chính bắt buộc ở cuối.
  Tắt một nguồn không xóa model, thứ tự hoặc key. Tắt toàn bộ vẫn cho bot
  nhận tin, nhưng không gọi AI/gửi phản hồi và không tính ngân sách AI.
- Thêm providers để xem offline và providers enable/disable/only cho một
  hoặc nhiều tên nguồn. Bật/chỉ dùng nguồn yêu cầu đã chọn model và có key;
  tắt nguồn không cần đọc secrets. Cờ lưu chung cho cả hai tuyến ảnh/chữ.
- configure-ai hỗ trợ cả bốn nguồn, --model/--models dùng chung bộ xử lý.
  configure-google/configure-nvidia và các cờ cũ là lớp gọi tương thích;
  --fallback chuyển thành thao tác cờ nguồn. configure-vision --chain mẫu
  chỉ lấy nguồn đang bật/có key, không bật lại các nguồn đã tắt. Danh sách
  ảnh chọn tường minh bật các nguồn được nêu; danh sách chữ giữ nguyên.
- Đọc được cấu hình cũ; chuyển sang ba trường mới khi lưu cấu hình nguồn.
  Tạo config.before-providers.bak quyền 0600 trước khi đổi, không ghi đè bản
  sao đã có và bỏ qua file này trong Git. Giữ nguyên tuyến/thứ tự thực tế,
  kể cả nguồn chỉ dùng cho ảnh, chế độ Google duy nhất và cookie/persona/
  dữ liệu/giới hạn. Cấu hình cũ sai hoặc key thiếu không bị ghi dở.
- Cập nhật cookie giữ cờ và thứ tự model, kể cả tất cả nguồn đang tắt.
  Copy AI sang acc khác lấy danh sách/cờ theo cùng schema, vẫn yêu cầu
  cookie riêng và không lấy persona/lịch sử/thiết bị. Google pool chỉ tính
  thời gian đã dùng cho Google, để hỗ trợ xen nguồn trong thứ tự mới mà
  không tiêu hao thời gian chờ của Google khi đang gọi API khác.
- 426 kiểm thử offline đạt, gồm 41 ca mới cho thao tác giống nhau ở bốn
  nguồn, HTTP payload thật qua MockTransport cho cả chữ/ảnh khi thành công
  và lỗi, nguồn tắt không được gọi khi nguồn khác lỗi, không bắt buộc key
  của bên khác, tắt toàn bộ không tạo client/tính quota, chuyển cấu hình
  cũ/bản sao riêng tư, CLI, khởi tạo Google/NVIDIA và giữ thứ tự/cờ khi đổi
  cookie. Các kiểm thử cũ được cập nhật để kiểm tra schema mới và hành vi
  tắt mà vẫn giữ model, thay cho xóa model hoặc bắt buộc nguồn chính cũ.
- Ruff E4/E7/E9/F, git diff --check, CLI help, config.example.json và cú
  pháp 35 khối Bash + một khối JSON trong README đạt. Không gọi AI hay
  Facebook thật, không sửa dữ liệu hoặc triển khai trên VPS người dùng.

## Giữ lượt chờ và thử lại khi AI lỗi tạm thời — 25/10/2026

- Thêm ai_retry_enabled, mặc định true. Worker giữ câu hỏi/ảnh đang chờ khi
  mạng, timeout, 408/429/5xx hoặc NVIDIA xếp hàng, kể cả chỉ bật một nhà
  cung cấp. Lỗi tạm thời của cả chuỗi có cooldown theo model có thể thử sớm
  nhất; lỗi key/quyền/model 401/403/404/410 được phân biệt khi cần dừng thay
  vì lặp vô hạn. NVIDIA 202 cũng tôn trọng Retry-After.
- Mỗi vòng vẫn có deadline cũ, giữa vòng dùng backoff 5/10/20/40/60 giây và
  chờ lâu hơn theo cooldown/Retry-After. Khóa và thời gian nghỉ dùng chung
  giữa các chat của cùng chuỗi trong một bot, kiểm tra trước khi tải ảnh/
  tạo request. Tin mới không kéo dài hay rút ngắn cooldown hoặc tạo thêm
  request khi nguồn chưa sẵn sàng. Nguồn đang tắt vẫn không được gọi.
- Tuổi tin được lọc lúc nhận; lượt đã nhận có thể chờ vượt 120 giây. Không
  thêm nháp lỗi vào lịch sử. Tin mới dùng ngữ cảnh mới nhất; bạn tự rep/yêu
  cầu dừng hủy lượt chờ. Khi chờ quota tắt typing, thử thật mới bật lại.
  Event giúp hủy chờ ngay khi đóng bot, không đợi hết timer quota hàng giờ.
- Lỗi ngân sách AI cục bộ có kiểu riêng; giữ lượt tới nửa đêm giờ Việt Nam,
  không phát sinh HTTP vượt cap. Giữ lượt khi đạt cap rep/chat/ngày tương
  tự. Không tăng/reset ngân sách hay quota API. Sửa trường hợp tin mới đến
  ngay sau nửa đêm làm kéo thời gian nghỉ sang thêm một ngày, và trường hợp
  lỗi của bản nháp cũ làm mất tin mới vừa nhận trong lúc gọi AI.
- Ảnh đã xử lý được tái sử dụng trong RAM, tải một lần qua các vòng thử;
  không giữ semaphore trong lúc chờ. Không ghi ảnh/URL ký/khóa vào SQLite.
  Lượt gửi Messenger chưa rõ thành công vẫn ghi unknown và nhường, không
  gửi lại. Lượt chờ hiện không được lưu bền: dừng/restart xóa lượt chờ;
  check-ai/check-vision/chat-ai vẫn thử hữu hạn. false giữ cơ chế bỏ lượt.
- 446 kiểm thử offline đạt, gồm 20 ca mới cho thử quá số lần cũ và vượt
  tuổi tin, cập nhật câu mới/không phình lịch sử, tôn trọng cooldown giữa
  các chat, dừng/nhường/close, ảnh tái sử dụng, HTTP thật qua MockTransport
  khi một provider có nhiều model hồi phục và không dùng nguồn tắt, chờ
  reset quota cục bộ/giới hạn gửi, lỗi vĩnh viễn, gửi chưa rõ kết quả và
  cấu hình tắt retry. Cập nhật kiểm tra copy AI để giữ cả cờ retry.
- Ruff E4/E7/E9/F, git diff --check, cú pháp 35 khối Bash và một khối JSON
  README đạt. Chưa gọi AI/Facebook thật hoặc triển khai trên VPS người dùng.
