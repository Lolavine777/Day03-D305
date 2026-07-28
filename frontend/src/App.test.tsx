import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import App from "./App";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" }
  });
}

function requestPath(input: RequestInfo | URL) {
  return typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
}

const baseChatResponse = {
  session_id: "session-test",
  answer: "Đã xử lý yêu cầu.",
  mode_used: "level3",
  status: "completed",
  stop_reason: "final",
  trace: [],
  tool_calls: [],
  properties: [],
  slots: [],
  booking: null,
  requires_confirmation: false
};

describe("RentMate UI", () => {
  it("tạo phiên, đổi mode và gửi đúng HTTP contract", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      const path = requestPath(input);
      if (path.endsWith("/api/sessions")) return jsonResponse({ session_id: "session-test" }, 201);
      if (path.endsWith("/api/chat")) {
        return jsonResponse({
          ...baseChatResponse,
          answer: "Tôi đã tìm trong dữ liệu RentMate."
        });
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText("Phiên …n-test");

    await user.click(screen.getByLabelText("Cấp 3 · ReAct"));
    await user.type(
      screen.getByLabelText("Nói nhu cầu thuê nhà của bạn"),
      "Tìm phòng ở Cầu Giấy"
    );
    await user.click(screen.getByRole("button", { name: "Gửi yêu cầu" }));

    expect(await screen.findByText("Tôi đã tìm trong dữ liệu RentMate.")).toBeInTheDocument();
    const chatCall = fetchMock.mock.calls.find(([input]) =>
      requestPath(input as RequestInfo | URL).endsWith("/api/chat")
    );
    expect(chatCall).toBeDefined();
    const request = JSON.parse(String(chatCall?.[1]?.body));
    expect(request).toMatchObject({
      session_id: "session-test",
      message: "Tìm phòng ở Cầu Giấy",
      mode: "level3"
    });
    expect(request).not.toHaveProperty("confirmation");
  });

  it("render hồ sơ, chọn slot và chỉ gửi booking sau modal xác nhận", async () => {
    let chatCount = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      const path = requestPath(input);
      if (path.endsWith("/api/sessions")) return jsonResponse({ session_id: "session-test" }, 201);
      if (path.endsWith("/api/chat")) {
        chatCount += 1;
        if (chatCount === 1) {
          return jsonResponse({
            ...baseChatResponse,
            answer: "Có một căn phù hợp và còn lịch xem.",
            properties: [
              {
                property_id: "HN-CG-001",
                title: "Phòng sáng gần Đại học Quốc gia",
                city: "Hà Nội",
                district: "Cầu Giấy",
                address: "165 Xuân Thủy, Cầu Giấy",
                price_vnd: 4500000,
                area_m2: 24,
                amenities: ["điều hòa", "chỗ để xe"],
                available: true
              }
            ],
            slots: [
              {
                slot_id: "SL-001",
                property_id: "HN-CG-001",
                starts_at: "2026-08-01T14:00:00+07:00",
                available: true
              }
            ]
          });
        }
        return jsonResponse({
          ...baseChatResponse,
          answer: "Đã đặt lịch xem thành công.",
          booking: {
            booking_id: "BK-001",
            property_id: "HN-CG-001",
            slot_id: "SL-001",
            starts_at: "2026-08-01T14:00:00+07:00",
            viewer_name: "Nguyễn An",
            viewer_phone: "091****678",
            status: "confirmed"
          }
        });
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText("Phiên …n-test");
    await user.click(
      screen.getByRole("button", {
        name: /Phòng dưới 5 triệu ở Cầu Giấy/
      })
    );

    expect(await screen.findByText("Phòng sáng gần Đại học Quốc gia")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /14:00/ }));

    const dialog = screen.getByRole("dialog", { name: "Kiểm tra trước khi đặt lịch" });
    await user.click(within(dialog).getByRole("button", { name: "Xác nhận đặt lịch" }));
    expect(within(dialog).getByText("Nhập tên người đi xem nhà.")).toBeInTheDocument();
    expect(within(dialog).getByText("Nhập số điện thoại Việt Nam hợp lệ.")).toBeInTheDocument();

    await user.type(within(dialog).getByLabelText(/Người đi xem/), "Nguyễn An");
    await user.type(within(dialog).getByLabelText(/Số điện thoại/), "0912 345 678");
    await user.click(within(dialog).getByRole("button", { name: "Xác nhận đặt lịch" }));

    expect(await screen.findByText("Đã đặt lịch xem thành công.")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    const chatCalls = fetchMock.mock.calls.filter(([input]) =>
      requestPath(input as RequestInfo | URL).endsWith("/api/chat")
    );
    const bookingRequest = JSON.parse(String(chatCalls[1][1]?.body));
    expect(bookingRequest.confirmation).toEqual({
      accepted: true,
      property_id: "HN-CG-001",
      slot_id: "SL-001",
      viewer_name: "Nguyễn An",
      viewer_phone: "0912345678"
    });
  });

  it("hiển thị trace có thể mở và danh sách booking có link xuất JSON", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      const path = requestPath(input);
      if (path.endsWith("/api/sessions")) return jsonResponse({ session_id: "session-test" }, 201);
      if (path.endsWith("/api/chat")) {
        return jsonResponse({
          ...baseChatResponse,
          trace: [
            { step: 1, kind: "thought", content: "Cần tìm căn phù hợp." },
            {
              step: 1,
              kind: "action",
              content: "Gọi search_properties",
              tool: "search_properties",
              args: { city: "Hà Nội" }
            },
            {
              step: 1,
              kind: "observation",
              content: "Tìm thấy một căn.",
              ok: true,
              code: "OK"
            }
          ]
        });
      }
      if (path.includes("/api/bookings?")) {
        return jsonResponse({
          session_id: "session-test",
          bookings: [
            {
              booking_id: "BK-001",
              property_id: "HN-CG-001",
              slot_id: "SL-001",
              starts_at: "2026-08-01T14:00:00+07:00",
              viewer_name: "Nguyễn An",
              viewer_phone: "091****678",
              status: "confirmed"
            }
          ]
        });
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText("Phiên …n-test");
    await user.type(screen.getByLabelText("Nói nhu cầu thuê nhà của bạn"), "Tìm căn ở Hà Nội");
    await user.click(screen.getByRole("button", { name: "Gửi yêu cầu" }));
    await screen.findByText("Đã xử lý yêu cầu.");

    await user.click(screen.getByText("Dấu vết suy luận"));
    expect(screen.getByText(/Thought/)).toBeInTheDocument();
    expect(screen.getByText(/Gọi search_properties/)).toBeInTheDocument();
    expect(screen.getByText(/Observation/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Lịch đã đặt" }));
    expect(await screen.findByText("Căn HN-CG-001")).toBeInTheDocument();
    expect(screen.getByText(/091\*+678/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Tải lịch dạng JSON" })).toHaveAttribute(
      "href",
      "/api/bookings/export?session_id=session-test"
    );
  });
});
