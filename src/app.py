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
import unicodedata
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
from artifacts import project_tool_artifacts
from ai_levels.level4_autonomous_agent import AutonomousGoalAgent
from privacy import mask_phone_number, redact_pii

load_dotenv()


def _fold_text(value: str) -> str:
    """Case-fold and strip Vietnamese accents for intent-only matching."""

    decomposed = unicodedata.normalize("NFD", str(value).casefold()).replace(
        "đ",
        "d",
    )
    return "".join(
        character
        for character in decomposed
        if unicodedata.category(character) != "Mn"
    )


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
        """Match only the target; trusted contact fields never come from the LLM."""
        return (
            self.accepted
            and self.property_id.strip().upper()
            == str(args.get("property_id", "")).strip().upper()
            and self.slot_id.strip().upper()
            == str(args.get("slot_id", "")).strip().upper()
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
        autonomous_mode: bool = False,
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

        if tool_name == "book_viewing":
            if autonomous_mode:
                return self._error(
                    "AUTONOMY_BOUNDARY",
                    "Level 4 chỉ lập kế hoạch và phải dừng trước thao tác đặt lịch.",
                    {
                        "property_id": args.get("property_id"),
                        "slot_id": args.get("slot_id"),
                    },
                )
            if confirmation is None or not confirmation.matches(args):
                return self._error(
                    "CONFIRMATION_REQUIRED",
                    "Bạn cần xác nhận chính xác căn và lịch xem trên giao diện.",
                    {
                        "property_id": args.get("property_id"),
                        "slot_id": args.get("slot_id"),
                    },
                )

        call_args = dict(args)
        if tool_name == "book_viewing" and confirmation is not None:
            call_args["property_id"] = confirmation.property_id
            call_args["slot_id"] = confirmation.slot_id
            call_args["viewer_name"] = confirmation.viewer_name
            call_args["viewer_phone"] = confirmation.viewer_phone
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
        return redact_pii(
            {
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
        )


def _mask_phone(value: Any) -> Any:
    """Backward-compatible alias for the centralized privacy policy."""

    return redact_pii(value)


def _mask_phone_number(value: Any) -> str:
    """Backward-compatible alias for callers importing the old helper."""

    return mask_phone_number(value)


class AgentEngine:
    """Coordinate routing, LLM calls, tool execution, memory and trace output."""

    _TOOL_INTENT_PATTERNS = (
        r"\b(?:tim|find|search)\b",
        r"(?:tra cuu|lookup)",
        r"(?:con trong|available)",
        r"(?:lich xem|viewing slot)",
        r"(?:dat lich|book(?:ing)?)",
        r"(?:so sanh|compare)",
        r"\b(?:HN|HCM)-[A-Z]{2,}-\d+\b",
    )
    _LISTING_NOUN_PATTERN = (
        r"\b(?:phong(?: tro)?|can ho|nha tro|studio|apartment|room|rental)\b"
    )
    _LISTING_CRITERIA_PATTERN = (
        r"\b(?:duoi|tren|tu|ngan sach|trieu|vnd|m2|m²|dieu hoa|"
        r"cho de xe|noi that|quan|district|ward|ha noi|tp hcm|"
        r"ho chi minh|cau giay|binh thanh)\b|\d"
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
            history.append({"role": role, "content": str(redact_pii(content))})
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
    def _has_constrained_listing(cls, folded_message: str) -> bool:
        return bool(
            re.search(cls._LISTING_NOUN_PATTERN, folded_message, flags=re.I)
            and re.search(
                cls._LISTING_CRITERIA_PATTERN,
                folded_message,
                flags=re.I,
            )
        )

    @classmethod
    def route_mode(cls, message: str) -> str:
        folded_message = _fold_text(message)
        has_explicit_tool_intent = any(
            re.search(pattern, folded_message, flags=re.I)
            for pattern in cls._TOOL_INTENT_PATTERNS
        )
        return (
            "level3"
            if has_explicit_tool_intent
            or cls._has_constrained_listing(folded_message)
            else "level2"
        )

    @staticmethod
    def _sanitize_result(result: AgentResult) -> AgentResult:
        """Apply one privacy boundary before results enter memory or adapters."""

        result.answer = str(redact_pii(result.answer))
        result.trace = redact_pii(result.trace)
        result.tool_calls = redact_pii(result.tool_calls)
        result.properties = redact_pii(result.properties)
        result.slots = redact_pii(result.slots)
        result.booking = redact_pii(result.booking)
        return result

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
        resolved_mode = self.route_mode(message) if mode == "auto" else mode

        normalized_message = _fold_text(message)
        if (
            resolved_mode in {"level3", "level4"}
            and "bo qua" in normalized_message
            and "xac nhan" in normalized_message
            and "dat" in normalized_message
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
            result = self._sanitize_result(result)
            self._remember(session_id, "user", message.strip())
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

        result = self._sanitize_result(result)
        self._remember(session_id, "user", message.strip())
        self._remember(session_id, "assistant", result.answer)
        return result

    def _run_baseline(self, message: str, session_id: str) -> AgentResult:
        safe_message = str(redact_pii(message))
        prompt_parts = [self._history_text(session_id), f"User: {safe_message}"]
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
        safe_answer = str(redact_pii(str(answer).strip()))
        return AgentResult(
            answer=safe_answer,
            mode_used="level2",
            trace=[
                {
                    "step": 1,
                    "kind": "final",
                    "content": safe_answer,
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
        safe_message = str(redact_pii(message))
        folded_message = _fold_text(message)
        booking_intent = bool(
            re.search(
                r"(?:dat\s+lich|lich\s+xem.*dat|\bbook(?:ing)?\b)",
                folded_message,
                flags=re.I,
            )
        )
        discovery_intent = self._has_constrained_listing(
            folded_message
        ) or bool(
            re.search(
                (
                    r"\b(?:tim|find|search|compare)\b|so sanh|tra cuu|"
                    r"con trong|available|viewing slot"
                ),
                folded_message,
                flags=re.I,
            )
        )
        pure_booking_intent = booking_intent and not discovery_intent
        scratchpad: list[str] = []
        seen_actions: set[str] = set()
        last_observation_succeeded = False
        last_tool_failure: dict[str, Any] | None = None
        booking_succeeded = False
        ungrounded_final_count = 0
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
        needs_tool_grounding = (
            self.route_mode(message) == "level3"
            and not pure_booking_intent
        )

        planner: AutonomousGoalAgent | None = None
        autonomous_plan: list[dict[str, Any]] = []
        if mode_used == "level4":
            planner = AutonomousGoalAgent(safe_message, iteration_limit)
            autonomous_plan = planner.create_plan()
            trace.append(
                {
                    "step": 0,
                    "kind": "plan",
                    "content": "Đã lập kế hoạch tự chủ có giới hạn.",
                    "data": {"steps": redact_pii(autonomous_plan)},
                }
            )
            if history:
                history = history.replace(
                    "Lịch sử hội thoại:",
                    "Memory history:",
                    1,
                )

            if confirmation is not None and confirmation.accepted:
                boundary = ToolExecutor._error(
                    "AUTONOMY_BOUNDARY",
                    (
                        "Level 4 chỉ tìm, so sánh và tra lịch; thao tác đặt lịch "
                        "phải được thực hiện ở Level 3 sau xác nhận."
                    ),
                    {
                        "property_id": confirmation.property_id,
                        "slot_id": confirmation.slot_id,
                    },
                )
                trace.extend(
                    [
                        {
                            "step": 0,
                            "kind": "guardrail",
                            "content": boundary["message"],
                            "ok": False,
                            "code": boundary["code"],
                            "data": boundary["data"],
                        },
                        {
                            "step": 0,
                            "kind": "evaluation",
                            "content": "Đã dừng trước side effect theo autonomy boundary.",
                            "data": {
                                "planned_steps": len(autonomous_plan),
                                "observed_steps": 0,
                                "next_action": "switch_to_level3_for_booking",
                            },
                        },
                    ]
                )
                return AgentResult(
                    answer=boundary["message"],
                    mode_used=mode_used,
                    status="guardrail",
                    stop_reason="autonomy_boundary",
                    trace=trace,
                    requires_confirmation=True,
                )

        if pure_booking_intent and confirmation is None:
            confirmation_error = ToolExecutor._error(
                "CONFIRMATION_REQUIRED",
                (
                    "Tôi chưa đặt lịch. Hãy tra lịch, chọn một khung giờ rồi "
                    "xác nhận tên và số điện thoại trên giao diện."
                ),
            )
            trace.append(
                {
                    "step": 0,
                    "kind": "guardrail",
                    "content": confirmation_error["message"],
                    "ok": False,
                    "code": confirmation_error["code"],
                }
            )
            if planner is not None:
                trace.append(
                    {
                        "step": 0,
                        "kind": "evaluation",
                        "content": "Kế hoạch dừng tại confirmation gate.",
                        "data": {
                            "planned_steps": len(autonomous_plan),
                            "observed_steps": 0,
                            "next_action": "select_slot_and_confirm",
                        },
                    }
                )
            return AgentResult(
                answer=confirmation_error["message"],
                mode_used=mode_used,
                status="guardrail",
                stop_reason="confirmation_required",
                trace=trace,
                requires_confirmation=True,
            )

        trusted_confirmation = ""
        if (
            mode_used != "level4"
            and confirmation is not None
            and confirmation.accepted
        ):
            trusted_confirmation = "Trusted confirmation context: " + json.dumps(
                {
                    "accepted": True,
                    "property_id": confirmation.property_id,
                    "slot_id": confirmation.slot_id,
                    "viewer_name": "[provided securely]",
                    "viewer_phone": "[provided securely]",
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        plan_context = (
            "Autonomous plan: "
            + json.dumps(
                redact_pii(autonomous_plan),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            if autonomous_plan
            else ""
        )

        for step in range(1, iteration_limit + 1):
            prompt_parts = [
                history,
                f"Question: {safe_message}",
                plan_context,
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
                    booking=booking,
                    requires_confirmation=requires_confirmation,
                )

            safe_raw_output = str(redact_pii(str(raw_output)))
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
                    f"Model output: {safe_raw_output}\n"
                    f"Observation: {json.dumps(error, ensure_ascii=False)}"
                )
                continue

            if parsed.thought:
                safe_thought = str(redact_pii(parsed.thought))
                trace.append(
                    {
                        "step": step,
                        "kind": "thought",
                        "content": safe_thought,
                    }
                )

            if parsed.kind == "final":
                requires_booking_observation = (
                    confirmation is not None
                    and confirmation.accepted
                    and mode_used != "level4"
                )
                lacks_grounding = (
                    needs_tool_grounding and not last_observation_succeeded
                ) or (
                    requires_booking_observation and not booking_succeeded
                )
                if lacks_grounding:
                    if last_tool_failure is not None:
                        failure_code = str(
                            last_tool_failure.get("code", "TOOL_ERROR")
                        )
                        failure_message = str(
                            last_tool_failure.get(
                                "message",
                                "Không thể xác minh dữ liệu bằng công cụ.",
                            )
                        )
                        answer = (
                            f"Không thể tiếp tục vì công cụ trả về "
                            f"{failure_code}: {failure_message}"
                        )
                        trace.append(
                            {
                                "step": step,
                                "kind": "final",
                                "content": answer,
                                "source": (
                                    "application_after_failed_observation"
                                ),
                            }
                        )
                        return AgentResult(
                            answer=answer,
                            mode_used=mode_used,
                            status="error",
                            stop_reason=failure_code.casefold(),
                            trace=trace,
                            tool_calls=tool_calls,
                            properties=properties,
                            slots=slots,
                            booking=booking,
                            requires_confirmation=booking_intent,
                        )

                    ungrounded_final_count += 1
                    grounding_error = ToolExecutor._error(
                        "GROUNDING_REQUIRED",
                        (
                            "Final Answer bị từ chối vì chưa có Observation thật "
                            "cho yêu cầu dữ liệu hoặc booking."
                        ),
                    )
                    trace.append(
                        {
                            "step": step,
                            "kind": "guardrail",
                            "content": grounding_error["message"],
                            "ok": False,
                            "code": grounding_error["code"],
                        }
                    )
                    scratchpad.append(
                        f"Model output: {safe_raw_output}\n"
                        "Observation: "
                        + json.dumps(grounding_error, ensure_ascii=False)
                    )
                    if ungrounded_final_count >= 2:
                        return AgentResult(
                            answer=(
                                "Tôi chưa thể trả lời vì chưa xác minh được dữ "
                                "liệu bằng công cụ. Không có thông tin hay lịch "
                                "xem nào được tạo."
                            ),
                            mode_used=mode_used,
                            status="guardrail",
                            stop_reason="ungrounded_final",
                            trace=trace,
                            tool_calls=tool_calls,
                            properties=properties,
                            slots=slots,
                            booking=booking,
                            requires_confirmation=booking_intent,
                        )
                    continue

                answer = str(
                    redact_pii(
                        parsed.answer or "Tôi chưa thể tổng hợp câu trả lời."
                    )
                )
                if booking_intent and confirmation is None and booking is None:
                    requires_confirmation = True
                if mode_used == "level4" and booking_intent:
                    requires_confirmation = True
                if planner is not None:
                    trace.append(
                        {
                            "step": step,
                            "kind": "evaluation",
                            "content": "Đã tự đánh giá tiến độ trước khi kết thúc.",
                            "data": {
                                "planned_steps": len(autonomous_plan),
                                "observed_steps": len(planner.memory),
                                "next_action": (
                                    "await_user_confirmation"
                                    if requires_confirmation
                                    else "present_results"
                                ),
                            },
                        }
                    )
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
                    booking=booking,
                    requires_confirmation=requires_confirmation,
                )
            seen_actions.add(canonical_action)

            safe_args = _mask_phone(parsed.args)
            safe_canonical_action = json.dumps(
                {"tool": parsed.tool, "args": safe_args},
                ensure_ascii=False,
                sort_keys=True,
            )
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
                autonomous_mode=mode_used == "level4",
            )
            safe_observation = _mask_phone(observation)
            last_observation_succeeded = bool(
                parsed.tool in self.executor.registry
                and observation.get("ok") is True
            )
            last_tool_failure = (
                None
                if last_observation_succeeded
                else safe_observation
            )
            if parsed.tool == "book_viewing" and observation.get("ok") is True:
                booking_succeeded = True
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
            if observation.get("code") in {
                "CONFIRMATION_REQUIRED",
                "AUTONOMY_BOUNDARY",
            }:
                requires_confirmation = True

            projected = project_tool_artifacts(
                parsed.tool or "",
                safe_observation,
            )
            if projected.properties is not None:
                properties = projected.properties
            if projected.slots is not None:
                slots = projected.slots
            if projected.booking is not None:
                booking = projected.booking

            if planner is not None:
                planned_step = next(
                    (
                        item
                        for item in autonomous_plan
                        if item.get("tool") == parsed.tool
                    ),
                    {
                        "step": step,
                        "objective": "Bước ReAct phát sinh từ Observation.",
                        "tool": parsed.tool,
                        "side_effect": (
                            "write"
                            if parsed.tool == "book_viewing"
                            else "read_only"
                        ),
                    },
                )
                planner.remember(planned_step, safe_observation)

            scratchpad.append(
                f"Thought: {redact_pii(parsed.thought)}\n"
                f"Action: {safe_canonical_action}\n"
                "Observation: "
                + json.dumps(safe_observation, ensure_ascii=False)
            )

            if booking_succeeded:
                if booking is None and confirmation is not None:
                    booking = {
                        "property_id": confirmation.property_id,
                        "slot_id": confirmation.slot_id,
                        "status": "confirmed",
                    }
                booking_id = (
                    str(booking.get("booking_id", "")).strip()
                    if isinstance(booking, dict)
                    else ""
                )
                answer = (
                    "Đặt lịch xem nhà thành công"
                    + (f" với mã {booking_id}" if booking_id else "")
                    + ". Thông tin liên hệ đã được che trong kết quả."
                )
                trace.append(
                    {
                        "step": step,
                        "kind": "final",
                        "content": answer,
                        "source": "application_after_booking_observation",
                    }
                )
                return AgentResult(
                    answer=answer,
                    mode_used=mode_used,
                    trace=trace,
                    tool_calls=tool_calls,
                    properties=properties,
                    slots=slots,
                    booking=booking,
                    requires_confirmation=False,
                )

            if observation.get("code") == "AUTONOMY_BOUNDARY":
                trace.append(
                    {
                        "step": step,
                        "kind": "evaluation",
                        "content": "Đã dừng trước side effect theo autonomy boundary.",
                        "data": {
                            "planned_steps": len(autonomous_plan),
                            "observed_steps": len(planner.memory) if planner else 0,
                            "next_action": "await_user_confirmation",
                        },
                    }
                )
                return AgentResult(
                    answer=observation["message"],
                    mode_used=mode_used,
                    status="guardrail",
                    stop_reason="autonomy_boundary",
                    trace=trace,
                    tool_calls=tool_calls,
                    properties=properties,
                    slots=slots,
                    requires_confirmation=True,
                )

            if (
                parsed.tool == "book_viewing"
                and confirmation is not None
                and observation.get("ok") is not True
            ):
                return AgentResult(
                    answer=(
                        "Không thể tạo booking: "
                        + str(safe_observation.get("message", "lỗi công cụ."))
                    ),
                    mode_used=mode_used,
                    status="error",
                    stop_reason=str(
                        observation.get("code", "tool_error")
                    ).casefold(),
                    trace=trace,
                    tool_calls=tool_calls,
                    properties=properties,
                    slots=slots,
                    requires_confirmation=True,
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
    *,
    emit: bool | None = None,
) -> AgentResult | str:
    """Run Level 2 while preserving the original lab helper contract.

    New callers omit ``emit`` and receive the structured :class:`AgentResult`.
    Legacy callers that pass ``emit`` receive the provider's text response.
    """
    if emit is None:
        return AgentEngine(provider, {}).run_turn(user_query, mode="level2")

    response = str(
        provider.generate(user_query, system_prompt=CHATBOT_BASELINE_PROMPT)
    )
    if emit:
        print(f"\n💬 [CHATBOT BASELINE] Câu hỏi: {user_query}")
        print(f"⚙️ System Prompt: {CHATBOT_BASELINE_PROMPT.strip()}")
        print(f"🤖 Chatbot trả lời:\n{response}")
    return response


def run_baseline_suite(
    provider: Any,
    tests: list[dict[str, Any]] | None = None,
    *,
    emit: bool = True,
) -> list[dict[str, Any]]:
    """Run the legacy baseline suite over every configured test case."""
    cases = load_test_cases() if tests is None else tests
    return [
        {
            "id": case.get("id"),
            "question": case["question"],
            "response": run_baseline_chatbot(
                case["question"],
                provider,
                emit=emit,
            ),
        }
        for case in cases
    ]


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
