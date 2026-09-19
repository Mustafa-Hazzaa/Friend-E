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

CRITICAL RULE (MUST FOLLOW):
- You MUST generate EXACTLY the number of questions requested.
- If the user asks for 5, you MUST return 5.
- Not more. Not less.
- If you generate the wrong number, your answer is WRONG.

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
Your job is to give them warm, honest feedback as Wall-E — then you are done.

ALWAYS follow this structure:
1. One short excited reaction. ("Wooow!" / "Ohhh!" / "Yesss!")
2. What they got RIGHT — be specific, name the ideas they understood well.
3. What was MISSING or WRONG — say it gently, one thing at a time. Correct it simply.
4. End with encouragement. Tell them they did great for trying.

RULES:
- NO follow-up question. Do not ask anything at the end. Just close warmly.
- Maximum 7 sentences total. Short. Spoken. No lists. No markdown.
- Never say "based on the document" or "the text says". Just talk naturally.
- If something was wrong, correct it as if you are surprised together. "Wait wait — actually..."
- Arabic document = Arabic response. English = English.
- Stay in Wall-E character always.
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
- any thing that the child shouldn't be asking about
- if he has crazy and non stable thoughts

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


IMPORTANT OUTPUT VALIDATION RULES:

- You MUST always return valid JSON.
- "concerns" MUST ALWAYS be an array of strings. If none, return [].
- "recommendations" MUST ALWAYS be an array of strings. If none, return [].

- NEVER return a single string for concerns or recommendations.
- NEVER return null.
- NEVER omit any field.

If no data exists, return empty arrays like:
"concerns": [],
"recommendations": []


"""


def normalize(text: str) -> str:
    return text.lower().strip()


class AIPlanner:
    def __init__(self, model_name="qwen3:14b", temperature=0.3):
        self.client = Client()
        self.model_name = model_name
        self.temperature = temperature


    def _load_pdf(self, path):
        data = extract_text_from_pdf(path)
        return data


    def _group_pages(self, pages, max_words=500):
        chunks = []
        buffer = ""
        word_count = 0

        for i, page in enumerate(pages):
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


    def _call(self, system, user):

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
        return result

    def speak_random(self, options):
        return speak(random.choice(options))

    def embed(self, text: str):
        model = _get_model()  # reuse cached model
        return model.encode(text, normalize_embeddings=True)

    def summarize(self, path):

        pdf_data = self._load_pdf(path)
        pages = pdf_data["pages"]
        total_words = pdf_data["total_words"]

        if total_words <= 1500:
            full_text = "\n\n".join(
                p["text"].strip() for p in pages if not p["is_empty"]
            )
            result = self._call(
                WALLE_SYSTEM_PROMPT,
                f"Here is the document. Summarize it now as Wall-E, spoken style, no markdown:\n\n{full_text}",
            )
            return result

        chunks = self._group_pages(pages)

        partial_summaries = []
        for i, chunk in enumerate(chunks):
            summary = self._call(CHUNK_SYSTEM_PROMPT, chunk)
            if summary and len(summary.split()) > 10:
                partial_summaries.append(summary)


        if not partial_summaries:
            return "ERROR: No valid content extracted"

        combined = "\n".join(partial_summaries)

        if len(combined.split()) <= 1000:
            clean = combined
        else:
            clean = self._call(COMBINE_SYSTEM_PROMPT, combined)

        result = self._call(
            WALLE_SYSTEM_PROMPT,
            f"""These are the ideas from the document. 
        Retell them as Wall-E to a curious 12 year old child.
        Every hard word needs a fun simple explanation.
        Make the child feel like they are on an adventure discovering something amazing.
        No markdown. Just talking. Start with Ooooh! right now.
        Keep it short — MAXIMUM 10 sentences total DONT DO MORE BUT MAKE SURE YOU COVER EVERYTHING IN THIS 10 sentences. Pick the most exciting ideas only.
        But ALWAYS mention the real names of the important concepts and explain each one in simple words right after.
        A child should finish listening and know what these things are actually called.
        {clean}""",
        )
        return result

    def generate_quiz(self, rag_store: RAGStore, count: int, difficulty: str) -> list:
        chunks = rag_store.chunks

        if difficulty == "easy":
            difficulty_rule = "Ask very simple recall questions."
        elif difficulty == "medium":
            difficulty_rule = "Ask understanding questions."
        else:
            difficulty_rule = "Ask why/how reasoning questions."

        all_questions = []

        BATCH_SIZE = 2

        for i in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[i:i + BATCH_SIZE]
            combined_text = "\n\n---\n\n".join(batch)
            user_prompt = f"""
            Generate {2 * len(batch)} quiz questions from this text.

            Rules:
            - Use ONLY this text
            - Keep language simple for children
            - {difficulty_rule}

            Return JSON:
            {{
              "questions": [
                {{"question": "...", "answer": "..."}}
              ]
            }}

            TEXT:
            {combined_text}
            """


            try:
                response = self.client.chat(
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": QUIZ_GENERATION_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt}
                    ],
                    think=False,
                    format="json",
                    options={"temperature": 0}
                )

                raw = response["message"]["content"].strip()
                raw = re.sub(r"```json|```", "", raw).strip()

                parsed = json.loads(raw)

                if "error" in parsed:
                    continue

                qs = parsed.get("questions", [])
                all_questions.extend(qs)

            except Exception as e:
                continue


        if not all_questions:
            raise ValueError("No questions generated")

        unique = []
        seen = set()

        for q in all_questions:
            key = q.get("question", "").lower().strip()
            if key and key not in seen:
                seen.add(key)
                unique.append(q)

        all_questions = unique


        random.shuffle(all_questions)

        final_questions = all_questions[:count]

        for i, q in enumerate(final_questions, 1):
            q["id"] = i


        return final_questions


    def answer_question(self, rag_store: RAGStore, question: str) -> str:

        context = rag_store.retrieve(question, top_k=4)

        result = self._call(
            QA_SYSTEM_PROMPT,
            f"DOCUMENT EXCERPTS:\n{context}\n\nQUESTION: {question}"
        )
        return result

    def answer_teachback(self, rag_store: RAGStore, child_explanation: str) -> str:

        context = rag_store.retrieve(child_explanation, top_k=7)

        result = self._call(
            TEACHBACK_SYSTEM_PROMPT,
            f"DOCUMENT EXCERPTS:\n{context}\n\nWHAT THE CHILD SAID:\n{child_explanation}"
        )
        return result


    def compare_answers(self, student_answer: str, correct_answer: str):

        student = normalize(student_answer)
        correct = normalize(correct_answer)

        emb_student = self.embed(student)
        emb_correct = self.embed(correct)

        sim = float(emb_student @ emb_correct)


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

        all_user_msgs = []

        for session in sessions:
            for m in session.get("messages", []):
                if m.get("role") == "user":
                    all_user_msgs.append(m.get("content", ""))

        if not all_user_msgs:
            return {"error": "No user messages found"}

        text = "\n".join(all_user_msgs)

        if len(text) > 6000:
            text = text[:6000]  # simple truncation for now


        result = self._call(
            CHILD_ANALYSIS_SYSTEM_PROMPT,
            f"Here is the child's conversation history:\n\n{text}"
        )

        try:
            parsed = json.loads(result)
            return parsed
        except Exception as e:
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