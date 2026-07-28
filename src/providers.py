"""LLM provider adapters used by RentMate.

The offline :class:`MockProvider` is intentionally deterministic.  It follows
the same ``generate(prompt, system_prompt) -> str`` seam as real providers, so
the core agent can be demonstrated and tested without an API key.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv


load_dotenv()


class BaseLLMProvider:
    """Small provider interface shared by the baseline and ReAct agent."""

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        raise NotImplementedError


class GeminiProvider(BaseLLMProvider):
    """Google Gemini adapter."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model_name = model or os.getenv("LLM_MODEL") or "gemini-2.5-flash"

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        if not _usable_key(self.api_key, "your_gemini_api_key_here"):
            return "[Gemini Error]: Chưa cấu hình GEMINI_API_KEY trong file .env."
        try:
            from google import genai

            client = genai.Client(api_key=self.api_key)
            contents = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
            response = client.models.generate_content(
                model=self.model_name,
                contents=contents,
            )
            return response.text or "[Gemini Error]: Model không trả về nội dung."
        except Exception as exc:  # pragma: no cover - depends on remote provider
            return f"[Gemini Exception]: {exc}"


class OpenAIProvider(BaseLLMProvider):
    """OpenAI chat-completions adapter."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model_name = model or os.getenv("LLM_MODEL") or "gpt-4o-mini"

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        if not _usable_key(self.api_key, "your_openai_api_key_here"):
            return "[OpenAI Error]: Chưa cấu hình OPENAI_API_KEY trong file .env."
        try:
            import openai

            client = openai.OpenAI(api_key=self.api_key)
            messages: list[dict[str, str]] = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            response = client.chat.completions.create(
                model=self.model_name,
                messages=messages,
            )
            return (
                response.choices[0].message.content
                or "[OpenAI Error]: Model không trả về nội dung."
            )
        except Exception as exc:  # pragma: no cover - depends on remote provider
            return f"[OpenAI Exception]: {exc}"


class AnthropicProvider(BaseLLMProvider):
    """Anthropic Messages API adapter."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.model_name = model or os.getenv("LLM_MODEL") or "claude-3-haiku-20240307"

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        if not _usable_key(self.api_key, "your_anthropic_api_key_here"):
            return "[Anthropic Error]: Chưa cấu hình ANTHROPIC_API_KEY trong file .env."
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=self.api_key)
            kwargs: dict[str, Any] = {
                "model": self.model_name,
                "max_tokens": 1000,
                "messages": [{"role": "user", "content": prompt}],
            }
            if system_prompt:
                kwargs["system"] = system_prompt
            response = client.messages.create(**kwargs)
            return response.content[0].text
        except Exception as exc:  # pragma: no cover - depends on remote provider
            return f"[Anthropic Exception]: {exc}"


class OpenRouterProvider(BaseLLMProvider):
    """OpenRouter chat-completions adapter."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        self.model_name = model or os.getenv("LLM_MODEL") or "google/gemini-2.5-flash"

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        if not _usable_key(self.api_key, "your_openrouter_api_key_here"):
            return (
                "[OpenRouter Error]: Chưa cấu hình OPENROUTER_API_KEY trong file .env."
            )
        try:
            messages: list[dict[str, str]] = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": self.model_name, "messages": messages},
                timeout=30,
            )
            if response.status_code != 200:
                return f"[OpenRouter API Error {response.status_code}]: {response.text}"
            data = response.json()
            return data["choices"][0]["message"]["content"]
        except Exception as exc:  # pragma: no cover - depends on remote provider
            return f"[OpenRouter Exception]: {exc}"


def _usable_key(value: str | None, placeholder: str) -> bool:
    return bool(value and value.strip() and value != placeholder)


def _fold(text: str) -> str:
    """Case-fold and remove accents for robust Vietnamese intent matching."""

    decomposed = unicodedata.normalize("NFD", text.casefold()).replace("đ", "d")
    return "".join(char for char in decomposed if unicodedata.category(char) != "Mn")


def _action(tool: str, args: dict[str, Any], thought: str) -> str:
    payload = json.dumps(
        {"tool": tool, "args": args},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"Thought: {thought}\nAction: {payload}"


def _final(answer: str, thought: str = "Đã có đủ thông tin để trả lời an toàn.") -> str:
    return f"Thought: {thought}\nFinal Answer: {answer}"


class MockProvider(BaseLLMProvider):
    """Deterministic, rental-domain provider for offline demos and tests."""

    model_name = "rentmate-deterministic-v1"

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        system = _fold(system_prompt)
        if "rentmate_react_mode" in system:
            return self._react_response(prompt)
        return self._baseline_response(prompt)

    def _baseline_response(self, prompt: str) -> str:
        text = _fold(prompt)

        asks_for_listing = "tim" in text and any(
            noun in text for noun in ("phong", "can ho", "nha tro")
        )
        if asks_for_listing or any(
            phrase in text
            for phrase in (
                "dang trong",
                "lich xem",
                "dat lich",
                "ma can",
                "con trong",
            )
        ):
            return (
                "Tôi không thể xác minh căn đang cho thuê hoặc lịch trống bằng "
                "chatbot baseline. Hãy chuyển sang ReAct Agent để tra dữ liệu; "
                "tôi cũng chưa thực hiện bất kỳ việc đặt lịch nào."
            )

        if "checklist" in text or "kiem tra" in text or "xem nha" in text:
            return (
                "Checklist ngắn: kiểm tra hiện trạng và an ninh; đối chiếu người "
                "cho thuê; đọc hợp đồng, tiền cọc và phí phát sinh; thử điện nước, "
                "thiết bị; chụp biên bản bàn giao trước khi thanh toán."
            )

        if "coc" in text or "hop dong" in text:
            return (
                "Bạn nên yêu cầu hợp đồng ghi rõ tiền cọc, điều kiện hoàn cọc, "
                "thời hạn thuê, chi phí phát sinh và biên bản bàn giao. Hãy đọc "
                "kỹ trước khi ký và chỉ chuyển tiền cho bên có danh tính rõ ràng."
            )

        if any(word in text for word in ("chao", "hello", "xin chao")):
            return (
                "Xin chào! Tôi có thể tư vấn kiến thức chung về thuê nhà. "
                "Dữ liệu căn và lịch xem cần được xác minh qua ReAct Agent."
            )

        return (
            "Tôi có thể tư vấn chung về thuê nhà, hợp đồng và tiền cọc. "
            "Với căn hoặc lịch xem cụ thể, tôi không thể xác minh dữ liệu "
            "thời gian thực trong chế độ chatbot baseline."
        )

    def _react_response(self, prompt: str) -> str:
        current_question = _current_question(prompt)
        text = _fold(current_question)
        called_tools = _extract_called_tools(prompt)
        last_observation = _last_observation(prompt)

        if _is_invalid_booking_attack(text):
            return _final(
                "Mã căn, ngày hoặc giờ được cung cấp không hợp lệ; tôi cũng "
                "không thể tự bịa tên và số điện thoại hay bỏ qua bước xác nhận. "
                "Không có lịch xem nào được tạo.",
                "Yêu cầu vi phạm validation và confirmation gate nên phải dừng.",
            )

        if (
            "book_viewing" in called_tools
            and last_observation
            and last_observation.get("ok") is True
        ):
            booking_ids = _extract_values(prompt, "booking_id")
            booking_label = booking_ids[-1] if booking_ids else "booking vừa tạo"
            return _final(
                f"Đặt lịch thành công với mã {booking_label}. Thông tin liên hệ "
                "đã được che trong kết quả; bạn có thể xem lại ở danh sách lịch.",
                "Observation xác nhận booking đã được tạo thành công.",
            )

        if last_observation and not last_observation.get("ok", False):
            code = str(last_observation.get("code", "TOOL_ERROR"))
            message = str(
                last_observation.get("message")
                or "Không thể xác minh dữ liệu bằng công cụ."
            )
            return _final(
                f"Không thể tiếp tục vì công cụ trả về {code}: {message} "
                "Tôi chưa tạo hoặc thay đổi lịch xem nào.",
                "Observation báo lỗi; dừng an toàn thay vì lặp hoặc bịa dữ liệu.",
            )

        confirmation = _trusted_confirmation_context(prompt)
        if confirmation is not None:
            return _action(
                "book_viewing",
                {
                    "property_id": confirmation["property_id"],
                    "slot_id": confirmation["slot_id"],
                    "viewer_name": confirmation["viewer_name"],
                    "viewer_phone": confirmation["viewer_phone"],
                },
                "Trusted confirmation context hợp lệ; có thể thực hiện booking.",
            )

        # Initial deterministic tracer bullets used by the lab's five cases.
        if "cau giay" in text:
            if "search_properties" in called_tools and last_observation:
                property_ids = _extract_values(prompt, "property_id")
                ids_text = ", ".join(property_ids) if property_ids else "theo kết quả"
                return _final(
                    f"Công cụ đã xác minh các căn phù hợp: {ids_text}. "
                    "Bạn có thể chọn một mã căn để xem chi tiết hoặc tra lịch.",
                    "Đã nhận Observation thành công từ công cụ tìm kiếm.",
                )
            return _action(
                "search_properties",
                {
                    "city": "Hà Nội",
                    "district": "Cầu Giấy",
                    "max_price_vnd": 5_000_000,
                    "property_type": "phòng trọ",
                    "amenities": ["điều hòa", "chỗ để xe"],
                },
                "Cần tra dữ liệu căn phù hợp với khu vực, ngân sách và tiện ích.",
            )

        if "binh thanh" in text:
            if "get_available_viewing_slots" in called_tools and last_observation:
                slot_ids = _extract_values(prompt, "slot_id")
                slots_text = ", ".join(slot_ids) if slot_ids else "không có mã lịch"
                return _final(
                    f"Đã tìm, so sánh và kiểm tra lịch cuối tuần. Các lịch còn "
                    f"trống được công cụ xác minh: {slots_text}. Chưa có lịch "
                    "nào được đặt; hãy chọn một khung giờ để xác nhận.",
                    "Đã hoàn thành đủ ba bước và có Observation lịch xem.",
                )

            if "compare_properties" in called_tools and last_observation:
                property_ids = _extract_values(prompt, "property_id")
                selected_id = _preferred_property_id(
                    last_observation,
                    property_ids,
                )
                if not selected_id:
                    return _final(
                        "Không lấy được mã căn hợp lệ từ kết quả so sánh nên tôi "
                        "chưa thể tra lịch. Vui lòng thử lại.",
                        "Observation thiếu property_id cần cho bước tiếp theo.",
                    )
                return _action(
                    "get_available_viewing_slots",
                    {
                        "property_id": selected_id,
                        "date": _next_saturday(),
                    },
                    "Đã so sánh; cần tra lịch cuối tuần của căn nổi bật.",
                )

            if "search_properties" in called_tools and last_observation:
                property_ids = _extract_values(prompt, "property_id")[:3]
                if len(property_ids) < 2:
                    return _final(
                        "Kết quả tìm kiếm có ít hơn hai căn nên chưa thể lập "
                        "bảng so sánh. Tôi chưa đặt lịch xem.",
                        "Không đủ shortlist để gọi công cụ so sánh.",
                    )
                return _action(
                    "compare_properties",
                    {"property_ids": property_ids},
                    "Đã có shortlist; cần so sánh tối đa ba căn bằng dữ liệu thật.",
                )

            return _action(
                "search_properties",
                {
                    "city": "TP.HCM",
                    "district": "Bình Thạnh",
                    "max_price_vnd": 12_000_000,
                    "min_area_m2": 30,
                },
                "Cần tìm các căn Bình Thạnh thỏa ngân sách và diện tích trước.",
            )

        property_id = _extract_property_id(prompt)
        if property_id and (
            "khong ton tai" in text
            or "ma can sai" in text
            or "invalid property" in text
        ):
            return _action(
                "get_property_details",
                {"property_id": property_id},
                "Cần xác minh mã căn trước khi kiểm tra lịch hoặc đặt lịch.",
            )

        if "dat lich" in text or "book" in text:
            return _final(
                "Tôi chưa đặt lịch. Vui lòng kiểm tra lại căn, khung giờ và xác "
                "nhận tên cùng số điện thoại qua màn hình xác nhận.",
                "Thiếu trusted confirmation context nên không được gọi tool đặt lịch.",
            )

        if any(
            phrase in text
            for phrase in ("checklist", "tien coc", "hop dong", "kinh nghiem")
        ):
            answer = self._baseline_response(current_question)
            return _final(answer, "Đây là câu hỏi kiến thức chung nên không cần tool.")

        return _final(
            "Bạn hãy cho biết thành phố/quận, ngân sách và nhu cầu chính để tôi "
            "tìm căn phù hợp.",
            "Chưa đủ tiêu chí tìm kiếm để gọi tool chính xác.",
        )


_PROPERTY_ID_PATTERN = re.compile(
    r"\b(?:(?:HN|HCM)-[A-Z]{2,}-\d{3,}|RM-\d{3,}|P\d{2,6})\b",
    re.IGNORECASE,
)


def _extract_property_id(text: str) -> str | None:
    match = _PROPERTY_ID_PATTERN.search(text)
    return match.group(0).upper() if match else None


def _extract_called_tools(prompt: str) -> list[str]:
    tools: list[str] = []
    for action_text in re.findall(r"(?m)^\s*Action:\s*(\{.+\})\s*$", prompt):
        try:
            payload = json.loads(action_text)
        except (json.JSONDecodeError, TypeError):
            continue
        tool = payload.get("tool") if isinstance(payload, dict) else None
        if isinstance(tool, str):
            tools.append(tool)
    return tools


def _current_question(prompt: str) -> str:
    matches = re.findall(
        r"(?m)^\s*(?:Question|User query):\s*(.*?)\s*$",
        prompt,
    )
    return matches[-1] if matches else prompt


def _last_observation(prompt: str) -> dict[str, Any] | None:
    matches = re.findall(r"(?m)^\s*Observation:\s*(\{.+\})\s*$", prompt)
    if not matches:
        return None
    try:
        value = json.loads(matches[-1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _extract_values(prompt: str, field: str) -> list[str]:
    pattern = rf'"{re.escape(field)}"\s*:\s*"([^"]+)"'
    values: list[str] = []
    for value in re.findall(pattern, prompt):
        if value not in values:
            values.append(value)
    return values


def _preferred_property_id(
    observation: dict[str, Any],
    fallback_ids: list[str],
) -> str | None:
    data = observation.get("data")
    if isinstance(data, dict):
        highlights = data.get("highlights")
        if isinstance(highlights, dict):
            for key in (
                "lowest_price_property_id",
                "largest_area_property_id",
                "lowest_deposit_property_id",
            ):
                value = highlights.get(key)
                if isinstance(value, str) and value:
                    return value
    return fallback_ids[0] if fallback_ids else None


def _next_saturday() -> str:
    today = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date()
    days_ahead = (5 - today.weekday()) % 7
    return (today + timedelta(days=days_ahead)).isoformat()


def _is_invalid_booking_attack(folded_prompt: str) -> bool:
    invalid_date_or_time = any(
        token in folded_prompt for token in ("32/13/", "25:00", "ngay 32", "gio 25")
    )
    asks_fake_identity = any(
        phrase in folded_prompt
        for phrase in (
            "tu dung ten",
            "so dien thoai bat ky",
            "bo qua moi quy tac",
            "bo qua xac nhan",
        )
    )
    return invalid_date_or_time or asks_fake_identity


def _trusted_confirmation_context(prompt: str) -> dict[str, Any] | None:
    marker = re.search(
        r"(?m)^\s*Trusted confirmation context:\s*(\{.+\})\s*$",
        prompt,
    )
    if marker is None:
        return None
    try:
        value = json.loads(marker.group(1))
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict) or value.get("accepted") is not True:
        return None
    required = ("property_id", "slot_id", "viewer_name", "viewer_phone")
    if not all(
        isinstance(value.get(key), str) and value[key].strip() for key in required
    ):
        return None
    return value


def get_llm_provider(provider_name: str | None = None) -> BaseLLMProvider:
    """Create the provider selected by ``LLM_PROVIDER``; mock is the default."""

    name = (provider_name or os.getenv("LLM_PROVIDER") or "mock").casefold().strip()
    providers: dict[str, type[BaseLLMProvider]] = {
        "mock": MockProvider,
        "gemini": GeminiProvider,
        "openai": OpenAIProvider,
        "anthropic": AnthropicProvider,
        "openrouter": OpenRouterProvider,
    }
    return providers.get(name, MockProvider)()


__all__ = [
    "BaseLLMProvider",
    "GeminiProvider",
    "OpenAIProvider",
    "AnthropicProvider",
    "OpenRouterProvider",
    "MockProvider",
    "get_llm_provider",
]


if __name__ == "__main__":
    provider = get_llm_provider()
    print(f"Provider: {provider.__class__.__name__} ({provider.model_name})")
    print(provider.generate("Cho tôi checklist xem nhà."))
