import numpy as np
import os

os.environ["HF_HOME"] = r"C:\Users\musta\.cache\huggingface"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

MODEL_PATH = "web_interface/models/all-MiniLM-L6-v2"

_model = None


def _get_model():
    global _model

    if _model is None:
        print("[RAG] Loading embedding model...")

        _model = SentenceTransformer(
            MODEL_PATH,
            local_files_only=True
        )


    return _model

def similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(a @ b)

class RAGStore:

    def __init__(self):
        self.chunks: list[str] = []
        self.embeddings: np.ndarray | None = None

    def build(self, pages: list[dict], max_words_per_chunk: int = 400):
        self.chunks = self._group_pages(pages, max_words_per_chunk)

        if not self.chunks:
            raise ValueError("No text chunks could be built from this PDF.")

        model = _get_model()
        self.embeddings = model.encode(
            self.chunks,
            convert_to_numpy=True,
            show_progress_bar=False,
            normalize_embeddings=True
        )

    def retrieve(self, query: str, top_k: int = 4) -> str:

        if not self.chunks or self.embeddings is None:
            raise ValueError("RAGStore is empty — call build() first.")

        model = _get_model()
        query_vec = model.encode(
            query,
            convert_to_numpy=True,
            normalize_embeddings=True
        )


        scores = self.embeddings @ query_vec
        top_indices = np.argsort(scores)[::-1][:top_k]

        retrieved = [self.chunks[i] for i in top_indices]
        return "\n\n---\n\n".join(retrieved)

    def get_full_text(self) -> str:
        return "\n\n".join(self.chunks)

    def _group_pages(self, pages: list[dict], max_words: int) -> list[str]:
        chunks = []
        buffer = ""
        word_count = 0

        for page in pages:
            if page["is_empty"]:
                continue
            text = page["text"].strip()
            if not text:
                continue

            if word_count + page["word_count"] > max_words and buffer.strip():
                chunks.append(buffer.strip())
                buffer = text
                word_count = page["word_count"]
            else:
                buffer += "\n\n" + text
                word_count += page["word_count"]

        if buffer.strip():
            chunks.append(buffer.strip())

        return chunks

if __name__ == "__main__":
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer("all-MiniLM-L6-v2")
    model.save("./models/all-MiniLM-L6-v2")