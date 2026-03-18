import json
import os
import queue
from datetime import datetime

import requests
from flask import Flask, Response, jsonify, render_template, request
from flask_cors import CORS

app = Flask(__name__, template_folder='templates')
CORS(app, origins="*")

qa_store = []
sse_queues = []

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"


def improve_answers_with_gemini(page_text, raw_results, url):
    if not GEMINI_API_KEY:
        return raw_results

    questions = [r['question'] for r in raw_results]
    questions_text = "\n".join([f"{i+1}. {q}" for i, q in enumerate(questions)])

    prompt = f"""You are a knowledgeable assistant helping answer questions found on a screen.

Page URL: {url}

Screen content (what was visible on screen):
{page_text[:8000]}

Questions detected on screen:
{questions_text}

For each question:
- If it is a multiple choice question, identify the CORRECT answer from the options and explain briefly why.
- If it is a fill-in-the-blank or open question, provide the correct answer using your knowledge.
- If context from the screen helps, use it. Otherwise use your general knowledge.
- Keep answers short and direct (1-2 sentences max).
- Never say "I don't know" -- always give your best answer.

Respond ONLY with a JSON array in this exact format, no other text:
[
  {{"question": "exact question text", "answer": "your answer here"}}
]"""

    try:
        resp = requests.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=15
        )
        resp.raise_for_status()
        data = resp.json()
        text = data['candidates'][0]['content']['parts'][0]['text']
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        improved = json.loads(text.strip())
        return improved
    except Exception as e:
        print(f"Gemini error: {e}")
        return raw_results


@app.route('/receive_qa', methods=['POST'])
def receive_qa():
    if request.is_json:
        data = request.get_json()
        if data and 'results' in data and 'url' in data:
            raw_results = data['results']
            page_text = data.get('pageText', '')
            url = data['url']
if page_text and GEMINI_API_KEY:
                improved_results = improve_answers_with_gemini(page_text, raw_results, url)
            else:
                improved_results = raw_results

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            new_entry = {
                "timestamp": timestamp,
                "url": url,
                "results": improved_results
            }
            qa_store.insert(0, new_entry)

            for q in list(sse_queues):
                try:
                    q.put(new_entry)
                except Exception:
                    pass

            return jsonify({"status": "success"}), 200
    return jsonify({"status": "error"}), 400


@app.route('/clear', methods=['GET', 'POST'])
def clear_qa_store():
    global qa_store
    qa_store = []
    for q in list(sse_queues):
        try:
            q.put({"type": "clear"})
        except Exception:
            pass
    return jsonify({"status": "success"}), 200


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/stream')
def stream():
    client_queue = queue.Queue()
    sse_queues.append(client_queue)

    def generate():
        for entry in qa_store:
            yield f"data: {json.dumps(entry)}\n\n"
        while True:
            try:
                new_qa = client_queue.get(timeout=25)
                yield f"data: {json.dumps(new_qa)}\n\n"
            except queue.Empty:
                yield ": ping\n\n"
            except GeneratorExit:
                if client_queue in sse_queues:
                    sse_queues.remove(client_queue)
                break
            except Exception:
                if client_queue in sse_queues:
                    sse_queues.remove(client_queue)
                break

    return Response(generate(), mimetype='text/event-stream')


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)),
            debug=False, use_reloader=False)
