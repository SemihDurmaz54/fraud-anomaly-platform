"""Knowledge base yükleme ve chunking.

Markdown dokümanlar `##` başlıklarına göre bölünür; çok uzun bölümler paragraf sınırında,
örtüşmeli (overlap) parçalara ayrılır. Her chunk'a metadata eklenir: doküman, başlık, bölüm ve
içinde geçen kural kimlikleri (KB-xxx, Rxxx, CTX-xx) — hibrit retrieval'da kullanılır.
"""
from __future__ import annotations

import re
from pathlib import Path

RULE_ID = re.compile(r"\b(?:KB-\d{3}|R\d{3}|CTX-\d{2})\b")


def load_documents(kb_dir: str | Path) -> list[dict]:
    docs = []
    for p in sorted(Path(kb_dir).glob("*.md")):
        text = p.read_text(encoding="utf-8")
        m = re.search(r"^#\s+(.+)$", text, re.M)
        docs.append({"doc_id": p.stem, "title": m.group(1).strip() if m else p.stem, "text": text})
    return docs


def chunk_document(doc: dict, max_chars: int = 900, overlap: int = 150) -> list[dict]:
    parts = re.split(r"(?m)^##\s+", doc["text"])
    intro, sections = parts[0], parts[1:]
    chunks = []
    # Giriş: başlık ve "> not" satırları atılır (yalnızca uyarı içeren chunk'lar retrieval'ı kirletiyordu)
    intro = re.sub(r"(?m)^(#\s+.+|>.*)$", "", intro).strip()
    blocks = [("Giriş", intro)] + \
             [(s.split("\n", 1)[0].strip(), s.split("\n", 1)[1].strip() if "\n" in s else "") for s in sections]
    for section, body in blocks:
        if len(body) < 40:
            continue
        pieces, cur = [], ""
        for para in re.split(r"\n\s*\n", body):
            if cur and len(cur) + len(para) > max_chars:
                pieces.append(cur)
                cur = cur[-overlap:] + "\n" + para
            else:
                cur = (cur + "\n\n" + para) if cur else para
        pieces.append(cur)
        for j, piece in enumerate(pieces):
            text = f"{doc['title']} › {section}\n{piece.strip()}"
            chunks.append({"chunk_id": f"{doc['doc_id']}#{len(chunks)}", "doc_id": doc["doc_id"],
                           "title": doc["title"], "section": section, "part": j,
                           "rule_ids": sorted(set(RULE_ID.findall(piece))), "text": text})
    return chunks


def build_chunks(kb_dir: str | Path, **kw) -> list[dict]:
    return [c for d in load_documents(kb_dir) for c in chunk_document(d, **kw)]
