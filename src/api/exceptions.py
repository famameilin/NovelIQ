from __future__ import annotations


class NovelNotFoundError(Exception):
    def __init__(self, novel_id: str | None = None, message: str | None = None):
        self.novel_id = novel_id
        self.message = message or (f"Novel not found: {novel_id}" if novel_id else "Novel not found")
        super().__init__(self.message)


class InvalidFileError(Exception):
    def __init__(self, filename: str | None = None, message: str | None = None):
        self.filename = filename
        self.message = message or (f"Invalid file: {filename}" if filename else "Invalid file")
        super().__init__(self.message)


class AnalysisNotCompleteError(Exception):
    def __init__(
        self,
        novel_id: str | None = None,
        message: str | None = None,
        run_status: str | None = None,
    ):
        self.novel_id = novel_id
        self.run_status = run_status
        self.message = message or (
            f"Analysis not complete for novel: {novel_id}" if novel_id else "Analysis not complete"
        )
        super().__init__(self.message)


class AnalysisError(Exception):
    def __init__(self, novel_id: str | None = None, message: str | None = None):
        self.novel_id = novel_id
        self.message = message or (
            f"Analysis error for novel: {novel_id}" if novel_id else "Analysis error"
        )
        super().__init__(self.message)


class FileStorageError(Exception):
    def __init__(self, filename: str | None = None, message: str | None = None):
        self.filename = filename
        self.message = message or (
            f"File storage error: {filename}" if filename else "File storage error"
        )
        super().__init__(self.message)


class GraphReadinessError(RuntimeError):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class DiagnosisRerunRequiredError(RuntimeError):
    def __init__(self, reason: str | None = None, message: str | None = None):
        self.reason = reason or "focus_contract_incomplete"
        self.message = message or "Diagnosis rerun required"
        super().__init__(self.message)
