import datetime
import json
import os

from flask import Blueprint, request, current_app, jsonify
from werkzeug.utils import secure_filename

from web_interface.website_AI import AIPlanner
from .rag import RAGStore
from .extract import extract_text_from_pdf
from .pi_bridge import speak, listen

pdf = Blueprint('pdf', __name__)

_rag_cache: dict[str, RAGStore] = {}
_ai = AIPlanner()

CORRECT_RESPONSES = [
    "Yaaay! That's correct!",
    "Nice job! You got it!",
    "Perfect! That's right!",
    "Awesome! Well done!",
    "Correct! You're doing great!",
    "Boom! That's it!",
]

INCORRECT_RESPONSES = [
    "Hmm, not quite, but that's okay!",
    "Almost! Let's keep going!",
    "Not exactly, but good try!",
    "Close! You're learning!",
    "That's not it, but don't worry!",
    "Try the next one, you've got this!",
]

QUIZ_START_RESPONSES = [
    "Let's start the quiz!",
    "Time for some questions!",
    "Ready? Let's begin!",
    "Here we go!",
]

QUIZ_END_RESPONSES = [
    "We finished! You did amazing!",
    "Quiz complete! Great job today!",
    "That was awesome! Well done!",
    "You're done! I'm proud of you!",
]

READY_RESPONSES = [
    "I'm ready!",
    "Ready when you are!",
    "All set! Go ahead.",
    "I'm listening. Ask me anything.",
    "Ready! What's your question?",
    "I'm prepared. Let's do this.",
    "Ready to help. What do you need?",
]


# =============================================================
# Save PDF session history
# =============================================================
def save_pdf_session(session_type, filename, data):
    try:
        history_folder = os.path.join(
            current_app.config["UPLOAD_FOLDER"],
            "history"
        )

        os.makedirs(history_folder, exist_ok=True)

        history_data = {
            "timestamp": datetime.datetime.now().isoformat(),
            "session_type": session_type,
            "pdf_filename": filename,
            "data": data
        }

        save_name = (
            f"{session_type}_"
            f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )

        filepath = os.path.join(history_folder, save_name)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(history_data, f, indent=4, ensure_ascii=False)

        print(f"[HISTORY] Saved: {filepath}")

    except Exception as e:
        print(f"[ERROR] Failed saving history: {e}")


# =============================================================
# Receive history JSON from another laptop
# =============================================================
@pdf.route("/upload_history", methods=["POST"])
def upload_history():
    try:
        data = request.get_json(force=True)

        history_folder = os.path.join(
            current_app.config["UPLOAD_FOLDER"],
            "history"
        )

        os.makedirs(history_folder, exist_ok=True)

        filename = (
            f"history_"
            f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )

        filepath = os.path.join(history_folder, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

        print(f"[HISTORY] Uploaded: {filepath}")

        return jsonify({
            "status": "success",
            "file": filename
        })

    except Exception as e:
        print(f"[ERROR] History upload failed: {e}")

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


# =============================================================
def _get_or_build_rag(filename: str, path: str) -> RAGStore:
    if filename not in _rag_cache:
        print(f"[RAG] Building store for: {filename}")

        pdf_data = extract_text_from_pdf(path)

        store = RAGStore()
        store.build(pdf_data["pages"])

        _rag_cache[filename] = store

        print(f"[RAG] Store ready — {len(store.chunks)} chunks")

    else:
        print(f"[RAG] Cache hit for: {filename}")

    return _rag_cache[filename]


# =============================================================
def _get_path(filename: str):
    if not filename:
        return None, (jsonify({"error": "No filename provided"}), 400)

    path = os.path.join(
        current_app.config["UPLOAD_FOLDER"],
        filename
    )

    if not os.path.exists(path):
        return None, (jsonify({"error": "File not found"}), 404)

    return path, None


# =============================================================
@pdf.route("/upload", methods=["POST"])
def upload_pdf():
    file = request.files.get("file")

    if not file:
        return jsonify({"error": "No file"}), 400

    filename = secure_filename(file.filename)

    upload_folder = current_app.config["UPLOAD_FOLDER"]

    os.makedirs(upload_folder, exist_ok=True)

    path = os.path.join(upload_folder, filename)

    file.save(path)

    try:
        store = _get_or_build_rag(filename, path)

        return jsonify({
            "filename": filename,
            "chunks": len(store.chunks)
        })

    except Exception as e:
        print(f"[ERROR] RAG build failed: {e}")

        return jsonify({
            "error": "Failed to process PDF",
            "details": str(e)
        }), 500


# =============================================================
@pdf.route("/summarize", methods=["POST"])
def summarize():
    data = request.json

    filename = data.get("filename")

    path, err = _get_path(filename)

    if err:
        return err

    try:
        summary = _ai.summarize(path)

        speak(summary)

        save_pdf_session(
            session_type="summary",
            filename=filename,
            data={
                "summary": summary
            }
        )

        return jsonify({
            "summary": summary
        })

    except Exception as e:
        print(f"[ERROR] Summarize failed: {e}")

        return jsonify({
            "error": "Summarization failed",
            "details": str(e)
        }), 500


# =============================================================
@pdf.route("/quiz/generate", methods=["POST"])
def quiz():
    data = request.get_json(force=True)

    filename = data.get("filename")
    count = int(data.get("count", 5))
    difficulty = data.get("difficulty", "medium")

    print(f"\n[QUIZ] filename={filename} count={count} difficulty={difficulty}")

    path, err = _get_path(filename)

    if err:
        return err

    try:
        store = _get_or_build_rag(filename, path)

        questions = _ai.generate_quiz(
            store,
            count,
            difficulty
        )

        save_pdf_session(
            session_type="quiz_generate",
            filename=filename,
            data={
                "count": count,
                "difficulty": difficulty,
                "questions": questions
            }
        )

        return jsonify({
            "questions": questions
        })

    except Exception as e:
        print(f"[ERROR] Quiz generation failed: {e}")

        return jsonify({
            "error": "Quiz generation failed",
            "details": str(e)
        }), 500


# =============================================================
@pdf.route("/quiz/run", methods=["POST"])
def quiz_run():
    right = 0
    wrong = 0

    data = request.get_json(force=True)

    filename = data.get("filename")
    count = int(data.get("count", 5))
    difficulty = data.get("difficulty", "medium")

    path, err = _get_path(filename)

    if err:
        return err

    try:
        store = _get_or_build_rag(filename, path)

        questions = _ai.generate_quiz(
            store,
            count,
            difficulty
        )

        results = []

        _ai.speak_random(QUIZ_START_RESPONSES)

        for q in questions:
            speak(q["question"])

            child_answer = listen(timeout=30.0)

            print(f"[QUIZ] Child answered: '{child_answer}'")

            result = _ai.compare_answers(
                student_answer=child_answer,
                correct_answer=q["answer"]
            )

            if result == "MATCH":
                _ai.speak_random(CORRECT_RESPONSES)
                right += 1
            else:
                _ai.speak_random(INCORRECT_RESPONSES)
                wrong += 1

            speak(q["explanation"])

            results.append({
                "question": q["question"],
                "expected": q["answer"],
                "child_answer": child_answer,
                "result": result
            })

        speak(
            f"you got {right} questions right and got {wrong} answers wrong"
        )

        _ai.speak_random(QUIZ_END_RESPONSES)

        save_pdf_session(
            session_type="quiz_run",
            filename=filename,
            data={
                "count": count,
                "difficulty": difficulty,
                "right": right,
                "wrong": wrong,
                "results": results
            }
        )

        return jsonify({
            "results": results
        })

    except Exception as e:
        print(f"[ERROR] Quiz run failed: {e}")

        return jsonify({
            "error": "Quiz run failed",
            "details": str(e)
        }), 500


# =============================================================
@pdf.route("/qa", methods=["POST"])
def qa():
    data = request.get_json(force=True)

    filename = data.get("filename")
    question = data.get("question")

    print(f"\n[QA] filename={filename} question={question}")

    if not question:
        return jsonify({
            "error": "No question provided"
        }), 400

    path, err = _get_path(filename)

    if err:
        return err

    try:
        store = _get_or_build_rag(filename, path)

        answer = _ai.answer_question(store, question)

        speak(answer)

        save_pdf_session(
            session_type="qa",
            filename=filename,
            data={
                "question": question,
                "answer": answer
            }
        )

        return jsonify({
            "answer": answer
        })

    except Exception as e:
        print(f"[ERROR] QA failed: {e}")

        return jsonify({
            "error": "QA failed",
            "details": str(e)
        }), 500


# =============================================================
@pdf.route("/teachback", methods=["POST"])
def teachback():
    data = request.get_json(force=True)

    filename = data.get("filename")
    explanation = data.get("explanation")

    print(f"\n[TEACHBACK] filename={filename}")

    if not explanation:
        return jsonify({
            "error": "No explanation provided"
        }), 400

    path, err = _get_path(filename)

    if err:
        return err

    try:
        store = _get_or_build_rag(filename, path)

        feedback = _ai.answer_teachback(
            store,
            explanation
        )

        speak(feedback)

        save_pdf_session(
            session_type="teachback",
            filename=filename,
            data={
                "explanation": explanation,
                "feedback": feedback
            }
        )

        return jsonify({
            "feedback": feedback
        })

    except Exception as e:
        print(f"[ERROR] Teachback failed: {e}")

        return jsonify({
            "error": "Teachback failed",
            "details": str(e)
        }), 500


# =============================================================
@pdf.route("/qa/run", methods=["POST"])
def qa_run():
    data = request.get_json(force=True)

    filename = data.get("filename")

    path, err = _get_path(filename)

    if err:
        return err

    try:
        store = _get_or_build_rag(filename, path)

        _ai.speak_random(READY_RESPONSES)

        question = listen(timeout=90.0)

        if not question:
            speak("Hmm I did not hear anything. Try again!")

            return jsonify({
                "error": "No question heard"
            }), 400

        print(f"[QA] Heard question: '{question}'")

        answer = _ai.answer_question(store, question)

        speak(answer)

        save_pdf_session(
            session_type="qa_run",
            filename=filename,
            data={
                "question": question,
                "answer": answer
            }
        )

        return jsonify({
            "question": question,
            "answer": answer
        })

    except Exception as e:
        print(f"[ERROR] QA run failed: {e}")

        return jsonify({
            "error": "QA run failed",
            "details": str(e)
        }), 500


# =============================================================
@pdf.route("/teachback/run", methods=["POST"])
def teachback_run():
    data = request.get_json(force=True)

    filename = data.get("filename")

    path, err = _get_path(filename)

    if err:
        return err

    try:
        store = _get_or_build_rag(filename, path)

        speak(
            "Ooooh okay! Tell me everything you learned. I am listening!"
        )

        explanation = listen(timeout=90.0)

        if not explanation:
            speak("Hmm I did not hear anything. Try again!")

            return jsonify({
                "error": "No explanation heard"
            }), 400

        print(f"[TEACHBACK] Explanation: '{explanation[:80]}...'")

        feedback = _ai.answer_teachback(
            store,
            explanation
        )

        speak(feedback)

        save_pdf_session(
            session_type="teachback_run",
            filename=filename,
            data={
                "explanation": explanation,
                "feedback": feedback
            }
        )

        return jsonify({
            "explanation": explanation,
            "feedback": feedback
        })

    except Exception as e:
        print(f"[ERROR] Teachback run failed: {e}")

        return jsonify({
            "error": "Teachback run failed",
            "details": str(e)
        }), 500


# =============================================================
@pdf.route("/clear", methods=["POST"])
def clear_cache():
    data = request.get_json(force=True)

    filename = data.get("filename")

    if filename and filename in _rag_cache:
        del _rag_cache[filename]

        print(f"[RAG] Cache cleared for: {filename}")

    return jsonify({
        "status": "ok"
    })
