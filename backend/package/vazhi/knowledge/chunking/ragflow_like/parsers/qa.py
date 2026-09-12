import csv
import re
from typing import Any


def _rm_prefix(text: str) -> str:
    return re.sub(
        r"^(user|assistant|Q|A|Question|Answer)[\t: ]+",
        "",
        (text or "").strip(),
        flags=re.IGNORECASE,
    )


def _to_qa_chunk(question: str, answer: str) -> str:
    return "\t".join(["Question: " + _rm_prefix(question), "Answer: " + _rm_prefix(answer)])


def _guess_delimiter(lines: list[str]) -> str:
    comma = 0
    tab = 0
    for line in lines:
        if len(line.split(",")) == 2:
            comma += 1
        if len(line.split("\t")) == 2:
            tab += 1
    return "\t" if tab >= comma else ","


def _extract_pairs_with_delimiter(lines: list[str], delimiter: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    question = ""
    answer = ""

    for line in lines:
        arr = line.split(delimiter)
        if len(arr) != 2:
            if question:
                answer += "\n" + line
            continue

        if question and answer:
            pairs.append((question, answer))
        question, answer = arr

    if question:
        pairs.append((question, answer))

    return [(q.strip(), a.strip()) for q, a in pairs if q.strip()]


def _extract_pairs_from_csv(lines: list[str], delimiter: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    question = ""
    answer = ""

    reader = csv.reader(lines, delimiter=delimiter)
    for row, raw_line in zip(reader, lines, strict=False):
        if len(row) != 2:
            if question:
                answer += "\n" + raw_line
            continue

        if question and answer:
            pairs.append((question, answer))
        question, answer = row

    if question:
        pairs.append((question, answer))

    return [(q.strip(), a.strip()) for q, a in pairs if q.strip()]


def _parse_markdown_table_row(line: str) -> list[str] | None:
    if "|" not in line:
        return None

    text = line.strip()
    if not text:
        return None

    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]

    cells = [cell.strip() for cell in text.split("|")]
    if not cells:
        return None

    if all(re.fullmatch(r":?-{3,}:?", c.replace(" ", "")) for c in cells if c):
        return None

    return cells


def _extract_pairs_from_markdown_tables(markdown_content: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []

    for line in (markdown_content or "").splitlines():
        cells = _parse_markdown_table_row(line)
        if not cells or len(cells) < 2:
            continue

        question = cells[0]
        answer = cells[1]
        if question and answer:
            pairs.append((question, answer))

    return pairs


def _md_question_level(line: str) -> tuple[int, str]:
    match = re.match(r"^(#{1,6})(?:[ \t]+|$)", line)
    if not match:
        return 0, line
    return len(match.group(1)), line[match.end() :]


def _update_fence_state(line: str, fence: str) -> str:
    stripped = line.strip()
    if stripped.startswith("```") or stripped.startswith("~~~"):
        marker = stripped[:3]
        if not fence:
            return marker
        if marker == fence:
            return ""
    return fence


def _extract_pairs_from_markdown_headings(markdown_content: str) -> list[tuple[str, str]]:
    lines = (markdown_content or "").splitlines()
    if not lines:
        return []

    pairs: list[tuple[str, str]] = []
    last_answer = ""
    question_stack: list[str] = []
    level_stack: list[int] = []
    fence = ""

    for line in lines:
        fence = _update_fence_state(line, fence)

        question_level = 0
        question = ""
        if not fence:
            question_level, question = _md_question_level(line)

        if not question_level or question_level > 6:
            last_answer = f"{last_answer}\n{line}"
            continue

        if last_answer.strip():
            sum_question = "\n".join(question_stack)
            if sum_question:
                pairs.append((sum_question, last_answer.strip()))
            last_answer = ""

        while question_stack and question_level <= level_stack[-1]:
            question_stack.pop()
            level_stack.pop()

        question_stack.append(question)
        level_stack.append(question_level)

    if last_answer.strip():
        sum_question = "\n".join(question_stack)
        if sum_question:
            pairs.append((sum_question, last_answer.strip()))

    return pairs


def _extract_pairs_by_prefix(markdown_content: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    question = ""
    answer_lines: list[str] = []

    heading_re = re.compile(r"^#{1,6}(?:[ \t]+|$)")
    question_re = re.compile(r"^(?:Q|Question)\s*:\s*(.*)$", flags=re.IGNORECASE)
    answer_re = re.compile(r"^(?:A|Answer)\s*:\s*(.*)$", flags=re.IGNORECASE)
    fence = ""

    def flush_pair() -> None:
        nonlocal question, answer_lines
        if question:
            pairs.append((question, "\n".join(answer_lines)))
            question = ""
            answer_lines = []

    for line in (markdown_content or "").splitlines():
        stripped = line.strip()
        is_fence_line = stripped.startswith("```") or stripped.startswith("~~~")
        fence = _update_fence_state(line, fence)
        if is_fence_line or fence:
            if question:
                answer_lines.append(line)
            continue

        heading_match = heading_re.match(line)
        text = line[heading_match.end() :] if heading_match else line

        q_match = question_re.match(text)
        if q_match:
            flush_pair()
            question = q_match.group(1).strip()
            continue

        a_match = answer_re.match(text)
        if a_match:
            if question:
                answer_lines.append(a_match.group(1).strip())
            continue

        if heading_match:
            flush_pair()
            continue

        if question:
            answer_lines.append(line)

    flush_pair()

    return [(q.strip(), a.strip()) for q, a in pairs if q.strip() and a.strip()]


def _dedupe_pairs(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    res: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for question, answer in pairs:
        q = question.strip()
        a = answer.strip()
        if not q or not a:
            continue
        key = (q, a)
        if key in seen:
            continue
        seen.add(key)
        res.append((q, a))

    return res


_QA_CHUNK_MAX_CHARS = 4000
_QA_QUESTION_PREFIX = "Question: "
_QA_ANSWER_PREFIX = "Answer: "


def _split_qa_prefix(text: str, prefix: str) -> tuple[str, str]:
    if text.startswith(prefix):
        return prefix, text[len(prefix) :].strip()
    return "", text.strip()


def _hard_split_text(text: str, max_chars: int) -> list[str]:
    return [text[i : i + max_chars] for i in range(0, len(text), max_chars) if text[i : i + max_chars].strip()]


def _split_answer_by_paragraphs(answer: str, max_chars: int) -> list[str]:
    paragraphs = [p.strip() for p in answer.split("\n\n") if p.strip()]
    if not paragraphs:
        return [answer] if answer.strip() else []

    result: list[str] = []
    current = ""
    for p in paragraphs:
        if len(p) > max_chars:
            if current:
                result.append(current)
                current = ""
            result.extend(_split_answer_by_lines(p, max_chars))
            continue
        if current and len(current) + 2 + len(p) > max_chars:
            result.append(current)
            current = p
        else:
            current = f"{current}\n\n{p}" if current else p
    if current:
        result.append(current)
    return result


def _split_answer_by_lines(answer: str, max_chars: int) -> list[str]:
    lines = [line for line in answer.splitlines() if line.strip()]
    if not lines:
        return [answer] if answer.strip() else []

    result: list[str] = []
    current = ""
    for line in lines:
        if len(line) > max_chars:
            if current:
                result.append(current)
                current = ""
            result.extend(_hard_split_text(line, max_chars))
            continue
        if current and len(current) + 1 + len(line) > max_chars:
            result.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        result.append(current)
    return result


def _split_long_qa_chunks(chunks: list[str], max_chars: int = _QA_CHUNK_MAX_CHARS) -> list[str]:
    if max_chars <= 0:
        return [c.strip() for c in chunks if c and c.strip()]

    result: list[str] = []
    for chunk in chunks:
        text = (chunk or "").strip()
        if not text:
            continue
        if len(text) <= max_chars:
            result.append(text)
            continue

        marker = "\tAnswer: "
        sep_pos = text.find(marker)
        if sep_pos == -1:
            result.extend(_hard_split_text(text, max_chars))
            continue

        q_part, a_part = text[:sep_pos], text[sep_pos + 1 :]
        q_prefix, q_body = _split_qa_prefix(q_part, _QA_QUESTION_PREFIX)
        a_prefix, a_body = _split_qa_prefix(a_part, _QA_ANSWER_PREFIX)
        if not q_body or not a_body:
            result.extend(_hard_split_text(text, max_chars))
            continue

        if len(q_prefix) + len(q_body) + len(a_prefix) + 1 >= max_chars:
            result.extend(_hard_split_text(text, max_chars))
            continue

        max_answer_chars = max_chars - len(q_prefix) - len(q_body) - len(a_prefix) - 1
        for sub_answer in _split_answer_by_paragraphs(a_body, max_answer_chars):
            result.append(f"{q_prefix}{q_body}\t{a_prefix}{sub_answer}")

    return result


def chunk_markdown(filename: str, markdown_content: str, parser_config: dict[str, Any] | None = None) -> list[str]:
    parser_config = parser_config or {}

    suffix = ""
    if filename and "." in filename:
        suffix = "." + filename.lower().split(".")[-1]

    lines = [line for line in (markdown_content or "").splitlines() if line.strip()]
    pairs: list[tuple[str, str]] = []

    if suffix in {".xlsx", ".xls"}:
        pairs.extend(_extract_pairs_from_markdown_tables(markdown_content))
        if not pairs:
            delimiter = _guess_delimiter(lines)
            pairs.extend(_extract_pairs_with_delimiter(lines, delimiter))
    elif suffix == ".csv":
        pairs.extend(_extract_pairs_from_markdown_tables(markdown_content))
        delimiter = "\t" if any("\t" in line for line in lines) else ","
        pairs.extend(_extract_pairs_from_csv(lines, delimiter))
    elif suffix == ".txt":
        delimiter = _guess_delimiter(lines)
        pairs.extend(_extract_pairs_with_delimiter(lines, delimiter))
        if not pairs:
            pairs.extend(_extract_pairs_by_prefix(markdown_content))
    elif suffix in {".md", ".markdown", ".mdx", ".docx"}:
        pairs.extend(_extract_pairs_by_prefix(markdown_content))
        if not pairs:
            pairs.extend(_extract_pairs_from_markdown_headings(markdown_content))
        pairs.extend(_extract_pairs_from_markdown_tables(markdown_content))
    else:
        pairs.extend(_extract_pairs_by_prefix(markdown_content))
        if not pairs:
            pairs.extend(_extract_pairs_from_markdown_headings(markdown_content))
        pairs.extend(_extract_pairs_from_markdown_tables(markdown_content))
        if not pairs:
            delimiter = _guess_delimiter(lines)
            pairs.extend(_extract_pairs_with_delimiter(lines, delimiter))

    pairs = _dedupe_pairs(pairs)

    if not pairs and lines:
        for i in range(0, len(lines), 2):
            q = lines[i]
            a = lines[i + 1] if i + 1 < len(lines) else ""
            if q.strip() and a.strip():
                pairs.append((q, a))

    chunks = [_to_qa_chunk(q, a) for q, a in pairs]
    return _split_long_qa_chunks(chunks)
