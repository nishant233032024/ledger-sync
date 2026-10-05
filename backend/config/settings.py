"""Django settings for LedgerSync.

The file intentionally keeps configuration in one place for a first project.
When you deploy to multiple environments, split this into base, local, and
production modules after you understand each setting.
"""

import os
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlparse

from django.core.exceptions import ImproperlyConfigured


# BASE_DIR is the backend folder containing manage.py.
BASE_DIR = Path(__file__).resolve().parent.parent


# Read values from the environment so secrets never need to be committed.
SECRET_KEY = os.getenv(
    "DJANGO_SECRET_KEY",
    "local-only-secret-key-change-me",
)
DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"
LEDGERSYNC_PUBLIC_DEMO = os.getenv("LEDGERSYNC_PUBLIC_DEMO", "0") == "1"
if not DEBUG and (SECRET_KEY == "local-only-secret-key-change-me" or len(SECRET_KEY) < 50):
    raise ImproperlyConfigured("Set DJANGO_SECRET_KEY to a random value of at least 50 characters.")


# Convert a comma-separated environment value into Django's list format.
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv(
        "DJANGO_ALLOWED_HOSTS",
        "localhost,127.0.0.1",
    ).split(",")
    if host.strip()
]
# Render supplies the actual hostname, including any generated suffix.
if os.getenv("RENDER_EXTERNAL_HOSTNAME"):
    ALLOWED_HOSTS.append(os.environ["RENDER_EXTERNAL_HOSTNAME"])


# Installed applications are grouped by purpose for easier navigation.
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "django_filters",
    "rest_framework_simplejwt.token_blacklist",
    "ledger",
]


# Middleware order matters: CORS must run before CommonMiddleware.
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


ROOT_URLCONF = "config.urls"


# Django's template configuration is needed by admin and error pages.
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
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


def database_from_environment() -> dict:
    """Build a Django database configuration from DATABASE_URL.

    PostgreSQL is used when DATABASE_URL starts with postgres. SQLite is a
    convenient fallback for learning and backend unit tests.
    """

    database_url = os.getenv("DATABASE_URL", "").strip()

    if not database_url:
        if LEDGERSYNC_PUBLIC_DEMO and not DEBUG:
            raise ImproperlyConfigured("The hosted demo requires a persistent PostgreSQL DATABASE_URL.")
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }

    parsed = urlparse(database_url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ValueError("DATABASE_URL must be a PostgreSQL URL")

    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(parsed.path.lstrip("/")),
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "localhost",
        "PORT": str(parsed.port or 5432),
        "CONN_MAX_AGE": int(os.getenv("DATABASE_CONN_MAX_AGE", "60")),
        "CONN_HEALTH_CHECKS": True,
        # Neon pooled connections use transaction pooling.
        "DISABLE_SERVER_SIDE_CURSORS": True,
        "OPTIONS": dict(parse_qsl(parsed.query)),
    }


DATABASES = {"default": database_from_environment()}


# Tell Django to use the custom User model in ledger/models.py.
AUTH_USER_MODEL = "ledger.User"


# Password validators are enabled even though the demo project uses a simple
# seed password, so future accounts still receive Django's safety checks.
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
]


LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True


STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}


DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# DRF defaults keep organization scoping in each view explicit.
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "ledger.pagination.StandardResultsSetPagination",
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
}


# Short access tokens reduce the impact of a leaked browser token.
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
}


# Redis provides Celery's broker, result backend, cache, and progress store.
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}
if LEDGERSYNC_PUBLIC_DEMO:
    # Public requests only read precomputed SQL results. Seeding runs jobs
    # synchronously from a management command, without a Redis subscription.
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}


CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_TIME_LIMIT = 60 * 30
CELERY_TASK_SOFT_TIME_LIMIT = 60 * 25
CELERY_TASK_ALWAYS_EAGER = os.getenv("CELERY_TASK_ALWAYS_EAGER", "0") == "1"
CELERY_TASK_EAGER_PROPAGATES = True
if LEDGERSYNC_PUBLIC_DEMO:
    CELERY_BROKER_URL = "memory://"
    CELERY_RESULT_BACKEND = "cache+memory://"
    CELERY_TASK_ALWAYS_EAGER = True
CELERY_BROKER_TRANSPORT_OPTIONS = {"visibility_timeout": 3600}
CELERY_RESULT_EXPIRES = 86400
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_BEAT_SCHEDULE = {
    "dispatch-pending-jobs": {
        "task": "ledger.tasks.dispatch_pending_jobs",
        "schedule": 30.0,
    },
    "mark-stale-batches": {
        "task": "ledger.tasks.mark_stale_batches",
        "schedule": 300.0,
    },
}


# The frontend is a separate local service during development.
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "DJANGO_CORS_ALLOWED_ORIGINS",
        "http://localhost:3000",
    ).split(",")
    if origin.strip()
]
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]


# Keep uploads bounded before a worker ever sees the file.
DATA_UPLOAD_MAX_MEMORY_SIZE = int(
    os.getenv("MAX_UPLOAD_SIZE", str(100 * 1024 * 1024))
)
MAX_UPLOAD_SIZE = DATA_UPLOAD_MAX_MEMORY_SIZE
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024


# The request ID is added by the API layer when an endpoint needs it.
USE_X_FORWARDED_HOST = False
# Enable only behind a proxy that strips client-supplied forwarded headers.
if os.getenv("DJANGO_TRUST_PROXY", "0") == "1":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")


# Production-only browser and transport protections. Local development keeps
# HTTP enabled so localhost remains easy to use.
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31_536_000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
