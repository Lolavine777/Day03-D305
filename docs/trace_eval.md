# 📊 BÁO CÁO GIÁM SÁT & ĐÁNH GIÁ (OBSERVABILITY TRACE LOGS)

*Dành cho Role 5: Observability & Reviewer*

---

## 🎯 1. BẢNG CHẤM ĐIỂM AGENTIC FIT (SCORING MATRIX)

**Đề tài:** Trợ lý tìm nhà trọ và đặt lịch xem nhà.

| Tiêu chí | Điểm (1-5) | Lý do đánh giá |
| :--- | :---: | :--- |
| 🧠 **Multi-step Reasoning** | **5/5** | Cần phân tích ngân sách, vị trí, tiện ích, thời gian di chuyển và yêu cầu của người thuê để lọc nhà phù hợp. |
| 🛠️ **Tool Interaction** | **5/5** | Cần tìm kiếm dữ liệu phòng trọ, kiểm tra tình trạng còn phòng, tra cứu khoảng cách và xem các khung giờ hẹn. |
| 🔀 **Dynamic Decision** | **5/5** | Nếu phòng đã được thuê, vượt ngân sách hoặc không có lịch xem phù hợp, agent phải tìm và đề xuất phương án thay thế. |
| ⏳ **Long Horizon** | **4/5** | Quy trình gồm nhiều bước: thu thập nhu cầu, tìm kiếm, so sánh, kiểm tra tình trạng phòng, chọn thời gian và đặt lịch xem. |
| **TỔNG ĐIỂM FIT** | **19/20** | **KẾT LUẬN: Bài toán rất phù hợp để triển khai bằng ReAct Agent.** |

### Kết luận Phase 1

Bài toán tìm nhà trọ không chỉ yêu cầu sinh câu trả lời bằng ngôn ngữ tự nhiên.
Hệ thống còn phải truy vấn dữ liệu nhà trọ, áp dụng nhiều điều kiện lọc, kiểm tra trạng thái và điều chỉnh hành động dựa trên kết quả của từng bước.
Vì vậy, ReAct Agent phù hợp hơn chatbot thông thường đối với các yêu cầu tìm kiếm và xử lý nhiều bước.

Trong phạm vi bài lab, dữ liệu có thể được lưu trong `data.json`.
Các tool sẽ đọc dữ liệu này để tìm, lọc và kiểm tra nhà trọ.
Core agent chịu trách nhiệm chọn tool, truyền tham số, nhận Observation và tổng hợp câu trả lời có căn cứ từ dữ liệu.

---

## 🔍 2. TRACE VÀ ĐÁNH GIÁ TEST CASES

*Phần này sẽ được hoàn thiện trong các phase tiếp theo sau khi bộ test case, tools và core agent đã sẵn sàng.*
