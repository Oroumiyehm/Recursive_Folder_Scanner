import os
import sys
import json
import fnmatch
from pathlib import Path
from datetime import datetime

# History file stored in the user's home directory
HISTORY_FILE = Path.home() / ".folder_scanner_history.json"


def load_history():
    """Load the whole history dict from disk"""
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_history(data):
    """Save the history dict to disk"""
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"Could not save history: {e}")


def normalize_extensions(raw):
    """Turn 'py, sql .js' into ['.py', '.sql', '.js']"""
    parts = raw.replace(",", " ").split()
    exts = []
    for p in parts:
        p = p.strip().lower()
        if not p:
            continue
        if not p.startswith("."):
            p = "." + p
        exts.append(p)
    return exts


def normalize_names(raw):
    """Turn 'a.txt, %secret%' into ['a.txt', '%secret%'] lowercased"""
    parts = raw.replace(",", " ").split()
    return [p.strip().lower() for p in parts if p.strip()]


def matches_any(name, patterns):
    """SQL-style match: '%' is a wildcard. '*' also works."""
    name = name.lower()
    for p in patterns:
        glob_pat = p.replace("%", "*")
        if fnmatch.fnmatch(name, glob_pat):
            return True
    return False


def format_size(num_bytes):
    """Human-readable size string"""
    size = float(num_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024 or unit == "TB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


def parse_size_limit(raw):
    """Parse '500 KB', '1.5MB', '1024' into bytes. Bare number = MB. 0 = no limit."""
    raw = raw.strip().lower()
    if not raw or raw == "none":
        return 0
    units = {
        "b": 1,
        "kb": 1024,
        "mb": 1024 ** 2,
        "gb": 1024 ** 3,
        "tb": 1024 ** 4,
    }
    num, unit = "", ""
    for ch in raw:
        if ch.isdigit() or ch == ".":
            num += ch
        elif not ch.isspace():
            unit += ch
    try:
        value = float(num)
    except ValueError:
        return 0
    multiplier = units.get(unit, units["mb"])  # default unit is MB
    return int(value * multiplier)


def ask_list(label, example, history_key, history, normalizer):
    """Generic prompt that offers last-used values as a default"""
    last = history.get(history_key, [])
    if last:
        prompt = (
            f"\n{label}\n"
            f"Enter values (e.g. {example}) or press Enter to reuse "
            f"[{', '.join(last)}]\n"
            f"(type 'none' to clear): "
        )
    else:
        prompt = f"\n{label}\nEnter values (e.g. {example}) or press Enter to skip: "

    raw = input(prompt).strip()
    if not raw:
        return last
    if raw.lower() == "none":
        return []
    return normalizer(raw)


def ask_size_limit(history):
    """Ask for the max file size whose contents will be read"""
    last = history.get("size_limit", 0)
    if last:
        prompt = (
            "\nMax file size to READ contents (larger files are listed but not read).\n"
            f"Enter a value (e.g. 500KB, 1.5MB) or press Enter to reuse "
            f"[{format_size(last)}]\n"
            "(type 'none' for no limit): "
        )
    else:
        prompt = (
            "\nMax file size to READ contents (larger files are listed but not read).\n"
            "Enter a value (e.g. 500KB, 1.5MB) or press Enter for no limit: "
        )

    raw = input(prompt).strip()
    if not raw:
        return last
    if raw.lower() == "none":
        return 0
    return parse_size_limit(raw)


def ask_settings():
    """Ask for the extensions to read plus all exclusion rules"""
    history = load_history()

    target_exts = ask_list(
        "Which file types should I read the contents of?",
        ".py,.sql,.js",
        "extensions",
        history,
        normalize_extensions,
    )

    size_limit = 0
    if target_exts:
        size_limit = ask_size_limit(history)

    exclude_folders = ask_list(
        "Which FOLDER names should I skip? (use % or * as wildcard)",
        "%git%,node_%,__pycache__",
        "exclude_folders",
        history,
        normalize_names,
    )
    exclude_files = ask_list(
        "Which FILE names should I skip? (use % or * as wildcard)",
        "%secret%,config.json,test_%",
        "exclude_files",
        history,
        normalize_names,
    )
    exclude_exts = ask_list(
        "Which file TYPES should I skip?",
        ".log,.pyc,.tmp",
        "exclude_exts",
        history,
        normalize_extensions,
    )

    save_history({
        "extensions": target_exts,
        "size_limit": size_limit,
        "exclude_folders": exclude_folders,
        "exclude_files": exclude_files,
        "exclude_exts": exclude_exts,
    })

    return target_exts, exclude_folders, exclude_files, exclude_exts, size_limit


def get_unique_filename(path):
    """If path exists, append _1, _2, ... until a free name is found"""
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 1
    while os.path.exists(f"{base}_{i}{ext}"):
        i += 1
    return f"{base}_{i}{ext}"


def get_extension_counts(files):
    """Count file extensions from the scanned file list"""
    counts = {}
    for file_path in files:
        ext = Path(file_path).suffix.lower()
        ext = ext if ext else "[no extension]"
        counts[ext] = counts.get(ext, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (item[0] != "[no extension]", item[0])))


def resolve_folder_path():
    """Get folder path from CLI arg or prompt"""
    if len(sys.argv) > 1:
        folder_path = sys.argv[1].strip()
    else:
        folder_path = input("Enter folder path to scan: ").strip()

    if not folder_path:
        print("No folder provided. Exiting.")
        return None

    folder_path = os.path.abspath(os.path.expanduser(folder_path))

    if not os.path.exists(folder_path):
        print(f"Path does not exist: {folder_path}")
        return None

    if not os.path.isdir(folder_path):
        print(f"Path is not a directory: {folder_path}")
        return None

    return folder_path


def scan_folder(folder_path):
    """Scan all contents, honoring exclusions"""
    print(f"\nSelected folder: {folder_path}")
    print("=" * 60)

    target_exts, exclude_folders, exclude_files, exclude_exts, size_limit = ask_settings()

    print(f"\nReading contents for: {', '.join(target_exts) or '(none)'}")
    print(f"Read size limit:      {format_size(size_limit) if size_limit else '(none)'}")
    print(f"Excluding folders:    {', '.join(exclude_folders) or '(none)'}")
    print(f"Excluding files:      {', '.join(exclude_files) or '(none)'}")
    print(f"Excluding file types: {', '.join(exclude_exts) or '(none)'}")

    report = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "folders": [],
        "files": [],
        "extensions": target_exts,
        "size_limit": size_limit,
        "exclude_folders": exclude_folders,
        "exclude_files": exclude_files,
        "exclude_exts": exclude_exts,
        "files_content": {},
        "file_sizes": {},
        "folder_stats": {},
        "total_size": 0,
        "base_path": folder_path,
        "extension_counts": {},
    }

    for root_dir, dirs, files in os.walk(folder_path):
        dirs[:] = [d for d in dirs if not matches_any(d, exclude_folders)]

        for dir_name in dirs:
            full_path = os.path.join(root_dir, dir_name)
            report["folders"].append(os.path.relpath(full_path, folder_path))

        rel_dir = os.path.relpath(root_dir, folder_path)
        folder_file_count = 0
        folder_size = 0

        for file_name in files:
            name_l = file_name.lower()

            if matches_any(file_name, exclude_files):
                continue
            if any(name_l.endswith(ext) for ext in exclude_exts):
                continue

            full_path = os.path.join(root_dir, file_name)
            relative_path = os.path.relpath(full_path, folder_path)

            try:
                size = os.path.getsize(full_path)
            except Exception:
                size = 0

            report["files"].append(relative_path)
            report["file_sizes"][relative_path] = size
            report["total_size"] += size
            folder_file_count += 1
            folder_size += size

            if any(name_l.endswith(ext) for ext in target_exts):
                if size_limit and size > size_limit:
                    report["files_content"][relative_path] = (
                        f"[Skipped: file size {format_size(size)} exceeds "
                        f"read limit {format_size(size_limit)}]"
                    )
                else:
                    try:
                        with open(full_path, "r", encoding="utf-8") as f:
                            report["files_content"][relative_path] = f.read()
                    except Exception as e:
                        report["files_content"][relative_path] = f"Error reading file: {str(e)}"

        report["folder_stats"][rel_dir] = {
            "subfolders": len(dirs),
            "files": folder_file_count,
            "size": folder_size,
        }

    report["extension_counts"] = get_extension_counts(report["files"])

    generate_report(report)
    return report


def _write_report(report, out):
    """Write the report using out(line) for each line"""
    exts = report.get("extensions", [])
    base_path = report.get("base_path", "")
    size_limit = report.get("size_limit", 0)
    exclude_folders = report.get("exclude_folders", [])
    exclude_files = report.get("exclude_files", [])
    exclude_exts = report.get("exclude_exts", [])
    generated = report.get("generated", "")
    extension_counts = report.get("extension_counts", {})

    out(f"SCAN REPORT for: {base_path}")
    out("=" * 60)
    out(f"Generated   : {generated}")

    out("")
    out("=" * 60)
    out("SELECTED OPTIONS")
    out("=" * 60)
    out(f"Read extensions      : {', '.join(exts) or '(none)'}")
    out(f"Read size limit      : {format_size(size_limit) if size_limit else '(none)'}")
    out(f"Excluded folders     : {', '.join(exclude_folders) or '(none)'}")
    out(f"Excluded files       : {', '.join(exclude_files) or '(none)'}")
    out(f"Excluded file types  : {', '.join(exclude_exts) or '(none)'}")

    out("")
    out("=" * 60)
    out("SUMMARY")
    out("=" * 60)
    out(f"Total folders : {len(report['folders'])}")
    out(f"Total files   : {len(report['files'])}")
    out(f"Total size    : {format_size(report['total_size'])}")

    out("")
    out("Extensions:")
    if extension_counts:
        for ext, count in extension_counts.items():
            out(f"{ext} : {count}")
    else:
        out("(none)")

    out("")
    out(f"FOLDERS ({len(report['folders'])} found):")
    out("-" * 40)
    for folder in sorted(report["folder_stats"].keys()):
        st = report["folder_stats"][folder]
        label = "(root)" if folder == "." else folder
        out(f"📁 {label}  [{st['subfolders']} subfolders, {st['files']} files, {format_size(st['size'])}]")

    out(f"\nFILES ({len(report['files'])} found):")
    out("-" * 40)
    for file in sorted(report["files"]):
        marker = "⭐" if any(file.lower().endswith(e) for e in exts) else "📄"
        size = report["file_sizes"].get(file, 0)
        out(f"{marker} {file}  ({format_size(size)})")

    out(f"\nFILE CONTENTS ({len(report['files_content'])} files): {', '.join(exts) or '(none)'}")
    out("-" * 50)
    for file_path, content in report["files_content"].items():
        out(f"\n{'=' * 60}")
        out(f"FILE: {file_path}")
        out(f"{'=' * 60}")
        out(content)
        out(f"\n--- END OF: {file_path} ---")
        out(f"{'=' * 60}")


def generate_report(report):
    _write_report(report, print)


def save_report_to_file(report, output_file="folder_scan_report.txt"):
    output_file = get_unique_filename(output_file)
    with open(output_file, "w", encoding="utf-8") as f:
        _write_report(report, lambda line: f.write(line + "\n"))
    print(f"\nReport saved to: {output_file}")
    return output_file


def main():
    folder_path = resolve_folder_path()
    if not folder_path:
        return

    report = scan_folder(folder_path)
    if report:
        response = input("\nDo you want to save this report to a file? (n to cancel): ").strip().lower()
        if response in ["n", "no"]:
            print("Report not saved to file.")
        else:
            output_name = input("Output filename [folder_scan_report.txt]: ").strip()
            if not output_name:
                output_name = "folder_scan_report.txt"
            save_report_to_file(report, output_name)


if __name__ == "__main__":
    main()
