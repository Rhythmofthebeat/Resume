from website import create_app
from flask import Flask, render_template, request, jsonify, abort, current_app
import openai
from PyPDF2 import PdfReader
from docx import Document
import io
import re
import os
import hashlib
import pickle
import markdown
from werkzeug.utils import secure_filename
from file_processor import extract_text_from_pdf
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from flask import Response, request

from openai._exceptions import RateLimitError, AuthenticationError, APIConnectionError

from config import Config
from flask_cors import CORS
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
import logging
from collections import Counter
import fitz  # PyMuPDF
from PIL import Image
import pytesseract

from flask import send_from_directory
import uuid
from dotenv import load_dotenv

app = create_app()

openai.api_key = Config.OPENAI_API_KEY
CACHE_DIR = "cache_results"

def generate_hash(job_desc_text: str, resume_bytes: bytes) -> str:
    hasher = hashlib.sha256()
    hasher.update(job_desc_text.encode('utf-8'))
    hasher.update(resume_bytes)
    return hasher.hexdigest()

def get_cached_result(hash_key):
    filepath = os.path.join(CACHE_DIR, f"{hash_key}.pkl")
    if os.path.exists(filepath):
        with open(filepath, "rb") as f:
            return pickle.load(f)
    return None

def save_cached_result(hash_key, result_data):
    os.makedirs(CACHE_DIR, exist_ok=True)
    filepath = os.path.join(CACHE_DIR, f"{hash_key}.pkl")
    with open(filepath, "wb") as f:
        pickle.dump(result_data, f)


def extract_pdf_text(file_stream):
    reader = PdfReader(file_stream)
    text = ""
    for page in reader.pages:
        text += page.extract_text() or ""
    return text

def extract_docx_text(file_stream):
    try:
        file_stream.seek(0)
        document = Document(file_stream)  # <- DO NOT wrap in BytesIO again
        text = "\n".join(para.text for para in document.paragraphs if para.text.strip())
        return text if text.strip() else "No text found in DOCX file."
    except Exception as e:
        logger.error(f"Error reading DOCX: {e}", exc_info=True)
        return f"Error reading DOCX: {str(e)}"


def extract_text_from_file(filename: str, resume_bytes: bytes):
    file_stream = io.BytesIO(resume_bytes)

    if filename.endswith('.pdf'):
        return extract_pdf_text(file_stream)
    elif filename.endswith('.docx'):
        return extract_docx_text(file_stream)
    elif filename.endswith('.txt'):
        return file_stream.getvalue().decode('utf-8')
    return ""
def compare_resume_to_job(job_description, resume):
    prompt = f"""
Given the following job description and resume, rate how well the resume matches the job description. Provide a score out of 100 and a short explanation.

Job Description:
{job_description}

Resume:
{resume}


Respond with:
Score: (number and write word based on number)
            0-30: Poor
            31-60: Fair
            61-80: Good 
            81-100: Excellent
score can be from 0-100
Explanation: 
(remove all asteriks)
    -What key job requirments the resume matches
    -What key job requirments the resume does not match
    -Education(High school, College, Degrees)
    -Skillset/Technical Skills
    -Experience/Internships
    -Links of projects (provide the ALL links in the resume and DO NOT repeat the SAME links)
(your reasoning by mentioning ALL specific parts of the resume that goes along with the job description. Show picture and highlight the places)
"""
    response = openai.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content

@app.route('/', methods=['GET', 'POST'])
def index():
    result = None
    score_value = 0 #so score is always defined

    if request.method == 'POST':
        job_text = request.form.get('job_req')
        resume_file = request.files.get('resume')
        
        

        if not job_text.strip() or not resume_file:
            return render_template('resumemat.html', result=None, score_value=0,  job_text=job_text)

        resume_bytes = resume_file.read()
        resume_file.stream.seek(0)  # Reset stream for further processing
        

        # Generate cache key from job text + resume bytes
        #hash_key = generate_hash(job_text, resume_bytes)

        # Try loading cached result
        # cached = get_cached_result(hash_key)
        #if cached:
            #return render_template('resumemat.html', result=cached["result"], score_value=cached["score"],  job_text=job_text)

        # Call GPT if not cached
        resume_text = extract_text_from_file(resume_file.filename, resume_bytes)


        result = compare_resume_to_job(job_text, resume_text)
        if not resume_text.strip():
            logger.error("Extracted resume text is empty")
            return render_template(
        'resumemat.html',
        result="Resume content could not be read. Please upload a readable DOCX/PDF/TXT file.",
        score_value=0,
        job_text=job_text,
    )


        # Optionally, save result to a file
        with open("resumemat.txt", "w", encoding="utf-8") as f:
            f.write(result)
        numbers = re.findall(r"\b(\d{1,3})\b", result)
        for num in numbers:
            val = int(num)
            if 0 <= val <= 100:
                score_value = val
                break
            else:
                score_value = 0
        cleaned_result = result.replace('*', '')
        #save_cached_result(hash_key, {"result": cleaned_result, "score": score_value,})

    return render_template('resumemat.html', result=cleaned_result, score_value = score_value, job_text=job_text)


# Initialize Flask app

app.config.from_object(Config)
CORS(app)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)



# Retry configuration for OpenAI API calls
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    retry=(
        retry_if_exception_type(RateLimitError)
        | retry_if_exception_type(APIConnectionError)
    ),
)
def generate_summary(text):
    """Generate text summary with retry logic"""
    try:
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system",
                    "content": "You're a professional resume analyst. Create a 8-9 sentence summary focusing on skills, experience, education, and other notable mentions. This should be specifics and highlight KEY details",
                },
                {
                    "role": "user",
                    "content": f"Summarize this resume:\n\n{text[:Config.MAX_TEXT_LENGTH]}",
                },
            ],
            max_tokens=900,
            timeout=Config.OPENAI_TIMEOUT,
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"OpenAI API error: {str(e)}")
        raise


def generate_basic_analysis(text):
    """Generate basic analysis when AI fails"""
    try:
        words = [w for w in text.split() if len(w) > 3]  # Ignore short words
        word_counts = Counter(words)
        top_terms = [w[0] for w in word_counts.most_common(5)]

        return {
            "analysis": "Basic Text Analysis",
            "word_count": len(words),
            "top_terms": top_terms,
            "estimated_experience": "Junior" if len(words) < 300 else "Senior",
        }
    except Exception as e:
        logger.error(f"Basic analysis failed: {str(e)}")
        return {"error": "Could not generate basic analysis"}


@app.route("/")
def home():
    """Serve the frontend"""
    return render_template("home.html")
@app.route("/resume-summarizer")
def resumesum():
    """Serve the frontend"""
    return render_template("resumesum.html")
@app.route("/resume-jobmatch")
def resumemat():
    """Serve the frontend"""
    return render_template("resumemat.html")


@app.route("/upload", methods=["POST"])
def upload_resume():
    """Handle resume uploads with robust DOCX & PDF support"""
    logger.info("Upload endpoint hit")

    if "file" not in request.files:
        logger.error("No file part in request")
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]

    if file.filename == "":
        logger.error("Empty filename received")
        return jsonify({"error": "Empty filename"}), 400

    filename = secure_filename(file.filename)
    ext = filename.lower()
    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)

    # Save the uploaded file temporarily
    try:
        file.save(filepath)
        logger.info(f"File saved to {filepath}")

        with open(filepath, "rb") as f:
            file_stream = io.BytesIO(f.read())

        if ext.endswith(".pdf"):
            logger.info("Extracting text from PDF")
            text = extract_pdf_text(file_stream)
        elif ext.endswith(".docx"):
            logger.info("Extracting text from DOCX")
            text = extract_docx_text(file_stream)
        elif ext.endswith(".txt"):
            logger.info("Extracting text from TXT")
            text = file_stream.getvalue().decode("utf-8")
        elif ext.endswith((".png", ".jpg", ".jpeg", ".bmp", ".tiff")):
            logger.info("Extracting text from image using OCR")
            image = Image.open(file_stream)
            text = pytesseract.image_to_string(image)
        else:
            logger.warning(f"Unsupported file type: {ext}")
            return jsonify({"error": "Unsupported file type"}), 400

        if not text.strip():
            logger.warning("Extracted text is empty or unreadable")
            return (
                jsonify(
                    {
                        "status": "partial",
                        "error": "File appears to be empty or image-based with unreadable text",
                        **generate_basic_analysis(text),
                    }
                ),
                200,
            )

        logger.info(f"Extracted {len(text)} characters")

        # Generate AI summary
        try:
            text_summary = generate_summary(text)
            return jsonify(
                {
                    "status": "success",
                    "text_summary": text_summary,
                    "analysis_type": "AI",
                }
            )
        except Exception as e:
            logger.error(f"OpenAI API failed: {str(e)}")
            return (
                jsonify(
                    {
                        "status": "partial",
                        "error": "AI analysis unavailable",
                        "analysis_type": "basic",
                        **generate_basic_analysis(text),
                    }
                ),
                200,
            )

    except Exception as e:
        logger.error(f"Unexpected error in /upload: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500

    finally:
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
                logger.info("Temporary file removed")
            except Exception as e:
                logger.error(f"Failed to delete temp file: {str(e)}")


   #Resume Summary
load_dotenv()

from config import Config
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = Config.GOOGLE_APPLICATION_CREDENTIALS





# Retry configuration for OpenAI API calls
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    retry=(
        retry_if_exception_type(RateLimitError)
        | retry_if_exception_type(APIConnectionError)
    ),
)
def generate_summary(text):
    """Generate text summary with retry logic"""
    try:
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system",
                    "content": "You're a professional resume analyst. Create a concise 3-5 sentence summary focusing on skills, experience, and education.",
                },
                {
                    "role": "user",
                    "content": f"Summarize this resume:\n\n{text[:Config.MAX_TEXT_LENGTH]}",
                },
            ],
            max_tokens=200,
            timeout=Config.OPENAI_TIMEOUT,
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"OpenAI API error: {str(e)}")
        raise


def generate_basic_analysis(text):
    """Generate basic analysis when AI fails"""
    try:
        words = [w for w in text.split() if len(w) > 3]  # Ignore short words
        word_counts = Counter(words)
        top_terms = [w[0] for w in word_counts.most_common(5)]

        return {
            "analysis": "Basic Text Analysis",
            "word_count": len(words),
            "top_terms": top_terms,
            "estimated_experience": "Junior" if len(words) < 300 else "Senior",
        }
    except Exception as e:
        logger.error(f"Basic analysis failed: {str(e)}")
        return {"error": "Could not generate basic analysis"}



@app.route("/uploads", methods=["POST"])
def uploads_resume():
    """Handle resume uploads with enhanced error handling"""
    logger.info("Upload endpoint hit")

    # Validate file exists
    if "file" not in request.files:
        logger.error("No file part in request")
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]

    # Validate filename
    if file.filename == "":
        logger.error("Empty filename received")
        return jsonify({"error": "Empty filename"}), 400

   
    # Validate file size
    if file.content_length > Config.MAX_FILE_SIZE:
        logger.error(f"File too large: {file.content_length} bytes")
        return (
            jsonify(
                {
                    "error": f"File size exceeds {Config.MAX_FILE_SIZE//(1024*1024)}MB limit"
                }
            ),
            400,
        )

    try:
        # Save the file temporarily
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(filepath)
        logger.info(f"File saved temporarily to: {filepath}")

        # Text Extraction
        ext = filename.lower()
        if ext.endswith(".pdf"):
            logger.info("Extracting text from PDF")
            text = extract_text_from_pdf(filepath)
        elif ext.endswith(".docx"):
            logger.info("Extracting text from Docx")
            with open(filepath, "rb") as docx_file:
                text = extract_docx_text(docx_file)

        elif ext.endswith((".png", ".jpg", ".jpeg", ".bmp", ".tiff")):
            logger.info("Extracting text from image using OCR")
            image = Image.open(filepath)
            text = pytesseract.image_to_string(image)

        else:
            logger.warning(f"Unsupported file type: {ext}")
            return jsonify({"error": "Unsupported file type"}), 400

        if not text.strip():
            logger.warning("Extracted text is empty or unreadable")
            return (
                jsonify(
                    {
                        "status": "partial",
                        "error": "File appears to be empty or image-based with unreadable text",
                        **generate_basic_analysis(text),
                    }
            ),
            200,
        )

            logger.info(f"Extracted {len(text)} characters")

           

        # Generation AI
        try:
            logger.info("Generating AI summary")
            text_summary = generate_summary(text)
            logger.info("Successfully generated summary")
            return jsonify(
                {
                    "status": "success",
                    "text_summary": text_summary,
                    "analysis_type": "AI",
                }
            )

        except RateLimitError as e:
            logger.warning(f"Rate limited: {str(e)}")
            return (
                jsonify(
                    {
                        "status": "rate_limited",
                        "error": "api_rate_limited",
                        "message": "Please wait before trying again",
                        "retry_after": 60,
                        "analysis_type": "basic",
                        **generate_basic_analysis(text),
                    }
                ),
                429,
            )

        except AuthenticationError as e:
            logger.error(f"Authentication failed: {str(e)}")
            return (
                jsonify(
                    {
                        "status": "error",
                        "error": "api_authentication_failed",
                        "message": "Invalid API configuration",
                        "analysis_type": "basic",
                        **generate_basic_analysis(text),
                    }
                ),
                500,
            )

        except Exception as e:
            logger.error(f"OpenAI API failed: {str(e)}")
            return (
                jsonify(
                    {
                        "status": "partial",
                        "error": "api_failed",
                        "message": "AI analysis unavailable",
                        "analysis_type": "basic",
                        **generate_basic_analysis(text),
                    }
                ),
                200,
            )

    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        return (
            jsonify(
                {
                    "status": "error",
                    "error": "server_error",
                    "message": "Internal server error",
                }
            ),
            500,
        )

    finally:
        # Clean up temporary file
        if "filepath" in locals() and os.path.exists(filepath):
            try:
                os.remove(filepath)
                logger.info("Temporary file removed")
            except Exception as e:
                logger.error(f"Failed to remove temporary file: {str(e)}")

   




@app.route("/health")
def health_check():
    """Health check endpoint"""
    return jsonify(
        {
            "status": "healthy",
            "services": {
                "openai": "enabled" if Config.OPENAI_API_KEY else "disabled",
                "storage": {
                    "upload_folder": os.path.exists(app.config["UPLOAD_FOLDER"]),
                    "audio_folder": os.path.exists(app.config["AUDIO_FOLDER"]),
                },
            },
        }
    )


@app.route("/test/pdf")
def test_pdf():
    """Test PDF processing"""
    try:
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 50), "Test PDF content")
        text = page.get_text()
        doc.close()
        return jsonify(
            {
                "status": "success",
                "text": text,
                "analysis": generate_basic_analysis(text),
            }
        )
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/test/openai")
def test_openai():
    """Test OpenAI API connectivity"""
    models_to_test = ["gpt-3.5-turbo", "gpt-4-turbo-preview"]
    results = {}

    for model in models_to_test:
        try:
            test_response = openai.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Say 'hello'"}],
                max_tokens=5,
                timeout=10,
            )
            results[model] = {
                "status": "success",
                "response": test_response.choices[0].message.content,
            }
        except Exception as e:
            results[model] = {"status": "error", "error": str(e)}

    return jsonify(results)

from google.cloud import texttospeech

@app.route("/speak", methods=["POST"])
def speak_summary():
    data = request.get_json()
    summary_text = data.get("text", "").strip()

    if not summary_text:
        logger.error("No summary text provided in /speak request")
        return jsonify({"error": "No summary text provided"}), 400

    try:
        audio_folder = os.path.join(current_app.root_path, "website", "audio")
        os.makedirs(audio_folder, exist_ok=True)
        filename = f"{uuid.uuid4()}.mp3"
        filepath = os.path.join(audio_folder, filename)

  
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.join("secrets", "dazzling-alpha-465307-a7-2417261faf21.json")




        # Google TTS client
        tts_client = texttospeech.TextToSpeechClient()
        print("Google TTS client initialized successfully.")

        input_text = texttospeech.SynthesisInput(text=summary_text)

        voice_name = data.get("voice", "en-US-Wavenet-D")

        voice = texttospeech.VoiceSelectionParams(
            language_code="en-US",
            name=voice_name, 
            ssml_gender=texttospeech.SsmlVoiceGender.MALE,
        )
        speed = float(data.get("speed", 1.2))
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=speed
        )

        logger.info(f"Sending text to Google TTS API: {summary_text[:50]}...")

        response = tts_client.synthesize_speech(
            input=input_text, voice=voice, audio_config=audio_config
        )

        with open(filepath, "wb") as out:
            out.write(response.audio_content)

        logger.info(f"Audio successfully saved to {filepath}")
        return jsonify({"audio_url": f"/audio/{filename}"})

        
    except Exception as e:
        logger.error(f"Google TTS error: {str(e)}", exc_info=True)
        return jsonify({"error": "Audio generation failed"}), 500
    
@app.route("/audio/<filename>")
def serve_audio(filename):
        audio_folder = os.path.join(current_app.root_path,  "website", "audio")
        return send_from_directory(audio_folder, filename)





    #debug=os.getenv("FLASK_DEBUG", "False").lower() == "true"

#Export PDF Summary
# PDF generation (ReportLab)

@app.route("/export/summary-pdf", methods=["POST"])
def export_summary_pdf():
    data = request.get_json()
    if not data:
        return "No data received", 400

    summary = data.get("summary", "").strip()
    if not summary:
        return "No summary provided", 400

   
    voice_names = ["Alex", "Rose", "Linda", "Tom"]
    lines = summary.split("\n")
    lines = [line for line in lines if line.strip() not in voice_names]
    summary = "\n".join(lines).strip()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=LETTER)
    styles = getSampleStyleSheet()

    story = []
    story.append(Paragraph("<b>Resume Summary</b>", styles["Title"]))
    story.append(Spacer(1, 12))

    for paragraph in summary.split("\n\n"):
        clean_paragraph = paragraph.strip().replace("\n", "<br/>")
        if clean_paragraph:
            story.append(Paragraph(clean_paragraph, styles["Normal"]))
            story.append(Spacer(1, 6))

    doc.build(story)
    buffer.seek(0)

    return Response(
        buffer,
        mimetype="application/pdf",
        headers={"Content-Disposition": "attachment; filename=resume_summary.pdf"},
    )



if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
    
