"""Local-only article creation, explicit publication dates, and content checks."""
from __future__ import annotations

import datetime as dt
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile
import tomllib


SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z", re.ASCII)
FRONT_MATTER = re.compile(rb"\A\+\+\+(\r?\n)(.*?)\r?\n\+\+\+(?=\r?\n|\Z)", re.DOTALL)
CONTENT_EXTENSIONS = {
    ".md", ".markdown", ".mdown", ".mdtext", ".mdtxt", ".mmark",
    ".html", ".htm", ".rst", ".adoc", ".asciidoc", ".ad", ".org",
    ".pandoc", ".pdc", ".mdx", ".qmd",
}


def _check_slug(slug: str) -> None:
    if not isinstance(slug, str) or len(slug) > 120 or not SLUG.fullmatch(slug):
        raise ValueError("slug 须为 1–120 个小写英文字母、数字或分隔单词的连字符。")


def _directory(path: Path, *, create: bool = False) -> bool:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        if not create:
            return False
        path.mkdir()
        mode = path.lstat().st_mode
    if not stat.S_ISDIR(mode):
        raise ValueError(f"目录不能是符号链接或其他文件：{path}")
    return True


def _posts_directory(root: Path, *, create: bool = False) -> Path | None:
    if not _directory(root):
        raise ValueError(f"找不到博客目录：{root}")
    for directory in [root / "content", root / "content/posts"]:
        if not _directory(directory, create=create):
            return None
    return root / "content/posts"


def _parse(raw: bytes, location: Path) -> tuple[dict, bytes, str, str]:
    match = FRONT_MATTER.match(raw)
    if not match:
        raise ValueError(f"文章须以 +++ TOML front matter 开头：{location}")
    try:
        header = match[2].decode("utf-8")
        metadata = tomllib.loads(header)
        raw[match.end():].decode("utf-8")
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ValueError(f"文章须为 UTF-8，且 TOML 有效：{location}：{error}") from error
    return metadata, raw[match.end():], header, match[1].decode("ascii")


def _calendar_value(value, field: str, location: Path) -> None:
    if isinstance(value, dt.datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} 的时间须明确指定时区：{location}")
        return
    if isinstance(value, dt.date):
        return
    if isinstance(value, str):
        try:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                dt.date.fromisoformat(value)
                return
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is not None and parsed.utcoffset() is not None:
                return
        except ValueError:
            pass
    raise ValueError(f"{field} 须为明确的日历日期或带时区的日期时间：{location}")


def _check_metadata(metadata: dict, slug: str, location: Path) -> None:
    if not isinstance(metadata.get("title"), str) or not metadata["title"].strip():
        raise ValueError(f"文章须有非空 title：{location}")
    if metadata.get("slug") != slug:
        raise ValueError(f"slug 须与文章目录名 {slug!r} 一致：{location}")
    if type(metadata.get("draft")) is not bool:
        raise ValueError(f"文章须明确填写 draft = true 或 false：{location}")
    if not metadata["draft"] and "date" not in metadata:
        raise ValueError(f"正式文章须有明确的 date，不能由文件时间推断：{location}")
    for field in ["date", "lastmod"]:
        if field in metadata:
            _calendar_value(metadata[field], field, location)
    if "tags" in metadata and (not isinstance(metadata["tags"], list) or any(not isinstance(tag, str) for tag in metadata["tags"])):
        raise ValueError(f"tags 须为字符串列表：{location}")


def _read_article(index: Path) -> bytes:
    if not stat.S_ISREG(index.lstat().st_mode):
        raise ValueError(f"文章必须是普通文件，不能是符号链接：{index}")
    return index.read_bytes()


def validate_articles(root) -> list[dict]:
    """Validate leaf bundles; return each article's metadata plus its Path."""
    root = Path(root).absolute()
    posts = _posts_directory(root)
    if posts is None:
        return []
    records = []
    seen = set()
    for bundle in sorted(posts.iterdir()):
        if bundle.name == "_index.md":
            _parse(_read_article(bundle), bundle)
            continue
        if not _directory(bundle):
            raise ValueError(f"文章须位于 content/posts/<slug>/index.md：{bundle}")
        _check_slug(bundle.name)
        index = bundle / "index.md"
        if not index.exists() and not index.is_symlink():
            raise ValueError(f"文章目录缺少 index.md：{bundle}")
        for item in bundle.rglob("*"):
            mode = item.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise ValueError(f"文章或资源不能是符号链接：{item}")
            if stat.S_ISDIR(mode):
                continue
            if not stat.S_ISREG(mode):
                raise ValueError(f"文章资源必须是普通文件：{item}")
            if item != index and item.suffix.lower() in CONTENT_EXTENSIONS:
                raise ValueError(f"每个文章目录仅允许直接的 index.md；发现额外内容文件：{item}")
        metadata, _, _, _ = _parse(_read_article(index), index)
        _check_metadata(metadata, bundle.name, index)
        if metadata["slug"] in seen:
            raise ValueError(f"重复的 slug：{metadata['slug']}")
        seen.add(metadata["slug"])
        records.append(dict(metadata, path=index))
    return records


def new_article(root, slug: str, title: str) -> Path:
    """Create one draft without a date. Existing bundles are never changed."""
    _check_slug(slug)
    if not isinstance(title, str) or not title.strip():
        raise ValueError("请提供非空的文章标题。")
    root = Path(root).absolute()
    validate_articles(root)
    posts = _posts_directory(root, create=True)
    bundle = posts / slug
    template = (root / "archetypes/default.md").read_text(encoding="utf-8")
    content = template.replace("{{ .Name | humanize | title | jsonify }}", json.dumps(title.strip(), ensure_ascii=False))
    content = content.replace("{{ .Name | jsonify }}", json.dumps(slug))
    raw = content.encode("utf-8")
    metadata, _, _, _ = _parse(raw, root / "archetypes/default.md")
    _check_metadata(metadata, slug, root / "archetypes/default.md")
    if metadata["draft"] is not True or "date" in metadata or "lastmod" in metadata:
        raise ValueError("新文章模板须为草稿，不预设 date 或 lastmod。")
    try:
        bundle.mkdir()
    except FileExistsError as error:
        raise ValueError(f"文章目录已存在，未覆盖：{bundle}") from error
    index = bundle / "index.md"
    created = False
    try:
        with index.open("xb") as stream:
            created = True
            stream.write(raw)
    except BaseException:
        if created and index.exists() and not index.is_symlink():
            index.unlink()
        try:
            bundle.rmdir()
        except OSError:
            pass
        raise
    return index


def _same_value(left, right) -> bool:
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_same_value(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_same_value(a, b) for a, b in zip(left, right))
    if isinstance(left, float) and isinstance(right, float) and math.isnan(left) and math.isnan(right):
        return True
    return left == right


def _set_field(header: str, key: str, literal: str, newline: str) -> str:
    original = tomllib.loads(header)
    expected = dict(original, **{key: tomllib.loads(f"value = {literal}")["value"]})
    if key not in original:
        result = f"{key} = {literal}{newline}{header}"
        if _same_value(tomllib.loads(result), expected):
            return result
    pattern = re.compile(rf"(?m)^([ \t]*(?:{key}|\"{key}\"|'{key}')[ \t]*=[ \t]*)([^\r\n]*)")
    for match in pattern.finditer(header):
        comment = re.search(r"([ \t]*#.*)$", match[2])
        suffix = comment[1] if comment else ""
        candidate = header[:match.start()] + match[1] + literal + suffix + header[match.end():]
        try:
            if _same_value(tomllib.loads(candidate), expected):
                return candidate
        except tomllib.TOMLDecodeError:
            continue
    raise ValueError(f"无法安全更新顶层 {key}；请将该字段写成独立的一行。")


def publish_article(root, slug: str, date: str) -> Path:
    """Publish a draft in place, retaining body bytes and explicit lastmod."""
    _check_slug(slug)
    if not isinstance(date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise ValueError("请明确指定 --date YYYY-MM-DD。")
    try:
        dt.date.fromisoformat(date)
    except ValueError as error:
        raise ValueError(f"无效的日历日期：{date}") from error
    root = Path(root).absolute()
    validate_articles(root)
    posts = _posts_directory(root)
    if posts is None or not (posts / slug).exists():
        raise ValueError(f"找不到草稿：{slug}")
    index = posts / slug / "index.md"
    original = _read_article(index)
    original_stat = index.stat()
    metadata, body, header, newline = _parse(original, index)
    if not metadata["draft"]:
        raise ValueError(f"文章已发布，未更改：{slug}")
    header = _set_field(header, "draft", "false", newline)
    header = _set_field(header, "date", f"{date}T00:00:00+08:00", newline)
    updated = b"+++" + newline.encode() + header.encode("utf-8") + newline.encode() + b"+++" + body
    checked, _, _, _ = _parse(updated, index)
    _check_metadata(checked, slug, index)
    handle, temporary_name = tempfile.mkstemp(prefix=".index-", suffix=".tmp", dir=index.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(updated)
            stream.flush()
            os.fchmod(stream.fileno(), stat.S_IMODE(original_stat.st_mode))
            os.fsync(stream.fileno())
        current = index.lstat()
        if (current.st_dev, current.st_ino) != (original_stat.st_dev, original_stat.st_ino) or _read_article(index) != original:
            raise ValueError("草稿在发布期间发生变化，未覆盖；请检查后重试。")
        os.replace(temporary, index)
        if _read_article(index) != updated:
            raise RuntimeError(f"发布后的文件与预期不同，请检查：{index}")
    finally:
        temporary.unlink(missing_ok=True)
    return index
