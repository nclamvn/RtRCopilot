import hashlib


class IngestionFailure(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        retryable: bool = False,
        stage: str,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.stage = stage
        self.fingerprint = hashlib.sha256(
            f"{stage}:{code}".encode(),
        ).hexdigest()


SAFE_MESSAGES = {
    "authentication_required": "Authentication is required.",
    "forbidden": "You are not authorized to access this file.",
    "policy_denied": "You are not authorized to perform this action.",
    "not_found": "The requested file was not found.",
    "retry_not_allowed": "This upload cannot be retried in its current state.",
    "viewer_not_ready": "The secure preview is not ready.",
    "upload_too_large": "The file exceeds the configured size limit.",
    "content_length_mismatch": "The received file size did not match the request.",
    "checksum_mismatch": "The received file checksum did not match the request.",
    "filename_invalid": "The supplied filename is not valid.",
    "unknown_format": "The file format is not supported.",
    "declared_mime_mismatch": "The declared file type does not match its content.",
    "extension_mismatch": "The filename extension does not match its content.",
    "suspicious_polyglot": "The file contains conflicting format signatures.",
    "malformed_content": "The file structure is invalid.",
    "archive_path_unsafe": "The document package contains an unsafe path.",
    "archive_budget_exceeded": "The document package exceeds safety limits.",
    "archive_entry_unsupported": "The document package contains unsupported content.",
    "ooxml_active_content": "Active document content is not accepted.",
    "pdf_active_content": "Active PDF content is not accepted.",
    "image_budget_exceeded": "The image exceeds safety limits.",
    "media_budget_exceeded": "The media file exceeds safety limits.",
    "malware_detected": "The file did not pass the security scan.",
    "scanner_unavailable": "The security scan could not be completed.",
    "scanner_timeout": "The security scan timed out.",
    "scanner_response_invalid": "The security scan returned an invalid response.",
    "scanner_signatures_stale": "The security scanner signatures are stale.",
    "tool_timeout": "File processing exceeded the configured time limit.",
    "sandbox_unavailable": "The private processing sandbox is unavailable.",
    "ocr_unavailable": "Private text recognition is unavailable.",
    "ocr_language_unavailable": "The requested OCR language is unavailable.",
    "ocr_failed": "Private text recognition could not be completed.",
    "transcript_unavailable": "Private transcription is unavailable.",
    "transcript_model_unavailable": "The private transcription model is unavailable.",
    "transcript_model_invalid": "The private transcription model failed integrity validation.",
    "transcript_failed": "Private transcription could not be completed.",
    "processing_failed": "The file could not be processed safely.",
}


def safe_message(code: str) -> str:
    return SAFE_MESSAGES.get(code, SAFE_MESSAGES["processing_failed"])
