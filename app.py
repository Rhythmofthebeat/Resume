from website import create_app
from flask import Flask, render_template, request, jsonify, current_app, Response, redirect, url_for
import openai
from PyPDF2 import PdfReader
from docx import Document
import io
import re
import os
import logging
from collections import Counter
from werkzeug.utils import secure_filename
from file_processor import extract_text_from_pdf
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from openai._exceptions import RateLimitError, AuthenticationError, APIConnectionError
from config import Config
from flask_cors import CORS
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import fitz # PyMuPDF
from PIL import Image
import pytesseract
from flask import send_from_directory
import uuid
from dotenv import load_dotenv
from flask_login import login_required, current_user

# Load env & config
load_dotenv(override=False)
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = Config.GOOGLE_APPLICATION_CREDENTIALS

# App setup
app = create_app()
app.config.from_object(Config)
CORS(app)

# Logging (must come before any function that uses logger)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# OpenAI
openai.api_key = Config.OPENAI_API_KEY

# Helper functions

def extract_pdf_text(file_stream):
    reader = PdfReader(file_stream)
    text = ""
    for page in reader.pages:
        text += page.extract_text() or ""
    return text

def extract_docx_text(file_stream):
    try:
        file_stream.seek(0)
        document = Document(file_stream)
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
Given the following job description and resume, rate how well the resume matches the job description.

Job Description:
{job_description}

Resume:
{resume}

Respond EXACTLY in this format (no asterisks, no markdown bold):

Score: <number 0-100> (<Poor / Fair / Good / Excellent>)

Explanation:

What the resume MATCHES (prefix each bullet with +):
+ <specific match>
+ <specific match>

What the resume is MISSING or does not match (prefix each bullet with -):
- <specific gap>
- <specific gap>

Education:
+ or - <education match/gap>

Skills / Technical:
+ or - <skill match or gap>

Experience / Internships:
+ or - <experience match or gap>

Project Links (list ALL links found in the resume, no duplicates):
<link>

Rules:
- Use + at the start of every line that is a STRENGTH or MATCH
- Use - at the start of every line that is a GAP or MISSING requirement
- Remove all asterisks
- Be specific -- mention exact skills, tools, and requirements from the job description
"""
    response = openai.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    retry=(
        retry_if_exception_type(RateLimitError)
        | retry_if_exception_type(APIConnectionError)
    ),
)
def generate_summary(text):
    """Generate AI resume summary with retry logic."""
    try:
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You're a professional resume analyst. Create a 9-11 sentence summary "
                        "focusing on skills, experience, education, and other notable mentions. "
                        "Highlight KEY details and technical experience specifically. Be concise."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Summarize this resume:\n\n{text[:Config.MAX_TEXT_LENGTH]}",
                },
            ],
            max_tokens=600,
            timeout=Config.OPENAI_TIMEOUT,
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"OpenAI API error: {str(e)}")
        raise

def generate_basic_analysis(text):
    """Fallback analysis when AI is unavailable."""
    try:
        words = [w for w in text.split() if len(w) > 3]
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

# ==============================================================================
# Routes
# ==============================================================================

@app.route('/', methods=['GET', 'POST'])
def index():
    """Resume job-match page."""
    result = None
    score_value = 0
    cleaned_result = None
    job_text = ''

    if request.method == 'POST':
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        job_text = request.form.get('job_req', '')
        resume_file = request.files.get('resume')

        if not job_text.strip() or not resume_file:
            return render_template('resumemat.html', result=None, score_value=0, job_text=job_text)

        resume_bytes = resume_file.read()
        resume_file.stream.seek(0)
        resume_text = extract_text_from_file(resume_file.filename, resume_bytes)

        if not resume_text.strip():
            logger.error("Extracted resume text is empty")
            return render_template(
                'resumemat.html',
                result="Resume content could not be read. Please upload a readable PDF, DOCX, or TXT file.",
                score_value=0,
                job_text=job_text,
            )

        result = compare_resume_to_job(job_text, resume_text)

        with open("resumemat.txt", "w", encoding="utf-8") as f:
            f.write(result)

        for num in re.findall(r"\b(\d{1,3})\b", result):
            val = int(num)
            if 0 <= val <= 100:
                score_value = val
                break

        cleaned_result = result.replace('*', '')
        return render_template('resumemat.html', result=cleaned_result, score_value=score_value, job_text=job_text)

    return render_template('resumemat.html', result=None, score_value=0, job_text='')

@app.route("/resume-summarizer")
def resumesum():
    return render_template("resumesum.html")

@app.route("/resume-jobmatch")
def resumemat():
    return render_template("resumemat.html")

@app.route("/uploads", methods=["POST"])
@login_required
def upload_resume():
    """Handle resume uploads for the summariser page."""
    logger.info("Upload endpoint hit")

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "Empty filename"}), 400

    filename = secure_filename(file.filename)
    ext = filename.lower()
    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)

    try:
        file.save(filepath)
        with open(filepath, "rb") as f:
            file_stream = io.BytesIO(f.read())

        if ext.endswith(".pdf"):
            text = extract_pdf_text(file_stream)
        elif ext.endswith(".docx"):
            text = extract_docx_text(file_stream)
        elif ext.endswith(".txt"):
            text = file_stream.getvalue().decode("utf-8")
        elif ext.endswith((".png", ".jpg", ".jpeg", ".bmp", ".tiff")):
            text = pytesseract.image_to_string(Image.open(file_stream))
        else:
            return jsonify({"error": "Unsupported file type"}), 400

        if not text.strip():
            return jsonify({"status": "partial", "error": "File appears empty or unreadable",
                            **generate_basic_analysis(text)}), 200

        logger.info(f"Extracted {len(text)} characters")

        try:
            text_summary = generate_summary(text)
            return jsonify({"status": "success", "text_summary": text_summary, "analysis_type": "AI"})
        except RateLimitError:
            return jsonify({"status": "rate_limited", "error": "api_rate_limited",
                            "retry_after": 60, "analysis_type": "basic",
                            **generate_basic_analysis(text)}), 429
        except AuthenticationError:
            return jsonify({"status": "error", "error": "api_authentication_failed",
                            "analysis_type": "basic", **generate_basic_analysis(text)}), 500
        except Exception as e:
            logger.error(f"OpenAI API failed: {str(e)}")
            return jsonify({"status": "partial", "error": "AI analysis unavailable",
                            "analysis_type": "basic", **generate_basic_analysis(text)}), 200

    except Exception as e:
        logger.error(f"Unexpected error in /upload: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500

    finally:
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception as e:
                logger.error(f"Failed to delete temp file: {str(e)}")

@app.route("/resume-chat", methods=["POST"])
@login_required
def resume_chat():
    """Chat endpoint -- resume coaching powered by GPT-4o."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    user_message = data.get("message", "").strip()
    job_description = data.get("job_description", "").strip()
    resume_analysis = data.get("resume_analysis", "").strip()
    history = data.get("history", [])

    if not user_message:
        return jsonify({"error": "No message provided"}), 400

    context_block = ""
    if job_description:
        context_block += f"\n=== JOB DESCRIPTION ===\n{job_description[:2000]}\n"
    if resume_analysis:
        context_block += f"\n=== MATCH ANALYSIS ===\n{resume_analysis[:2000]}\n"

    system_prompt = (
        "You are an expert career coach and resume advisor. "
        "Help the user improve their resume in any way they ask -- "
        "fixing sections, adding skills, rewriting bullet points, "
        "improving formatting, addressing gaps, or general best practices."
        + (f"\n\nYou have the following context:\n{context_block}" if context_block else "")
        + "\n\nGuidelines:\n"
        "- Answer ANY question about resume improvement.\n"
        "- Give concrete, specific suggestions with examples.\n"
        "- Be honest about weaknesses and encouraging about strengths.\n"
        "- Keep responses focused and easy to act on.\n"
        "- Politely redirect anything unrelated to resumes or careers."
    )

    messages = [{"role": "system", "content": system_prompt}]
    for msg in history[-20:]:
        if msg.get("role") in ("user", "assistant") and msg.get("content"):
            messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_message})

    try:
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            max_tokens=800,
            temperature=0.7,
        )
        return jsonify({"reply": response.choices[0].message.content.strip()})
    except Exception as e:
        logger.error(f"Resume chat API error: {str(e)}")
        return jsonify({"error": "Failed to get a response. Please try again."}), 500

@app.route("/speak", methods=["POST"])
@login_required
def speak_summary():
    from google.cloud import texttospeech
    data = request.get_json()
    summary_text = data.get("text", "").strip()

    if not summary_text:
        return jsonify({"error": "No summary text provided"}), 400

    try:
        audio_folder = os.path.join(current_app.root_path, "website", "audio")
        os.makedirs(audio_folder, exist_ok=True)
        filename = f"{uuid.uuid4()}.mp3"
        filepath = os.path.join(audio_folder, filename)

        tts_client = texttospeech.TextToSpeechClient()
        input_text = texttospeech.SynthesisInput(text=summary_text)
        voice_name = data.get("voice", "en-US-Wavenet-D")
        voice = texttospeech.VoiceSelectionParams(
            language_code="en-US",
            name=voice_name,
            ssml_gender=texttospeech.SsmlVoiceGender.MALE,
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=float(data.get("speed", 1.2)),
        )
        tts_response = tts_client.synthesize_speech(
            input=input_text, voice=voice, audio_config=audio_config
        )
        with open(filepath, "wb") as out:
            out.write(tts_response.audio_content)

        return jsonify({"audio_url": f"/audio/{filename}"})
    except Exception as e:
        logger.error(f"Google TTS error: {str(e)}", exc_info=True)
        return jsonify({"error": "Audio generation failed"}), 500

@app.route("/audio/<filename>")
def serve_audio(filename):
    audio_folder = os.path.join(current_app.root_path, "website", "audio")
    return send_from_directory(audio_folder, filename)

@app.route("/export/summary-pdf", methods=["POST"])
@login_required
def export_summary_pdf():
    data = request.get_json()
    summary = (data or {}).get("summary", "").strip()
    if not summary:
        return "No summary provided", 400

    voice_names = ["Alex", "Rose", "Linda", "Tom"]
    lines = [l for l in summary.split("\n") if l.strip() not in voice_names]
    summary = "\n".join(lines).strip()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=LETTER)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("<b>Resume Summary</b>", styles["Title"]),
        Spacer(1, 12),
    ]
    for paragraph in summary.split("\n\n"):
        clean = paragraph.strip().replace("\n", "<br/>")
        if clean:
            story.append(Paragraph(clean, styles["Normal"]))
            story.append(Spacer(1, 6))

    doc.build(story)
    buffer.seek(0)
    return Response(
        buffer,
        mimetype="application/pdf",
        headers={"Content-Disposition": "attachment; filename=resume_summary.pdf"},
    )

@app.route("/health")
def health_check():
    return jsonify({
        "status": "healthy",
        "services": {
            "openai": "enabled" if Config.OPENAI_API_KEY else "disabled",
            "storage": {
                "upload_folder": os.path.exists(app.config["UPLOAD_FOLDER"]),
                "audio_folder": os.path.exists(app.config["AUDIO_FOLDER"]),
            },
        },
    })

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)
