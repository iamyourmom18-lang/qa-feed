import json
import time
from datetime import datetime
from threading import Thread
import queue
import os

from flask_cors import CORS
from flask import Flask, request, jsonify, render_template, Response

# --- Flask Server Setup ---
app = Flask(__name__, template_folder='templates')
CORS(app, origins="*")

# This list holds all Q&A data received. It acts as our 'database'.
# In a real production app, this would be a persistent database.
# For this simple feed, it's in-memory.
qa_store = []

# Queue for Server-Sent Events (SSE) clients
sse_queues = []

@app.route('/receive_qa', methods=['POST'])
def receive_qa():
    """Endpoint for the browser extension to POST Q&A data."""
    if request.is_json:
        data = request.get_json()
        if data and 'results' in data and 'url' in data:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            new_entry = {"timestamp": timestamp, **data}
            qa_store.insert(0, new_entry) # Add to the beginning (newest first)

            # Notify all connected SSE clients
            for q in list(sse_queues): # Iterate over a copy to avoid issues if client disconnects
                try:
                    q.put(new_entry)
                except Exception:
                    # Handle disconnected clients gracefully
                    pass

            return jsonify({"status": "success", "message": "Q&A received"}), 200
    return jsonify({"status": "error", "message": "Request must be JSON and contain results/url"}), 400

@app.route('/clear', methods=['POST'])
def clear_qa_store():
    """Endpoint to clear all stored Q&A data."""
    global qa_store
    qa_store = []
    # Optionally, notify clients that store has been cleared
    for q in list(sse_queues):
        try:
            q.put({"type": "clear"})
        except Exception:
            pass
    return jsonify({"status": "success", "message": "Q&A store cleared"}), 200

@app.route('/')
def index():
    """Serves the main web page for displaying Q&A."""
    return render_template('index.html')

@app.route('/stream')
def stream():
    """Endpoint for Server-Sent Events (SSE) to push real-time updates."""
    client_queue = queue.Queue()
    sse_queues.append(client_queue)

    def generate():
        # First, send all existing data to the new client (newest first for UI)
        for entry in qa_store:
            yield f"data: {json.dumps(entry)}\n\n"
        
        # Then, keep sending new updates as they arrive
        while True:
            try:
                # Wait for new data, or send a ping to keep connection alive
                new_qa = client_queue.get(timeout=25) 
                yield f"data: {json.dumps(new_qa)}\n\n"
            except queue.Empty:
                yield ": ping\n\n"
            except GeneratorExit:
                # Client disconnected, remove from active queues
                if client_queue in sse_queues:
                    sse_queues.remove(client_queue)
                break
            except Exception as e:
                print(f"SSE error: {e}")
                if client_queue in sse_queues:
                    sse_queues.remove(client_queue)
                break

    return Response(generate(), mimetype='text/event-stream')


if __name__ == "__main__":
    # Ensure the templates directory exists for Flask to find index.html
    os.makedirs(os.path.join(os.path.dirname(__file__), 'templates'), exist_ok=True)

    print("\n--- Q&A Live Web Feed (Cloud-Ready) ---")
    print("  Flask server starting...")
    print("  This app is designed for deployment to a cloud platform.")
    print("  It will receive Q&A from your browser extension and serve it live to your phone.")
    print("  Access on your phone's browser at the deployed public URL.")
    print("  (e.g., https://your-app-name.onrender.com)")
    print("\n  Local testing: http://127.0.0.1:5000 (after `pip install flask` and `python app.py`)")
    print("  Waiting for Q&A from browser extension...")

    # Listen on all public IPs (0.0.0.0) in a cloud environment
    app.run(host='0.0.0.0', port=os.environ.get('PORT', 5000), debug=False, use_reloader=False)
