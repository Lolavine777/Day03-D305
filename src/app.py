"""
🚀 CORE AGENT APP (Dành cho Role 4: Core Agent Developer)
File chính ghép nối tất cả các thành phần: Tools + Prompts + Test Cases + Multi-Provider.
"""

import json
import os
import sys
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
from prompts import CHATBOT_BASELINE_PROMPT
from providers import get_llm_provider

load_dotenv()

def load_test_cases():
    """Đọc bộ test cases từ config/test_cases.json của Role 1"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, "config", "test_cases.json")
    
    # Fallback kiểm tra nếu file ở thư mục hiện tại
    if not os.path.exists(config_path):
        config_path = "test_cases.json"
        
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def run_baseline_chatbot(user_query: str, provider, *, emit: bool = True) -> str:
    """
    Dựng Chatbot gốc (Baseline) không có công cụ.

    Baseline chỉ thực hiện đúng một lượt gọi provider.
    ``emit=False`` dùng khi cần lưu kết quả để trace hoặc chạy test.
    """
    response = provider.generate(user_query, system_prompt=CHATBOT_BASELINE_PROMPT)
    if emit:
        print(f"\n💬 [CHATBOT BASELINE] Câu hỏi: {user_query}")
        print(f"⚙️ System Prompt: {CHATBOT_BASELINE_PROMPT.strip()}")
        print(f"🤖 Chatbot trả lời:\n{response}")
    return response


def run_baseline_suite(provider, tests=None, *, emit: bool = True):
    """Chạy baseline trên từng test case và trả kết quả để ghi trace."""
    tests = load_test_cases() if tests is None else tests
    results = []
    for case in tests:
        results.append({
            "id": case.get("id"),
            "question": case["question"],
            "response": run_baseline_chatbot(case["question"], provider, emit=emit),
        })
    return results


if __name__ == "__main__":
    print("==================================================")
    print("🏫 ĐẠI HỌC VINUNI - BÀI LAB 3: CHATBOT VS REACT AGENT")
    print("==================================================")
    
    # Khởi tạo Multi-Provider LLM Adapter (Đọc từ biến môi trường LLM_PROVIDER)
    provider = get_llm_provider()
    model_name = getattr(provider, "model_name", "Offline Mock Mode")
    print(f"🔌 LLM Provider đang hoạt động: {provider.__class__.__name__} (Model: {model_name})")
    
    tests = load_test_cases()
    print(f"✅ Đã tải thành công {len(tests)} Test Cases từ config/test_cases.json\n")
    
    print("--- MỐC 2: CHẠY BASELINE TRÊN 5 TEST CASES ---")
    run_baseline_suite(provider, tests)
