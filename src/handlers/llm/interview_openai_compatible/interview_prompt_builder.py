from typing import Dict, Iterable, List, Optional, Tuple


class InterviewPromptBuilder:
    """提示词拼接器。

    负责将多个来源的提示词片段按顺序拼接成：
    1) 初始化系统提示词
    2) 每一轮用户提示词
    """

    def __init__(self, separator: str = "\n\n"):
        self.separator = separator

    def _iter_ordered_items(
        self,
        sources: Optional[Dict[str, str]],
        preferred_order: Optional[List[str]] = None,
    ) -> Iterable[Tuple[str, str]]:
        if not sources:
            return []

        ordered_items: List[Tuple[str, str]] = []
        used_keys = set()

        if preferred_order:
            for key in preferred_order:
                value = sources.get(key)
                if value is None:
                    continue
                text = str(value).strip()
                if not text:
                    continue
                ordered_items.append((key, text))
                used_keys.add(key)

        # 未出现在 preferred_order 里的键保持原始插入顺序追加。
        for key, value in sources.items():
            if key in used_keys:
                continue
            text = str(value).strip()
            if not text:
                continue
            ordered_items.append((key, text))
        return ordered_items

    def _merge_sections(self, sections: List[str]) -> str:
        clean_sections = [item.strip() for item in sections if item and item.strip()]
        return self.separator.join(clean_sections)

    def build_system_prompt(
        self,
        base_system_prompt: str,
        initial_sources: Optional[Dict[str, str]] = None,
        preferred_order: Optional[List[str]] = None,
    ) -> str:
        """构建初始化系统提示词。"""
        sections: List[str] = [base_system_prompt]
        for key, text in self._iter_ordered_items(initial_sources, preferred_order):
            sections.append(f"[{key}]\n{text}")
        return self._merge_sections(sections)

    def build_turn_prompt(
        self,
        human_text: str,
        turn_sources: Optional[Dict[str, str]] = None,
        preferred_order: Optional[List[str]] = None,
    ) -> str:
        """构建每轮用户提示词。"""
        sections: List[str] = []
        for key, text in self._iter_ordered_items(turn_sources, preferred_order):
            sections.append(f"[{key}]\n{text}")
        sections.append(f"[candidate_input]\n{human_text}")
        return self._merge_sections(sections)
