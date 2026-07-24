"""
scaffold_plugin.py — سقالات مشاريع (project scaffolding) لعشرات
مجالات التطوير: ويب (frontend/backend/fullstack)، موبايل، ألعاب،
DevOps، AI/ML، Quantum، Blockchain، Embedded/Kernel، multiplayer
networking، AR/VR، وحتى سيناريو أفلام وحوار ألعاب متفرع. بيولّد ملفات
بداية حقيقية وشغالة قدر الإمكان — مش بديل عن الـ SDK/IDE الرسمي لكل
منصة (Xcode لـ iOS محتاج ماك، Android Studio لأندرويد، kernel headers
لموديولات اللينكس...)، لكنه بيوفر وقت الإعداد.
"""
from __future__ import annotations

import json
import pathlib

_INVALID_NAME_CHARS = set('/\\:*?"<>|')


def _validate_name(name: str) -> str | None:
    """يرجع رسالة خطأ لو الاسم غير آمن كاسم مجلد، وإلا None."""
    if not name or name in (".", ".."):
        return "❌ اسم المشروع لازم يكون غير فاضي ومش '.' أو '..'"
    if any(c in _INVALID_NAME_CHARS for c in name):
        return f"❌ اسم المشروع مينفعش يحتوي على: {' '.join(sorted(_INVALID_NAME_CHARS))}"
    return None


def _write(path: pathlib.Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _slugify(name: str) -> str:
    slug = "".join(c.lower() if c.isalnum() else "-" for c in name).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "project"


def _scaffold_web(root: pathlib.Path, name: str) -> list[str]:
    slug = _slugify(name)
    _write(root / "src" / "index.html", (
        '<!doctype html>\n<html lang="ar" dir="rtl">\n  <head>\n'
        '    <meta charset="utf-8" />\n'
        '    <meta name="viewport" content="width=device-width, initial-scale=1" />\n'
        '    <title>' + name + '</title>\n'
        '    <link rel="stylesheet" href="styles/main.css" />\n  </head>\n  <body>\n'
        '    <h1>' + name + '</h1>\n    <p>ابدأ هنا.</p>\n'
        '    <script type="module" src="scripts/main.js"></script>\n  </body>\n</html>\n'
    ))
    _write(root / "src" / "styles" / "main.css", (
        ":root {\n  --accent: #4f6ef7;\n  --bg: #0f1117;\n  --text: #f1f5f9;\n}\n\n"
        "body {\n  font-family: system-ui, sans-serif;\n  margin: 2rem;\n"
        "  background: var(--bg);\n  color: var(--text);\n}\n"
    ))
    _write(root / "src" / "scripts" / "main.js", (
        f'console.log("{name} جاهز");\n\n'
        "export function main() {\n  // ابدأ منطق التطبيق هنا\n}\n\nmain();\n"
    ))
    _write(root / "package.json", json.dumps({
        "name": slug, "version": "0.1.0", "private": True, "type": "module",
        "scripts": {
            "lint": "eslint src",
            "format": "prettier --check src",
            "format:fix": "prettier --write src",
        },
        "devDependencies": {"eslint": "^9.0.0", "prettier": "^3.2.0"},
    }, indent=2))
    _write(root / "eslint.config.js", (
        "export default [\n"
        "  {\n"
        "    languageOptions: {\n"
        "      ecmaVersion: \"latest\",\n"
        "      sourceType: \"module\",\n"
        "      globals: {\n"
        "        console: \"readonly\",\n"
        "        window: \"readonly\",\n"
        "        document: \"readonly\",\n"
        "        fetch: \"readonly\",\n"
        "        localStorage: \"readonly\",\n"
        "      },\n"
        "    },\n"
        "    rules: { \"no-unused-vars\": \"warn\", \"no-undef\": \"error\" },\n"
        "  },\n"
        "];\n"
    ))
    _write(root / ".prettierrc.json", json.dumps({"semi": True, "singleQuote": False, "printWidth": 100}, indent=2))
    _write(root / ".gitignore", "node_modules/\ndist/\n.DS_Store\n")
    _write(root / "README.md", (
        f"# {name}\n\n## التشغيل\n\nافتح `src/index.html` في المتصفح مباشرة — مفيش build step.\n\n"
        "## جودة الكود\n\n```bash\nnpm install\nnpm run lint\nnpm run format\n```\n"
    ))
    return [
        "src/index.html", "src/styles/main.css", "src/scripts/main.js",
        "package.json", "eslint.config.js", ".prettierrc.json", ".gitignore", "README.md",
    ]


def _scaffold_android(root: pathlib.Path, name: str) -> list[str]:
    slug = "".join(c.lower() for c in name if c.isalnum())
    pkg = "com.example." + slug if slug else "com.example.app"
    pkg_path = pkg.replace(".", "/")
    _write(root / "settings.gradle.kts", f'rootProject.name = "{name}"\ninclude(":app")\n')
    _write(root / "build.gradle.kts", "// top-level build file\n")
    _write(root / "app" / "build.gradle.kts", f"""plugins {{
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}}

android {{
    namespace = "{pkg}"
    compileSdk = 34
    defaultConfig {{
        applicationId = "{pkg}"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
    }}
}}
""")
    _write(root / "app" / "src" / "main" / "AndroidManifest.xml", f"""<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <application android:label="{name}">
        <activity android:name=".MainActivity" android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
""")
    _write(root / "app" / "src" / "main" / "java" / pkg_path / "MainActivity.kt", f"""package {pkg}

import android.os.Bundle
import androidx.activity.ComponentActivity
import android.widget.TextView

class MainActivity : ComponentActivity() {{
    override fun onCreate(savedInstanceState: Bundle?) {{
        super.onCreate(savedInstanceState)
        val view = TextView(this)
        view.text = "{name}"
        setContentView(view)
    }}
}}
""")
    return ["settings.gradle.kts", "build.gradle.kts", "app/build.gradle.kts",
            "app/src/main/AndroidManifest.xml", f"app/src/main/java/{pkg_path}/MainActivity.kt"]


def _scaffold_ios(root: pathlib.Path, name: str) -> list[str]:
    safe = "".join(c for c in name if c.isalnum()) or "App"
    _write(root / f"{safe}App.swift", f"""import SwiftUI

@main
struct {safe}App: App {{
    var body: some Scene {{
        WindowGroup {{
            ContentView()
        }}
    }}
}}
""")
    _write(root / "ContentView.swift", f"""import SwiftUI

struct ContentView: View {{
    var body: some View {{
        Text("{name}")
            .padding()
    }}
}}

#Preview {{
    ContentView()
}}
""")
    return [f"{safe}App.swift", "ContentView.swift"]


def _scaffold_game(root: pathlib.Path, name: str) -> list[str]:
    _write(root / "main.py", f'''"""{name} — Pygame starter."""
import pygame

pygame.init()
screen = pygame.display.set_mode((640, 480))
pygame.display.set_caption("{name}")
clock = pygame.time.Clock()

player_x, player_y = 320, 240
running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    keys = pygame.key.get_pressed()
    if keys[pygame.K_LEFT]:
        player_x -= 4
    if keys[pygame.K_RIGHT]:
        player_x += 4
    if keys[pygame.K_UP]:
        player_y -= 4
    if keys[pygame.K_DOWN]:
        player_y += 4

    screen.fill((30, 30, 40))
    pygame.draw.circle(screen, (79, 110, 247), (player_x, player_y), 20)
    pygame.display.flip()
    clock.tick(60)

pygame.quit()
''')
    _write(root / "requirements.txt", "pygame>=2.5.0\n")
    return ["main.py", "requirements.txt"]


def _scaffold_python(root: pathlib.Path, name: str) -> list[str]:
    slug = _slugify(name)
    pkg = slug.replace("-", "_")

    _write(root / "src" / pkg / "__init__.py", f'"""{name}."""\n\n__version__ = "0.1.0"\n')
    _write(root / "src" / pkg / "main.py", f'''"""نقطة الدخول الرئيسية."""


def greet(who: str = "world") -> str:
    return f"{{who}} جاهز"


def main() -> None:
    print(greet("{name}"))


if __name__ == "__main__":
    main()
''')
    _write(root / "tests" / "__init__.py", "")
    _write(root / "tests" / "test_main.py", f'''from {pkg}.main import greet


def test_greet_default():
    assert greet() == "world جاهز"


def test_greet_custom():
    assert greet("Ahmed") == "Ahmed جاهز"
''')
    _write(root / "pyproject.toml", f'''[project]
name = "{slug}"
version = "0.1.0"
description = "{name}"
requires-python = ">=3.11"
dependencies = []

[project.optional-dependencies]
dev = ["pytest>=8.0.0", "ruff>=0.4.0", "black>=24.0.0", "mypy>=1.9.0"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.black]
line-length = 100
target-version = ["py311"]

[tool.mypy]
python_version = "3.11"
ignore_missing_imports = true

[tool.pytest.ini_options]
testpaths = ["tests"]
''')
    _write(root / ".gitignore", "__pycache__/\n*.pyc\n.venv/\n.pytest_cache/\n.mypy_cache/\n.ruff_cache/\n*.egg-info/\n")
    _write(root / "README.md", f'''# {name}

## التشغيل

```bash
pip install -e ".[dev]"
python -m {pkg}.main
```

## الاختبارات

```bash
pytest
```

## جودة الكود

```bash
ruff check .
black --check .
mypy src
```
''')
    return [
        f"src/{pkg}/__init__.py", f"src/{pkg}/main.py", "tests/test_main.py",
        "pyproject.toml", ".gitignore", "README.md",
    ]


def _scaffold_backend(root: pathlib.Path, name: str) -> list[str]:
    slug = _slugify(name)

    _write(root / "app" / "__init__.py", "")
    _write(root / "app" / "core" / "__init__.py", "")
    _write(root / "app" / "core" / "config.py", f'''"""إعدادات التطبيق — بتتحمّل من متغيرات البيئة (.env)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "{name}"
    debug: bool = False
    log_level: str = "INFO"


settings = Settings()
''')
    _write(root / "app" / "core" / "logging.py", '''"""إعداد logging منظّم — يُستدعى مرة واحدة عند بدء التطبيق."""

import logging
import sys

from app.core.config import settings


def configure_logging() -> None:
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
''')
    _write(root / "app" / "api" / "__init__.py", "")
    _write(root / "app" / "api" / "routes" / "__init__.py", "")
    _write(root / "app" / "api" / "routes" / "health.py", '''from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
''')
    _write(root / "app" / "models" / "__init__.py", "")
    _write(root / "app" / "models" / "schemas.py", '''from pydantic import BaseModel


class Message(BaseModel):
    message: str
''')
    _write(root / "app" / "services" / "__init__.py", "")
    _write(root / "app" / "services" / "example_service.py", '''"""مثال طبقة منطق العمل (business logic layer) — منفصلة عن الـ routes
عمداً، عشان تقدر تختبرها من غير ما تشغّل سيرفر HTTP."""


def build_welcome_message(app_name: str) -> str:
    return f"{app_name} API جاهز"
''')
    _write(root / "app" / "main.py", '''from fastapi import FastAPI

from app.api.routes import health
from app.core.config import settings
from app.core.logging import configure_logging
from app.services.example_service import build_welcome_message

configure_logging()

app = FastAPI(title=settings.app_name, debug=settings.debug)
app.include_router(health.router)


@app.get("/")
def root() -> dict[str, str]:
    return {"message": build_welcome_message(settings.app_name)}
''')
    _write(root / "tests" / "__init__.py", "")
    _write(root / "tests" / "test_health.py", '''from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_endpoint():
    response = client.get("/")
    assert response.status_code == 200
    assert "message" in response.json()
''')
    _write(root / "tests" / "test_services.py", '''from app.services.example_service import build_welcome_message


def test_build_welcome_message():
    assert "MyApp" in build_welcome_message("MyApp")
''')
    _write(root / "pyproject.toml", f'''[project]
name = "{slug}"
version = "0.1.0"
description = "{name}"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.110.0",
    "uvicorn[standard]>=0.27.0",
    "pydantic-settings>=2.2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "httpx>=0.27.0",
    "ruff>=0.4.0",
    "black>=24.0.0",
    "mypy>=1.9.0",
]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.black]
line-length = 100
target-version = ["py311"]

[tool.mypy]
python_version = "3.11"
ignore_missing_imports = true

[tool.pytest.ini_options]
testpaths = ["tests"]
''')
    _write(root / ".env.example", f"APP_NAME={name}\nDEBUG=false\nLOG_LEVEL=INFO\n")
    _write(root / ".gitignore", "__pycache__/\n*.pyc\n.venv/\n.env\n.pytest_cache/\n.mypy_cache/\n.ruff_cache/\n")
    _write(root / ".pre-commit-config.yaml", '''repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.4.4
    hooks:
      - id: ruff
        args: [--fix]
  - repo: https://github.com/psf/black
    rev: 24.4.2
    hooks:
      - id: black
''')
    _write(root / "Dockerfile", '''FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir .
COPY app ./app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
''')
    _write(root / "README.md", f'''# {name}

## التشغيل

```bash
pip install -e ".[dev]"
cp .env.example .env
uvicorn app.main:app --reload
```

## الاختبارات

```bash
pytest
```

## جودة الكود

```bash
ruff check .
black --check .
mypy app
```

## البنية

```
app/
  core/      إعدادات ولوجينج
  api/routes/  نقاط النهاية (endpoints)
  models/    Pydantic schemas
  services/  منطق العمل — منفصل عن الـ HTTP layer
tests/       اختبارات pytest حقيقية (TestClient)
```
''')
    return [
        "app/main.py", "app/core/config.py", "app/core/logging.py",
        "app/api/routes/health.py", "app/models/schemas.py", "app/services/example_service.py",
        "tests/test_health.py", "tests/test_services.py",
        "pyproject.toml", ".env.example", ".gitignore", ".pre-commit-config.yaml",
        "Dockerfile", "README.md",
    ]


def _scaffold_fullstack(root: pathlib.Path, name: str) -> list[str]:
    files = [f"frontend/{f}" for f in _scaffold_web(root / "frontend", name)]
    files += [f"backend/{f}" for f in _scaffold_backend(root / "backend", name)]
    _write(root / "docker-compose.yml", '''services:
  backend:
    build: ./backend
    ports:
      - "8000:8000"
    env_file:
      - ./backend/.env.example

  frontend:
    image: nginx:alpine
    volumes:
      - ./frontend/src:/usr/share/nginx/html:ro
    ports:
      - "8080:80"
    depends_on:
      - backend
''')
    _write(root / "README.md", f"# {name} — Full-Stack\n\n```bash\ndocker compose up\n```\n\n"
           "- backend: http://localhost:8000\n- frontend: http://localhost:8080\n\n"
           "أو شغّل كل جزء لوحده حسب التعليمات في `backend/README.md` و`frontend/README.md`.\n")
    files += ["docker-compose.yml", "README.md"]
    return files


def _scaffold_docker(root: pathlib.Path, name: str) -> list[str]:
    _write(root / "Dockerfile", '''# ---- مرحلة البناء (builder) ----
# بتثبت المتطلبات في مجلد مستخدم منفصل، عشان الصورة النهائية متحتويش
# على أدوات بناء (compilers, ...) أو ملفات مؤقتة زيادة عن اللزوم.
FROM python:3.12-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ---- المرحلة النهائية (runtime) — صورة نظيفة وصغيرة ----
FROM python:3.12-slim
WORKDIR /app

# مستخدم غير root — تشغيل الحاوية كـ root ممارسة أمان سيئة
RUN useradd --create-home --uid 1000 appuser
COPY --from=builder /root/.local /home/appuser/.local
COPY . .
RUN chown -R appuser:appuser /app
USER appuser
ENV PATH=/home/appuser/.local/bin:$PATH

HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD python -c "print('ok')" || exit 1

# غيّر السطر ده لنقطة دخول مشروعك الفعلية (زي: uvicorn app.main:app --host 0.0.0.0)
CMD ["python", "main.py"]
''')
    _write(root / ".dockerignore", (
        "__pycache__/\n*.pyc\n.venv/\n.git/\n.pytest_cache/\n.mypy_cache/\n.ruff_cache/\n"
        "*.egg-info/\n.env\ntests/\nREADME.md\n"
    ))
    return ["Dockerfile", ".dockerignore"]


def _scaffold_ci(root: pathlib.Path, name: str) -> list[str]:
    _write(root / ".github" / "workflows" / "ci.yml", '''name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install ruff black
      - run: ruff check .
      - run: black --check .

  test:
    needs: lint
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
          cache: "pip"
      - run: pip install -e ".[dev]"
      - run: pytest --cov --cov-report=term-missing

  build:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build package
        run: |
          pip install build
          python -m build
''')
    return [".github/workflows/ci.yml"]


def _scaffold_pytest(root: pathlib.Path, name: str) -> list[str]:
    _write(root / "src" / "example.py", '''"""مثال كود عشان الاختبارات يكون ليها حاجة حقيقية تختبرها."""


def add(a: int, b: int) -> int:
    return a + b


def divide(a: float, b: float) -> float:
    if b == 0:
        raise ValueError("القسمة على صفر غير مسموحة")
    return a / b
''')
    _write(root / "tests" / "test_example.py", '''import pytest

from example import add, divide


def test_add():
    assert add(2, 3) == 5


def test_divide():
    assert divide(10, 2) == 5


def test_divide_by_zero_raises():
    with pytest.raises(ValueError):
        divide(1, 0)
''')
    _write(root / "pytest.ini", "[pytest]\ntestpaths = tests\npythonpath = src\naddopts = --cov=src --cov-report=term-missing\n")
    _write(root / "tox.ini", '''[tox]
envlist = py311, py312
isolated_build = true

[testenv]
deps =
    pytest
    pytest-cov
commands = pytest {posargs}

[testenv:lint]
deps = ruff
commands = ruff check src tests
''')
    _write(root / "requirements-dev.txt", "pytest>=8.0.0\npytest-cov>=5.0.0\ntox>=4.0.0\nruff>=0.4.0\n")
    _write(root / "README.md", f'''# {name} — QA/Test Automation

```bash
pip install -r requirements-dev.txt
pytest                # اختبار على بايثون الحالي + تقرير تغطية
tox                   # اختبار على كل نسخ بايثون في [tox] envlist
```
''')
    return ["src/example.py", "tests/test_example.py", "pytest.ini", "tox.ini", "requirements-dev.txt", "README.md"]


def _scaffold_ml(root: pathlib.Path, name: str) -> list[str]:
    slug = _slugify(name)
    pkg = slug.replace("-", "_")

    _write(root / "src" / pkg / "__init__.py", f'"""{name} — ML pipeline."""\n\n__version__ = "0.1.0"\n')
    _write(root / "src" / pkg / "data.py", '''"""تحميل وتقسيم البيانات — طبقة منفصلة عشان تقدر تستبدلها ببيانات
حقيقية من غير ما تلمس كود التدريب أو التقييم."""

from sklearn.datasets import load_iris
from sklearn.model_selection import train_test_split


def load_data(test_size: float = 0.2, random_state: int = 42):
    dataset = load_iris()
    return train_test_split(
        dataset.data, dataset.target, test_size=test_size, random_state=random_state
    )
''')
    _write(root / "src" / pkg / "model.py", '''"""تعريف النموذج — منفصل عن التدريب عشان تقدر تجرب نماذج مختلفة بسهولة."""

from sklearn.ensemble import RandomForestClassifier


def build_model(random_state: int = 42) -> RandomForestClassifier:
    return RandomForestClassifier(random_state=random_state)
''')
    _write(root / "src" / pkg / "train.py", f'''"""حلقة التدريب."""

from {pkg}.data import load_data
from {pkg}.model import build_model


def train():
    X_train, X_test, y_train, y_test = load_data()
    model = build_model()
    model.fit(X_train, y_train)
    return model, X_test, y_test
''')
    _write(root / "src" / pkg / "evaluate.py", '''"""تقييم النموذج بعد التدريب."""

from sklearn.metrics import accuracy_score


def evaluate(model, X_test, y_test) -> float:
    predictions = model.predict(X_test)
    return accuracy_score(y_test, predictions)
''')
    _write(root / "src" / pkg / "__main__.py", f'''"""نقطة الدخول: python -m {pkg}"""

from {pkg}.evaluate import evaluate
from {pkg}.train import train


def main() -> None:
    model, X_test, y_test = train()
    accuracy = evaluate(model, X_test, y_test)
    print(f"accuracy: {{accuracy:.3f}}")


if __name__ == "__main__":
    main()
''')
    _write(root / "tests" / "__init__.py", "")
    _write(root / "tests" / "test_pipeline.py", f'''from {pkg}.evaluate import evaluate
from {pkg}.train import train


def test_pipeline_trains_and_reaches_reasonable_accuracy():
    model, X_test, y_test = train()
    accuracy = evaluate(model, X_test, y_test)
    assert 0.0 <= accuracy <= 1.0
    assert accuracy > 0.7  # Iris + RandomForest بيوصل غالباً لأكتر من 90%
''')
    _write(root / "data" / ".gitkeep", "")
    _write(root / "models" / ".gitkeep", "")
    _write(root / "pyproject.toml", f'''[project]
name = "{slug}"
version = "0.1.0"
description = "{name}"
requires-python = ">=3.11"
dependencies = ["scikit-learn>=1.4.0"]

[project.optional-dependencies]
dev = ["pytest>=8.0.0", "ruff>=0.4.0", "black>=24.0.0"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.black]
line-length = 100
target-version = ["py311"]

[tool.pytest.ini_options]
testpaths = ["tests"]
''')
    _write(root / ".gitignore", "__pycache__/\n*.pyc\n.venv/\n.pytest_cache/\n.ruff_cache/\n*.egg-info/\ndata/*\n!data/.gitkeep\nmodels/*\n!models/.gitkeep\n")
    _write(root / "README.md", f'''# {name}

## التشغيل

```bash
pip install -e ".[dev]"
python -m {pkg}
```

## الاختبارات

```bash
pytest
```

## البنية

```
src/{pkg}/
  data.py      تحميل/تقسيم البيانات
  model.py     تعريف النموذج
  train.py     حلقة التدريب
  evaluate.py  التقييم
data/          بياناتك الحقيقية (فاضي دلوقتي — placeholder)
models/        النماذج المدرّبة المحفوظة
```

استبدل `src/{pkg}/data.py` ببياناتك الحقيقية بدل Iris demo dataset.
''')
    return [
        f"src/{pkg}/data.py", f"src/{pkg}/model.py", f"src/{pkg}/train.py",
        f"src/{pkg}/evaluate.py", f"src/{pkg}/__main__.py", "tests/test_pipeline.py",
        "pyproject.toml", ".gitignore", "README.md",
    ]


def _scaffold_quantum(root: pathlib.Path, name: str) -> list[str]:
    _write(root / "bell_state.py", f'''"""{name} — Qiskit starter: Bell state circuit (تشابك كمّي بسيط)."""
from qiskit import QuantumCircuit
from qiskit_aer import AerSimulator


def main():
    qc = QuantumCircuit(2, 2)
    qc.h(0)
    qc.cx(0, 1)
    qc.measure([0, 1], [0, 1])

    simulator = AerSimulator()
    result = simulator.run(qc, shots=1000).result()
    counts = result.get_counts()
    print(f"نتائج القياس: {{counts}}")


if __name__ == "__main__":
    main()
''')
    _write(root / "requirements.txt", "qiskit>=1.0.0\nqiskit-aer>=0.14.0\n")
    return ["bell_state.py", "requirements.txt"]


def _scaffold_blockchain(root: pathlib.Path, name: str) -> list[str]:
    safe = "".join(c for c in name if c.isalnum()) or "MyContract"
    _write(root / "contracts" / f"{safe}.sol", f'''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract {safe} {{
    string public message;
    address public owner;

    constructor(string memory initialMessage) {{
        message = initialMessage;
        owner = msg.sender;
    }}

    function setMessage(string memory newMessage) public {{
        require(msg.sender == owner, "not owner");
        message = newMessage;
    }}
}}
''')
    _write(root / "package.json", json.dumps({
        "name": safe.lower(), "version": "1.0.0",
        "devDependencies": {"hardhat": "^2.22.0"},
    }, indent=2))
    return [f"contracts/{safe}.sol", "package.json"]


def _scaffold_embedded(root: pathlib.Path, name: str) -> list[str]:
    _write(root / "main.c", f'''/* {name} — embedded C starter (GPIO blink pattern).
 * gpio_set/delay_ms متعمدين يتسابوا abstract — نفس أسلوب الـ HAL
 * (Hardware Abstraction Layer) الحقيقي: كل بورد له تعريف مختلف
 * لعناوين الذاكرة، فده بيتكتب حسب الـ board/MCU المستهدف. */
#include <stdint.h>

#define LED_PIN 13

void gpio_set(int pin, int value);
void delay_ms(int ms);

int main(void) {{
    while (1) {{
        gpio_set(LED_PIN, 1);
        delay_ms(500);
        gpio_set(LED_PIN, 0);
        delay_ms(500);
    }}
    return 0;
}}
''')
    return ["main.c"]


def _scaffold_kernel_module(root: pathlib.Path, name: str) -> list[str]:
    safe = "".join(c.lower() if c.isalnum() else "_" for c in name) or "hello_module"
    _write(root / f"{safe}.c", f'''#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>

MODULE_LICENSE("GPL");
MODULE_AUTHOR("{name}");
MODULE_DESCRIPTION("{name} — minimal kernel module starter");

static int __init {safe}_init(void) {{
    printk(KERN_INFO "{name}: module loaded\\n");
    return 0;
}}

static void __exit {safe}_exit(void) {{
    printk(KERN_INFO "{name}: module unloaded\\n");
}}

module_init({safe}_init);
module_exit({safe}_exit);
''')
    _write(root / "Makefile", f"""obj-m += {safe}.o

all:
\tmake -C /lib/modules/$(shell uname -r)/build M=$(PWD) modules

clean:
\tmake -C /lib/modules/$(shell uname -r)/build M=$(PWD) clean
""")
    return [f"{safe}.c", "Makefile"]


def _scaffold_multiplayer_server(root: pathlib.Path, name: str) -> list[str]:
    _write(root / "server.py", f'''"""{name} — خادم متعدد اللاعبين أساسي (asyncio TCP broadcast)."""
import asyncio

clients: set[asyncio.StreamWriter] = set()


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    clients.add(writer)
    addr = writer.get_extra_info("peername")
    print(f"اتصل: {{addr}}")
    try:
        while True:
            data = await reader.readline()
            if not data:
                break
            for client in clients:
                if client is not writer:
                    client.write(data)
                    await client.drain()
    finally:
        clients.discard(writer)
        writer.close()


async def main(host="0.0.0.0", port=8765):
    server = await asyncio.start_server(handle_client, host, port)
    print(f"شغال على {{host}}:{{port}}")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
''')
    _write(root / "client.py", '''"""عميل بسيط للاتصال بالسيرفر."""
import asyncio


async def main():
    reader, writer = await asyncio.open_connection("127.0.0.1", 8765)
    writer.write(b"hello\\n")
    await writer.drain()
    writer.close()


if __name__ == "__main__":
    asyncio.run(main())
''')
    return ["server.py", "client.py"]


def _scaffold_arvr(root: pathlib.Path, name: str) -> list[str]:
    _write(root / "index.html", f'''<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{name}</title>
  <script src="https://aframe.io/releases/1.5.0/aframe.min.js"></script>
</head>
<body>
  <a-scene>
    <a-box position="0 1.5 -3" rotation="0 45 0" color="#4f6ef7"></a-box>
    <a-sky color="#ECECEC"></a-sky>
  </a-scene>
</body>
</html>
''')
    return ["index.html"]


def _scaffold_screenplay(root: pathlib.Path, name: str) -> list[str]:
    _write(root / f"{name}.fountain", f'''Title: {name}
Credit: Written by
Draft date:

FADE IN:

INT. LOCATION - DAY

Action description goes here.

CHARACTER
Dialogue goes here.

FADE OUT.
''')
    return [f"{name}.fountain"]


def _scaffold_ink_story(root: pathlib.Path, name: str) -> list[str]:
    _write(root / "story.ink", f'''// {name} — قصة متفرعة أساسية (Ink format: inklestudios.com/ink)
-> start

=== start ===
تبدأ القصة هنا.

* [اختيار أ] -> choice_a
* [اختيار ب] -> choice_b

=== choice_a ===
اخترت أ.
-> END

=== choice_b ===
اخترت ب.
-> END
''')
    return ["story.ink"]


_SCAFFOLDS = {
    "web": (_scaffold_web, "موقع ويب ثابت — Frontend (HTML/CSS/JS)"),
    "backend": (_scaffold_backend, "خادم Backend (FastAPI) — شغال فوراً"),
    "fullstack": (_scaffold_fullstack, "مشروع Full-Stack (frontend + backend مع بعض)"),
    "android": (_scaffold_android, "مشروع أندرويد (Kotlin/Gradle) — يفتح في Android Studio"),
    "ios": (_scaffold_ios, "مشروع iOS (SwiftUI) — يحتاج Xcode على ماك"),
    "game": (_scaffold_game, "لعبة 2D بـ Pygame (شغالة فوراً: pip install pygame && python main.py)"),
    "python": (_scaffold_python, "مشروع بايثون عام"),
    "docker": (_scaffold_docker, "Dockerfile + .dockerignore لمشروع بايثون"),
    "ci": (_scaffold_ci, "GitHub Actions CI workflow حقيقي"),
    "pytest": (_scaffold_pytest, "سقالة اختبارات pytest"),
    "ml": (_scaffold_ml, "تدريب نموذج AI/ML (scikit-learn) — شغال فوراً"),
    "quantum": (_scaffold_quantum, "دائرة كمّية (Qiskit) — Bell state شغالة فوراً"),
    "blockchain": (_scaffold_blockchain, "عقد ذكي (Solidity) + إعداد Hardhat"),
    "embedded": (_scaffold_embedded, "سقالة C للأنظمة المدمجة (GPIO blink pattern)"),
    "kernel_module": (_scaffold_kernel_module, "موديول Linux kernel أساسي — يحتاج kernel headers للبناء"),
    "multiplayer_server": (_scaffold_multiplayer_server, "خادم متعدد اللاعبين (asyncio) — شغال فوراً"),
    "arvr": (_scaffold_arvr, "مشروع WebXR (A-Frame، مجاني ومفتوح المصدر)"),
    "screenplay": (_scaffold_screenplay, "سيناريو فيلم بصيغة Fountain القياسية"),
    "ink_story": (_scaffold_ink_story, "قصة متفرعة بصيغة Ink (نفس أداة ألعاب حقيقية زي 80 Days)"),
}


def _cmd_scaffold(ctx) -> str:
    if len(ctx.args) < 2:
        types = "\n".join(f"  {k} — {desc}" for k, (_, desc) in _SCAFFOLDS.items())
        return f"usage: scaffold <type> <project_name> [output_dir]\nالأنواع المتاحة:\n{types}"
    kind, name = ctx.args[0], ctx.args[1]
    if kind not in _SCAFFOLDS:
        return f"❌ نوع غير معروف: {kind} (المتاح: {', '.join(_SCAFFOLDS)})"
    name_error = _validate_name(name)
    if name_error:
        return name_error
    base = pathlib.Path(ctx.args[2]) if len(ctx.args) > 2 else pathlib.Path(".")
    root = base / name
    if root.exists() and any(root.iterdir()):
        return f"❌ المجلد {root} موجود بالفعل ومش فاضي — اختار اسم/مكان تاني"
    fn, _ = _SCAFFOLDS[kind]
    try:
        files = fn(root, name)
    except OSError as e:
        return f"❌ فشل إنشاء الملفات: {e}"
    listing = "\n".join(f"  📄 {f}" for f in files)
    return f"✅ اتعمل مشروع {kind} في {root}:\n{listing}"


def register(engine):
    engine.registry.register(
        "scaffold", _cmd_scaffold,
        "scaffold <web|android|ios|game|python> <name> [dir] — إنشاء سقالة مشروع جاهزة",
    )
