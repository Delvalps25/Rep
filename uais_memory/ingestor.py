import re
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Any
from uais_memory.memory import Memory

class DocumentIngestor:
    CHUNK_SIZE = 512
    OVERLAP    = 64

    def __init__(self, memory: Memory, workspace: Path):
        self._mem  = memory
        self._ws   = workspace
        self.SUPPORTED = {".pdf", ".docx", ".txt", ".md",
                          ".html", ".htm", ".csv", ".json"}

    def _extract_pdf(self, path: Path) -> str:
        try:
            import pypdf
            reader = pypdf.PdfReader(str(path))
            return "\n".join(p.extract_text() or "" for p in reader.pages)
        except ImportError:
            pass
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(str(path))
            return "\n".join(p.extract_text() or "" for p in reader.pages)
        except ImportError:
            return f"[PDF extraction requires pypdf: pip install pypdf]"

    def _extract_docx(self, path: Path) -> str:
        try:
            import docx
            doc = docx.Document(str(path))
            return "\n".join(p.text for p in doc.paragraphs)
        except ImportError:
            return "[DOCX extraction requires python-docx: pip install python-docx]"

    def _extract_html(self, path: Path) -> str:
        raw = path.read_text(encoding="utf-8", errors="replace")
        try:
            from bs4 import BeautifulSoup
            return BeautifulSoup(raw, "html.parser").get_text(separator="\n")
        except ImportError:
            return re.sub(r"<[^>]+>", " ", raw)

    def _extract_csv(self, path: Path) -> str:
        import csv
        rows = []
        with open(path, newline="", encoding="utf-8", errors="replace") as f:
            for row in csv.reader(f):
                rows.append(", ".join(row))
        return "\n".join(rows)

    def _extract(self, path: Path) -> str:
        ext = path.suffix.lower()
        if ext == ".pdf":   return self._extract_pdf(path)
        if ext == ".docx":  return self._extract_docx(path)
        if ext in (".html", ".htm"): return self._extract_html(path)
        if ext == ".csv":   return self._extract_csv(path)
        return path.read_text(encoding="utf-8", errors="replace")

    def _chunk(self, text: str) -> list[str]:
        chunks, i = [], 0
        while i < len(text):
            end = min(i + self.CHUNK_SIZE, len(text))
            chunks.append(text[i:end].strip())
            i += self.CHUNK_SIZE - self.OVERLAP
        return [c for c in chunks if len(c) > 10]

    def ingest(self, path: str | Path) -> int:
        p = Path(path).expanduser()
        if not p.exists() or p.suffix.lower() not in self.SUPPORTED:
            return 0
        text   = self._extract(p)
        chunks = self._chunk(text)
        try:
            source = str(p.relative_to(self._ws)) if str(p).startswith(str(self._ws)) else p.name
        except ValueError:
            source = p.name
        for i, chunk in enumerate(chunks):
            self._mem.store(chunk, {"source": source, "chunk": i})
        ingested = self._mem.get("_ingested_docs", {})
        ingested[source] = len(chunks)
        self._mem.set("_ingested_docs", ingested)
        return len(chunks)

    def ingest_dir(self, directory: Path, glob: str = "**/*") -> dict[str, int]:
        results: dict[str, int] = {}
        for p in Path(directory).glob(glob):
            if p.is_file() and p.suffix.lower() in self.SUPPORTED:
                n = self.ingest(p)
                if n: results[p.name] = n
        return results

    def ingest_url(self, url: str) -> int:
        try:
            jina_url = "https://reader.jina.ai/" + urllib.parse.quote(url, safe=":/?=&%")
            text = urllib.request.urlopen(jina_url, timeout=15).read().decode(
                "utf-8", errors="replace")[:50000]
            if not text.strip():
                return 0
            chunks = self._chunk(text)
            for i, chunk in enumerate(chunks):
                self._mem.store(chunk, {"source": url, "chunk": i})
            ingested = self._mem.get("_ingested_docs", {})
            ingested[url] = len(chunks)
            self._mem.set("_ingested_docs", ingested)
            return len(chunks)
        except Exception:
            return 0

    def list_ingested(self) -> dict[str, int]:
        return self._mem.get("_ingested_docs", {})
