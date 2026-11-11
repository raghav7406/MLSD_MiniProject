import os
import pytest
from pathlib import Path


@pytest.fixture(autouse=True)
def tmp_data_dir(tmp_path):
    """Isolate result, quarantine, and feedback files in a temp directory."""
    os.environ["RESULT_STORE_PATH"] = str(tmp_path / "results.json")
    os.environ["QUARANTINE_PATH"] = str(tmp_path / "quarantine_records.json")
    os.environ["FEEDBACK_PATH"] = str(tmp_path / "feedback.json")
    yield tmp_path
    os.environ.pop("RESULT_STORE_PATH", None)
    os.environ.pop("QUARANTINE_PATH", None)
    os.environ.pop("FEEDBACK_PATH", None)


@pytest.fixture
def reset_tools():
    """Reset the cached vector store between tests."""
    from src.agents.tools import reset_store
    reset_store()
    yield
    reset_store()

