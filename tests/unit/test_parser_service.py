"""Unit tests for ParserService (Tree-sitter Python adapter)."""

from __future__ import annotations

from pathlib import Path

import pytest

from refactory.core.exceptions import ParserError
from refactory.core.logger import get_service_logger
from refactory.parser.models import CommentTag, ImportKind
from refactory.parser.service import ParserService
from refactory.review.models import Repository


def _service() -> ParserService:
    return ParserService(ignore_dirs=[".git", "venv", "__pycache__"], logger=get_service_logger("test.parser"))


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture
def sample_file(tmp_path: Path) -> Path:
    content = '''\
"""Module docstring."""
import os
from pathlib import Path
from auth import validate
import jwt as jwt_lib

# TODO: tighten validation
CONSTANT = 42
name: str = "demo"

def helper(x: int) -> int:
    """Helper doc."""
    return x + 1

async def fetch(url: str) -> str:
    yield url  # not really async gen pattern but marks yield
    return url

def outer():
    def nested():
        return 1
    return nested

class UserService:
    """Service doc."""

    @property
    def active(self) -> bool:
        return True

    def login(self, user: str) -> bool:
        """Login user."""
        return validate(user)
'''
    return _write(tmp_path / "user_service.py", content)


def test_parse_module_name_and_docstring(sample_file: Path):
    parsed = _service().parse_file(sample_file)
    assert parsed.module.name == "user_service"
    assert parsed.module.docstring == "Module docstring."
    assert parsed.metadata.language == "python"
    assert parsed.metadata.line_count > 0
    assert parsed.metadata.content_hash


def test_parse_functions_and_nested(sample_file: Path):
    parsed = _service().parse_file(sample_file)
    names = {fn.name for fn in parsed.module.functions}
    assert "helper" in names
    assert "outer" in names
    outer = next(fn for fn in parsed.module.functions if fn.name == "outer")
    assert any(n.name == "nested" for n in outer.nested_functions)
    nested = next(n for n in outer.nested_functions if n.name == "nested")
    assert nested.parent_function == "outer"


def test_parse_async_and_generator(sample_file: Path):
    parsed = _service().parse_file(sample_file)
    fetch = next(fn for fn in parsed.module.functions if fn.name == "fetch")
    assert fetch.is_async is True
    assert fetch.is_generator is True
    assert fetch.return_type == "str"


def test_parse_function_parameters_and_return(sample_file: Path):
    parsed = _service().parse_file(sample_file)
    helper = next(fn for fn in parsed.module.functions if fn.name == "helper")
    assert helper.docstring == "Helper doc."
    assert helper.return_type == "str" or helper.return_type == "int"
    assert any(p.name == "x" for p in helper.parameters)
    param = next(p for p in helper.parameters if p.name == "x")
    assert param.type_hint == "int"


def test_parse_classes_methods_decorators(sample_file: Path):
    parsed = _service().parse_file(sample_file)
    assert len(parsed.module.classes) == 1
    cls = parsed.module.classes[0]
    assert cls.name == "UserService"
    assert cls.docstring == "Service doc."
    method_names = {m.name for m in cls.methods}
    assert "login" in method_names
    assert "active" in method_names
    active = next(m for m in cls.methods if m.name == "active")
    assert any("property" in d for d in active.decorators)
    assert "active" in cls.properties


def test_parse_imports_kinds_and_aliases(sample_file: Path):
    parsed = _service().parse_file(sample_file)
    modules = {imp.module for imp in parsed.module.imports}
    assert "os" in modules
    assert "pathlib" in modules or "Path" in str(parsed.module.imports)
    assert "auth" in modules
    assert "jwt" in modules

    os_imp = next(imp for imp in parsed.module.imports if imp.module == "os")
    assert os_imp.kind == ImportKind.STDLIB

    auth_imp = next(imp for imp in parsed.module.imports if imp.module == "auth")
    assert "validate" in auth_imp.names
    assert auth_imp.kind in {ImportKind.THIRD_PARTY, ImportKind.LOCAL}

    jwt_imp = next(imp for imp in parsed.module.imports if imp.module == "jwt")
    assert jwt_imp.alias == "jwt_lib"

    refs = {f"{r.target_module}.{r.symbol}" for r in parsed.module.references if r.symbol}
    assert "auth.validate" in refs


def test_parse_comments_and_tags(sample_file: Path):
    parsed = _service().parse_file(sample_file)
    tags = {c.tag for c in parsed.module.comments}
    assert CommentTag.TODO in tags


def test_parse_variables_and_constants(sample_file: Path):
    parsed = _service().parse_file(sample_file)
    names = {v.name for v in parsed.module.variables}
    assert "CONSTANT" in names
    constant = next(v for v in parsed.module.variables if v.name == "CONSTANT")
    assert constant.is_constant is True


def test_empty_file(tmp_path: Path):
    path = _write(tmp_path / "empty.py", "")
    parsed = _service().parse_file(path)
    assert parsed.module.name == "empty"
    assert parsed.module.functions == []
    assert parsed.module.classes == []


def test_syntax_error_still_returns_structure(tmp_path: Path):
    path = _write(tmp_path / "broken.py", "def broken(\n")
    parsed = _service().parse_file(path)
    assert parsed.has_syntax_errors is True


def test_unicode_content(tmp_path: Path):
    path = _write(tmp_path / "i18n.py", 'MSG = "こんにちは"\n\ndef greet():\n    return MSG\n')
    parsed = _service().parse_file(path)
    assert parsed.module.name == "i18n"
    assert any(fn.name == "greet" for fn in parsed.module.functions)


def test_large_file(tmp_path: Path):
    body = "\n".join(f"def f_{i}():\n    return {i}" for i in range(200))
    path = _write(tmp_path / "large.py", body)
    parsed = _service().parse_file(path)
    assert len(parsed.module.functions) == 200


def test_unsupported_extension(tmp_path: Path):
    path = _write(tmp_path / "notes.md", "# hi")
    with pytest.raises(ParserError, match="Unsupported"):
        _service().parse_file(path)


def test_missing_file(tmp_path: Path):
    with pytest.raises(ParserError, match="not found"):
        _service().parse_file(tmp_path / "missing.py")


def test_parse_repository_summary(tmp_path: Path):
    (tmp_path / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "b.py").write_text("class B:\n    pass\n", encoding="utf-8")
    (tmp_path / "venv" / "lib").mkdir(parents=True)
    (tmp_path / "venv" / "lib" / "skip.py").write_text("x=1\n", encoding="utf-8")

    repo = Repository(name="demo", root_path=str(tmp_path), current_branch="main")
    summary = _service().parse_repository(repo)
    assert summary.file_count == 2
    assert "python" in summary.languages


def test_class_with_bases_and_decorators(tmp_path: Path):
    content = '''\
from dataclasses import dataclass

@dataclass
class Item(BaseModel):
    def value(self) -> int:
        return 1
'''
    path = _write(tmp_path / "item.py", content)
    parsed = _service().parse_file(path)
    cls = parsed.module.classes[0]
    assert cls.name == "Item"
    assert "BaseModel" in cls.bases
    assert any("dataclass" in d for d in cls.decorators)
