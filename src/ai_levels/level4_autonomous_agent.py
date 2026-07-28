"""Level 4 — bounded planning and session memory for rental goals.

The shared ``AgentEngine`` remains responsible for real orchestration.  This
module is an educational planning demo and deliberately stops before the
side-effecting ``book_viewing`` tool.
"""

from __future__ import annotations

import unicodedata
from copy import deepcopy
from typing import Any, Callable

try:
    from prompts import MAX_AUTONOMOUS_STEPS
except ImportError:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from prompts import MAX_AUTONOMOUS_STEPS


PlanStep = dict[str, Any]
StepRunner = Callable[[PlanStep], Any]


class AutonomousGoalAgent:
    """Create a bounded read-only plan, remember progress and require confirmation."""

    def __init__(self, goal: str, max_steps: int = MAX_AUTONOMOUS_STEPS):
        self.goal = (goal or "").strip()
        requested_steps = max_steps if isinstance(max_steps, int) else 1
        self.max_steps = max(1, min(requested_steps, MAX_AUTONOMOUS_STEPS))
        self.memory: list[dict[str, Any]] = []

    def create_plan(self) -> list[PlanStep]:
        """Build the smallest useful rental plan without a booking action."""

        text = _fold_text(self.goal)
        plan: list[PlanStep] = [
            {
                "step": 1,
                "objective": "Tìm các căn phù hợp với tiêu chí người dùng.",
                "tool": "search_properties",
                "side_effect": "read_only",
            }
        ]

        if any(word in text for word in ("so sanh", "compare", "shortlist", "tot nhat")):
            plan.append(
                {
                    "step": len(plan) + 1,
                    "objective": "So sánh tối đa ba căn trong shortlist.",
                    "tool": "compare_properties",
                    "side_effect": "read_only",
                }
            )

        if any(
            word in text
            for word in (
                "lich",
                "khung gio",
                "xem nha",
                "dat",
                "viewing",
                "slot",
                "book",
            )
        ):
            plan.append(
                {
                    "step": len(plan) + 1,
                    "objective": "Kiểm tra các khung giờ xem nhà còn trống.",
                    "tool": "get_available_viewing_slots",
                    "side_effect": "read_only",
                }
            )

        if _requests_booking(text):
            plan.append(
                {
                    "step": len(plan) + 1,
                    "objective": (
                        "Dừng và yêu cầu người dùng xác nhận căn, khung giờ, "
                        "tên và số điện thoại qua confirmation gate."
                    ),
                    "tool": None,
                    "side_effect": "confirmation_required",
                }
            )

        return plan[: self.max_steps]

    def remember(self, step: PlanStep, result: Any) -> None:
        """Save a sanitized progress record in this agent's session memory."""

        self.memory.append(
            {
                "goal": self.goal,
                "step": deepcopy(step),
                "result": result,
            }
        )

    def execute(self, step_runner: StepRunner | None = None) -> dict[str, Any]:
        """Plan and optionally execute read-only steps through an injected runner."""

        plan = self.create_plan()
        for step in plan:
            if step.get("tool") is None:
                result: Any = {"status": "waiting_for_confirmation"}
            elif step_runner is None:
                result = {"status": "planned"}
            else:
                result = step_runner(deepcopy(step))
            self.remember(step, result)

        requires_confirmation = _requests_booking(_fold_text(self.goal))
        return {
            "goal": self.goal,
            "plan": deepcopy(plan),
            "memory": deepcopy(self.memory),
            "requires_confirmation": requires_confirmation,
            "evaluation": {
                "planned_steps": len(plan),
                "completed_with_runner": step_runner is not None,
                "next_action": (
                    "await_user_confirmation"
                    if requires_confirmation
                    else "present_results"
                ),
            },
        }


def _requests_booking(text: str) -> bool:
    return "dat lich" in text or "book" in text or "xac nhan lich" in text


def _fold_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.casefold()).replace("đ", "d")
    return "".join(
        character
        for character in decomposed
        if unicodedata.category(character) != "Mn"
    )


if __name__ == "__main__":
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    agent = AutonomousGoalAgent(
        "Tìm, so sánh căn ở Bình Thạnh rồi kiểm tra và đặt lịch xem."
    )
    print(agent.execute())
