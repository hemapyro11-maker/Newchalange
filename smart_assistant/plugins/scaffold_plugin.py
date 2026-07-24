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


def _scaffold_web(root: pathlib.Path, name: str) -> list[str]:
    _write(root / "index.html", (
        '<!doctype html>\n<html lang="ar" dir="rtl">\n<head>\n'
        '  <meta charset="utf-8">\n  <title>' + name + '</title>\n'
        '  <link rel="stylesheet" href="style.css">\n</head>\n<body>\n'
        '  <h1>' + name + '</h1>\n  <p>ابدأ هنا.</p>\n'
        '  <script src="script.js"></script>\n</body>\n</html>\n'
    ))
    _write(root / "style.css", "body { font-family: sans-serif; margin: 2rem; }\n")
    _write(root / "script.js", f"console.log('{name} جاهز');\n")
    return ["index.html", "style.css", "script.js"]


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
    _write(root / "main.py", f'"""{name}"""\n\n\ndef main():\n    print("{name} جاهز")\n\n\nif __name__ == "__main__":\n    main()\n')
    _write(root / "requirements.txt", "")
    _write(root / "README.md", f"# {name}\n")
    return ["main.py", "requirements.txt", "README.md"]


def _scaffold_backend(root: pathlib.Path, name: str) -> list[str]:
    _write(root / "main.py", f'''"""{name} — FastAPI backend starter."""
from fastapi import FastAPI

app = FastAPI(title="{name}")


@app.get("/health")
def health():
    return {{"status": "ok"}}


@app.get("/")
def root():
    return {{"message": "{name} API جاهز"}}
''')
    _write(root / "requirements.txt", "fastapi>=0.110.0\nuvicorn>=0.27.0\n")
    _write(root / "README.md", f"# {name}\n\n```bash\npip install -r requirements.txt\nuvicorn main:app --reload\n```\n")
    return ["main.py", "requirements.txt", "README.md"]


def _scaffold_fullstack(root: pathlib.Path, name: str) -> list[str]:
    files = [f"frontend/{f}" for f in _scaffold_web(root / "frontend", name)]
    files += [f"backend/{f}" for f in _scaffold_backend(root / "backend", name)]
    return files


def _scaffold_docker(root: pathlib.Path, name: str) -> list[str]:
    _write(root / "Dockerfile", '''FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "main.py"]
''')
    _write(root / ".dockerignore", "__pycache__/\n*.pyc\n.venv/\n.git/\n")
    return ["Dockerfile", ".dockerignore"]


def _scaffold_ci(root: pathlib.Path, name: str) -> list[str]:
    _write(root / ".github" / "workflows" / "ci.yml", '''name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
      - run: pip install pytest
      - run: pytest
''')
    return [".github/workflows/ci.yml"]


def _scaffold_pytest(root: pathlib.Path, name: str) -> list[str]:
    _write(root / "tests" / "test_example.py", '''def test_example():
    assert 1 + 1 == 2
''')
    _write(root / "pytest.ini", "[pytest]\ntestpaths = tests\n")
    return ["tests/test_example.py", "pytest.ini"]


def _scaffold_ml(root: pathlib.Path, name: str) -> list[str]:
    _write(root / "train.py", f'''"""{name} — scikit-learn training starter (Iris classifier)."""
from sklearn.datasets import load_iris
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score


def main():
    data = load_iris()
    X_train, X_test, y_train, y_test = train_test_split(
        data.data, data.target, test_size=0.2, random_state=42
    )
    model = RandomForestClassifier(random_state=42)
    model.fit(X_train, y_train)
    predictions = model.predict(X_test)
    print(f"accuracy: {{accuracy_score(y_test, predictions):.3f}}")


if __name__ == "__main__":
    main()
''')
    _write(root / "requirements.txt", "scikit-learn>=1.4.0\n")
    return ["train.py", "requirements.txt"]


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
