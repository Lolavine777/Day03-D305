import { useState, type FormEvent, type KeyboardEvent } from "react";
import { Icon } from "./Icon";

interface ChatComposerProps {
  disabled?: boolean;
  onSend: (message: string) => void;
}

export function ChatComposer({ disabled, onSend }: ChatComposerProps) {
  const [message, setMessage] = useState("");

  const submit = (event?: FormEvent) => {
    event?.preventDefault();
    const cleaned = message.trim();
    if (!cleaned || disabled) return;
    onSend(cleaned);
    setMessage("");
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <form className="composer" onSubmit={submit}>
      <label className="sr-only" htmlFor="rentmate-message">
        Nói nhu cầu thuê nhà của bạn
      </label>
      <textarea
        aria-describedby="composer-hint"
        disabled={disabled}
        id="rentmate-message"
        onChange={(event) => setMessage(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Ví dụ: Phòng dưới 6 triệu ở Nam Từ Liêm, có ban công…"
        rows={1}
        value={message}
      />
      <button
        aria-label="Gửi yêu cầu"
        className="send-button"
        disabled={disabled || !message.trim()}
        type="submit"
      >
        <Icon name="arrow" size={21} />
      </button>
      <p id="composer-hint">
        Enter để gửi <span aria-hidden="true">·</span> Shift + Enter để xuống dòng
      </p>
    </form>
  );
}
