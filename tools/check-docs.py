"""Check the repository documentation index, local links, and visible status."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
INDEX = DOCS / "README.md"
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
STATUS = re.compile(r"^>\s*状态：\s*(现行|历史)")


def links(source: Path, content: str) -> list[Path]:
    result: list[Path] = []
    in_fence = False
    for line in content.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for match in LINK.finditer(line):
            target = match.group(1).strip()
            if target.startswith("<") and target.endswith(">"):
                target = target[1:-1]
            target = unquote(target.split("#", 1)[0].split("?", 1)[0])
            if not target or "://" in target or target.startswith(("mailto:", "#")):
                continue
            result.append((source.parent / target).resolve())
    return result


def main() -> int:
    errors: list[str] = []
    # Working drafts are intentionally absent from the authoritative docs index.
    pages = sorted(
        page
        for page in DOCS.rglob("*.md")
        if page.relative_to(DOCS).parts[0] != "draft"
    )
    index_links = set(links(INDEX, INDEX.read_text(encoding="utf-8")))
    for page in pages:
        content = page.read_text(encoding="utf-8")
        display = page.relative_to(ROOT)
        status_lines = [
            match for line in content.splitlines()[:12] if (match := STATUS.match(line))
        ]
        if not status_lines:
            errors.append(f"{display}: 标题后缺少可见的 `> 状态：现行/历史` 标记")
        elif status_lines[0].group(1) == "历史":
            preface = "\n".join(content.splitlines()[:12])
            if not any(word in preface for word in ("适用", "截至")):
                errors.append(f"{display}: 历史页页首缺少适用范围或截至日期")
            if not any(word in preface for word in ("继任", "现行")):
                errors.append(f"{display}: 历史页页首缺少现行入口或继任版本")
        if page != INDEX and page.resolve() not in index_links:
            errors.append(f"{display}: docs/README.md 未直接收录此页")
        for target in links(page, content):
            if not target.exists():
                errors.append(f"{display}: 本地链接不存在：{target}")
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"文档检查通过：{len(pages)} 页，索引覆盖、相对链接和页首状态均有效")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
