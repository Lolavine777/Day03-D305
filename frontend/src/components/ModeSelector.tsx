import type { AgentMode } from "../types";

const MODES: Array<{ value: AgentMode; label: string; short: string }> = [
  { value: "auto", label: "Tự chọn luồng phù hợp", short: "Auto" },
  { value: "level1", label: "Cấp 1 · Theo luật", short: "Cấp 1" },
  { value: "level2", label: "Cấp 2 · Chatbot", short: "Cấp 2" },
  { value: "level3", label: "Cấp 3 · ReAct", short: "Cấp 3" },
  { value: "level4", label: "Cấp 4 · Lập kế hoạch", short: "Cấp 4" }
];

interface ModeSelectorProps {
  value: AgentMode;
  onChange: (mode: AgentMode) => void;
  disabled?: boolean;
}

export function ModeSelector({ value, onChange, disabled }: ModeSelectorProps) {
  return (
    <fieldset className="mode-selector" disabled={disabled}>
      <legend className="sr-only">Chọn cấp độ trợ lý</legend>
      {MODES.map((mode) => (
        <label
          className={`mode-option ${value === mode.value ? "is-active" : ""}`}
          key={mode.value}
          title={mode.label}
        >
          <input
            aria-label={mode.label}
            checked={value === mode.value}
            name="agent-mode"
            onChange={() => onChange(mode.value)}
            type="radio"
            value={mode.value}
          />
          <span>{mode.short}</span>
        </label>
      ))}
    </fieldset>
  );
}
