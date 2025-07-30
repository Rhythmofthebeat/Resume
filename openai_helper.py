Course Hero logo
Search and extract from study contents
Make the most of your study experience


Login or sign up


from openai import OpenAI, RateLimitError, APIConnectionError, AuthenticationError
from config import Config
import logging
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)
from collections import Counter

logger = logging.getLogger(__name__)


class OpenAIHelper:
    def __init__(self):
        self.client = OpenAI(
            api_key=Config.OPENAI_API_KEY, timeout=Config.OPENAI_TIMEOUT
        )
        self.model = Config.OPENAI_MODEL
        self.system_prompt = Config.SYSTEM_PROMPT.strip()
        self.max_text_length = Config.MAX_TEXT_LENGTH

    @retry(
        stop=stop_after_attempt(Config.OPENAI_RETRY_ATTEMPTS),
        wait=wait_exponential(
            multiplier=1,
            min=Config.OPENAI_RETRY_DELAY,
            max=Config.OPENAI_RETRY_DELAY * 3,
        ),
        retry=(
            retry_if_exception_type(RateLimitError)
            | retry_if_exception_type(APIConnectionError)
        ),
        reraise=True,
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def _call_openai_api(self, text):
        """Internal method to call OpenAI API with retry logic"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {
                        "role": "user",
                        "content": f"Analyze this resume:\n\n{text[:self.max_text_length]}",
                    },
                ],
                max_tokens=300,
                temperature=0.2,
                timeout=Config.OPENAI_TIMEOUT,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"OpenAI API call failed: {str(e)}")
            raise

    def generate_summary(self, text):
        """
        Generate AI summary with fallback to local analysis
        Returns: dict {
            'status': 'success'|'partial'|'error',
            'content': str|dict,
            'analysis_type': 'ai'|'basic',
            'error': str|None,
            'message': str|None
        }
        """
        if not text or not isinstance(text, str):
            return self._create_response(
                content=None,
                status="error",
                message="Invalid input text",
                analysis_type="error",
                error="input_error",
            )

        clean_text = " ".join(text.strip().split())
        if len(clean_text) < 50:
            return self._basic_analysis_response(clean_text)

        try:
            ai_summary = self._call_openai_api(clean_text)
            return self._create_response(
                content=ai_summary,
                status="success",
                message=None,
                analysis_type="ai",
                error=None,
            )
        except RateLimitError:
            logger.warning("Rate limit exceeded")
            return self._basic_analysis_response(clean_text, "rate_limit")
        except AuthenticationError:
            logger.error("Authentication failed")
            return self._create_response(
                content=None,
                status="error",
                message="API authentication failed",
                analysis_type="error",
                error="auth_error",
            )
        except APIConnectionError:
            logger.warning("Connection error")
            return self._basic_analysis_response(clean_text, "connection_error")
        except Exception as e:
            error_type = "quota_exceeded" if "quota" in str(e).lower() else "api_error"
            logger.error(f"API error: {error_type}")
            return self._basic_analysis_response(clean_text, error_type)

    def _create_response(self, content, status, message, analysis_type, error=None):
        """Create standardized response dictionary"""
        return {
            "status": status,
            "content": content,
            "analysis_type": analysis_type,
            "error": error,
            "message": message,
        }

    def _basic_analysis_response(self, text, error_type=None):
        """Generate response with local analysis"""
        analysis = self._generate_local_analysis(text)
        status = "partial" if error_type != "auth_error" else "error"
        return self._create_response(
            content=analysis,
            status=status,
            message=(
                "Basic analysis completed" if status == "partial" else "Analysis failed"
            ),
            analysis_type="basic",
            error=error_type,
        )

    def _generate_local_analysis(self, text):
        """Generate comprehensive local analysis"""
        try:
            words = [w.lower() for w in text.split() if len(w) > 3 and w.isalpha()]
            word_counts = Counter(words)
            sentences = [s.strip() for s in text.split(".") if len(s.split()) > 3]

            return {
                "top_terms": [w[0] for w in word_counts.most_common(5)],
                "word_count": len(words),
                "sentence_count": len(sentences),
                "estimated_experience": "Senior" if len(words) > 500 else "Junior",
                "readability": self._calculate_readability(words, sentences),
            }
        except Exception as e:
            logger.error(f"Local analysis failed: {str(e)}")
            return {"error": "Failed to generate local analysis"}

    def _calculate_readability(self, words, sentences):
        """Calculate simple readability score"""
        if not sentences:
            return 50
        avg_sentence_length = len(words) / len(sentences)
        return max(10, min(100, int(100 - (avg_sentence_length / 2))))

    def _error_response(self, message, error_type):
        return {
            "status": "error",
            "content": message,
            "analysis_type": "basic",
            "error": error_type,
        }


# Singleton instance for easy import
openai_helper = OpenAIHelper()