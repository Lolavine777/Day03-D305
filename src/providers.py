"""LLM provider adapters used by RentMate.

Runtime composition requires a real provider selected through ``LLM_PROVIDER``.
The deterministic :class:`MockProvider` implements the same
``generate(prompt, system_prompt) -> str`` seam only for isolated tests.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime, timedelta
from typing import Any

import requests
from dotenv import load_dotenv

try:
    from .timezone_support import VIETNAM_TIMEZONE
except ImportError:  # Supports ``python src/app.py``.
    from timezone_support import VIETNAM_TIMEZONE


load_dotenv()


class ProviderConfigurationError(RuntimeError):
    """Raised when the runtime cannot build the configured real LLM provider."""


class ProviderRequestError(RuntimeError):
    """Raised when a configured LLM provider cannot complete a request."""


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
            raise ProviderConfigurationError(
                "Chưa cấu hình GEMINI_API_KEY hợp lệ trong file .env."
            )
        try:
            from google import genai

            client = genai.Client(api_key=self.api_key)
            contents = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
            response = client.models.generate_content(
                model=self.model_name,
                contents=contents,
            )
            if not response.text:
                raise ProviderRequestError("Gemini không trả về nội dung.")
            return response.text
        except ProviderRequestError:
            raise
        except Exception as exc:  # pragma: no cover - depends on remote provider
            raise _provider_request_error(
                "Gemini",
                "GEMINI_API_KEY",
                exc,
            ) from exc


class OpenAIProvider(BaseLLMProvider):
    """OpenAI chat-completions adapter."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model_name = model or os.getenv("LLM_MODEL") or "gpt-4o-mini"
        configured_base_url = (
            base_url
            or os.getenv("LLM_BASE_URL")
            or os.getenv("OPENAI_BASE_URL")
        )
        self.base_url = configured_base_url.strip() if configured_base_url else None

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        if not _usable_key(self.api_key, "your_openai_api_key_here"):
            raise ProviderConfigurationError(
                "Chưa cấu hình OPENAI_API_KEY hợp lệ trong file .env."
            )
        try:
            import openai

            client_options: dict[str, Any] = {"api_key": self.api_key}
            if self.base_url:
                client_options["base_url"] = self.base_url
            client = openai.OpenAI(**client_options)
            messages: list[dict[str, str]] = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            response = client.chat.completions.create(
                model=self.model_name,
                messages=messages,
            )
            content = response.choices[0].message.content
            if not content:
                raise ProviderRequestError("OpenAI không trả về nội dung.")
            return content
        except ProviderRequestError:
            raise
        except Exception as exc:  # pragma: no cover - depends on remote provider
            raise _provider_request_error(
                "OpenAI",
                "OPENAI_API_KEY",
                exc,
            ) from exc


class AnthropicProvider(BaseLLMProvider):
    """Anthropic Messages API adapter."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.model_name = model or os.getenv("LLM_MODEL") or "claude-3-haiku-20240307"

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        if not _usable_key(self.api_key, "your_anthropic_api_key_here"):
            raise ProviderConfigurationError(
                "Chưa cấu hình ANTHROPIC_API_KEY hợp lệ trong file .env."
            )
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
            content = response.content[0].text
            if not content:
                raise ProviderRequestError("Anthropic không trả về nội dung.")
            return content
        except ProviderRequestError:
            raise
        except Exception as exc:  # pragma: no cover - depends on remote provider
            raise _provider_request_error(
                "Anthropic",
                "ANTHROPIC_API_KEY",
                exc,
            ) from exc


class OpenRouterProvider(BaseLLMProvider):
    """OpenRouter chat-completions adapter."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        self.model_name = model or os.getenv("LLM_MODEL") or "google/gemini-2.5-flash"

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        if not _usable_key(self.api_key, "your_openrouter_api_key_here"):
            raise ProviderConfigurationError(
                "Chưa cấu hình OPENROUTER_API_KEY hợp lệ trong file .env."
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
                raise _provider_request_error(
                    "OpenRouter",
                    "OPENROUTER_API_KEY",
                    response,
                )
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            if not content:
                raise ProviderRequestError("OpenRouter không trả về nội dung.")
            return content
        except ProviderRequestError:
            raise
        except Exception as exc:  # pragma: no cover - depends on remote provider
            raise _provider_request_error(
                "OpenRouter",
                "OPENROUTER_API_KEY",
                exc,
            ) from exc


def _usable_key(value: str | None, placeholder: str) -> bool:
    normalized = value.strip() if value else ""
    return bool(normalized and normalized != placeholder)


def _provider_request_error(
    provider_name: str,
    api_key_name: str,
    failure: Any,
) -> ProviderRequestError:
    """Map provider failures to safe, actionable messages without raw details."""

    status_code = getattr(failure, "status_code", None)
    error_code = str(getattr(failure, "code", "") or "").casefold()
    if status_code in {401, 403} or error_code in {
        "invalid_api_key",
        "authentication_error",
    }:
        return ProviderRequestError(
            f"{provider_name} từ chối API key (HTTP {status_code or 401}). "
            f"Hãy cập nhật {api_key_name} trong .env rồi khởi động lại backend."
        )
    if status_code == 429:
        return ProviderRequestError(
            f"{provider_name} đang giới hạn lượt gọi hoặc tài khoản đã hết quota "
            "(HTTP 429). Hãy kiểm tra quota/billing rồi thử lại."
        )
    if status_code == 404:
        return ProviderRequestError(
            f"{provider_name} không tìm thấy model đã cấu hình (HTTP 404). "
            "Hãy kiểm tra LLM_MODEL trong .env."
        )
    return ProviderRequestError(
        f"Không thể hoàn tất yêu cầu tới {provider_name}. "
        "Hãy kiểm tra kết nối, cấu hình provider và thử lại."
    )


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
    """Deterministic rental-domain provider for isolated tests only."""

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
    today = datetime.now(VIETNAM_TIMEZONE).date()
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
    """Create the real provider selected by ``LLM_PROVIDER``."""

    configured_name = provider_name or os.getenv("LLM_PROVIDER")
    if not configured_name or not configured_name.strip():
        raise ProviderConfigurationError(
            "Thiếu LLM_PROVIDER trong file .env. "
            "Hãy chọn gemini, openai, anthropic hoặc openrouter."
        )
    name = configured_name.casefold().strip()
    providers: dict[
        str,
        tuple[type[BaseLLMProvider], str, str],
    ] = {
        "gemini": (
            GeminiProvider,
            "GEMINI_API_KEY",
            "your_gemini_api_key_here",
        ),
        "openai": (
            OpenAIProvider,
            "OPENAI_API_KEY",
            "your_openai_api_key_here",
        ),
        "anthropic": (
            AnthropicProvider,
            "ANTHROPIC_API_KEY",
            "your_anthropic_api_key_here",
        ),
        "openrouter": (
            OpenRouterProvider,
            "OPENROUTER_API_KEY",
            "your_openrouter_api_key_here",
        ),
    }
    provider_config = providers.get(name)
    if provider_config is None:
        raise ProviderConfigurationError(
            f"LLM_PROVIDER '{name}' không được hỗ trợ. "
            "Hãy chọn gemini, openai, anthropic hoặc openrouter."
        )
    provider_class, api_key_name, placeholder = provider_config
    api_key = os.getenv(api_key_name)
    if not _usable_key(api_key, placeholder):
        raise ProviderConfigurationError(
            f"Thiếu {api_key_name} hợp lệ cho LLM_PROVIDER='{name}' trong file .env."
        )
    return provider_class(api_key=api_key.strip())


__all__ = [
    "BaseLLMProvider",
    "ProviderConfigurationError",
    "ProviderRequestError",
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
