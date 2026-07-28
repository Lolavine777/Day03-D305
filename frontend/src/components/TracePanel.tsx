import type { TraceEntry, TraceKind } from "../types";
import { Icon } from "./Icon";

const LABELS: Record<TraceKind, string> = {
  thought: "Thought",
  action: "Action",
  observation: "Observation",
  guardrail: "Guardrail",
  final: "Final",
  system: "System"
};

function traceKind(entry: TraceEntry): TraceKind {
  const raw = String(entry.kind ?? entry.type ?? entry.label ?? "system").toLowerCase();
  if (raw.includes("thought")) return "thought";
  if (raw.includes("action")) return "action";
  if (raw.includes("observation")) return "observation";
  if (raw.includes("guard")) return "guardrail";
  if (raw.includes("final")) return "final";
  return "system";
}

function pretty(value: unknown): string {
  if (value === undefined || value === null) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function traceBody(entry: TraceEntry) {
  const sections: string[] = [];
  if (entry.content !== undefined) sections.push(pretty(entry.content));
  else if (entry.message) sections.push(entry.message);
  if (entry.tool && !sections.some((section) => section.includes(entry.tool ?? ""))) {
    sections.push(`Tool: ${entry.tool}`);
  }
  if (entry.args) sections.push(`Args:\n${pretty(entry.args)}`);
  if (entry.code || entry.ok !== undefined) {
    sections.push(`Result: ${entry.code ?? "UNKNOWN"} · ok=${String(entry.ok)}`);
  }
  if (entry.data !== undefined && pretty(entry.data) !== "{}") {
    sections.push(`Data:\n${pretty(entry.data)}`);
  }
  if (entry.result !== undefined) sections.push(pretty(entry.result));
  return sections.join("\n\n") || "Không có nội dung.";
}

interface TracePanelProps {
  trace: TraceEntry[];
  stopReason?: string;
}

export function TracePanel({ trace, stopReason }: TracePanelProps) {
  return (
    <details className="trace-panel">
      <summary>
        <span className="trace-summary-icon">
          <Icon name="trace" size={18} />
        </span>
        <span>
          <strong>Dấu vết suy luận</strong>
          <small>
            {trace.length ? `${trace.length} sự kiện` : "Chưa có lượt chạy Agent"}
            {stopReason ? ` · ${stopReason}` : ""}
          </small>
        </span>
        <Icon className="summary-chevron" name="chevron" size={18} />
      </summary>

      <div className="trace-body">
        {trace.length ? (
          <ol className="trace-list">
            {trace.map((entry, index) => {
              const kind = traceKind(entry);
              return (
                <li className={`trace-entry trace-${kind}`} key={entry.id ?? `${kind}-${index}`}>
                  <span className="trace-node" aria-hidden="true" />
                  <div className="trace-entry-content">
                    <p>
                      {entry.iteration ?? entry.step
                        ? `Vòng ${entry.iteration ?? entry.step} · `
                        : ""}
                      {LABELS[kind]}
                    </p>
                    <pre>{traceBody(entry)}</pre>
                  </div>
                </li>
              );
            })}
          </ol>
        ) : (
          <div className="trace-empty">
            <Icon name="trace" size={24} />
            <p>
              Chọn Cấp 3 hoặc Cấp 4 để xem Agent đi qua Thought, Action, Observation và
              Guardrail.
            </p>
          </div>
        )}
      </div>
    </details>
  );
}
