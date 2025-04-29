import os
import re
import logging
import base64
import datetime
import json
import magic
import time
import zipfile
import io
import google.generativeai as genai
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from threading import Thread

# === Setup ===
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === Flask Setup ===
app = Flask(__name__)

# === Enable CORS (allowing Flutter app to access API) ===
CORS(app)

# === Gemini API Setup ===
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
model = genai.GenerativeModel("models/gemini-1.5-pro")

# === Global Progress Tracker ===
progress = 0

# === Parse JSON from Gemini Response ===
def parse_json(text):
    try:
        if "```json" in text:
            match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
        else:
            match = re.search(r"\{.*\}", text, re.DOTALL)

        if not match:
            logger.warning("No JSON found in Gemini response.")
            return None

        return json.loads(match.group(1 if "```json" in text else 0))
    except Exception as e:
        logger.error(f"JSON parsing failed: {str(e)}")
        return None

# === Simulate Progress for multiple file uploads ===
def simulate_progress():
    global progress
    for i in range(1, 101):
        progress = i
        time.sleep(0.02)  # 20ms sleep for progress simulation

# === Process Single Image ===
def process_image(image_data):
    mime_type = magic.from_buffer(image_data, mime=True)
    if not mime_type.startswith("image/"):
        logger.error("Invalid file format. Expected an image.")
        return None

    image_base64 = base64.b64encode(image_data).decode("utf-8")
    prompt = [
        """You are an invoice data extractor. Extract the following fields in JSON format:
        {"vendor": {"name": "", "company": ""}, "invoice_no": "", "date": "", "due_date": "", "vehicle_no": "",
        "bill_to": {"name": "", "company": ""}, "issued_to": {"name": "", "company": ""}, "items": [{"description": "", "unit_price": 0, "quantity": 0, "total": 0, "remark": ""}],
        "subtotal": 0, "tax_percent": 0, "total": 0}""",
        {"mime_type": mime_type, "data": image_base64}
    ]
    response = model.generate_content(prompt)
    data = parse_json(response.text)

    if data:
        data["timestamp"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Clean empty fields
        def clean_empty(d):
            if isinstance(d, dict):
                return {k: clean_empty(v) for k, v in d.items() if v not in ("", None, [], {}, 0)}
            elif isinstance(d, list):
                return [clean_empty(i) for i in d if i not in ("", None, [], {}, 0)]
            return d

        data = clean_empty(data)
    return data

# === API to Get Progress ===
@app.route('/progress', methods=['GET'])
def get_progress():
    return jsonify({"progress": progress})

# === Upload and Process Invoice Image(s) ===
@app.route('/upload', methods=['POST'])
def upload_image():
    global progress
    progress = 0

    try:
        files = request.files.getlist('image')
        if not files:
            logger.error("No files uploaded.")
            return jsonify({"error": "No files uploaded"}), 400

        results = []
        zip_mode = False

        # Start progress simulation in background
        progress_thread = Thread(target=simulate_progress)
        progress_thread.start()

        for file in files:
            filename = file.filename.lower()
            file_data = file.read()

            if filename.endswith('.zip'):
                zip_mode = True
                with zipfile.ZipFile(io.BytesIO(file_data)) as z:
                    for zip_info in z.infolist():
                        if zip_info.is_dir():
                            continue  # Skip folders
                        with z.open(zip_info) as image_file:
                            image_bytes = image_file.read()
                            result = process_image(image_bytes)
                            if result:
                                result["filename"] = zip_info.filename
                                results.append(result)
            else:
                result = process_image(file_data)
                if result:
                    result["filename"] = filename
                    results.append(result)

        progress_thread.join()

        if not results:
            logger.error("No valid images found to process.")
            return jsonify({"error": "No valid images found to process"}), 400

        logger.info(f"Extracted {len(results)} invoice(s)")
        return jsonify({"invoices": results})

    except Exception as e:
        logger.error(f"Invoice processing failed: {str(e)}")
        return jsonify({"error": f"Invoice processing failed: {str(e)}"}), 500
    

# === Run the Flask App ===
if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0", port=5000)


    
