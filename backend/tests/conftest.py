"""Must set environment variables BEFORE importing anything from `app`,
since app.config.Settings reads os.environ at import time.
"""
import os
import tempfile

os.environ["APEX_JWT_SECRET"] = "test-secret-not-for-production"
os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-not-real"
os.environ["APEX_DATABASE_URL"] = f"sqlite:///{tempfile.mktemp(suffix='.db')}"
os.environ["APEX_SANDBOX_MODE"] = "local_dev_INSECURE"
os.environ["APEX_DAILY_MESSAGE_QUOTA"] = "3"  # small, so tests can actually exhaust it
