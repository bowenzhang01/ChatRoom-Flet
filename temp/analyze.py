"""Analyze the build and app for grey-screen root cause."""
import os, sys, json, zipfile, re, ast

OUT = "E:/dorm-flet-build/temp/result.txt"
LINES = []

def log(s):
    LINES.append(s)
    print(s)

# 1. Check serious_python_android version resolved
log("=== serious_python version ===")
try:
    with open("E:/dorm-flet-build/build/flutter/pubspec.lock") as f:
        content = f.read()
    for line in content.split("\n"):
        if "serious_python" in line.lower():
            log(line.strip())
except Exception as e:
    log(f"Error: {e}")

# 2. Find all imports
log("\n=== All imports in project ===")
imports = set()
for root, dirs, files in os.walk("E:/dorm-flet-build"):
    dirs[:] = [d for d in dirs if d not in (".git", "build", "__pycache__", ".flet")]
    for f in files:
        if f.endswith(".py"):
            path = os.path.join(root, f)
            try:
                with open(path, encoding="utf-8") as fp:
                    for line in fp:
                        line = line.strip()
                        if line.startswith("import ") or line.startswith("from "):
                            # Extract module name
                            if line.startswith("from "):
                                parts = line.split()
                                if len(parts) >= 2:
                                    mod = parts[1]
                                    if mod.startswith("."):
                                        continue  # relative import
                                    imports.add(mod.split(".")[0])
                            elif line.startswith("import "):
                                parts = line.split()[1:]
                                for p in parts:
                                    p = p.split(" as ")[0].strip(",")
                                    if p:
                                        imports.add(p.split(".")[0])
            except:
                pass

stdlib = {"flet", "json", "os", "sys", "re", "datetime", "pathlib", "typing", "math",
          "hashlib", "base64", "tempfile", "shutil", "traceback", "logging", "time",
          "threading", "uuid", "copy", "textwrap", "collections", "io", "itertools",
          "random", "string", "urllib", "html", "asyncio", "subprocess", "contextlib",
          "dataclasses", "enum", "functools", "getpass", "glob", "inspect"}
known_pip = {"flet", "httpx", "msgpack", "oauthlib", "repath", "certifi", "h11", "httpcore",
             "idna", "six", "typing_extensions"}

for imp in sorted(imports):
    tag = ""
    if imp in stdlib:
        tag = " [stdlib]"
    elif imp in known_pip:
        tag = " [pip]"
    else:
        tag = " [UNKNOWN - may be missing!]"
    log(f"  {imp}{tag}")

# 3. Check sitepackages in APK
log("\n=== Bundled site packages ===")
try:
    with zipfile.ZipFile("E:/dorm-flet-build/build/apk/dorm-flet.apk") as z:
        data = z.read("assets/sitepackages.zip")
    os.makedirs("E:/dorm-flet-build/temp", exist_ok=True)
    with open("E:/dorm-flet-build/temp/_sp.zip", "wb") as f:
        f.write(data)
    with zipfile.ZipFile("E:/dorm-flet-build/temp/_sp.zip") as z:
        pkgs = set()
        for name in z.namelist():
            top = name.split("/")[0]
            if top:
                pkgs.add(top)
        for p in sorted(pkgs):
            log(f"  {p}")
except Exception as e:
    log(f"Error: {e}")

# 4. Check app.zip contents (verify all modules)
log("\n=== Bundled app modules (.pyc) ===")
try:
    with zipfile.ZipFile("E:/dorm-flet-build/build/apk/dorm-flet.apk") as z:
        data = z.read("assets/app.zip")
    with open("E:/dorm-flet-build/temp/_app.zip", "wb") as f:
        f.write(data)
    with zipfile.ZipFile("E:/dorm-flet-build/temp/_app.zip") as z:
        pycs = [n for n in z.namelist() if n.endswith(".pyc")]
        dirs = set()
        for n in pycs:
            parts = n.split("/")
            if len(parts) >= 2:
                dirs.add(parts[0])
        for d in sorted(dirs):
            log(f"  {d}/ ({len([n for n in pycs if n.startswith(d+'/')])} .pyc)")
        log(f"  root ({len([n for n in pycs if '/' not in n[1:]])} .pyc)")
        log(f"  TOTAL: {len(pycs)} .pyc files")
except Exception as e:
    log(f"Error: {e}")

# 5. Check extract.zip
log("\n=== extract.zip ===")
try:
    with zipfile.ZipFile("E:/dorm-flet-build/build/apk/dorm-flet.apk") as z:
        data = z.read("assets/extract.zip")
    log(f"  Size: {len(data)} bytes")
    if len(data) > 0:
        with open("E:/dorm-flet-build/temp/_ext.zip", "wb") as f:
            f.write(data)
        with zipfile.ZipFile("E:/dorm-flet-build/temp/_ext.zip") as z:
            for n in sorted(z.namelist())[:20]:
                log(f"  {n}")
except Exception as e:
    log(f"Error: {e}")

# 6. Check AndroidManifest for extractNativeLibs
log("\n=== AndroidManifest key info ===")
try:
    with zipfile.ZipFile("E:/dorm-flet-build/build/apk/dorm-flet.apk") as z:
        manifest = z.read("AndroidManifest.xml").decode("utf-8", errors="replace")
    for line in manifest.split("\n"):
        if "extract" in line.lower() or "minSdk" in line.lower() or "targetSdk" in line.lower():
            log(f"  {line.strip()}")
except Exception as e:
    log(f"Error: {e}")

# 7. Check if the code changes introduced runtime errors
log("\n=== Syntax check all modified files ===")
mod_files = [
    "app/views/archives_view.py",
    "app/views/chat_view.py", 
    "app/views/profiles_view.py",
    "app/components/mode_chips.py",
    "app/components/reorderable_list.py",
    "app/components/transport_bar.py",
]
for f in mod_files:
    path = f"E:/dorm-flet-build/{f}"
    try:
        with open(path, encoding="utf-8") as fp:
            ast.parse(fp.read())
        log(f"  {f} ✓")
    except SyntaxError as e:
        log(f"  {f} ✗ SYNTAX ERROR: {e}")

# 8. Check if there are flet version-specific issues
log("\n=== Check for potentially problematic flet API usage ===")
problematic = [
    "ScrollMode.HIDDEN",  # Available since flet 0.24?
    "TextOverflow.ELLIPSIS",
]
for f in mod_files:
    path = f"E:/dorm-flet-build/{f}"
    try:
        with open(path, encoding="utf-8") as fp:
            content = fp.read()
        for p in problematic:
            if p in content:
                log(f"  {f}: uses {p}")
    except:
        pass

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(LINES))
print(f"\nDone! Results written to {OUT}")
