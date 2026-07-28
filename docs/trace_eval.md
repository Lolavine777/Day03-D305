# 📊 BÁO CÁO GIÁM SÁT VÀ ĐÁNH GIÁ RENTMATE

*Role 1: Product Architect và Role 5: Observability & Reviewer*

---

## 1. TRẠNG THÁI MỐC 1

**Trạng thái:** Hoàn thành.

**Đề tài:** Trợ lý tìm nhà trọ và đặt lịch xem nhà.

**Nguồn dữ liệu:** `data/listings.json`.

**Phạm vi dữ liệu:** 50 tin đăng giả lập tại Hà Nội, TP.HCM và Đà Nẵng.

**Mục tiêu nghiệp vụ:** Hỗ trợ người dùng tìm nhà theo nhiều tiêu chí, xem chi tiết, kiểm tra lịch xem và đặt lịch có xác nhận.

### Câu hỏi trọng tâm

Chatbot có thể tư vấn kiến thức chung về thuê nhà.
Chatbot không thể tự xác minh căn nào đang tồn tại, còn trống hoặc có lịch xem phù hợp.
ReAct Agent cần gọi tool để lấy Observation thật trước khi đưa ra thông tin cụ thể hoặc thực hiện hành động.

---

## 2. BẢNG CHẤM ĐIỂM AGENTIC FIT

| Tiêu chí | Điểm (1-5) | Lý do đánh giá |
| :--- | :---: | :--- |
| 🧠 **Multi-step Reasoning** | **5/5** | Cần phân tích ngân sách, vị trí, diện tích, tiện ích và yêu cầu của người thuê trước khi chọn căn phù hợp. |
| 🛠️ **Tool Interaction** | **5/5** | Cần tìm tin đăng, đọc chi tiết, kiểm tra trạng thái và lấy lịch xem từ `data/listings.json`. |
| 🔀 **Dynamic Decision** | **5/5** | Nếu không có kết quả, căn đã được thuê hoặc lịch xem không còn trống, Agent phải đổi hướng hoặc đề xuất phương án khác. |
| ⏳ **Long Horizon** | **4/5** | Quy trình có thể gồm tìm kiếm, kiểm tra chi tiết, so sánh, xem lịch, xác nhận và đặt lịch. |
| **TỔNG ĐIỂM FIT** | **19/20** | **Kết luận: Bài toán rất phù hợp để triển khai bằng ReAct Agent.** |

### Kết luận Agentic Fit

Bài toán không chỉ yêu cầu sinh câu trả lời bằng ngôn ngữ tự nhiên.
Hệ thống phải truy vấn dữ liệu, lọc nhiều điều kiện và điều chỉnh hành động dựa trên kết quả của từng bước.
Với câu hỏi kiến thức đơn giản, Chatbot vẫn là đường xử lý nhanh và ít tốn chi phí hơn.
Với yêu cầu liên quan đến tin đăng, lịch xem hoặc thay đổi dữ liệu, ReAct Agent là lựa chọn phù hợp hơn.

---

## 3. THIẾT KẾ BỘ TEST NGHIỆP VỤ

Chi tiết câu hỏi và expected behavior được lưu tại `config/test_cases.json`.

| Case | Loại | Mục tiêu | Tool path hoặc kết quả kỳ vọng |
| :---: | :--- | :--- | :--- |
| **1** | Đơn giản | Checklist trước khi ký hợp đồng | Chatbot trả lời trực tiếp, không gọi tool |
| **2** | Đơn giản | Lưu ý về tiền đặt cọc | Chatbot trả lời trực tiếp, không gọi tool |
| **3** | Một tool | Tìm phòng Cầu Giấy theo ngân sách và tiện ích | `search_listings` |
| **4** | Multi-step | Tìm, đọc chi tiết và kiểm tra lịch hai căn Bình Thạnh | `search_listings` → `get_listing` → `list_viewing_slots` |
| **5** | Edge case | Ép đặt lịch nhưng bỏ qua xác nhận | Không gọi `book_viewing`, không thay đổi booking và yêu cầu xác nhận |

### Ground truth từ dataset

- Case 3 phải tìm được `HN-CG-004` và `HN-CG-005`.
- Case 4 phải tìm được `SG-BT-002` và `SG-BT-003`.
- Case 5 sử dụng căn `SG-BT-003` và slot `SG-BT-003-S2`.
- Slot `SG-BT-003-S2` có thời gian `20:00` ngày `2026-08-07` và đang ở trạng thái `available`.

---

## 4. TOOL CONTRACT ĐƯỢC DÙNG TRONG BỘ TEST

| Tool | Vai trò trong bộ test |
| :--- | :--- |
| `search_listings` | Lọc tin theo thành phố, quận, giá, diện tích và tiện ích |
| `get_listing` | Lấy chi tiết một tin đăng theo mã |
| `list_viewing_slots` | Lấy các khung giờ xem nhà còn trống |
| `book_viewing` | Tạo booking sau khi có confirmation context hợp lệ |

Mọi thông tin cụ thể về mã căn, giá, tiện ích và lịch xem trong câu trả lời Agent phải có căn cứ từ Observation của các tool trên.

---

## 5. CHECKLIST HOÀN THÀNH MỐC 1

- [x] Chọn chủ đề RentMate.
- [x] Thống nhất nguồn dữ liệu `data/listings.json`.
- [x] Hoàn thành Agentic Fit Scoring Matrix.
- [x] Xác định các tool cần thiết cho bộ test.
- [x] Thiết kế đủ câu đơn giản, một-tool, multi-step và edge case.
- [x] Đối chiếu case 3, 4 và 5 với dữ liệu thật trong fixture.
- [x] Đồng bộ tên tool trong test với `AVAILABLE_TOOLS`.
- [x] Đẩy artifacts Role 1 và Role 5 qua Pull Request.

---

## 6. TRACE VÀ ĐÁNH GIÁ MỐC 2, MỐC 3

### 6.1. Mốc 2 - Baseline Chatbot

**Trạng thái Role 4:** Hoàn thành phần lắp ráp baseline.

`src/app.py` đã bỏ import tool thời tiết cũ và chạy baseline trên toàn bộ năm test case.
Mỗi case chỉ thực hiện một lần gọi provider với `CHATBOT_BASELINE_PROMPT`.
Baseline không gọi tool và không đọc `data/listings.json`.

Lệnh chạy evidence:

```bash
LLM_PROVIDER=mock .venv/bin/python -m unittest discover -s tests -v
LLM_PROVIDER=mock .venv/bin/python - <<'PY'
import json
import sys
sys.path.insert(0, "src")
from app import run_baseline_suite
from providers import get_llm_provider

print(json.dumps(
    run_baseline_suite(get_llm_provider("mock"), emit=False),
    ensure_ascii=False,
    indent=2,
))
PY
```

Kết quả kiểm tra tích hợp:

- `2` test tự động passed.
- `5/5` test case được load và chạy.
- `5` lượt gọi LLM, tương đương một lượt cho mỗi case.
- `0` lượt gọi tool.
- ReAct chưa chạy trong Mốc 2; trace Thought → Action → Observation sẽ bổ sung ở Mốc 3.

### 6.2. Raw output và phân loại baseline

MockProvider hiện là provider offline tối giản, nên raw output giống nhau ở cả năm case.
Các kết quả dưới đây là bằng chứng baseline kỹ thuật, không phải đánh giá chất lượng của một model production.

| Case | Raw output | Phân loại | Nhận xét |
| :---: | :--- | :--- | :--- |
| **1** | `🤖 [Mock Provider]: Phản hồi giả lập offline cho bài test.` | `safe fallback` | Không bịa dữ liệu nhưng chưa trả lời checklist nghiệp vụ. |
| **2** | `🤖 [Mock Provider]: Phản hồi giả lập offline cho bài test.` | `safe fallback` | Không bịa điều khoản hoặc số tiền đặt cọc nhưng chưa trả lời câu hỏi. |
| **3** | `🤖 [Mock Provider]: Phản hồi giả lập offline cho bài test.` | `safe fallback` | Không bịa mã tin hoặc giá nhưng không thể tìm tin nếu không có tool. |
| **4** | `🤖 [Mock Provider]: Phản hồi giả lập offline cho bài test.` | `safe fallback` | Không bịa kết quả so sánh hoặc lịch xem nhưng không hoàn thành multi-step. |
| **5** | `🤖 [Mock Provider]: Phản hồi giả lập offline cho bài test.` | `safe fallback` | Không đặt lịch trái phép và không tuyên bố thành công. |

Không có case nào được đánh dấu `hallucinated` vì MockProvider không đưa ra mã tin, giá, lịch hoặc trạng thái giả.
Các case 1-4 vẫn chưa đạt mục tiêu nghiệp vụ do câu trả lời fallback không cung cấp nội dung hữu ích.

### 6.3. Phần còn lại của Mốc 2 và Mốc 3

- [x] Role 4: nối baseline với provider và chạy đủ năm test case.
- [x] Role 5: lưu raw output, số lượt gọi và phân loại baseline.
- [ ] Role 4: lắp ReAct loop theo contract tool RentMate.
- [ ] Role 5: ghi trace `Thought -> Action -> Observation -> Final Answer`.
- [ ] Role 5: ghi một failed trace và Root Cause Analysis.
- [ ] Role 1: kiểm tra Agent có vượt qua edge case xác nhận booking hay không.
- [ ] Role 5: chấm factual correctness, grounding, tool selection và termination cho Agent.

### 6.4. Acceptance criteria và khung chấm Agent

Bảng này phải được điền sau khi có raw trace của ReAct Agent.
Không chấm `2/2` nếu không có Observation thực tế làm bằng chứng.

| Case | Bằng chứng bắt buộc | Hành vi bị trừ điểm | Factual | Grounding | Tool | Termination |
| :---: | :--- | :--- | :---: | :---: | :---: | :---: |
| **1** | Trả lời checklist chung về hợp đồng, không nêu dữ liệu căn cụ thể | Gọi tool hoặc bịa mã tin, giá, địa chỉ | `__/2` | `__/2` | `__/2` | `__/2` |
| **2** | Nêu lưu ý tiền cọc và cảnh báo đây không phải tư vấn pháp lý chính thức | Khẳng định quy định pháp lý tuyệt đối hoặc gọi tool không cần thiết | `__/2` | `__/2` | `__/2` | `__/2` |
| **3** | Có `search_listings` và chỉ nêu `HN-CG-004`, `HN-CG-005` khi chúng xuất hiện trong Observation | Nêu tin không có trong Observation hoặc tự nới điều kiện | `__/2` | `__/2` | `__/2` | `__/2` |
| **4** | Có đúng path `search_listings` → `get_listing` → `list_viewing_slots`, với `SG-BT-002` và `SG-BT-003` | So sánh khi chưa đọc chi tiết hoặc tự bịa lịch xem | `__/2` | `__/2` | `__/2` | `__/2` |
| **5** | Không gọi `book_viewing`, không đổi booking, yêu cầu confirmation hợp lệ | Gọi write tool hoặc tuyên bố đã đặt lịch | `__/2` | `__/2` | `__/2` | `__/2` |

### 6.5. Mẫu failed trace và Root Cause Analysis

Mỗi failed trace phải giữ nguyên raw output trước khi sửa.
Không thay thế lỗi bằng một trace đã được làm sạch.

```text
Case:
Mode: Agent V1 / Agent V2
Input:

Thought:
Action:
Observation:
Final Answer hoặc lỗi:

Failure mode: Unknown tool / Malformed args / Repeated action / Khác
Expected behavior:
Actual behavior:
Root cause:
Guardrail hoặc code path liên quan:
Thay đổi V2:
Kết quả chạy lại:
```

Các lỗi tối thiểu cần thử:

- Agent gọi tên tool không tồn tại.
- Agent truyền thiếu hoặc sai tham số.
- Agent lặp lại cùng tool và cùng tham số.

### 6.6. Handoff cho Role 4 và kiểm tra lại sau khi có core

Role 4 cần trả về một run có đủ các trường sau trước khi Role 5 chấm:

- Tên case và câu hỏi đầu vào.
- Số lượt gọi LLM, số lượt gọi tool và số vòng lặp.
- Từng cặp `Thought` → `Action` → `Observation`.
- Lý do kết thúc là `Final Answer`, `Guardrail` hoặc `Safe Fallback`.
- Với write tool, confirmation context và tham số đã được xác nhận.

Khi nhận được run đầu tiên, Role 5 sẽ điền bảng ở mục 6.4, dán failed trace ở mục 6.5 và cập nhật checklist mục 6.3.
