import unicodedata

import pytest

from messenger_ai.config import Settings
from messenger_ai.features import complex_question, plan

BRIDGE = (
    "Bốn người qua cầu ban đêm mất lần lượt 1, 2, 7 và 13 phút. "
    "Tối đa hai người đi cùng; đi cùng mất thời gian của người chậm hơn. "
    "Chỉ có một đèn pin, mọi lượt đi hoặc quay lại đều phải mang đèn. "
    "Ban đầu tất cả cùng ở một đầu cầu. Tổng thời gian nhỏ nhất để tất cả "
    "sang bên kia là bao nhiêu phút? Chỉ trả một số nguyên."
)


def user(text):
    return {"role": "user", "content": text}


def no_accents(text):
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", text.replace("đ", "d"))
        if not unicodedata.combining(c)
    )


@pytest.mark.parametrize(
    "text",
    [
        BRIDGE,
        "Tính toán bài toán sau: " + BRIDGE,
        "Phân tích và so sánh hai thuật toán này",
        "Debug đoạn code này giúp mình: ```a = b[0]```",
        "x + 5 = 17, tìm x",
    ],
)
@pytest.mark.parametrize("normalize", [str, no_accents])
def test_auto_recognizes_numeric_word_problems_and_unaccented_questions(
    text, normalize
):
    assert complex_question([user(normalize(text))])


@pytest.mark.parametrize(
    "latest",
    [
        "thế à",
        "vậy hả",
        "ok",
        "ừ cảm ơn bạn",
        "chào bạn",
        "hôm nay ngày mấy?",
        "Mạnh đang làm gì?",
        "tí đi chơi k",
        "12 nhân 17 bằng mấy?",
        "mình đi ăn đây",
    ],
)
def test_previous_hard_question_does_not_stick_to_new_smalltalk(latest):
    history = [
        user("Tính toán: " + BRIDGE),
        {"role": "assistant", "content": "20"},
        user(latest),
    ]
    assert not complex_question(history)


@pytest.mark.parametrize(
    "latest",
    [
        "Nếu đổi 13 thành 14 phút thì sao?",
        "neu doi 13 thanh 14 phut thi sao?",
        "Còn 15 phút?",
        "Tính lại giúp mình",
        "Chỉ trả một số nguyên",
        "Làm tiếp đi",
    ],
)
def test_real_followup_inherits_the_problem(latest):
    assert complex_question(
        [user(BRIDGE), {"role": "assistant", "content": "20"}, user(latest)]
    )


def test_followup_does_not_cross_a_changed_subject_or_use_assistant_instructions():
    assert not complex_question([user(BRIDGE), user("đi ăn chưa?"), user("còn bạn?")])
    assert not complex_question(
        [
            {"role": "assistant", "content": "Phân tích tính toán " * 40},
            user("còn bạn?"),
        ]
    )


@pytest.mark.parametrize(
    "model,minimum",
    [
        ("gemini-3.5-flash-lite", "minimal"),
        ("gemini-3.8-flash", "low"),
        ("gemma-4-26b-a4b-it", "minimal"),
    ],
)
@pytest.mark.parametrize("text", ["thế à", "ok cảm ơn bạn", "Chào bạn"])
def test_auto_uses_minimum_for_unambiguous_reactions_even_after_math(
    model, minimum, text
):
    features = plan(
        Settings(ai_provider="google", model=model, reasoning_mode="auto"),
        [user(BRIDGE), user(text)],
    )
    assert features.thinking == {"thinkingLevel": minimum, "includeThoughts": False}


def test_native_dynamic_thinking_is_preserved_for_substantive_questions_and_manual_on():
    history = [user(BRIDGE)]
    assert (
        plan(
            Settings(
                ai_provider="google",
                model="gemini-3.5-flash-lite",
                reasoning_mode="auto",
            ),
            history,
        ).thinking["thinkingLevel"]
        == "medium"
    )
    assert (
        plan(
            Settings(
                ai_provider="google", model="gemini-2.5-flash", reasoning_mode="auto"
            ),
            history,
        ).thinking["thinkingBudget"]
        == -1
    )
    assert (
        plan(
            Settings(
                ai_provider="google", model="gemma-4-26b-a4b-it", reasoning_mode="on"
            ),
            [user("thế à")],
        ).thinking["thinkingLevel"]
        == "high"
    )
