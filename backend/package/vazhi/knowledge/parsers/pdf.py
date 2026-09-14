import fitz


def extract_text_from_pdf(file_bytes: bytes) -> str:
    with fitz.open(stream=file_bytes, filetype="pdf") as doc:
        pages = [_extract_page(page) for page in doc]
    return "\n\n".join(pages).strip()


def _extract_page(page: fitz.Page) -> str:
    text = page.get_text()
    tables = page.find_tables()
    for table in tables:
        text += f"\n\n{table.to_markdown()}"
    return text
