"""
输入补全 —— 仅 / 命令补全，不干扰普通输入和粘贴
"""

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.auto_suggest import AutoSuggest, Suggestion


class CommandCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if "\n" in text:
            return
        text = text.strip()
        if not text.startswith("/"):
            return
        if " " in text:
            return
        from cli.registry import get_all
        for cmd, desc in sorted(get_all().items()):
            if cmd.startswith(text):
                yield Completion(cmd, start_position=-len(text), display_meta=desc)


class CommandAutoSuggest(AutoSuggest):
    def get_suggestion(self, buffer, document):
        text = document.text_before_cursor
        if "\n" in text or " " in text:
            return None
        if not text.startswith("/"):
            return None
        from cli.registry import get_all
        for cmd in sorted(get_all().keys()):
            if cmd.startswith(text) and cmd != text:
                return Suggestion(cmd[len(text):])
        return None


def create_session():
    return PromptSession(
        completer=CommandCompleter(),
        auto_suggest=CommandAutoSuggest(),
        complete_while_typing=True,
    )
