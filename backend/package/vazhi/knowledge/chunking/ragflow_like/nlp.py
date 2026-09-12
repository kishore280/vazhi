import random
import re

BULLET_PATTERN = [
    [
        r"[0-9]{1,2}[\. ]",
        r"[0-9]{1,2}\.[0-9]{1,2}[^a-zA-Z/%~-]",
        r"[0-9]{1,2}\.[0-9]{1,2}\.[0-9]{1,2}",
        r"[0-9]{1,2}\.[0-9]{1,2}\.[0-9]{1,2}\.[0-9]{1,2}",
    ],
    [
        r"PART (ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN)",
        r"Chapter (I+V?|VI*|XI|IX|X)",
        r"Section [0-9]+",
        r"Article [0-9]+",
    ],
    [
        r"^#[^#]",
        r"^##[^#]",
        r"^###.*",
        r"^####.*",
        r"^#####.*",
        r"^######.*",
    ],
]

MARKDOWN_BULLET_GROUP_INDEX = 2


def count_tokens(text: str) -> int:
    if not text:
        return 0
    parts = re.findall(r"[A-Za-z0-9_]+", text)
    return max(1, len(parts)) if text.strip() else 0


def hard_split_by_token_limit(text: str, chunk_token_num: int, hard_limit_token_num: int | None = None) -> list[str]:
    token_iter = list(re.finditer(r"[A-Za-z0-9_]+", text or ""))
    if not token_iter:
        cleaned = (text or "").strip()
        return [cleaned] if cleaned else []

    max_tokens = max(int(chunk_token_num or 0), 1)
    hard_limit = None
    if hard_limit_token_num is not None:
        hard_limit = max(int(hard_limit_token_num or 0), max_tokens)
        if len(token_iter) <= hard_limit:
            cleaned = (text or "").strip()
            return [cleaned] if cleaned else []

    spans: list[tuple[int, int]] = []
    start = 0
    index = 0

    while index < len(token_iter):
        next_index = min(index + max_tokens, len(token_iter))
        if next_index < len(token_iter):
            end = token_iter[next_index].start()
        else:
            end = len(text)
        if text[start:end].strip():
            spans.append((start, end))
        start = end
        index = next_index

    tail = text[start:].strip()
    if tail:
        spans.append((start, len(text)))

    if hard_limit is not None and len(spans) >= 2:
        prev_start, _ = spans[-2]
        _, tail_end = spans[-1]
        candidate = text[prev_start:tail_end].strip()
        if count_tokens(candidate) <= hard_limit:
            spans[-2] = (prev_start, tail_end)
            spans.pop()

    return [text[start:end].strip() for start, end in spans if text[start:end].strip()]


def _remove_pdf_tags(text: str) -> str:
    return re.sub(r"@@[0-9-]+\t[0-9.\t]+##", "", text or "")


def _extract_custom_delimiters(delimiter: str) -> list[str]:
    return [m.group(1) for m in re.finditer(r"`([^`]+)`", delimiter or "")]


def naive_merge(
    sections: str | list[str] | list[tuple[str, str]],
    chunk_token_num: int = 128,
    delimiter: str = "\n;!?",
    overlapped_percent: int = 0,
) -> list[str]:
    if not sections:
        return []

    if isinstance(sections, str):
        typed_sections: list[tuple[str, str]] = [(sections, "")]
    elif isinstance(sections[0], str):
        typed_sections = [(s, "") for s in sections]  # type: ignore[index]
    else:
        typed_sections = sections  # type: ignore[assignment]

    chunk_token_num = max(int(chunk_token_num or 0), 0)
    overlap = max(0, min(int(overlapped_percent or 0), 99))

    custom_delimiters = _extract_custom_delimiters(delimiter)
    if custom_delimiters:
        pattern = "|".join(re.escape(t) for t in sorted(set(custom_delimiters), key=len, reverse=True))
        chunks: list[str] = []
        for sec, pos in typed_sections:
            split_sec = re.split(rf"({pattern})", sec, flags=re.DOTALL)
            for sub in split_sec:
                if re.fullmatch(pattern, sub or ""):
                    continue
                text = "\n" + sub
                local_pos = pos if count_tokens(text) >= 8 else ""
                if local_pos and local_pos not in text:
                    text += local_pos
                if text.strip():
                    chunks.append(text)
        return chunks

    if chunk_token_num <= 0:
        merged = "\n".join(sec for sec, _ in typed_sections if sec and sec.strip())
        return [merged] if merged.strip() else []

    chunks = [""]
    token_nums = [0]

    def add_chunk(text: str, pos: str) -> None:
        tnum = count_tokens(text)
        local_pos = pos or ""
        if tnum < 8:
            local_pos = ""

        threshold = chunk_token_num * (100 - overlap) / 100.0
        if chunks[-1] == "" or token_nums[-1] > threshold:
            if chunks:
                prev = _remove_pdf_tags(chunks[-1])
                start = int(len(prev) * (100 - overlap) / 100.0)
                text = prev[start:] + text
            if local_pos and local_pos not in text:
                text += local_pos
            chunks.append(text)
            token_nums.append(tnum)
        else:
            if local_pos and local_pos not in chunks[-1]:
                text += local_pos
            chunks[-1] += text
            token_nums[-1] += tnum

    for sec, pos in typed_sections:
        if not sec:
            continue
        add_chunk("\n" + sec, pos)

    return [chunk for chunk in chunks if chunk.strip()]


def random_choices(arr: list[str], k: int) -> list[str]:
    if not arr:
        return []
    return random.choices(arr, k=min(len(arr), k))


def is_probable_heading_line(line: str) -> bool:
    text = (line or "").strip()
    if not text:
        return False

    if re.match(r"^#{1,6}\s+\S", text):
        return True

    if re.search(r"</?(table|tr|td|th|caption|tbody|thead)[^>]*>", text, flags=re.IGNORECASE):
        return False

    if len(text) > 96:
        return False
    if count_tokens(text) > 72:
        return False

    if re.search(r"[,;!?:]", text[:24]):
        return False

    if text.endswith((".", ";", "!", "?")) and len(text) > 20:
        return False

    return True


def _is_mid_sentence_bullet(line: str) -> bool:
    text = (line or "").strip()
    if not text:
        return False

    if re.match(r"^#{1,6}\s+\S", text):
        return False

    marker = re.search(r"[0-9]{1,2}[.)]", text)
    if not marker:
        return False

    if marker.start() == 0:
        return False

    prev = text[marker.start() - 1]
    return prev not in {"#", "\n"}


def not_bullet(line: str) -> bool:
    patt = [
        r"0",
        r"[0-9]+ +[0-9~-]",
        r"[0-9]+\.{2,}",
    ]
    return any(re.match(p, line) for p in patt)


def bullets_category(sections: list[str]) -> int:
    hits: list[float] = [0.0] * len(BULLET_PATTERN)

    def bullet_weight(group_idx: int, line: str) -> float:
        if group_idx != MARKDOWN_BULLET_GROUP_INDEX:
            return 1.0

        heading = line.strip()
        if not re.match(r"^#{1,6}\s+\S", heading):
            return 1.0

        level = len(heading) - len(heading.lstrip("#"))
        if level <= 2:
            return 4.0
        if level <= 4:
            return 3.0
        return 2.0

    for i, pro in enumerate(BULLET_PATTERN):
        for sec in sections:
            sec = sec.strip()
            for p in pro:
                if re.match(p, sec) and not not_bullet(sec):
                    w = bullet_weight(i, sec)
                    if _is_mid_sentence_bullet(sec):
                        w *= 0.1
                    if i != MARKDOWN_BULLET_GROUP_INDEX and not is_probable_heading_line(sec):
                        w *= 0.2
                    hits[i] += w
                    break
    maximum = 0
    res = -1
    for i, hit in enumerate(hits):
        if hit <= maximum:
            continue
        res = i
        maximum = hit
    return res


def _get_text(section: str | tuple[str, str]) -> str:
    if isinstance(section, str):
        return section.strip()
    return (section[0] or "").strip()


def remove_contents_table(sections: list[str] | list[tuple[str, str]]) -> None:
    i = 0
    while i < len(sections):
        line = re.sub(r"\s+", "", _get_text(sections[i]).split("@@")[0], flags=re.IGNORECASE)
        if not re.match(r"(contents|tableofcontents|acknowledge(ments)?)$", line, flags=re.IGNORECASE):
            i += 1
            continue

        sections.pop(i)
        if i >= len(sections):
            break

        prefix = " ".join(_get_text(sections[i]).split()[:2])
        while not prefix and i < len(sections):
            sections.pop(i)
            if i >= len(sections):
                break
            prefix = " ".join(_get_text(sections[i]).split()[:2])

        if i >= len(sections) or not prefix:
            break

        sections.pop(i)
        if i >= len(sections):
            break

        for j in range(i, min(i + 128, len(sections))):
            if not re.match(re.escape(prefix), _get_text(sections[j])):
                continue
            for _ in range(i, j):
                sections.pop(i)
            break


def make_colon_as_title(sections: list[str] | list[tuple[str, str]]) -> list[str] | list[tuple[str, str]]:
    if not sections:
        return sections
    if isinstance(sections[0], str):
        return sections

    i = 0
    while i < len(sections):
        text, layout = sections[i]
        i += 1
        text = text.split("@")[0].strip()
        if not text or text[-1] != ":":
            continue

        rev = text[::-1]
        arr = re.split(r"([!?;]| \.)", rev)
        if len(arr) < 2 or len(arr[1]) < 32:
            continue

        sections.insert(i - 1, (arr[0][::-1], "title"))
        i += 1

    return sections


def not_title(text: str) -> bool:
    if len(text.split()) > 12 or (" " not in text and len(text) >= 32):
        return True
    return bool(re.search(r"[,;!]", text))


def hierarchical_merge(bull: int, sections: list[str] | list[tuple[str, str]], depth: int) -> list[list[str]]:
    if not sections or bull < 0:
        return []

    if isinstance(sections[0], str):
        typed_sections: list[tuple[str, str]] = [(s, "") for s in sections]
    else:
        typed_sections = sections  # type: ignore[assignment]

    typed_sections = [
        (t, o)
        for t, o in typed_sections
        if t and len(t.split("@")[0].strip()) > 1 and not re.match(r"[0-9]+$", t.split("@")[0].strip())
    ]

    bullets_size = len(BULLET_PATTERN[bull])
    levels: list[list[int]] = [[] for _ in range(bullets_size + 2)]

    for i, (text, layout) in enumerate(typed_sections):
        for j, patt in enumerate(BULLET_PATTERN[bull]):
            if re.match(patt, text.strip()) and is_probable_heading_line(text):
                levels[j].append(i)
                break
        else:
            if re.search(r"(title|head)", layout) and not not_title(text):
                levels[bullets_size].append(i)
            else:
                levels[bullets_size + 1].append(i)

    pure_sections = [t for t, _ in typed_sections]

    def binary_search(arr: list[int], target: int) -> int:
        if not arr:
            return -1
        if target > arr[-1]:
            return len(arr) - 1
        if target < arr[0]:
            return -1

        s, e = 0, len(arr)
        while e - s > 1:
            mid = (e + s) // 2
            if target > arr[mid]:
                s = mid
            elif target < arr[mid]:
                e = mid
            else:
                return mid
        return s

    cks: list[list[int]] = []
    readed = [False] * len(pure_sections)
    levels = list(reversed(levels))
    for i, arr in enumerate(levels[:depth]):
        for j in arr:
            if readed[j]:
                continue
            readed[j] = True
            cks.append([j])
            if i + 1 == len(levels) - 1:
                continue

            for ii in range(i + 1, len(levels)):
                jj = binary_search(levels[ii], j)
                if jj < 0:
                    continue
                if levels[ii][jj] > cks[-1][-1]:
                    cks[-1].pop(-1)
                cks[-1].append(levels[ii][jj])

            for ii in cks[-1]:
                readed[ii] = True

    if not cks:
        return []

    for i in range(len(cks)):
        cks[i] = [pure_sections[j] for j in reversed(cks[i])]

    res: list[list[str]] = [[]]
    num = [0]
    for ck in cks:
        if len(ck) == 1:
            n = count_tokens(re.sub(r"@@[0-9]+.*", "", ck[0]))
            if n + num[-1] < 218:
                res[-1].append(ck[0])
                num[-1] += n
                continue
            res.append(ck)
            num.append(n)
            continue
        res.append(ck)
        num.append(218)

    return [chunk for chunk in res if chunk]
