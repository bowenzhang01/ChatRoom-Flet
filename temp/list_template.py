import os, json

template = r"E:\dorm-flet-build\temp\template\{{cookiecutter.out_dir}}"
if os.path.isdir(template):
    files = os.listdir(template)
    with open(r"E:\dorm-flet-build\temp\template_files.txt", "w") as f:
        for fn in sorted(files):
            f.write(fn + "\n")
    print("OK:", len(files), "files")
else:
    print("NOT FOUND, listing parent:")
    parent = r"E:\dorm-flet-build\temp\template"
    for root, dirs, files in os.walk(parent):
        for fn in files[:30]:
            print(os.path.relpath(os.path.join(root, fn), parent))
