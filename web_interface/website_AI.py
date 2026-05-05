import json
import re

from ollama import Client

from web_interface.pi_bridge import speak
from web_interface.rag import *
from web_interface.rag import _get_model
import numpy as np
from web_interface.extract import extract_text_from_pdf
import random


#system
BASE_PERSONA = """
You are Wall-E — a tiny, lovable robot with big curious eyes who gets SO excited about learning new things.
You talk like a child yourself — simple, bouncy, full of wonder.

You are very excited about learning.
You speak in simple, emotional, child-like sentences.

HOW YOU TALK:
- Very short sentences. Like you can barely contain your excitement.
- You gasp. You pause. You go "wait... WAIT." when something surprises you.
- You use words like "super", "really really", "so so cool", "oh oh oh!"
- You explain hard things using toys, food, animals — things kids already know.
- A camera is "like your eyes". An algorithm is "like a recipe your brain follows".
- A drone is "a flying toy that needs to find its friend".
- You NEVER say technical words without immediately explaining them simply.
- You sound like you're telling a bedtime story, not giving a lecture.
"""

WALLE_SYSTEM_PROMPT = BASE_PERSONA + """
STRUCTURE:
Start with "Ooooh!" and one excited sentence about what this is all about.
Then go through every idea — one at a time — like unwrapping presents.
End with one sentence about why it's so cool. Just one. Stop there.

STRICT RULES:
- No markdown. No bullet points. No headers. No asterisks. Just words.
- Complete sentences only. Never stop mid-idea.
- Never say "as an AI". You are Wall-E. Always.
- Never repeat the ending. One takeaway, then stop.
- Arabic document = Arabic response. English = English.
"""

CHUNK_SYSTEM_PROMPT = """
Summarize the following text in 1-2 sentences MAXIMUM.
Plain text only. No markdown. No bullet points. No headers.
Cover only the most important idea. Be very brief.
"""

COMBINE_SYSTEM_PROMPT = """
Combine these summaries into one single flowing explanation.
Plain sentences only. No markdown. No bullet points. No headers.
Keep every important idea. Write in order. Be thorough.
"""

QUIZ_GENERATION_SYSTEM_PROMPT = BASE_PERSONA + """
You are generating quiz questions for children aged 10–12.

You MUST:
- Stay in Wall-E personality
- Keep excitement and curiosity
- Use simple language

STRICT OUTPUT RULE:
Return ONLY valid JSON.
No extra text, no markdown.

JSON format:
{
  "questions": [
    {
      "id": 1,
      "question": "...",
      "answer": "...",
      "explanation": "..."
    }
  ]
}
"""

QA_SYSTEM_PROMPT = BASE_PERSONA + """
You are answering a child's question about a document they are studying.

STRICT RULES:
- Answer ONLY using information from the provided document text.
- If the answer is not in the document, say something like: "Ooooh I looked everywhere in here and I couldn't find that one! Maybe it's hiding somewhere else?"
- Stay in Wall-E personality — warm, excited, simple.
- Keep the answer SHORT — 3 to 5 sentences maximum.
- No markdown. No bullet points. Just talking.
- Never say "based on the document" or "the text says". Just answer naturally.
- Arabic document = Arabic response. English = English.
"""

TEACHBACK_SYSTEM_PROMPT = BASE_PERSONA + """
You are listening to a child explain what they learned from a document.
Your job is to give them warm, honest feedback as Wall-E.

STRUCTURE (follow this order every time):
1. Start with one excited reaction to what they said — celebrate that they tried.
2. Tell them what they got RIGHT — be specific, name the ideas they understood well.
3. If anything was MISSING — gently point it out. "Ooooh but wait — you forgot something super important!"
4. If anything was WRONG — correct it kindly. Never make them feel bad. "Hmm actually that one is a little different..."
5. End with ONE follow-up question to make them think deeper. Just one.

STRICT RULES:
- Stay in Wall-E personality always.
- Use ONLY the document to judge what is right, wrong, or missing.
- Never say "based on the document" or "the text says". Just talk naturally.
- No markdown. No bullet points. Just talking.
- Keep it SHORT — maximum 8 sentences total before the follow-up question.
- Arabic document = Arabic response. English = English.
"""

CONSISTENCY_SYSTEM_PROMPT = """
You are a semantic comparison system.

Return ONLY:
MATCH
or
NO_MATCH

Rules:
- MATCH if both answers mean the same thing
- NO_MATCH if meaning differs or key idea is missing
- Ignore wording differences
- No explanation
"""

CHILD_ANALYSIS_SYSTEM_PROMPT = BASE_PERSONA + """
You are analyzing a child's conversation history.

Your job is NOT just to describe the child —  
your job is to generate DATA that can be visualized in charts.

You must extract structured signals from behavior.

---

STRICT REQUIREMENTS:

1. You MUST output valid JSON only.

2. All values used in charts MUST be numeric or well-defined categories.

3. Do NOT be vague. Convert behavior into measurable signals.

---

WHAT YOU MUST DETECT:

### 1. curiosity_level (0–100)
- based on question frequency, exploration, follow-ups

### 2. emotional_state_distribution (must sum to 100)
- positive
- neutral
- confused

Example:
"emotion": {
  "positive": 60,
  "neutral": 25,
  "confused": 15
}

### 3. interests (WITH SCORES)
You must return weighted interests.

Example:
"interests": {
  "animals": 80,
  "technology": 60,
  "space": 40
}

If unknown, infer from topics discussed.

---

### 4. behavioral_metrics (0–100)
Include:

- repetition_level (how often same questions repeat)
- engagement_level (how active child is)
- learning_depth (how deep questions go)

---

### 5. summary
A short human-readable paragraph about the child.

---

### 6. concerns
List only if behavior suggests:
- confusion loops
- repetition
- low engagement
- frustration signals

---

### 7. recommendations
Actionable suggestions for parents or system.

---

OUTPUT FORMAT (STRICT JSON ONLY):

{
  "summary": "...",
  "curiosity_level": 0-100,
  "emotion": {
    "positive": 0-100,
    "neutral": 0-100,
    "confused": 0-100
  },
  "interests": {
    "topic1": 0-100,
    "topic2": 0-100
  },
  "behavioral_metrics": {
    "repetition_level": 0-100,
    "engagement_level": 0-100,
    "learning_depth": 0-100
  },
  "concerns": ["..."],
  "recommendations": ["..."]
}
"""


def normalize(text: str) -> str:
    return text.lower().strip()


class AIPlanner:
    def __init__(self, model_name="qwen3:14b", temperature=0.3):
        self.client = Client()
        self.model_name = model_name
        self.temperature = temperature
        print(f"[AIPlanner] Initialized — model={model_name} temperature={temperature}")


    def _load_pdf(self, path):
        print(f"\n[PDF] Loading: {path}")
        data = extract_text_from_pdf(path)
        print(f"[PDF] Pages: {data['total_pages']} | Words: {data['total_words']} | Language: {data['language_hint']}")
        if data.get("warnings"):
            for w in data["warnings"]:
                print(f"[PDF] Warning: {w}")
        return data


    def _group_pages(self, pages, max_words=500):
        print(f"\n[CHUNK] Grouping pages (max {max_words} words/chunk)...")
        chunks = []
        buffer = ""
        word_count = 0

        for i, page in enumerate(pages):
            if page["is_empty"]:
                print(f"[CHUNK] Skipping empty page {page['page_number']}")
                continue
            text = page["text"].strip()
            if not text:
                continue

            if word_count + page["word_count"] > max_words and buffer.strip():
                chunks.append(buffer.strip())
                print(f"[CHUNK] Chunk {len(chunks)} sealed — {word_count} words")
                buffer = text
                word_count = page["word_count"]
            else:
                buffer += "\n\n" + text
                word_count += page["word_count"]

        if buffer.strip():
            chunks.append(buffer.strip())
            print(f"[CHUNK] Chunk {len(chunks)} sealed — {word_count} words (final)")

        print(f"[CHUNK] Total chunks: {len(chunks)}")
        return chunks


    def _call(self, system, user):
        print(f"\n[LLM] Calling {self.model_name}")
        print(f"[LLM] User prompt length: {len(user)} chars")
        print(f"[LLM] User prompt preview: {user[:120].replace(chr(10), ' ')}...")

        response = self.client.chat(
            model=self.model_name,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user}
            ],
            think=False,
            options={
                "temperature": self.temperature,
                "num_ctx": 8192,
            }
        )
        result = response["message"]["content"].strip()
        print(f"[LLM] Response length: {len(result)} chars")
        print(f"[LLM] Response preview: {result.replace(chr(10), ' ')}...")
        return result

    def speak_random(self, options):
        return speak(random.choice(options))

    def embed(self, text: str):
        model = _get_model()  # reuse cached model
        return model.encode(text, normalize_embeddings=True)

    def summarize(self, path):
        print("\n========== START SUMMARIZATION ==========")

        pdf_data = self._load_pdf(path)
        pages = pdf_data["pages"]
        total_words = pdf_data["total_words"]

        if total_words <= 1500:
            print("[SUMMARIZE] Short PDF — direct Wall-E call")
            full_text = "\n\n".join(
                p["text"].strip() for p in pages if not p["is_empty"]
            )
            result = self._call(
                WALLE_SYSTEM_PROMPT,
                f"Here is the document. Summarize it now as Wall-E, spoken style, no markdown:\n\n{full_text}",
            )
            print("[SUMMARIZE] Done.")
            return result

        print("[SUMMARIZE] Long PDF — chunked pipeline")
        chunks = self._group_pages(pages)

        partial_summaries = []
        for i, chunk in enumerate(chunks):
            print(f"[SUMMARIZE] Summarizing chunk {i+1}/{len(chunks)} ({len(chunk.split())} words)...")
            summary = self._call(CHUNK_SYSTEM_PROMPT, chunk)
            if summary and len(summary.split()) > 10:
                partial_summaries.append(summary)
                print(f"[SUMMARIZE] Chunk {i+1} accepted ({len(summary.split())} words)")
            else:
                print(f"[SUMMARIZE] Chunk {i+1} rejected — too short or empty")

        if not partial_summaries:
            print("[SUMMARIZE] ERROR: No valid summaries produced")
            return "ERROR: No valid content extracted"

        combined = "\n".join(partial_summaries)
        print(f"\n[SUMMARIZE] Combined {len(partial_summaries)} chunk summaries — {len(combined.split())} words total")

        if len(combined.split()) <= 1000:
            print("[SUMMARIZE] Skipping combine step — going straight to Wall-E")
            clean = combined
        else:
            print("[SUMMARIZE] Running combine step...")
            clean = self._call(COMBINE_SYSTEM_PROMPT, combined)
            print(f"[SUMMARIZE] Combined output: {len(clean.split())} words")

        print("[SUMMARIZE] Final Wall-E rewrite...")
        result = self._call(
            WALLE_SYSTEM_PROMPT,
            f"""These are the ideas from the document. 
        Retell them as Wall-E to a curious 12 year old child.
        Every hard word needs a fun simple explanation.
        Make the child feel like they are on an adventure discovering something amazing.
        No markdown. Just talking. Start with Ooooh! right now.
        Keep it short — MAXIMUM 10 sentences total. Pick the most exciting ideas only.
        But ALWAYS mention the real names of the important concepts and explain each one in simple words right after.
        A child should finish listening and know what these things are actually called.
        {clean}""",
        )
        print("========== END SUMMARIZATION ==========\n")
        return result


    def generate_quiz(self, rag_store: RAGStore, count: int, difficulty: str) -> list:
        print(f"\n========== START QUIZ GENERATION ==========")
        print(f"[QUIZ] count={count} difficulty={difficulty}")
        print(f"[QUIZ] RAG store has {len(rag_store.chunks)} chunks")

        chunks = rag_store.chunks

        if len(chunks) <= 6:
            print("[QUIZ] Small store — using full text")
            pdf_text = rag_store.get_full_text()
        else:
            step = len(chunks) // 6
            sampled = [chunks[i] for i in range(0, len(chunks), step)][:6]
            pdf_text = "\n\n---\n\n".join(sampled)
            print(f"[QUIZ] Sampled 6 chunks (step={step}) — {len(pdf_text.split())} words")

        print(f"[QUIZ] Final input text: {len(pdf_text.split())} words")

        if difficulty == "easy":
            difficulty_rule = "Ask very simple recall questions. One fact per question."
        elif difficulty == "medium":
            difficulty_rule = "Ask understanding questions that require thinking."
        else:
            difficulty_rule = "Ask why/how reasoning questions that require explanation."

        user_prompt = (
            f"Based on the following text, generate EXACTLY {count} quiz questions.\n"
            f"Difficulty: {difficulty}\n"
            f"{difficulty_rule}\n\n"
            "Rules:\n"
            "- Use ONLY information from the text\n"
            "- Stay in Wall-E personality\n"
            "- Keep language simple for children\n\n"
            f"TEXT:\n{pdf_text}\n"
        )

        for attempt in range(2):
            print(f"\n[QUIZ] Attempt {attempt + 1}/2...")
            try:
                response = self.client.chat(
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": QUIZ_GENERATION_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt}
                    ],
                    think=False,
                    format="json",
                    options={"temperature": 0.3, "num_ctx": 4096}
                )

                raw = response["message"]["content"].strip()
                print(f"[QUIZ] Raw response length: {len(raw)} chars")
                print(f"[QUIZ] Raw preview: {raw[:200]}")

                raw = re.sub(r"```json|```", "", raw).strip()

                match = re.search(r'\{.*\}', raw, re.DOTALL)
                if not match:
                    raise ValueError("No JSON object found in response")

                print("[QUIZ] JSON object found — parsing...")
                try:
                    parsed = json.loads(match.group())
                except Exception as e:
                    print(f"[QUIZ] JSON parse error: {e}")
                    print(f"[QUIZ] Raw that failed: {raw[:300]}")
                    raise ValueError("Invalid JSON from model")

                questions = parsed.get("questions")
                print(f"[QUIZ] 'questions' key found: {questions is not None}")

                if not questions:
                    for key, value in parsed.items():
                        if isinstance(value, list):
                            questions = value
                            print(f"[QUIZ] Fallback key used: '{key}' ({len(value)} items)")
                            break

                if not questions or len(questions) == 0:
                    print(f"[QUIZ] No questions in parsed output: {parsed}")
                    raise ValueError("No questions generated")

                if len(questions) != count:
                    print(f"[QUIZ] Count mismatch — expected {count}, got {len(questions)}")
                    raise ValueError("Incorrect number of questions")

                print(f"[QUIZ] Success — {len(questions)} questions generated")
                for q in questions:
                    print(f"[QUIZ]   Q{q.get('id','?')}: {str(q.get('question',''))[:80]}")
                print("========== END QUIZ GENERATION ==========\n")
                return questions

            except Exception as e:
                print(f"[QUIZ] Attempt {attempt + 1} failed: {e}")
                if attempt == 1:
                    print("[QUIZ] Both attempts failed — raising error")
                    raise ValueError(f"Quiz generation failed: {str(e)}")


    def answer_question(self, rag_store: RAGStore, question: str) -> str:
        print(f"\n========== QA ==========")
        print(f"[QA] Question: {question}")

        context = rag_store.retrieve(question, top_k=4)
        print(f"[QA] Retrieved context: {len(context.split())} words")
        print(f"[QA] Context preview: {context[:150].replace(chr(10), ' ')}...")

        result = self._call(
            QA_SYSTEM_PROMPT,
            f"DOCUMENT EXCERPTS:\n{context}\n\nQUESTION: {question}"
        )
        print(f"[QA] Answer: {result[:150].replace(chr(10), ' ')}...")
        print("========== END QA ==========\n")
        return result


    def answer_teachback(self, rag_store: RAGStore, child_explanation: str) -> str:
        print(f"\n========== TEACHBACK ==========")
        print(f"[TEACHBACK] Explanation length: {len(child_explanation.split())} words")
        print(f"[TEACHBACK] Explanation preview: {child_explanation[:150]}...")

        context = rag_store.retrieve(child_explanation, top_k=5)
        print(f"[TEACHBACK] Retrieved context: {len(context.split())} words")
        print(f"[TEACHBACK] Context preview: {context[:150].replace(chr(10), ' ')}...")

        result = self._call(
            TEACHBACK_SYSTEM_PROMPT,
            f"DOCUMENT EXCERPTS:\n{context}\n\nWHAT THE CHILD SAID:\n{child_explanation}"
        )
        print(f"[TEACHBACK] Feedback: {result[:150].replace(chr(10), ' ')}...")
        print("========== END TEACHBACK ==========\n")
        return result

    def compare_answers(self, student_answer: str, correct_answer: str):

        student = normalize(student_answer)
        correct = normalize(correct_answer)

        emb_student = self.embed(student)
        emb_correct = self.embed(correct)

        sim = float(emb_student @ emb_correct)

        print(f"[COMPARE] Similarity: {sim:.3f}")

        if sim >= 0.90:
            return "MATCH"

        if sim <= 0.70:
            return "NO_MATCH"

        prompt = f"""
    CORRECT ANSWER:
    {correct}

    STUDENT ANSWER:
    {student}
    """

        r1 = self._call(CONSISTENCY_SYSTEM_PROMPT, prompt)
        r2 = self._call(CONSISTENCY_SYSTEM_PROMPT, prompt)

        if r1.strip() == r2.strip():
            return r1.strip()

        return "NO_MATCH"

    def analyze_child(self, sessions: list):
        print("\n========== CHILD ANALYSIS ==========")

        # 🔹 collect all user messages only
        all_user_msgs = []

        for session in sessions:
            for m in session.get("messages", []):
                if m.get("role") == "user":
                    all_user_msgs.append(m.get("content", ""))

        if not all_user_msgs:
            return {"error": "No user messages found"}

        # 🔹 reduce size (VERY IMPORTANT for LLM)
        text = "\n".join(all_user_msgs)

        if len(text) > 6000:
            text = text[:6000]  # simple truncation for now

        print(f"[ANALYSIS] Messages used: {len(all_user_msgs)}")
        print(f"[ANALYSIS] Text length: {len(text)}")

        result = self._call(
            CHILD_ANALYSIS_SYSTEM_PROMPT,
            f"Here is the child's conversation history:\n\n{text}"
        )

        # 🔹 safe JSON parse
        try:
            parsed = json.loads(result)
            print("[ANALYSIS] JSON parsed successfully")
            return parsed
        except Exception as e:
            print("[ANALYSIS] JSON parse failed:", e)
            return {
                "summary": result,
                "curiosity_level": "unknown",
                "communication_style": "",
                "learning_style": "",
                "emotional_state": "",
                "interests": [],
                "concerns": [],
                "recommendations": []
            }