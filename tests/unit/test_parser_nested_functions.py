"""Nested function detection — recursive AST traversal."""

from __future__ import annotations

from pathlib import Path

from refactory.core.logger import get_service_logger
from refactory.parser.service import ParserService


def _service() -> ParserService:
    return ParserService(
        ignore_dirs=[".git", "venv", "__pycache__"],
        logger=get_service_logger("test.parser.nested"),
    )


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_one_level_nested_functions(tmp_path: Path):
    path = _write(
        tmp_path / "one_level.py",
        """
def outer():
    def inner():
        return True
    return inner()

def another_function():
    return "Hello"
""",
    )
    parsed = _service().parse_file(path)
    top = {fn.name for fn in parsed.module.functions}
    assert top == {"outer", "another_function"}

    outer = next(fn for fn in parsed.module.functions if fn.name == "outer")
    assert len(outer.nested_functions) == 1
    inner = outer.nested_functions[0]
    assert inner.name == "inner"
    assert inner.parent_function == "outer"
    assert inner.nested_functions == []


def test_multiple_nested_levels(tmp_path: Path):
    path = _write(
        tmp_path / "multi_level.py",
        """
def level1():
    def level2():
        def level3():
            return 3
        return level3()
    return level2()
""",
    )
    parsed = _service().parse_file(path)
    level1 = parsed.module.functions[0]
    assert level1.name == "level1"
    assert len(level1.nested_functions) == 1

    level2 = level1.nested_functions[0]
    assert level2.name == "level2"
    assert level2.parent_function == "level1"
    assert len(level2.nested_functions) == 1

    level3 = level2.nested_functions[0]
    assert level3.name == "level3"
    assert level3.parent_function == "level2"


def test_nested_async_functions(tmp_path: Path):
    path = _write(
        tmp_path / "nested_async.py",
        """
async def outer():
    async def inner():
        return 1
    return await inner()
""",
    )
    parsed = _service().parse_file(path)
    outer = parsed.module.functions[0]
    assert outer.is_async is True
    inner = outer.nested_functions[0]
    assert inner.name == "inner"
    assert inner.is_async is True
    assert inner.parent_function == "outer"


def test_nested_generators(tmp_path: Path):
    path = _write(
        tmp_path / "nested_gen.py",
        """
def outer():
    def inner():
        yield 1
        yield 2
    return inner
""",
    )
    parsed = _service().parse_file(path)
    outer = parsed.module.functions[0]
    inner = outer.nested_functions[0]
    assert inner.name == "inner"
    assert inner.is_generator is True
    assert inner.parent_function == "outer"


def test_method_containing_nested_functions(tmp_path: Path):
    path = _write(
        tmp_path / "method_nested.py",
        """
class AuthService:
    def login(self, user):
        def validate():
            return True
        return validate()
""",
    )
    parsed = _service().parse_file(path)
    cls = parsed.module.classes[0]
    login = next(m for m in cls.methods if m.name == "login")
    assert login.is_method is True
    assert len(login.nested_functions) == 1
    validate = login.nested_functions[0]
    assert validate.name == "validate"
    assert validate.parent_function == "login"
    assert validate.is_method is False


def test_nested_function_inside_control_flow(tmp_path: Path):
    """Nested defs inside if/for must still be discovered."""
    path = _write(
        tmp_path / "control_flow.py",
        """
def outer(flag):
    if flag:
        def inner():
            return 1
        return inner()
    return 0
""",
    )
    parsed = _service().parse_file(path)
    outer = parsed.module.functions[0]
    assert [n.name for n in outer.nested_functions] == ["inner"]
    assert outer.nested_functions[0].parent_function == "outer"
