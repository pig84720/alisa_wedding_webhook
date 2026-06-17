import unittest

from handlers.seat import (
    SeatCacheEntry,
    format_seat_confirm_text,
    format_seat_result_text,
    normalize_guest_name,
)


def _entry(raw_name: str, table: int | str | None) -> SeatCacheEntry:
    normalized_name = normalize_guest_name(raw_name)
    return SeatCacheEntry(
        raw_name=raw_name,
        normalized_name=normalized_name,
        table=table,
        syllables=tuple(),
    )


class SeatFormattingTests(unittest.TestCase):
    def test_normalize_guest_name_strips_notes_and_digits_for_matching(self) -> None:
        self.assertEqual(normalize_guest_name(" 吳和洺(素) "), "吳和洺")
        self.assertEqual(normalize_guest_name("許馨云3"), "許馨云")

    def test_single_result_keeps_full_firestore_name(self) -> None:
        result = format_seat_result_text((_entry("吳和洺(素)", 6),))
        self.assertEqual(result, "吳和洺(素) 的座位 在第6桌")

    def test_same_table_group_lists_all_numeric_suffix_variants(self) -> None:
        result = format_seat_result_text(
            (
                _entry("許馨云1", 12),
                _entry("許馨云2", 12),
                _entry("許馨云3", 12),
            )
        )
        self.assertEqual(
            result,
            "以下賓客的座位都在第12桌：\n許馨云1、許馨云2、許馨云3",
        )

    def test_multi_table_group_lists_each_full_name_by_table(self) -> None:
        result = format_seat_result_text(
            (
                _entry("吳和洺(素)", 6),
                _entry("吳和洺(兒童椅)", 9),
            )
        )
        self.assertEqual(
            result,
            "查到以下座位資訊：\n第6桌：吳和洺(素)\n第9桌：吳和洺(兒童椅)",
        )

    def test_confirm_text_keeps_full_names_for_multi_match(self) -> None:
        result = format_seat_confirm_text(
            (
                _entry("吳和洺(素)", 6),
                _entry("吳和洺(兒童椅)", 9),
            )
        )
        self.assertEqual(
            result,
            "您是指以下賓客嗎？\n第6桌：吳和洺(素)\n第9桌：吳和洺(兒童椅)\n請回覆「是」確認，或重新輸入姓名",
        )


if __name__ == "__main__":
    unittest.main()
