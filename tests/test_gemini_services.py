from pathlib import Path
from src.services.gemini_image import GeminiImageService
from src.services.queue_worker import GenerationJob, GenerationQueueWorker


def test_build_generation_prompt():
    service = GeminiImageService(api_key="mock_key")
    prompt = service.build_generation_prompt("Golden hour light, warm smiling expression")

    assert "REFERENCE 1 (FACE REFERENCE)" in prompt
    assert "REFERENCE 2 (BODY / FIGURE REFERENCE)" in prompt
    assert "REFERENCE 3 (POSE REFERENCE)" in prompt
    assert "REFERENCE 4 (OUTFIT / CLOTHING REFERENCE)" in prompt
    assert "REFERENCE 5 (BACKGROUND / SETTING REFERENCE)" in prompt
    assert "Golden hour light" in prompt


def test_queue_worker_basics():
    worker = GenerationQueueWorker()
    assert worker.get_queue_size() == 0

    job = GenerationJob(
        job_id="test-job-1",
        user_id=123,
        chat_id=456,
        session_id="session-789",
        face_path=Path("face.jpg"),
        body_path=Path("body.jpg"),
        pose_path=Path("pose.jpg"),
        outfit_path=Path("outfit.jpg"),
        background_path=Path("bg.jpg"),
    )
    worker.queue.put_nowait(job)
    assert worker.get_queue_size() == 1


def test_parse_gemini_error_daily_quota():
    from src.services.gemini_image import parse_gemini_error

    err_str = (
        "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your current quota... "
        "Please retry in 1h40m15.398178868s.', 'details': [{'@type': 'type.googleapis.com/google.rpc.QuotaFailure', "
        "'violations': [{'quotaMetric': 'generativelanguage.googleapis.com/generate_content_free_tier_requests', "
        "'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier'}]}, "
        "{'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '6015s'}]}}"
    )
    is_429, is_daily, retry_msg, retry_secs = parse_gemini_error(Exception(err_str))
    assert is_429 is True
    assert is_daily is True
    assert retry_msg == "1h40m15"
    assert retry_secs == 6015


def test_parse_gemini_error_rpm_rate_limit():
    from src.services.gemini_image import parse_gemini_error

    err_str = "429 RESOURCE_EXHAUSTED. Rate limit exceeded. retryDelay: '30s'"
    is_429, is_daily, retry_msg, retry_secs = parse_gemini_error(Exception(err_str))
    assert is_429 is True
    assert is_daily is False


def test_format_wait_time():
    from src.services.gemini_image import format_wait_time

    assert "1 год" in format_wait_time(6015)
    assert "45 сек" in format_wait_time(45)
    assert "~2h" in format_wait_time(None, "2h30m")


def test_key_rotation_and_exhaustion():
    from src.services.gemini_image import GeminiImageService

    service = GeminiImageService()
    service._custom_api_key = None
    # Test active keys filtering
    service._exhausted_keys["exhausted_key"] = 9999999999.0
    active = service.get_active_keys()
    assert "exhausted_key" not in active

