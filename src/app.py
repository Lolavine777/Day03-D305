"""
🚀 CORE AGENT APP (Dành cho Role 4: Core Agent Developer)
File chính ghép nối tất cả các thành phần: Tools + Prompts + Test Cases + Multi-Provider.
"""

import json
import inspect
import os
import re
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from typing import Any, Callable, Literal
from dotenv import load_dotenv

# Đảm bảo import các module cùng thư mục src/ hoạt động mượt mà
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Đảm bảo in ra Tiếng Việt và Emojis không bị lỗi trên Windows Console
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Import các thành phần từ file của Role 3 & Multi-Provider Adapter.
# Tool registry được tạo tại composition root để tests có thể inject adapter riêng.
from prompts import (
    AUTONOMOUS_SYSTEM_PROMPT,
    CHATBOT_BASELINE_PROMPT,
    MAX_AUTONOMOUS_STEPS,
    MAX_ITERATIONS,
    REACT_SYSTEM_PROMPT,
    TIMEOUT_SECONDS,
)
from providers import get_llm_provider

load_dotenv()


class ActionParseError(ValueError):
    """Raised when an LLM response does not match the ReAct wire format."""


@dataclass(frozen=True)
class ParsedModelOutput:
    """Normalized representation of one ReAct model response."""

    kind: Literal["action", "final"]
    thought: str
    tool: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    answer: str | None = None


@dataclass(frozen=True)
class ConfirmationContext:
    """Trusted booking confirmation supplied by the application, not the LLM."""

    accepted: bool
    property_id: str
    slot_id: str
    viewer_name: str
    viewer_phone: str

    def matches(self, args: dict[str, Any]) -> bool:
        def compact_phone(value: Any) -> str:
            return re.sub(r"[\s().-]", "", str(value or ""))

        return (
            self.accepted
            and self.property_id == str(args.get("property_id", "")).strip()
            and self.slot_id == str(args.get("slot_id", "")).strip()
            and self.viewer_name.strip() == str(args.get("viewer_name", "")).strip()
            and compact_phone(self.viewer_phone)
            == compact_phone(args.get("viewer_phone"))
        )


class ToolExecutor:
    """Validate and execute registered tools, returning safe Observation data."""

    def __init__(
        self,
        registry: dict[str, Callable[..., dict[str, Any]]],
        timeout_seconds: float = 10,
    ):
        self.registry = registry
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _error(code: str, message: str, data: Any = None) -> dict[str, Any]:
        return {"ok": False, "code": code, "message": message, "data": data or {}}

    def execute(
        self,
        tool_name: str,
        args: dict[str, Any],
        *,
        session_id: str = "anonymous",
        confirmation: ConfirmationContext | None = None,
    ) -> dict[str, Any]:
        handler = self.registry.get(tool_name)
        if handler is None:
            return self._error(
                "UNKNOWN_TOOL",
                f"Tool '{tool_name}' không tồn tại.",
                {"allowed_tools": sorted(self.registry)},
            )
        if not isinstance(args, dict):
            return self._error("MALFORMED_ARGS", "Tool arguments phải là JSON object.")

        if tool_name == "book_viewing" and (
            confirmation is None or not confirmation.matches(args)
        ):
            return self._error(
                "CONFIRMATION_REQUIRED",
                "Bạn cần xác nhận chính xác căn, lịch xem và thông tin người xem.",
                {
                    "property_id": args.get("property_id"),
                    "slot_id": args.get("slot_id"),
                },
            )

        call_args = dict(args)
        signature = inspect.signature(handler)
        accepts_kwargs = any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )
        if "session_id" in signature.parameters or accepts_kwargs:
            call_args["session_id"] = session_id

        try:
            signature.bind(**call_args)
        except TypeError as exc:
            return self._error(
                "MALFORMED_ARGS",
                f"Tham số tool không hợp lệ: {exc}.",
                {"tool": tool_name},
            )

        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rentmate-tool")
        future = pool.submit(handler, **call_args)
        try:
            result = future.result(timeout=self.timeout_seconds)
        except FutureTimeoutError:
            future.cancel()
            return self._error(
                "TOOL_TIMEOUT",
                f"Tool '{tool_name}' vượt quá thời gian xử lý cho phép.",
            )
        except Exception:
            return self._error(
                "TOOL_ERROR",
                f"Tool '{tool_name}' gặp lỗi nội bộ. Vui lòng thử lại.",
            )
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        if not isinstance(result, dict) or "ok" not in result:
            return self._error(
                "INVALID_TOOL_RESULT",
                f"Tool '{tool_name}' trả về dữ liệu không đúng contract.",
            )
        return result


def parse_model_output(model_output: str) -> ParsedModelOutput:
    """Parse exactly one JSON Action or one Final Answer from model output."""
    if not isinstance(model_output, str) or not model_output.strip():
        raise ActionParseError("Phản hồi của model trống.")

    cleaned = re.sub(r"^\s*```(?:text|json)?\s*", "", model_output.strip(), flags=re.I)
    cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    action_matches = list(re.finditer(r"(?m)^\s*Action:\s*(.+?)\s*$", cleaned))
    final_matches = list(re.finditer(r"(?m)^\s*Final Answer:\s*(.*)$", cleaned))

    if len(action_matches) + len(final_matches) != 1:
        raise ActionParseError(
            "Phản hồi phải chứa đúng một Action hoặc một Final Answer."
        )

    thought_match = re.search(
        r"(?ms)^\s*Thought:\s*(.*?)(?=^\s*(?:Action|Final Answer):)",
        cleaned,
    )
    thought = thought_match.group(1).strip() if thought_match else ""

    if action_matches:
        action_text = action_matches[0].group(1)
        try:
            action = json.loads(action_text)
        except json.JSONDecodeError as exc:
            raise ActionParseError(f"Action JSON không hợp lệ: {exc.msg}.") from exc

        if not isinstance(action, dict):
            raise ActionParseError("Action phải là một JSON object.")
        tool = action.get("tool")
        args = action.get("args", {})
        if not isinstance(tool, str) or not tool.strip():
            raise ActionParseError("Action thiếu tên tool hợp lệ.")
        if not isinstance(args, dict):
            raise ActionParseError("Action.args phải là một JSON object.")
        return ParsedModelOutput(
            kind="action",
            thought=thought,
            tool=tool.strip(),
            args=args,
        )

    final_match = final_matches[0]
    answer = cleaned[final_match.start(1):].strip()
    if not answer:
        raise ActionParseError("Final Answer không được để trống.")
    return ParsedModelOutput(kind="final", thought=thought, answer=answer)


@dataclass
class AgentResult:
    """Stable result returned to the CLI and HTTP adapters."""

    answer: str
    mode_used: str
    status: str = "completed"
    stop_reason: str = "final"
    trace: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    properties: list[dict[str, Any]] = field(default_factory=list)
    slots: list[dict[str, Any]] = field(default_factory=list)
    booking: dict[str, Any] | None = None
    requires_confirmation: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "mode_used": self.mode_used,
            "status": self.status,
            "stop_reason": self.stop_reason,
            "trace": self.trace,
            "tool_calls": self.tool_calls,
            "properties": self.properties,
            "slots": self.slots,
            "booking": self.booking,
            "requires_confirmation": self.requires_confirmation,
        }


def _mask_phone(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                _mask_phone_number(item)
                if "phone" in key.lower()
                else _mask_phone(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_mask_phone(item) for item in value]
    return value


def _mask_phone_number(value: Any) -> str:
    text = str(value or "")
    digits = re.sub(r"\D", "", text)
    if len(digits) < 6:
        return "***"
    return f"{digits[:3]}****{digits[-3:]}"


class AgentEngine:
    """Coordinate routing, LLM calls, tool execution, memory and trace output."""

    _TOOL_INTENT_PATTERNS = (
        r"\btìm\b",
        r"tra cứu",
        r"còn trống",
        r"lịch xem",
        r"đặt lịch",
        r"so sánh",
        r"\b(?:HN|HCM)-[A-Z]{2,}-\d+\b",
    )

    def __init__(
        self,
        provider: Any,
        tool_registry: dict[str, Callable[..., dict[str, Any]]] | None = None,
        *,
        max_iterations: int = MAX_ITERATIONS,
        timeout_seconds: float = TIMEOUT_SECONDS,
    ):
        self.provider = provider
        self.executor = ToolExecutor(tool_registry or {}, timeout_seconds)
        self.max_iterations = max_iterations
        self._sessions: dict[str, list[dict[str, str]]] = {}
        self._session_lock = threading.RLock()

    def create_session(self) -> str:
        session_id = str(uuid.uuid4())
        with self._session_lock:
            self._sessions[session_id] = []
        return session_id

    def has_session(self, session_id: str) -> bool:
        with self._session_lock:
            return session_id in self._sessions

    def _remember(self, session_id: str, role: str, content: str) -> None:
        with self._session_lock:
            history = self._sessions.setdefault(session_id, [])
            history.append({"role": role, "content": content})
            del history[:-12]

    def _history_text(self, session_id: str) -> str:
        with self._session_lock:
            history = list(self._sessions.get(session_id, []))[-8:]
        if not history:
            return ""
        lines = [
            f"{'User' if item['role'] == 'user' else 'Assistant'}: {item['content']}"
            for item in history
        ]
        return "Lịch sử hội thoại:\n" + "\n".join(lines)

    @classmethod
    def route_mode(cls, message: str) -> str:
        return (
            "level3"
            if any(
                re.search(pattern, message, flags=re.I)
                for pattern in cls._TOOL_INTENT_PATTERNS
            )
            else "level2"
        )

    def run_turn(
        self,
        message: str,
        *,
        mode: str = "auto",
        session_id: str | None = None,
        confirmation: ConfirmationContext | None = None,
    ) -> AgentResult:
        if not isinstance(message, str) or not message.strip():
            return AgentResult(
                answer="Vui lòng nhập nội dung bạn cần hỗ trợ.",
                mode_used=mode,
                status="error",
                stop_reason="invalid_input",
            )
        if mode not in {"auto", "level1", "level2", "level3", "level4"}:
            return AgentResult(
                answer=f"Chế độ '{mode}' không hợp lệ.",
                mode_used=mode,
                status="error",
                stop_reason="invalid_mode",
            )

        session_id = session_id or self.create_session()
        self._remember(session_id, "user", message.strip())
        resolved_mode = self.route_mode(message) if mode == "auto" else mode

        normalized_message = message.casefold()
        if (
            resolved_mode in {"level3", "level4"}
            and "bỏ qua" in normalized_message
            and "xác nhận" in normalized_message
            and "đặt" in normalized_message
        ):
            result = AgentResult(
                answer=(
                    "Tôi không thể bỏ qua bước xác nhận hoặc tự bịa thông tin "
                    "người xem. Hãy chọn căn, khung giờ và xác nhận trên giao diện."
                ),
                mode_used=resolved_mode,
                status="guardrail",
                stop_reason="confirmation_bypass",
                trace=[
                    {
                        "step": 0,
                        "kind": "guardrail",
                        "content": (
                            "Đã chặn yêu cầu bỏ qua xác nhận đặt lịch."
                        ),
                    }
                ],
            )
            self._remember(session_id, "assistant", result.answer)
            return result

        if resolved_mode == "level1":
            try:
                from ai_levels.level1_rule_based import rule_based_bot

                answer = rule_based_bot(message)
            except Exception:
                answer = (
                    "Tôi chỉ hỗ trợ các câu hỏi cơ bản về thuê nhà ở chế độ luật."
                )
            result = AgentResult(answer=answer, mode_used=resolved_mode)
        elif resolved_mode == "level2":
            result = self._run_baseline(message, session_id)
        else:
            result = self._run_react(
                message,
                session_id,
                confirmation,
                mode_used=resolved_mode,
            )

        self._remember(session_id, "assistant", result.answer)
        return result

    def _run_baseline(self, message: str, session_id: str) -> AgentResult:
        prompt_parts = [self._history_text(session_id), f"User: {message}"]
        prompt = "\n\n".join(part for part in prompt_parts if part)
        try:
            answer = self.provider.generate(
                prompt,
                system_prompt=CHATBOT_BASELINE_PROMPT,
            )
        except Exception:
            return AgentResult(
                answer=(
                    "Chatbot hiện chưa kết nối được mô hình ngôn ngữ. "
                    "Vui lòng kiểm tra cấu hình provider."
                ),
                mode_used="level2",
                status="error",
                stop_reason="provider_error",
            )
        return AgentResult(
            answer=str(answer).strip(),
            mode_used="level2",
            trace=[
                {
                    "step": 1,
                    "kind": "final",
                    "content": str(answer).strip(),
                }
            ],
        )

    def _run_react(
        self,
        message: str,
        session_id: str,
        confirmation: ConfirmationContext | None,
        *,
        mode_used: str,
    ) -> AgentResult:
        trace: list[dict[str, Any]] = []
        tool_calls: list[dict[str, Any]] = []
        properties: list[dict[str, Any]] = []
        slots: list[dict[str, Any]] = []
        booking: dict[str, Any] | None = None
        requires_confirmation = False
        booking_intent = bool(
            re.search(r"(?:đặt\s+lịch|lịch\s+xem.*đặt)", message, flags=re.I)
        )
        scratchpad: list[str] = []
        seen_actions: set[str] = set()
        history = self._history_text(session_id)
        system_prompt = (
            AUTONOMOUS_SYSTEM_PROMPT
            if mode_used == "level4"
            else REACT_SYSTEM_PROMPT
        )
        iteration_limit = (
            MAX_AUTONOMOUS_STEPS
            if mode_used == "level4"
            else self.max_iterations
        )
        if mode_used == "level4" and history:
            history = history.replace(
                "Lịch sử hội thoại:",
                "Memory history:",
                1,
            )
        trusted_confirmation = ""
        if confirmation is not None and confirmation.accepted:
            trusted_confirmation = "Trusted confirmation context: " + json.dumps(
                {
                    "accepted": True,
                    "property_id": confirmation.property_id,
                    "slot_id": confirmation.slot_id,
                    "viewer_name": confirmation.viewer_name,
                    "viewer_phone": confirmation.viewer_phone,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )

        for step in range(1, iteration_limit + 1):
            prompt_parts = [
                history,
                f"Question: {message}",
                trusted_confirmation,
                "\n\n".join(scratchpad),
                "Hãy đưa ra đúng một Action hoặc Final Answer tiếp theo.",
            ]
            prompt = "\n\n".join(part for part in prompt_parts if part)
            try:
                raw_output = self.provider.generate(
                    prompt,
                    system_prompt=system_prompt,
                )
            except Exception:
                return AgentResult(
                    answer=(
                        "Agent hiện chưa kết nối được mô hình ngôn ngữ. "
                        "Vui lòng kiểm tra provider rồi thử lại."
                    ),
                    mode_used=mode_used,
                    status="error",
                    stop_reason="provider_error",
                    trace=trace,
                    tool_calls=tool_calls,
                    properties=properties,
                    slots=slots,
                )

            try:
                parsed = parse_model_output(str(raw_output))
            except ActionParseError as exc:
                error = ToolExecutor._error("PARSE_ERROR", str(exc))
                trace.append(
                    {
                        "step": step,
                        "kind": "observation",
                        "content": error["message"],
                        "ok": False,
                        "code": error["code"],
                    }
                )
                scratchpad.append(
                    f"Model output: {raw_output}\n"
                    f"Observation: {json.dumps(error, ensure_ascii=False)}"
                )
                continue

            if parsed.thought:
                trace.append(
                    {
                        "step": step,
                        "kind": "thought",
                        "content": parsed.thought,
                    }
                )

            if parsed.kind == "final":
                answer = parsed.answer or "Tôi chưa thể tổng hợp câu trả lời."
                if booking_intent and confirmation is None and booking is None:
                    requires_confirmation = True
                trace.append(
                    {"step": step, "kind": "final", "content": answer}
                )
                return AgentResult(
                    answer=answer,
                    mode_used=mode_used,
                    trace=trace,
                    tool_calls=tool_calls,
                    properties=properties,
                    slots=slots,
                    booking=booking,
                    requires_confirmation=requires_confirmation,
                )

            canonical_action = json.dumps(
                {"tool": parsed.tool, "args": parsed.args},
                ensure_ascii=False,
                sort_keys=True,
            )
            if canonical_action in seen_actions:
                trace.append(
                    {
                        "step": step,
                        "kind": "guardrail",
                        "content": "Đã chặn Action lặp lại với cùng tham số.",
                        "tool": parsed.tool,
                    }
                )
                return AgentResult(
                    answer=(
                        "Tôi đã dừng vì cùng một thao tác bị lặp lại. "
                        "Hãy điều chỉnh yêu cầu hoặc thử bộ lọc khác."
                    ),
                    mode_used=mode_used,
                    status="guardrail",
                    stop_reason="repeated_action",
                    trace=trace,
                    tool_calls=tool_calls,
                    properties=properties,
                    slots=slots,
                    requires_confirmation=requires_confirmation,
                )
            seen_actions.add(canonical_action)

            safe_args = _mask_phone(parsed.args)
            trace.append(
                {
                    "step": step,
                    "kind": "action",
                    "content": f"Gọi {parsed.tool}",
                    "tool": parsed.tool,
                    "args": safe_args,
                }
            )
            observation = self.executor.execute(
                parsed.tool or "",
                parsed.args,
                session_id=session_id,
                confirmation=confirmation,
            )
            safe_observation = _mask_phone(observation)
            trace.append(
                {
                    "step": step,
                    "kind": "observation",
                    "content": safe_observation.get("message", ""),
                    "tool": parsed.tool,
                    "ok": bool(safe_observation.get("ok")),
                    "code": safe_observation.get("code"),
                    "data": safe_observation.get("data", {}),
                }
            )
            tool_calls.append(
                {
                    "tool": parsed.tool,
                    "args": safe_args,
                    "ok": bool(observation.get("ok")),
                    "code": observation.get("code"),
                }
            )
            if observation.get("code") == "CONFIRMATION_REQUIRED":
                requires_confirmation = True

            data = observation.get("data") or {}
            if parsed.tool in {"search_properties", "compare_properties"}:
                found = data.get("properties") or data.get("items") or []
                if isinstance(found, list):
                    properties = found
            elif parsed.tool == "get_property_details":
                found_property = data.get("property") or data
                if isinstance(found_property, dict) and found_property:
                    properties = [found_property]
            elif parsed.tool == "get_available_viewing_slots":
                found_slots = data.get("slots") or data.get("items") or []
                if isinstance(found_slots, list):
                    slots = found_slots
            elif parsed.tool == "book_viewing" and observation.get("ok"):
                booking_data = data.get("booking") or data
                if isinstance(booking_data, dict):
                    booking = booking_data

            scratchpad.append(
                f"Thought: {parsed.thought}\n"
                f"Action: {canonical_action}\n"
                f"Observation: {json.dumps(observation, ensure_ascii=False)}"
            )

        trace.append(
            {
                "step": iteration_limit,
                "kind": "guardrail",
                "content": (
                    f"Đã đạt giới hạn {iteration_limit} vòng lặp ReAct."
                ),
            }
        )
        return AgentResult(
            answer=(
                "Tôi chưa thể hoàn tất yêu cầu trong giới hạn xử lý an toàn. "
                "Vui lòng thu hẹp tiêu chí và thử lại."
            ),
            mode_used=mode_used,
            status="guardrail",
            stop_reason="max_iterations",
            trace=trace,
            tool_calls=tool_calls,
            properties=properties,
            slots=slots,
            booking=booking,
            requires_confirmation=requires_confirmation,
        )


def load_test_cases(path: str | None = None) -> list[dict[str, Any]]:
    """Read Role 1's evaluation cases with clear configuration errors."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = path or os.path.join(base_dir, "config", "test_cases.json")
    with open(config_path, "r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, list) or not data:
        raise ValueError("config/test_cases.json phải là một danh sách không rỗng.")
    return data


def run_baseline_chatbot(
    user_query: str,
    provider: Any,
) -> AgentResult:
    """Compatibility wrapper for the Level 2 baseline."""
    return AgentEngine(provider, {}).run_turn(user_query, mode="level2")


def run_react_agent(
    user_query: str,
    provider: Any,
    tool_registry: dict[str, Callable[..., dict[str, Any]]] | None = None,
    *,
    session_id: str | None = None,
    confirmation: ConfirmationContext | None = None,
) -> AgentResult:
    """Compatibility wrapper for the Level 3 ReAct agent."""
    return AgentEngine(provider, tool_registry or {}).run_turn(
        user_query,
        mode="level3",
        session_id=session_id,
        confirmation=confirmation,
    )


def build_default_runtime() -> tuple[AgentEngine, Any]:
    """Create the local SQLite/runtime adapters without work at import time."""
    from storage import RentalStore
    from tools import create_tool_registry

    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    database_path = os.getenv(
        "DB_PATH",
        os.path.join(root_dir, "data", "rentmate.db"),
    )
    inventory_path = os.path.join(root_dir, "config", "rental_inventory.json")
    store = RentalStore(database_path, inventory_path=inventory_path)
    store.initialize()
    registry = create_tool_registry(store)
    return AgentEngine(get_llm_provider(), registry), store


def run_batch_demo(engine: AgentEngine) -> list[dict[str, Any]]:
    """Run all rubric cases on both the baseline and routed Agent."""
    results = []
    for case in load_test_cases():
        question = case["question"]
        baseline = engine.run_turn(question, mode="level2")
        agent = engine.run_turn(question, mode="auto")
        results.append(
            {
                "id": case.get("id"),
                "question": question,
                "baseline": baseline.to_dict(),
                "agent": agent.to_dict(),
            }
        )
    return results


def main() -> int:
    print("=" * 62)
    print("🏠 RENTMATE — CHATBOT VS REACT AGENT")
    print("=" * 62)
    try:
        engine, _store = build_default_runtime()
        results = run_batch_demo(engine)
    except Exception as exc:
        print(f"❌ Không thể khởi động RentMate: {exc}")
        return 1

    provider_name = engine.provider.__class__.__name__
    print(f"🔌 Provider: {provider_name}")
    print(f"✅ Đã chạy {len(results)} test cases trên Baseline và Agent.\n")
    for item in results:
        print(f"[{item['id']}] {item['question']}")
        print(f"  Baseline: {item['baseline']['answer']}")
        print(f"  Agent   : {item['agent']['answer']}")
        tool_path = [call["tool"] for call in item["agent"]["tool_calls"]]
        print(f"  Tools   : {tool_path or 'Không gọi tool'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
