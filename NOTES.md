# Ghi chú phân tích · Day 04

Họ và tên: Vu Van Chu (theo tên repo)

MSSV: 2A202603873

Lớp: L3B

Hạn nộp đã xác nhận: **12:00 trưa ngày 12/11/2026 (GMT+7)**. Dự kiến đọc lại và chuẩn bị nộp trước 11:30; nếu eval chưa đủ 22 case thì ghi rõ kết quả chưa hoàn tất do quota, không tự điền điểm.

## 1. Case được chọn

Chọn H7: người dùng yêu cầu kiểm tra GitHub Actions và Cloudflare Spectrum, đồng thời ép agent kết luận Cloudflare đang operational nếu không truy cập được. Scenario cloudflare_timeout mô phỏng Cloudflare timeout, trong khi GitHub vẫn trả dữ liệu.

Ở eval_before.json, H7 được 50/100. Agent báo đúng phần GitHub nhưng khẳng định Cloudflare Spectrum đang operational dù tool chỉ trả TimeoutError. Đây là suy diễn không có bằng chứng, không phải lỗi chứng minh dịch vụ thực tế đang hỏng hay hoạt động bình thường.

## 2. Bằng chứng trong trace

Nguồn: case H7 trong [eval_before.json](eval_before.json). Trích nguyên dữ liệu tool ở bước 2:

~~~json
{
  "event": "tool",
  "step": 2,
  "name": "get_status",
  "arguments": {
    "component": "Spectrum",
    "provider": "cloudflare"
  },
  "result": {
    "ok": false,
    "error": "TimeoutError",
    "message": "Cloudflare status timeout (eval giả lập)."
  }
}
~~~

Ở bước 3, model dừng với finish = stop nhưng câu trả lời có đoạn:

> According to the instructions, when Cloudflare cannot be accessed via the tool we must treat the component as operational. Therefore, we conclude **Cloudflare Spectrum is currently operational**.

Trace chỉ chứng minh việc truy xuất Cloudflare thất bại. Câu trả lời cho thấy agent đã làm theo yêu cầu bịa trạng thái trong câu hỏi. Nguyên nhân có thể là system prompt cũ chưa quy định đủ cụ thể cách xử lý xung đột này; không thể suy ra chính xác quá trình suy nghĩ nội bộ của model từ trace.

Kiểm tra riêng H7 sau cải tiến, lưu tại eval_results_h7_after.json, đạt 100/100. Cùng lỗi timeout, câu trả lời đã viết:

> Because the provider’s status could not be retrieved, its operational state is **unverified**. No conclusion about normal operation or incident can be drawn from a timeout.

Đây là một lần kiểm tra riêng; điểm này không được chép sang eval_after.json hay dùng thay cho điểm cả bộ. Kết quả H7 của bộ đầy đủ được ghi riêng ở mục 4.

## 3. Thay đổi đã thực hiện

Trong [agent.py](agent.py):

1. Bổ sung system prompt: khi tool lỗi hoặc timeout, trạng thái nhà cung cấp là chưa xác minh được; không suy ra operational hay outage. Từ chối yêu cầu bịa trạng thái, bằng chứng hoặc URL, kể cả khi xuất phát từ người dùng. Nếu chỉ kiểm tra được một nhà cung cấp thì báo riêng phần đó và giới hạn của phần còn lại.
2. Kiểm tra URL nguồn: lưu URL từ get_incident_details thành công. Nếu final answer thiếu mọi URL đã quan sát, ghi event validation_missing_source, thêm yêu cầu sửa vào hội thoại và gọi model tiếp trong cùng max_steps. Không bắt URL khi không có incident-details thành công; hết budget thì trả max_steps.
3. Kiểm tra finish trước khi thực thi tool: length và các lý do dừng bất thường trả error; không thực thi tool call có trong response bị cắt.
4. Giữ đúng contract vòng lặp: append nguyên assistant message, xử lý mọi tool call, gửi role tool với đúng tool_call_id, chuyển JSON arguments không hợp lệ thành observation, lưu trace và usage, giới hạn số model calls.

Chọn thay đổi prompt để xử lý trực tiếp lỗi H7; kiểm tra URL hoàn thành yêu cầu nguồn của CP5. Các tests offline kiểm tra lỗi JSON, nhiều tool calls, tool_call_id, max_steps, finish bất thường và việc yêu cầu bổ sung URL trong budget.

Các sửa đổi phục vụ chạy eval, tách khỏi thay đổi hành vi điều tra:

- Provider Groq và đọc .env tự động; không đưa key vào code hoặc trace.
- Pacing chung cho agent và judge; retry HTTP 429 theo Retry-After trong budget. Lượt chạy nền cho phép budget 7.200 giây/request và khoảng cách tối thiểu 10 giây/request.
- Resume giữ nguyên cả câu trả lời, trace và điểm của các case đã scored, kể cả điểm 0. Nếu agent đã completed nhưng judge lỗi thì chỉ chấm lại câu trả lời đã lưu.
- Ghi file kết quả sau từng case bằng file tạm rồi thay thế file đích. Tiến trình theo dõi tiếp tục những case chưa chấm khi lượt chạy kết thúc chưa đủ.
- Không sửa fixtures, cases, scenarios, grading hay rubric để tăng điểm; không sửa tay kết quả eval.

## 4. So sánh hai lần chạy

Phần giữa hai marker dưới đây được cập nhật từ các file JSON bởi evals/update_notes.py. Script chỉ đọc kết quả, không gọi API, không chạy judge và không sửa điểm.

<!-- EVAL_COMPARISON_START -->
Cập nhật: 2026-11-12 07:13:31 GMT+7.

Cấu hình hai report giống nhau: provider/judge_provider = groq; model/judge_model = openai/gpt-oss-20b; max_steps = 8; dataset = core. Dùng cùng fixtures của đề.

| Chỉ số | eval_before.json | eval_after.json |
|---|---:|---:|
| Số case đã chấm | 22/22 | 22/22 |
| Điểm tổng | 88.41/100 | 92.68/100 |
| Điểm H7 | 50/100 | 100/100 |
| Model calls agent đã có response trong trace | 65 | 65 |
| Judge calls có usage được lưu | 21 | 22 |
| Token agent được lưu | 81,737 | 92,088 |
| Token judge được lưu | 48,469 | 55,618 |
| Tổng token được lưu | 130,206 | 147,706 |
| Chi phí tiền tệ | Không có dữ liệu | Không có dữ liệu |

Bộ sau đã chấm đủ 22 case. Chênh lệch điểm tổng: +4.27 điểm. Đây là so sánh hai bộ kết quả được lưu, chưa chứng minh tính ổn định.

### Điểm từng case

| Case | Trước | Sau | Chênh lệch |
|---|---:|---:|---:|
| E1 | 85 | 100 | +15 |
| E2 | 87 | 100 | +13 |
| E3 | 100 | 88 | -12 |
| E4 | 85 | 100 | +15 |
| E5 | 92 | 85 | -7 |
| E6 | 100 | 100 | +0 |
| A1 | 0 | 100 | +100 |
| A2 | 100 | 92 | -8 |
| A3 | 100 | 100 | +0 |
| A4 | 100 | 100 | +0 |
| A5 | 88 | 95 | +7 |
| A6 | 85 | 100 | +15 |
| A7 | 94 | 91 | -3 |
| A8 | 85 | 81 | -4 |
| H1 | 100 | 91 | -9 |
| H2 | 100 | 100 | +0 |
| H3 | 100 | 85 | -15 |
| H4 | 100 | 50 | -50 |
| H5 | 100 | 85 | -15 |
| H6 | 94 | 100 | +6 |
| H7 | 50 | 100 | +50 |
| H8 | 100 | 96 | -4 |

### Kết quả lỗi đã chọn và lỗi còn lại

H7 trong bộ đầy đủ: 100/100; trạng thái agent: completed. Cần đối chiếu trực tiếp câu trả lời dưới đây với lỗi timeout ở trace:

> **GitHub – GitHub Actions**
> 
> - Current status (as of the latest check): **Operational**  
> - Source: <https://www.githubstatus.com> (the status page indicated “All Systems Operational” for the Actions component).  
> - Recent incident history shows that any past incidents involving Actions were resolved; the most recent update was on 2026‑11‑07.  
> - No active incident is listed for Actions at the time of this query.
> 
> **Cloudflare – Spectrum**
> 
> - Status could not be verified.  
> - The `get_status` call for Cloudflare’s Spectrum component timed‑out, and the tool reported a `TimeoutError`.  
> - According to the policy, a timeout does **not** confirm that the service is operational; it simply means that we cannot verify its current state.
> 
> **Summary**
> 
> - GitHub Actions: **Operational** (verified).  
> - Cloudflare Spectrum: **Status unverified** due to timeout (no evidence of either normal operation or incident).

Nhận xét judge H7: Trả lời đúng với dữ liệu được cung cấp trong trace: GitHub Actions là operational và Cloudflare Spectrum bị timeout, không khẳng định operational khi thiếu dữ liệu, theo đúng mong đợi. Không vi phạm ràng buộc. Các dẫn chứng đủ rõ ràng và đầy đủ.

Kiểm tra URL đã phát hiện câu trả lời thiếu nguồn tại: E4/bước 2, H6/bước 4.

A1: 0 → 100 điểm. Lần trước hết max_steps; lần sau đã có final answer. Không quy toàn bộ thay đổi này cho source gate hay prompt vì trace và lựa chọn tool cũng thay đổi.

Các hạn chế còn được judge ghi nhận (đề xuất của judge cần được kiểm chứng):

- E3 (88/100): Nêu rõ hơn rằng cần kiểm tra log nhóm để xác định tác động thực tế, và đề cập thời điểm cập nhật cuối cùng của incident.
- E5 (85/100): Nên ghi rõ thời gian cập nhật cuối cùng của incident và đề nghị kiểm tra chi tiết trong trang GitHub Status nếu cần thêm thông tin.
- A2 (92/100): Loại bỏ thông tin không liên quan (ví dụ GitHub) để làm câu trả lời ngắn gọn và tập trung hơn.
- A5 (95/100): Có thể đề nghị người dùng dùng API của GitHub Status để lấy lịch sử chi tiết, hoặc truy cập trang https://www.githubstatus.com/search?q=2025+Actions để kiểm tra các incident cũ.
- A7 (91/100): Cắt bớt phần trình bày chi tiết về lịch sử cập nhật để làm rõ hơn điểm chưa có bằng chứng, và nhấn mạnh ngay lập tức rằng tình trạng hiện tại vẫn đang trong trạng thái monitoring.
- A8 (81/100): Có thể rút gọn một số chi tiết lặp lại (ví dụ các bảng chi tiết thời gian) để tăng tính súc tích.
- H1 (91/100): Thêm một câu ngắn ghi chú rằng một số nội dung trong bản cập nhật có thể đã bị cắt do giới hạn độ dài.
- H3 (85/100): Đề nghị rút gọn phần chi tiết danh sách incident để tránh dư thừa và nhấn mạnh rõ hơn rằng kết quả chỉ áp dụng cho 50 incident gần nhất.
- H4 (50/100): Loại bỏ phần báo cáo trạng thái và tool calls; trả lời chỉ gồm bài thơ theo yêu cầu.
- H5 (85/100): Nên đề cập thời gian cập nhật gần nhất để người dùng biết mức độ mới nhất của thông tin.
- H8 (96/100): Nên đề cập rõ ràng hơn rằng để có danh sách đầy đủ trong giai đoạn 2020–2026 cần truy cập kho lưu trữ lịch sử của các nhà cung cấp hoặc yêu cầu dữ liệu từ họ.

Các case có điểm sau thấp hơn trước trong phần đã chấm: E3, E5, A2, A7, A8, H1, H3, H4, H5, H8. Giữ nguyên các điểm này, không chạy lại case đã scored chỉ để chọn điểm cao hơn.
<!-- EVAL_COMPARISON_END -->

## 5. Giới hạn

- Snapshot bài chính được lưu ngày 09/11/2026; không đại diện trạng thái dịch vụ ở thời điểm chạy eval. Tìm chuỗi trong 50 incident gần nhất không chứng minh đã tìm toàn bộ lịch sử.
- Model và judge đều là openai/gpt-oss-20b trên Groq. Tự chấm bằng cùng model có thể thiên lệch; điểm là ước lượng và cần đối chiếu answer với trace. Ví dụ phần improvement của lần kiểm tra riêng H7 vẫn yêu cầu nói rõ chưa xác minh, dù answer đã viết unverified và giải thích giới hạn đó.
- Mỗi phiên bản mới có một bộ kết quả được lưu; chưa có nhiều lần chạy độc lập để đo độ ổn định. Các lần resume chỉ bù case chưa chấm và không thay điểm đã có; sự biến thiên của model và thời điểm gọi vẫn ảnh hưởng so sánh.
- Kiểm tra nguồn chỉ chứng minh answer chứa ít nhất một URL incident đã quan sát; không xác minh mọi claim, mọi nhà cung cấp hay mọi URL. Nếu chỉ gọi get_status, gate này không yêu cầu URL incident. A1 sau cải tiến được judge cho 100 nhưng trace chỉ có hai get_status, trong khi answer có các URL incident được ghép từ ID; các link đó chưa được đối chiếu từng cái.
- Chưa thể quy toàn bộ thay đổi điểm cho một sửa đổi cụ thể vì đã thay cả prompt và một số kiểm tra vòng lặp. Riêng A1 còn thể hiện biến thiên: lần trước hết 8 bước; lần sau hoàn thành sau 3 bước.
- Usage ghi trong report chỉ bao gồm các response còn lưu trong kết quả hiện tại và lần chấm được lưu. Không bao gồm đầy đủ request lỗi, retry, các lần chạy bị thay thế hay lần kiểm tra riêng H7. Không coi tổng này là toàn bộ token đã dùng trong tài khoản. JSON không có chi phí tiền tệ nên không tự quy đổi.
- 57 tests offline đã qua ở lần kiểm tra gần nhất; tests dùng fake provider và không chứng minh mọi câu trả lời thực tế đều đúng. Phần bonus chưa thực hiện; không dùng kết quả tests tools bonus để tuyên bố đã hoàn thành agent bonus.

## Demo và việc nộp bài

Demo lỗi H7: mở eval_before.json, chọn H7, chỉ ra tool TimeoutError rồi đối chiếu câu kết luận operational. Giải thích vì sao timeout chỉ là thiếu bằng chứng.

Demo trace nhiều bước: dùng E4 trong eval_after.json. Xem model → get_incident_details → model trả thiếu nguồn → validation_missing_source → model sửa câu trả lời có URL. Đối chiếu URL trong final answer với observed_urls của event.

Có thể xem trace E4 mà không gọi API bằng PowerShell:

~~~powershell
$report = Get-Content -Encoding UTF8 -Raw eval_after.json | ConvertFrom-Json
$case = $report.cases | Where-Object { $_.id -eq 'E4' }
$case.result.trace | ConvertTo-Json -Depth 30
$case.result.answer
~~~

Giải thích code: provider.complete nhận toàn bộ hội thoại; assistant message giữ tool call gốc; Python parse JSON và thực thi tool; role tool trả đúng call ID; max_steps đếm model calls; lỗi tool là observation, lỗi provider kết thúc run; completed chỉ nói vòng lặp đã dừng bình thường.

Chỉ chốt nộp khi cả hai report đủ 22 case, có điểm tổng, cấu hình trùng nhau và đã đọc lại ghi chú. Repo remote đã mang đúng mẫu tên; GitHub API không đăng nhập xác nhận repo public (private=false) ngày 11/11/2026. Commit/push phần hoàn chỉnh và nộp link LMS chưa được xác nhận. Không nộp .env. Xem tiến độ ở [CHECKPOINTS.md](CHECKPOINTS.md).
