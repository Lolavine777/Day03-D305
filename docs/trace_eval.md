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

Phần này chỉ được điền sau khi Baseline và ReAct core chạy được đủ năm test case.

Các bằng chứng cần bổ sung:

- Raw output của Chatbot Baseline cho từng case.
- Phân loại `correct`, `safe fallback` hoặc `hallucinated`.
- Trace `Thought -> Action -> Observation -> Final Answer`.
- Số lần gọi LLM, số lần gọi tool và số vòng lặp.
- Một failed trace và Root Cause Analysis.
- Trace sau khi sửa Agent V2.
- Điểm factual correctness, grounding, tool selection và termination cho từng case.
