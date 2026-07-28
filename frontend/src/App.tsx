import { useEffect, useRef, useState } from "react";
import { ApiError, bookingExportUrl, createSession, listBookings, sendChat } from "./api";
import { BookingDrawer } from "./components/BookingDrawer";
import { ChatComposer } from "./components/ChatComposer";
import { ConfirmationModal } from "./components/ConfirmationModal";
import { Icon } from "./components/Icon";
import { ModeSelector } from "./components/ModeSelector";
import { PropertyCard } from "./components/PropertyCard";
import { SlotPicker } from "./components/SlotPicker";
import { TracePanel } from "./components/TracePanel";
import type {
  AgentMode,
  Booking,
  ChatMessage,
  ConfirmationContext,
  Property,
  TraceEntry,
  ViewingSlot
} from "./types";

const SESSION_KEY = "rentmate.session.v1";

const WELCOME_MESSAGE: ChatMessage = {
  id: "welcome",
  role: "assistant",
  content:
    "Chào bạn, mình là RentMate. Hãy cho mình biết khu vực, ngân sách và điều bạn không muốn thỏa hiệp ở chỗ ở mới."
};

const SUGGESTIONS = [
  "Phòng dưới 5 triệu ở Cầu Giấy, có điều hòa và chỗ để xe",
  "Căn hộ Bình Thạnh từ 30 m², ngân sách 12 triệu",
  "Tôi cần kiểm tra gì trước khi ký hợp đồng thuê?"
];

const MODE_LABELS: Record<AgentMode, string> = {
  auto: "Auto",
  level1: "Cấp 1 · Theo luật",
  level2: "Cấp 2 · Chatbot",
  level3: "Cấp 3 · ReAct",
  level4: "Cấp 4 · Lập kế hoạch"
};

function makeId() {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
}

function messageModeLabel(mode?: string) {
  if (!mode) return undefined;
  return MODE_LABELS[mode as AgentMode] ?? mode;
}

function App() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionPending, setSessionPending] = useState(true);
  const [mode, setMode] = useState<AgentMode>("auto");
  const [messages, setMessages] = useState<ChatMessage[]>([WELCOME_MESSAGE]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [properties, setProperties] = useState<Property[]>([]);
  const [slots, setSlots] = useState<ViewingSlot[]>([]);
  const [trace, setTrace] = useState<TraceEntry[]>([]);
  const [stopReason, setStopReason] = useState<string>();
  const [requiresConfirmation, setRequiresConfirmation] = useState(false);
  const [confirmationTarget, setConfirmationTarget] = useState<{
    property: Property;
    slot: ViewingSlot;
  } | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [bookings, setBookings] = useState<Booking[]>([]);
  const [bookingDrawerOpen, setBookingDrawerOpen] = useState(false);
  const [bookingsLoading, setBookingsLoading] = useState(false);
  const feedEndRef = useRef<HTMLDivElement>(null);

  const hasUserMessage = messages.some((message) => message.role === "user");
  const journeyStage = bookings.length ? 3 : slots.length ? 2 : properties.length ? 1 : 0;

  useEffect(() => {
    let active = true;
    const existing = localStorage.getItem(SESSION_KEY);
    if (existing) {
      setSessionId(existing);
      setSessionPending(false);
      return () => {
        active = false;
      };
    }

    createSession()
      .then((session) => {
        if (!active) return;
        localStorage.setItem(SESSION_KEY, session.session_id);
        setSessionId(session.session_id);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setError(
          reason instanceof Error
            ? reason.message
            : "Không thể tạo phiên làm việc. Kiểm tra backend rồi thử lại."
        );
      })
      .finally(() => active && setSessionPending(false));

    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    feedEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [loading, messages]);

  const dispatchMessage = async (
    text: string,
    confirmationContext?: ConfirmationContext
  ): Promise<{ ok: boolean; status?: number }> => {
    if (!sessionId || loading) return { ok: false };

    setError(null);
    setLoading(true);
    setMessages((current) => [
      ...current,
      { id: makeId(), role: "user", content: text, mode: MODE_LABELS[mode] }
    ]);

    try {
      const response = await sendChat({
        session_id: sessionId,
        message: text,
        mode,
        ...(confirmationContext ? { confirmation: confirmationContext } : {})
      });

      if (response.session_id && response.session_id !== sessionId) {
        localStorage.setItem(SESSION_KEY, response.session_id);
        setSessionId(response.session_id);
      }

      setMessages((current) => [
        ...current,
        {
          id: makeId(),
          role: "assistant",
          content: response.answer,
          mode: messageModeLabel(response.mode_used),
          stopReason: response.stop_reason
        }
      ]);
      if (response.properties) setProperties(response.properties);
      if (response.slots) setSlots(response.slots);
      if (response.trace) setTrace(response.trace);
      setStopReason(response.stop_reason);
      setRequiresConfirmation(Boolean(response.requires_confirmation));
      if (response.booking) {
        setBookings((current) => {
          const withoutDuplicate = current.filter(
            (booking) => booking.booking_id !== response.booking?.booking_id
          );
          return response.booking ? [response.booking, ...withoutDuplicate] : current;
        });
      }
      return { ok: true };
    } catch (reason: unknown) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Không thể gửi yêu cầu. Kiểm tra kết nối backend rồi thử lại."
      );
      return {
        ok: false,
        ...(reason instanceof ApiError ? { status: reason.status } : {})
      };
    } finally {
      setLoading(false);
    }
  };

  const checkSlots = (property: Property) => {
    void dispatchMessage(
      `Kiểm tra các lịch xem còn trống trong 7 ngày tới cho căn ${property.property_id}.`
    );
  };

  const chooseSlot = (slot: ViewingSlot) => {
    if (!slot.confirmation_token?.trim()) {
      setError(
        "Khung giờ này thiếu mã xác nhận an toàn. Hãy tra lịch lại rồi chọn một khung giờ mới."
      );
      setConfirmationTarget(null);
      return;
    }

    setError(null);
    const property =
      properties.find((item) => item.property_id === slot.property_id) ??
      ({
        property_id: slot.property_id,
        title: `Căn ${slot.property_id}`
      } satisfies Property);
    setConfirmationTarget({ property, slot });
  };

  const confirmBooking = async (context: ConfirmationContext) => {
    setConfirming(true);
    const result = await dispatchMessage(
      `Xác nhận đặt lịch xem căn ${context.property_id} ở khung giờ đã chọn.`,
      context
    );
    setConfirming(false);
    if (result.ok) {
      setConfirmationTarget(null);
    } else if (result.status === 403) {
      setConfirmationTarget(null);
      setSlots([]);
      setRequiresConfirmation(false);
    }
  };

  const openBookings = async () => {
    if (!sessionId) return;
    setBookingDrawerOpen(true);
    setBookingsLoading(true);
    setError(null);
    try {
      setBookings(await listBookings(sessionId));
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "Không thể tải danh sách lịch.");
    } finally {
      setBookingsLoading(false);
    }
  };

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="RentMate — trang chính">
          <span className="brand-mark" aria-hidden="true">
            <span>R</span>
            <i />
            <span>M</span>
          </span>
          <span className="brand-copy">
            <strong>RentMate</strong>
            <small>Rental viewing concierge</small>
          </span>
        </a>

        <ModeSelector disabled={loading} onChange={setMode} value={mode} />

        <div className="header-actions">
          <span className="session-status" title={sessionId ?? "Đang tạo phiên"}>
            <i className={sessionId ? "is-online" : ""} />
            {sessionPending
              ? "Đang nối"
              : sessionId
                ? `Phiên …${sessionId.slice(-6)}`
                : "Mất kết nối"}
          </span>
          <button className="booking-button" disabled={!sessionId} onClick={openBookings} type="button">
            <Icon name="calendar" size={18} />
            <span>Lịch đã đặt</span>
            {bookings.length ? <b>{bookings.length}</b> : null}
          </button>
        </div>
      </header>

      <nav aria-label="Tiến trình tìm chỗ ở" className="journey-strip">
        {["Nói nhu cầu", "Chọn căn phù hợp", "Giữ lịch xem"].map((label, index) => (
          <div className={journeyStage >= index ? "is-reached" : ""} key={label}>
            <span>{journeyStage > index ? <Icon name="check" size={13} /> : index + 1}</span>
            <p>{label}</p>
          </div>
        ))}
      </nav>

      <main className="workspace">
        <section className="conversation-desk" aria-label="Hội thoại với RentMate">
          {!hasUserMessage ? (
            <div className="conversation-intro">
              <div className="intro-copy">
                <p className="eyebrow">Một chỗ ở vừa vặn bắt đầu từ một câu hỏi đúng</p>
                <h1>
                  Tìm nơi ở
                  <em> hợp nhịp sống.</em>
                </h1>
                <p>
                  Nói điều bạn cần theo cách tự nhiên. RentMate sẽ biết lúc nào nên tư vấn,
                  lúc nào cần mở dữ liệu và lúc nào phải dừng để bạn xác nhận.
                </p>
              </div>
              <div className="blueprint-house" aria-hidden="true">
                <span className="house-sun" />
                <span className="house-roof" />
                <span className="house-body" />
                <span className="house-door" />
                <span className="house-window window-one" />
                <span className="house-window window-two" />
                <small>10°47′N · 106°41′E</small>
              </div>
            </div>
          ) : null}

          <div aria-live="polite" className="chat-feed">
            {messages.map((message) => (
              <article className={`message message-${message.role}`} key={message.id}>
                <div className="message-author">
                  {message.role === "assistant" ? (
                    <span className="assistant-avatar">
                      <Icon name="spark" size={15} />
                    </span>
                  ) : (
                    <span className="user-avatar">B</span>
                  )}
                  <p>{message.role === "assistant" ? "RentMate" : "Bạn"}</p>
                  {message.mode ? <small>{message.mode}</small> : null}
                </div>
                <div className="message-bubble">
                  <p>{message.content}</p>
                  {message.stopReason ? <span>Dừng: {message.stopReason}</span> : null}
                </div>
              </article>
            ))}

            {loading ? (
              <article className="message message-assistant">
                <div className="message-author">
                  <span className="assistant-avatar">
                    <Icon name="spark" size={15} />
                  </span>
                  <p>RentMate</p>
                  <small>Đang dò hồ sơ</small>
                </div>
                <div className="thinking-bubble" aria-label="RentMate đang xử lý">
                  <span />
                  <span />
                  <span />
                </div>
              </article>
            ) : null}
            <div ref={feedEndRef} />
          </div>

          {!hasUserMessage ? (
            <div className="suggestion-row" aria-label="Gợi ý yêu cầu">
              {SUGGESTIONS.map((suggestion) => (
                <button
                  disabled={!sessionId || loading}
                  key={suggestion}
                  onClick={() => void dispatchMessage(suggestion)}
                  type="button"
                >
                  <Icon name="message" size={16} />
                  {suggestion}
                </button>
              ))}
            </div>
          ) : null}

          {requiresConfirmation && !slots.length ? (
            <div className="confirmation-callout">
              <Icon name="key" size={19} />
              <p>
                Agent đang chờ xác nhận. Hãy chọn đúng căn và khung giờ trước khi cung cấp
                thông tin người xem.
              </p>
            </div>
          ) : null}

          <ChatComposer
            disabled={!sessionId || loading}
            onSend={(message) => void dispatchMessage(message)}
          />
        </section>

        <aside className="listing-rail" aria-label="Hồ sơ căn hộ và dấu vết Agent">
          <div className="rail-header">
            <div>
              <p className="eyebrow">Hồ sơ tìm thấy</p>
              <h2>Căn phù hợp</h2>
            </div>
            <span className="count-badge">{properties.length}</span>
          </div>

          <div className="property-stack">
            {properties.length ? (
              properties.map((property) => (
                <PropertyCard key={property.property_id} onCheckSlots={checkSlots} property={property} />
              ))
            ) : (
              <div className="property-empty">
                <div className="empty-address-lines" aria-hidden="true">
                  <span />
                  <span />
                  <span />
                </div>
                <Icon name="building" size={30} />
                <h3>Chưa mở hồ sơ căn nào</h3>
                <p>
                  Cho RentMate biết quận, ngân sách và tiện ích bạn cần. Kết quả có nguồn từ
                  dữ liệu sẽ xuất hiện tại đây.
                </p>
              </div>
            )}
          </div>

          <SlotPicker onSelect={chooseSlot} slots={slots} />
          <TracePanel stopReason={stopReason} trace={trace} />
        </aside>
      </main>

      {error ? (
        <div className="error-toast" role="alert">
          <span>!</span>
          <p>
            <strong>Chưa hoàn tất yêu cầu</strong>
            {error}
          </p>
          <button aria-label="Đóng thông báo lỗi" onClick={() => setError(null)} type="button">
            <Icon name="close" size={18} />
          </button>
        </div>
      ) : null}

      {confirmationTarget ? (
        <ConfirmationModal
          onClose={() => !confirming && setConfirmationTarget(null)}
          onConfirm={(context) => void confirmBooking(context)}
          property={confirmationTarget.property}
          slot={confirmationTarget.slot}
          submitting={confirming}
        />
      ) : null}

      {bookingDrawerOpen && sessionId ? (
        <BookingDrawer
          bookings={bookings}
          exportUrl={bookingExportUrl(sessionId)}
          loading={bookingsLoading}
          onClose={() => setBookingDrawerOpen(false)}
        />
      ) : null}
    </div>
  );
}

export default App;
