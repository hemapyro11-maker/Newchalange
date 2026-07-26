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
        return "❌ the project name must not be empty, '.' or '..'"
    if any(c in _INVALID_NAME_CHARS for c in name):
        return f"❌ the project name may not contain: {' '.join(sorted(_INVALID_NAME_CHARS))}"
    return None


def _write(path: pathlib.Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _slugify(name: str) -> str:
    slug = "".join(c.lower() if c.isalnum() else "-" for c in name).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "project"


def _ensure_identifier(candidate: str, fallback: str) -> str:
    """يتأكد إن candidate معرّف (identifier) صالح في بايثون/Kotlin/Swift/
    Solidity/C — كل اللغات دي بتتفق إن المعرّف مايبدأش برقم. لو فاضي،
    بيرجع fallback؛ لو بادئ برقم، بيضيف underscore قبله (بادئة صالحة
    في كل اللغات الخمس) بدل ما يولّد كود مكسور (زي SyntaxError في
    بايثون لو اسم المشروع "9lives" اتحط زي ما هو كـ اسم موديول)."""
    if not candidate:
        return fallback
    if candidate[0].isdigit():
        return "_" + candidate
    return candidate


def _scaffold_web(root: pathlib.Path, name: str) -> list[str]:
    slug = _slugify(name)
    _write(root / "src" / "index.html", (
        '<!doctype html>\n<html lang="ar" dir="rtl">\n  <head>\n'
        '    <meta charset="utf-8" />\n'
        '    <meta name="viewport" content="width=device-width, initial-scale=1" />\n'
        '    <title>' + name + '</title>\n'
        '    <link rel="stylesheet" href="styles/main.css" />\n  </head>\n  <body>\n'
        '    <h1>' + name + '</h1>\n    <p>Start here.</p>\n'
        '    <script type="module" src="scripts/main.js"></script>\n  </body>\n</html>\n'
    ))
    _write(root / "src" / "styles" / "main.css", (
        ":root {\n  --accent: #4f6ef7;\n  --bg: #0f1117;\n  --text: #f1f5f9;\n}\n\n"
        "body {\n  font-family: system-ui, sans-serif;\n  margin: 2rem;\n"
        "  background: var(--bg);\n  color: var(--text);\n}\n"
    ))
    _write(root / "src" / "scripts" / "main.js", (
        f'console.log("{name} ready");\n\n'
        "export function main() {\n  // application logic starts here\n}\n\nmain();\n"
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
        f"# {name}\n\n## Running it\n\nOpen `src/index.html` in a browser directly — there is no build step.\n\n"
        "## Code quality\n\n```bash\nnpm install\nnpm run lint\nnpm run format\n```\n"
    ))
    return [
        "src/index.html", "src/styles/main.css", "src/scripts/main.js",
        "package.json", "eslint.config.js", ".prettierrc.json", ".gitignore", "README.md",
    ]


def _scaffold_android(root: pathlib.Path, name: str) -> list[str]:
    slug = _ensure_identifier("".join(c.lower() for c in name if c.isalnum()), "app")
    pkg = "com.example." + slug
    pkg_path = pkg.replace(".", "/")
    _write(root / "settings.gradle.kts", f'''pluginManagement {{
    repositories {{
        google()
        mavenCentral()
        gradlePluginPortal()
    }}
}}
dependencyResolutionManagement {{
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {{
        google()
        mavenCentral()
    }}
}}

rootProject.name = "{name}"
include(":app")
''')
    _write(root / "build.gradle.kts", "// top-level build file — do not add dependencies here, use app/build.gradle.kts\n")
    _write(root / "gradle.properties", (
        "org.gradle.jvmargs=-Xmx2048m -Dfile.encoding=UTF-8\n"
        "android.useAndroidX=true\n"
        "kotlin.code.style=official\n"
    ))
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
    compileOptions {{
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }}
    kotlinOptions {{
        jvmTarget = "17"
    }}
}}

dependencies {{
    implementation("androidx.core:core-ktx:1.13.0")
    implementation("androidx.appcompat:appcompat:1.6.1")
    implementation("com.google.android.material:material:1.11.0")
    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.1.5")
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
    _write(root / "app" / "src" / "main" / "java" / pkg_path / "Greeter.kt", f"""package {pkg}

/** Pure logic with no dependency on the Android framework — so it can be
 * tested as an ordinary JVM unit test (app/src/test/...) with no emulator
 * or real device. */
object Greeter {{
    fun greet(who: String): String = "Hello, $who!"
}}
""")
    _write(root / "app" / "src" / "main" / "java" / pkg_path / "MainActivity.kt", f"""package {pkg}

import android.os.Bundle
import androidx.activity.ComponentActivity
import android.widget.TextView

class MainActivity : ComponentActivity() {{
    override fun onCreate(savedInstanceState: Bundle?) {{
        super.onCreate(savedInstanceState)
        val view = TextView(this)
        view.text = Greeter.greet("{name}")
        setContentView(view)
    }}
}}
""")
    _write(root / "app" / "src" / "test" / "java" / pkg_path / "GreeterTest.kt", f"""package {pkg}

import org.junit.Assert.assertEquals
import org.junit.Test

class GreeterTest {{
    @Test
    fun greet_includesTheName() {{
        assertEquals("Hello, Ahmed!", Greeter.greet("Ahmed"))
    }}

    @Test
    fun greet_isNeverEmpty() {{
        assert(Greeter.greet("{name}").isNotEmpty())
    }}
}}
""")
    _write(root / ".gitignore", (
        "*.iml\n.gradle/\n/local.properties\n/.idea/\n.DS_Store\n"
        "/build/\napp/build/\ncaptures/\n.externalNativeBuild/\n.cxx/\nlocal.properties\n"
    ))
    _write(root / "README.md", f'''# {name} — Android (Kotlin) Starter

Open the folder in Android Studio (it fetches the Gradle wrapper itself),
or from the command line if you have Gradle installed:

```bash
gradle test              # runs the JUnit unit tests (app/src/test)
gradle assembleDebug     # builds an APK
```

The greeting logic in `Greeter.kt` is deliberately separate from
`MainActivity.kt` (which needs the Android framework and an emulator), so it
can be tested as a plain JVM unit test in `GreeterTest.kt` without one.
''')
    return [
        "settings.gradle.kts", "build.gradle.kts", "gradle.properties", "app/build.gradle.kts",
        "app/src/main/AndroidManifest.xml",
        f"app/src/main/java/{pkg_path}/Greeter.kt",
        f"app/src/main/java/{pkg_path}/MainActivity.kt",
        f"app/src/test/java/{pkg_path}/GreeterTest.kt",
        ".gitignore", "README.md",
    ]


def _scaffold_ios(root: pathlib.Path, name: str) -> list[str]:
    safe = _ensure_identifier("".join(c for c in name if c.isalnum()), "App")
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
    _write(root / "Greeter.swift", '''// Pure logic with no dependency on SwiftUI or UIKit — so it can be tested
// with ordinary XCTest (see GreeterTests.swift), no simulator or device.
enum Greeter {
    static func greet(_ who: String) -> String {
        "Hello, \\(who)!"
    }
}
''')
    _write(root / "ContentView.swift", f"""import SwiftUI

struct ContentView: View {{
    var body: some View {{
        Text(Greeter.greet("{name}"))
            .padding()
    }}
}}

#Preview {{
    ContentView()
}}
""")
    _write(root / f"{safe}Tests" / "GreeterTests.swift", f"""import XCTest
@testable import {safe}

final class GreeterTests: XCTestCase {{
    func testGreetIncludesTheName() {{
        XCTAssertEqual(Greeter.greet("Ahmed"), "Hello, Ahmed!")
    }}

    func testGreetIsNeverEmpty() {{
        XCTAssertFalse(Greeter.greet("{name}").isEmpty)
    }}
}}
""")
    _write(root / ".gitignore", (
        ".build/\nDerivedData/\n*.xcuserstate\nxcuserdata/\n.swiftpm/\nPackage.resolved\n"
    ))
    _write(root / "README.md", f'''# {name} — SwiftUI Starter

Open the folder in Xcode (on a Mac), add the files to a new iOS App project,
and run the tests (⌘U), or from the command line:

```bash
xcodebuild test -scheme {safe} -destination 'platform=iOS Simulator,name=iPhone 15'
```

The greeting logic in `Greeter.swift` is deliberately separate from
`ContentView.swift` (which needs the SwiftUI runtime), so it can be tested as
plain XCTest in `{safe}Tests/GreeterTests.swift` without a simulator.

**Note:** these are starter files to add to an Xcode project (.xcodeproj).
Xcode itself generates the full project structure (project file, build
settings, and so on) when you choose "New Project", and it needs a Mac.
''')
    return [
        f"{safe}App.swift", "Greeter.swift", "ContentView.swift",
        f"{safe}Tests/GreeterTests.swift", ".gitignore", "README.md",
    ]


def _scaffold_game(root: pathlib.Path, name: str) -> list[str]:
    _write(root / "player.py", '''"""player.py — pure player-movement logic, with no dependency on pygame or
the screen, so it can be tested directly like any other business logic
without opening a window or faking keyboard events."""


class Player:
    def __init__(self, x: float = 320, y: float = 240, speed: float = 4):
        self.x = x
        self.y = y
        self.speed = speed

    def move(self, left: bool, right: bool, up: bool, down: bool) -> None:
        if left:
            self.x -= self.speed
        if right:
            self.x += self.speed
        if up:
            self.y -= self.speed
        if down:
            self.y += self.speed

    @property
    def position(self) -> tuple[float, float]:
        return (self.x, self.y)
''')
    _write(root / "main.py", f'''"""{name} — Pygame starter.

The game loop lives in run() rather than at module level, so tests can call
it with a bounded max_frames (see tests/test_headless_smoke.py) instead of
entering an infinite loop."""
import pygame

from player import Player

WIDTH, HEIGHT = 640, 480


def run(max_frames: int | None = None) -> None:
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("{name}")
    clock = pygame.time.Clock()
    player = Player(x=WIDTH / 2, y=HEIGHT / 2)

    frame = 0
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

        keys = pygame.key.get_pressed()
        player.move(keys[pygame.K_LEFT], keys[pygame.K_RIGHT], keys[pygame.K_UP], keys[pygame.K_DOWN])

        screen.fill((30, 30, 40))
        pygame.draw.circle(screen, (79, 110, 247), (int(player.x), int(player.y)), 20)
        pygame.display.flip()
        clock.tick(60)

        frame += 1
        if max_frames is not None and frame >= max_frames:
            running = False

    pygame.quit()


if __name__ == "__main__":
    run()
''')
    _write(root / "tests" / "test_player.py", '''from player import Player


def test_moves_right():
    p = Player(x=0, y=0, speed=4)
    p.move(left=False, right=True, up=False, down=False)
    assert p.position == (4, 0)


def test_no_input_stays_still():
    p = Player(x=10, y=10, speed=4)
    p.move(False, False, False, False)
    assert p.position == (10, 10)


def test_opposite_keys_cancel_out():
    p = Player(x=0, y=0, speed=4)
    p.move(left=True, right=True, up=False, down=False)
    assert p.position == (0, 0)
''')
    _write(root / "tests" / "test_headless_smoke.py", '''"""A real test that runs the game loop for a bounded number of frames with no
actual display (SDL_VIDEODRIVER=dummy) — confirming that pygame.init,
drawing and event handling work together without crashing, not merely that
the code parses."""
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from main import run


def test_game_loop_runs_headless_for_a_few_frames():
    run(max_frames=5)
''')
    _write(root / "pytest.ini", "[pytest]\ntestpaths = tests\npythonpath = .\n")
    _write(root / "requirements.txt", "pygame>=2.5.0\n")
    _write(root / "requirements-dev.txt", "-r requirements.txt\npytest>=8.0.0\n")
    _write(root / ".gitignore", "__pycache__/\n*.pyc\n.pytest_cache/\n")
    _write(root / "README.md", f'''# {name} — Pygame Starter

```bash
pip install -r requirements.txt
python main.py          # opens a real game window
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest                   # player logic plus a headless smoke test of the whole loop
```

The movement logic in `player.py` is separate from pygame so it can be tested
directly, and the headless smoke test genuinely runs `main.run()` for 5
frames with no real display (`SDL_VIDEODRIVER=dummy`).
''')
    return [
        "player.py", "main.py", "tests/test_player.py", "tests/test_headless_smoke.py",
        "pytest.ini", "requirements.txt", "requirements-dev.txt", ".gitignore", "README.md",
    ]


def _scaffold_python(root: pathlib.Path, name: str) -> list[str]:
    slug = _slugify(name)
    pkg = _ensure_identifier(slug.replace("-", "_"), "app")

    _write(root / "src" / pkg / "__init__.py", f'"""{name}."""\n\n__version__ = "0.1.0"\n')
    _write(root / "src" / pkg / "main.py", f'''"""Main entry point."""


def greet(who: str = "world") -> str:
    return f"{{who}} ready"


def main() -> None:
    print(greet("{name}"))


if __name__ == "__main__":
    main()
''')
    _write(root / "tests" / "__init__.py", "")
    _write(root / "tests" / "test_main.py", f'''from {pkg}.main import greet


def test_greet_default():
    assert greet() == "world ready"


def test_greet_custom():
    assert greet("Ahmed") == "Ahmed ready"
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

## Running it

```bash
pip install -e ".[dev]"
python -m {pkg}.main
```

## Tests

```bash
pytest
```

## Code quality

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
    _write(root / "app" / "core" / "config.py", f'''"""Application settings — loaded from environment variables (.env)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "{name}"
    debug: bool = False
    log_level: str = "INFO"


settings = Settings()
''')
    _write(root / "app" / "core" / "logging.py", '''"""Structured logging setup — called once at application start."""

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
    _write(root / "app" / "services" / "example_service.py", '''"""An example business-logic layer — deliberately separate from the routes so
you can test it without starting an HTTP server."""


def build_welcome_message(app_name: str) -> str:
    return f"{app_name} API ready"
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

## Running it

```bash
pip install -e ".[dev]"
cp .env.example .env
uvicorn app.main:app --reload
```

## Tests

```bash
pytest
```

## Code quality

```bash
ruff check .
black --check .
mypy app
```

## Structure

```
app/
  core/      settings and logging
  api/routes/  endpoints
  models/    Pydantic schemas
  services/  business logic — separate from the HTTP layer
tests/       real pytest tests (TestClient)
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
           "or run each part on its own, following `backend/README.md` and `frontend/README.md`.\n")
    files += ["docker-compose.yml", "README.md"]
    return files


def _scaffold_docker(root: pathlib.Path, name: str) -> list[str]:
    _write(root / "Dockerfile", '''# ---- build stage (builder) ----
# Dependencies install into a separate user directory so the final image
# carries no build tools (compilers and the like) or leftover temporaries.
FROM python:3.12-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ---- final stage (runtime) — a clean, small image ----
FROM python:3.12-slim
WORKDIR /app

# Non-root user — running a container as root is poor security practice
RUN useradd --create-home --uid 1000 appuser
COPY --from=builder /root/.local /home/appuser/.local
COPY . .
RUN chown -R appuser:appuser /app
USER appuser
ENV PATH=/home/appuser/.local/bin:$PATH

HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD python -c "print('ok')" || exit 1

# Change this line to your project's real entry point (e.g. uvicorn app.main:app --host 0.0.0.0)
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
    _write(root / "src" / "example.py", '''"""Example code so the tests have something real to test."""


def add(a: int, b: int) -> int:
    return a + b


def divide(a: float, b: float) -> float:
    if b == 0:
        raise ValueError("division by zero is not allowed")
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
pytest                # test on the current Python, with a coverage report
tox                   # test across every Python in the [tox] envlist
```
''')
    return ["src/example.py", "tests/test_example.py", "pytest.ini", "tox.ini", "requirements-dev.txt", "README.md"]


def _scaffold_ml(root: pathlib.Path, name: str) -> list[str]:
    slug = _slugify(name)
    pkg = _ensure_identifier(slug.replace("-", "_"), "app")

    _write(root / "src" / pkg / "__init__.py", f'"""{name} — ML pipeline."""\n\n__version__ = "0.1.0"\n')
    _write(root / "src" / pkg / "data.py", '''"""Loading and splitting the data — a separate layer so you can swap in real
data without touching the training or evaluation code."""

from sklearn.datasets import load_iris
from sklearn.model_selection import train_test_split


def load_data(test_size: float = 0.2, random_state: int = 42):
    dataset = load_iris()
    return train_test_split(
        dataset.data, dataset.target, test_size=test_size, random_state=random_state
    )
''')
    _write(root / "src" / pkg / "model.py", '''"""Model definition — kept apart from training so you can try different models easily."""

from sklearn.ensemble import RandomForestClassifier


def build_model(random_state: int = 42) -> RandomForestClassifier:
    return RandomForestClassifier(random_state=random_state)
''')
    _write(root / "src" / pkg / "train.py", f'''"""The training loop."""

from {pkg}.data import load_data
from {pkg}.model import build_model


def train():
    X_train, X_test, y_train, y_test = load_data()
    model = build_model()
    model.fit(X_train, y_train)
    return model, X_test, y_test
''')
    _write(root / "src" / pkg / "evaluate.py", '''"""Evaluating the model after training."""

from sklearn.metrics import accuracy_score


def evaluate(model, X_test, y_test) -> float:
    predictions = model.predict(X_test)
    return accuracy_score(y_test, predictions)
''')
    _write(root / "src" / pkg / "__main__.py", f'''"""Entry point: python -m {pkg}"""

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
    assert accuracy > 0.7  # Iris with RandomForest usually clears 90%
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

## Running it

```bash
pip install -e ".[dev]"
python -m {pkg}
```

## Tests

```bash
pytest
```

## Structure

```
src/{pkg}/
  data.py      loading and splitting the data
  model.py     model definition
  train.py     the training loop
  evaluate.py  evaluation
data/          your real data (empty for now — a placeholder)
models/        saved trained models
```

Replace `src/{pkg}/data.py` with your real data instead of the Iris demo dataset.
''')
    return [
        f"src/{pkg}/data.py", f"src/{pkg}/model.py", f"src/{pkg}/train.py",
        f"src/{pkg}/evaluate.py", f"src/{pkg}/__main__.py", "tests/test_pipeline.py",
        "pyproject.toml", ".gitignore", "README.md",
    ]


def _scaffold_quantum(root: pathlib.Path, name: str) -> list[str]:
    _write(root / "circuit.py", '''"""circuit.py — building a Bell state (quantum entanglement) circuit, kept
apart from any simulator. Same separation of logic from execution as the
embedded and game scaffolds, so tests can check the circuit structure itself
without running a simulator every time."""
from qiskit import QuantumCircuit


def build_bell_circuit() -> QuantumCircuit:
    qc = QuantumCircuit(2, 2)
    qc.h(0)
    qc.cx(0, 1)
    qc.measure([0, 1], [0, 1])
    return qc
''')
    _write(root / "bell_state.py", f'''"""{name} — Qiskit starter: genuinely runs a Bell state (entanglement)
circuit on a local simulator (AerSimulator) — no cloud service and no IBM
Quantum account."""
from qiskit_aer import AerSimulator

from circuit import build_bell_circuit


def main():
    qc = build_bell_circuit()
    simulator = AerSimulator()
    result = simulator.run(qc, shots=1000).result()
    counts = result.get_counts()
    print(f"measurement results: {{counts}}")


if __name__ == "__main__":
    main()
''')
    _write(root / "tests" / "test_circuit.py", '''from circuit import build_bell_circuit


def test_circuit_has_expected_gate_structure():
    qc = build_bell_circuit()
    gate_names = [instr.operation.name for instr in qc.data]
    assert gate_names == ["h", "cx", "measure", "measure"]


def test_circuit_measures_both_qubits():
    qc = build_bell_circuit()
    assert qc.num_qubits == 2
    assert qc.num_clbits == 2
''')
    _write(root / "tests" / "test_bell_state_simulation.py", '''"""Runs the circuit on AerSimulator and checks the defining property of
entanglement: measurements must come out '00' or '11' only, never '01' or
'10'. That is what a Bell state *is* — not merely that the code ran."""
from qiskit_aer import AerSimulator

from circuit import build_bell_circuit


def test_bell_state_only_produces_correlated_outcomes():
    qc = build_bell_circuit()
    simulator = AerSimulator()
    result = simulator.run(qc, shots=500).result()
    counts = result.get_counts()
    assert set(counts.keys()) <= {"00", "11"}
    assert "00" in counts or "11" in counts
''')
    _write(root / "pytest.ini", "[pytest]\ntestpaths = tests\npythonpath = .\n")
    _write(root / "requirements.txt", "qiskit>=1.0.0\nqiskit-aer>=0.14.0\n")
    _write(root / "requirements-dev.txt", "-r requirements.txt\npytest>=8.0.0\n")
    _write(root / ".gitignore", "__pycache__/\n*.pyc\n.pytest_cache/\n")
    _write(root / "README.md", f'''# {name} — Qiskit Bell State Starter

```bash
pip install -r requirements.txt
python bell_state.py     # actually runs the circuit and prints the measurements
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest    # circuit structure, plus a real check of entanglement via AerSimulator
```

The circuit-building logic in `circuit.py` is separate from execution
(`bell_state.py`) so it can be tested directly.
''')
    return [
        "circuit.py", "bell_state.py", "tests/test_circuit.py",
        "tests/test_bell_state_simulation.py", "pytest.ini",
        "requirements.txt", "requirements-dev.txt", ".gitignore", "README.md",
    ]


def _scaffold_blockchain(root: pathlib.Path, name: str) -> list[str]:
    safe = _ensure_identifier("".join(c for c in name if c.isalnum()), "MyContract")
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
        "name": safe.lower(),
        "version": "1.0.0",
        "scripts": {"test": "hardhat test", "compile": "hardhat compile"},
        "devDependencies": {
            "hardhat": "^2.22.0",
            "@nomicfoundation/hardhat-toolbox": "^5.0.0",
        },
    }, indent=2))
    _write(root / "hardhat.config.js", '''require("@nomicfoundation/hardhat-toolbox");

/** @type import('hardhat/config').HardhatUserConfig */
module.exports = {
  solidity: "0.8.20",
};
''')
    _write(root / "test" / f"{safe}.test.js", f'''const {{ expect }} = require("chai");

describe("{safe}", function () {{
  async function deploy(initialMessage) {{
    const [owner, other] = await ethers.getSigners();
    const Contract = await ethers.getContractFactory("{safe}");
    const contract = await Contract.deploy(initialMessage);
    await contract.waitForDeployment();
    return {{ contract, owner, other }};
  }}

  it("records the initial message and owner on deploy", async function () {{
    const {{ contract, owner }} = await deploy("hello");
    expect(await contract.message()).to.equal("hello");
    expect(await contract.owner()).to.equal(owner.address);
  }});

  it("lets the owner change the message", async function () {{
    const {{ contract }} = await deploy("hello");
    await contract.setMessage("updated");
    expect(await contract.message()).to.equal("updated");
  }});

  it("stops anyone else changing the message", async function () {{
    const {{ contract, other }} = await deploy("hello");
    await expect(contract.connect(other).setMessage("nope")).to.be.revertedWith("not owner");
  }});
}});
''')
    _write(root / ".gitignore", "node_modules/\nartifacts/\ncache/\ncoverage/\ncoverage.json\n.env\n")
    _write(root / "README.md", f'''# {name} — Smart Contract ({safe})

```bash
npm install
npx hardhat compile
npx hardhat test
```

The contract is in `contracts/{safe}.sol`, and the tests (deploy, changing
the message, blocking non-owners) are in `test/{safe}.test.js` using Hardhat,
ethers.js and chai via `@nomicfoundation/hardhat-toolbox`.
''')
    return [
        f"contracts/{safe}.sol", "package.json", "hardhat.config.js",
        f"test/{safe}.test.js", ".gitignore", "README.md",
    ]


def _scaffold_embedded(root: pathlib.Path, name: str) -> list[str]:
    _write(root / "hal.h", '''#ifndef HAL_H
#define HAL_H

/* HAL (Hardware Abstraction Layer): each board supplies its own
 * implementation of gpio_set/delay_ms — direct register writes, or a HAL
 * library from the MCU vendor. The program logic (blink.c) neither knows nor
 * cares how the pin actually moves, and that is exactly what lets us test it
 * on the host with no real hardware. */
typedef struct {
    void (*gpio_set)(int pin, int value);
    void (*delay_ms)(int ms);
} hal_t;

#endif
''')
    _write(root / "blink.h", '''#ifndef BLINK_H
#define BLINK_H

#include <stdint.h>
#include "hal.h"

typedef struct {
    int led_on;
    uint32_t elapsed_ms;
} blink_state_t;

void blink_init(blink_state_t *state);
void blink_step(blink_state_t *state, const hal_t *hal, uint32_t dt_ms);

#endif
''')
    _write(root / "blink.c", f'''/* {name} — the pure blink logic (toggle the LED every INTERVAL_MS), kept
 * apart from any hardware detail so it can be tested in test/test_blink.c
 * with no simulator and no real board. */
#include "blink.h"

#define LED_PIN 13
#define INTERVAL_MS 500

void blink_init(blink_state_t *state) {{
    state->led_on = 0;
    state->elapsed_ms = 0;
}}

void blink_step(blink_state_t *state, const hal_t *hal, uint32_t dt_ms) {{
    state->elapsed_ms += dt_ms;
    if (state->elapsed_ms >= INTERVAL_MS) {{
        state->elapsed_ms = 0;
        state->led_on = !state->led_on;
        hal->gpio_set(LED_PIN, state->led_on);
    }}
}}
''')
    _write(root / "main.c", f'''/* {name} — entry point: wires the blink.c logic to the target board's real
 * gpio_set/delay_ms. Building actual firmware needs a cross toolchain such as
 * arm-none-eabi-gcc. This file stays deliberately freestanding (no ordinary
 * libc) so it compiles anywhere. */
#include <stdint.h>
#include "hal.h"
#include "blink.h"

void gpio_set(int pin, int value);
void delay_ms(int ms);

int main(void) {{
    hal_t hal = {{ gpio_set, delay_ms }};
    blink_state_t state;
    blink_init(&state);
    while (1) {{
        blink_step(&state, &hal, 10);
        hal.delay_ms(10);
    }}
    return 0;
}}
''')
    _write(root / "test" / "test_blink.c", '''/* A real test that runs on the host — it uses a mock hal_t that records every
 * gpio_set call, and confirms the LED toggles exactly every 500ms, with no
 * hardware at all. */
#include <assert.h>
#include <stdio.h>
#include "../blink.h"

static int gpio_calls = 0;
static int last_value = -1;

static void mock_gpio_set(int pin, int value) {
    (void)pin;
    last_value = value;
    gpio_calls++;
}

static void mock_delay_ms(int ms) {
    (void)ms;
}

int main(void) {
    hal_t hal = { mock_gpio_set, mock_delay_ms };
    blink_state_t state;
    blink_init(&state);

    blink_step(&state, &hal, 100);
    assert(gpio_calls == 0 && "nothing has reached 500ms yet");

    blink_step(&state, &hal, 450);
    assert(gpio_calls == 1);
    assert(last_value == 1);

    blink_step(&state, &hal, 500);
    assert(gpio_calls == 2);
    assert(last_value == 0);

    printf("blink logic ok — %d correct gpio_set calls\\n", gpio_calls);
    return 0;
}
''')
    _write(root / "Makefile", """CC = gcc
CFLAGS = -Wall -Wextra -std=c11

# Checks that main.c and blink.c compile (compile-only) in freestanding mode.
# Real firmware needs a genuine cross toolchain such as arm-none-eabi-gcc.
check:
\t$(CC) -ffreestanding -std=c11 -c main.c -o /dev/null
\t$(CC) -ffreestanding -std=c11 -c blink.c -o /dev/null
\t@echo "✅ main.c and blink.c compile (compile-only, freestanding)"

# Tests the blink.c logic for real on the host — not on hardware
test:
\t$(CC) $(CFLAGS) test/test_blink.c blink.c -o test/test_blink
\t./test/test_blink

clean:
\trm -f test/test_blink

.PHONY: check test clean
""")
    _write(root / "README.md", f'''# {name} — Embedded/MCU Starter

A simple HAL (Hardware Abstraction Layer): the blink logic in `blink.c` is
fully separate from hardware detail (`hal.h`), so it can be tested on the
host with no real board.

```bash
make check   # confirms main.c and blink.c compile (freestanding)
make test    # builds and runs a real test of the blink.c logic on the host
```

For real firmware on a real board you need a cross toolchain (such as
`arm-none-eabi-gcc`) and your board's actual `gpio_set` and `delay_ms`.
''')
    _write(root / ".gitignore", "*.o\n*.elf\n*.bin\n*.hex\ntest/test_blink\n")
    return ["hal.h", "blink.h", "blink.c", "main.c", "test/test_blink.c", "Makefile", "README.md", ".gitignore"]


def _scaffold_kernel_module(root: pathlib.Path, name: str) -> list[str]:
    safe = _ensure_identifier("".join(c.lower() if c.isalnum() else "_" for c in name), "hello_module")
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
    _write(root / ".gitignore", (
        "*.o\n*.ko\n*.mod\n*.mod.c\n*.mod.o\n*.symvers\n*.order\n"
        "*.cmd\n.tmp_versions/\n.cache.mk\nModule.symvers\nmodules.order\n"
    ))
    _write(root / "README.md", f'''# {name} — Linux Kernel Module Starter

## Building (needs kernel headers — `apt install linux-headers-$(uname -r)`)

```bash
make            # builds {safe}.ko
```

## Loading and running it

```bash
sudo insmod {safe}.ko    # load the module
dmesg | tail              # look for "module loaded" in the kernel log
sudo rmmod {safe}         # unload the module
dmesg | tail               # look for "module unloaded"
```

## Cleaning up

```bash
make clean
```

**Safety note:** kernel modules run with kernel privileges (ring 0) — a bug
here can hang or corrupt the entire system, unlike an ordinary user-space
crash. Test it in a VM until you trust it.
''')
    return [f"{safe}.c", "Makefile", ".gitignore", "README.md"]


def _scaffold_multiplayer_server(root: pathlib.Path, name: str) -> list[str]:
    _write(root / "server.py", f'''"""{name} — a basic multiplayer server (asyncio TCP broadcast)."""
import asyncio

clients: set[asyncio.StreamWriter] = set()


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    clients.add(writer)
    addr = writer.get_extra_info("peername")
    print(f"connected: {{addr}}")
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
    print(f"listening on {{host}}:{{port}}")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
''')
    _write(root / "client.py", '''"""A simple client for connecting to the server."""
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
  <script src="src/main.js"></script>
</head>
<body>
  <a-scene>
    <a-box position="0 1.5 -3" rotation="0 45 0" color="#4f6ef7"
           cursor-listener class="clickable"></a-box>
    <a-sky color="#ECECEC"></a-sky>
    <a-entity camera look-controls position="0 1.6 0">
      <a-cursor></a-cursor>
    </a-entity>
  </a-scene>
</body>
</html>
''')
    _write(root / "src" / "main.js", '''// A small component: each click on the box moves it to the next colour in a
// fixed cycle. It shows the basics plainly — registering a component,
// listening for a click, and changing the colour property on interaction,
// with no library beyond A-Frame itself.
AFRAME.registerComponent("cursor-listener", {
  init: function () {
    const colors = ["#4f6ef7", "#f74f6e", "#4ff7a0", "#f7d24f"];
    let index = 0;
    this.el.addEventListener("click", () => {
      index = (index + 1) % colors.length;
      this.el.setAttribute("color", colors[index]);
    });
  },
});
''')
    _write(root / "package.json", json.dumps({
        "name": _slugify(name),
        "version": "1.0.0",
        "scripts": {"start": "http-server -p 8080"},
        "devDependencies": {"http-server": "^14.1.0"},
    }, indent=2))
    _write(root / ".gitignore", "node_modules/\n")
    _write(root / "README.md", f'''# {name} — WebXR (A-Frame) Starter

```bash
npm install
npm start        # serves it on http://localhost:8080
```

Open the link in a browser, or a WebXR-capable headset — click the box and it
changes colour. The logic is in `src/main.js`, an A-Frame component registered
as `cursor-listener`.
''')
    return ["index.html", "src/main.js", "package.json", ".gitignore", "README.md"]


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
    _write(root / "story.ink", f'''// {name} — a basic branching story (Ink format: inklestudios.com/ink)
-> start

=== start ===
The story starts here.

* [Choice A] -> choice_a
* [Choice B] -> choice_b

=== choice_a ===
You chose A.
-> END

=== choice_b ===
You chose B.
-> END
''')
    return ["story.ink"]


_SCAFFOLDS = {
    "web": (_scaffold_web, "static website — frontend (HTML/CSS/JS)"),
    "backend": (_scaffold_backend, "backend server (FastAPI) — runs immediately"),
    "fullstack": (_scaffold_fullstack, "full-stack project (frontend and backend together)"),
    "android": (_scaffold_android, "Android project (Kotlin/Gradle) — opens in Android Studio"),
    "ios": (_scaffold_ios, "iOS project (SwiftUI) — needs Xcode on a Mac"),
    "game": (_scaffold_game, "2D game with Pygame (runs immediately: pip install pygame && python main.py)"),
    "python": (_scaffold_python, "general Python project"),
    "docker": (_scaffold_docker, "Dockerfile and .dockerignore for a Python project"),
    "ci": (_scaffold_ci, "a real GitHub Actions CI workflow"),
    "pytest": (_scaffold_pytest, "pytest test skeleton"),
    "ml": (_scaffold_ml, "AI/ML model training (scikit-learn) — runs immediately"),
    "quantum": (_scaffold_quantum, "quantum circuit (Qiskit) — a Bell state that runs immediately"),
    "blockchain": (_scaffold_blockchain, "smart contract (Solidity) plus Hardhat setup"),
    "embedded": (_scaffold_embedded, "embedded C skeleton (GPIO blink pattern)"),
    "kernel_module": (_scaffold_kernel_module, "basic Linux kernel module — needs kernel headers to build"),
    "multiplayer_server": (_scaffold_multiplayer_server, "multiplayer server (asyncio) — runs immediately"),
    "arvr": (_scaffold_arvr, "WebXR project (A-Frame, free and open source)"),
    "screenplay": (_scaffold_screenplay, "film screenplay in the standard Fountain format"),
    "ink_story": (_scaffold_ink_story, "branching story in Ink format (the same tool real games like 80 Days use)"),
}


def _cmd_scaffold(ctx) -> str:
    if len(ctx.args) < 2:
        types = "\n".join(f"  {k} — {desc}" for k, (_, desc) in _SCAFFOLDS.items())
        return f"usage: scaffold <type> <project_name> [output_dir]\nAvailable types:\n{types}"
    kind, name = ctx.args[0], ctx.args[1]
    if kind not in _SCAFFOLDS:
        return f"❌ unknown type: {kind} (available: {', '.join(_SCAFFOLDS)})"
    name_error = _validate_name(name)
    if name_error:
        return name_error
    base = pathlib.Path(ctx.args[2]) if len(ctx.args) > 2 else pathlib.Path(".")
    root = base / name
    if root.exists() and any(root.iterdir()):
        return f"❌ {root} already exists and is not empty — pick another name or location"
    fn, _ = _SCAFFOLDS[kind]
    try:
        files = fn(root, name)
    except OSError as e:
        return f"❌ could not create the files: {e}"
    listing = "\n".join(f"  📄 {f}" for f in files)
    return f"✅ created a {kind} project at {root}:\n{listing}"


def register(engine):
    engine.registry.register(
        "scaffold", _cmd_scaffold,
        "scaffold <web|android|ios|game|python> <name> [dir] — generate a ready-to-run project skeleton",
    )
