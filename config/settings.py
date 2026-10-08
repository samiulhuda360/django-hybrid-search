"""Django settings.

Every value that differs between machines comes from an environment variable. The defaults are for local
development only; set DJANGO_SECRET_KEY and DJANGO_DEBUG=0 for anything public.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
VAR_DIR = Path(os.environ.get("SEARCH_VAR_DIR", BASE_DIR / "var"))
VAR_DIR.mkdir(parents=True, exist_ok=True)


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-not-a-secret")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = [h for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if h]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "search",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": VAR_DIR / "db.sqlite3",
        "OPTIONS": {"timeout": 20},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = VAR_DIR / "static"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Search engine -------------------------------------------------------------------------------------------
SEARCH: dict[str, Any] = {
    # Where the built index (BM25 statistics, chunk text and embedding matrix) is stored.
    "INDEX_DIR": Path(os.environ.get("SEARCH_INDEX_DIR", VAR_DIR / "index")),
    # "fastembed" runs a small ONNX sentence-embedding model on the CPU; "hash" is a dependency-free
    # feature-hashing embedder used by the tests and CI.
    "EMBEDDER": os.environ.get("SEARCH_EMBEDDER", "fastembed"),
    "EMBED_MODEL": os.environ.get("SEARCH_EMBED_MODEL", "BAAI/bge-small-en-v1.5"),
    "MODEL_CACHE_DIR": Path(os.environ.get("SEARCH_MODEL_CACHE", VAR_DIR / "models")),
    "USER_AGENT": os.environ.get("SEARCH_USER_AGENT", "HybridSearchBot/1.0 (+https://github.com/samiulhuda360)"),
    "RRF_K": 60,
}

# --- Optional AI answers (any OpenAI-compatible endpoint) -------------------------------------------------
AI: dict[str, Any] = {
    "API_KEY": os.environ.get("AI_API_KEY", ""),
    "BASE_URL": os.environ.get("AI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai"),
    "MODEL": os.environ.get("AI_MODEL", "gemini-flash-lite-latest"),
    "CACHE_DIR": Path(os.environ.get("AI_CACHE_DIR", VAR_DIR / "llm-cache")),
    "MIN_INTERVAL_SECONDS": float(os.environ.get("AI_MIN_INTERVAL_SECONDS", "2.5")),
    "TIMEOUT_SECONDS": 30.0,
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"search": {"handlers": ["console"], "level": os.environ.get("SEARCH_LOG_LEVEL", "INFO")}},
}
