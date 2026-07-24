"""
scaffold_plugin.py — سقالات مشاريع (project scaffolding) لأنواع تطوير
مختلفة: ويب، أندرويد، iOS، ألعاب (Pygame)، بايثون عام. بيولّد ملفات
بداية حقيقية وشغالة — مش بديل عن الـ SDK/IDE الرسمي لكل منصة (Xcode
لـ iOS محتاج ماك، Android Studio لأندرويد)، لكنه بيوفر وقت الإعداد.
"""
from __future__ import annotations

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


_SCAFFOLDS = {
    "web": (_scaffold_web, "موقع ويب ثابت (HTML/CSS/JS)"),
    "android": (_scaffold_android, "مشروع أندرويد (Kotlin/Gradle) — يفتح في Android Studio"),
    "ios": (_scaffold_ios, "مشروع iOS (SwiftUI) — يحتاج Xcode على ماك"),
    "game": (_scaffold_game, "لعبة 2D بـ Pygame (شغالة فوراً: pip install pygame && python main.py)"),
    "python": (_scaffold_python, "مشروع بايثون عام"),
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
