import os
import json
import fnmatch
from pathlib import Path
from datetime import datetime
from threading import Thread
from tkinter import filedialog, messagebox

import customtkinter as ctk

HISTORY_FILE = Path.home() / ".folder_scanner_history.json"


# ----------------------------- Backend helpers ----------------------------- #
def load_history():
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_history(data):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"Could not save history: {e}")


def normalize_extensions(raw):
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
    parts = raw.replace(",", " ").split()
    return [p.strip().lower() for p in parts if p.strip()]


def matches_any(name, patterns):
    name = name.lower()
    for p in patterns:
        if fnmatch.fnmatch(name, p.replace("%", "*")):
            return True
    return False


def format_size(num_bytes):
    size = float(num_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024 or unit == "TB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


def parse_size_limit(raw):
    raw = raw.strip().lower()
    if not raw or raw == "none":
        return 0
    units = {"b": 1, "kb": 1024, "mb": 1024 ** 2, "gb": 1024 ** 3, "tb": 1024 ** 4}
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
    return int(value * units.get(unit, units["mb"]))


def get_unique_filename(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 1
    while os.path.exists(f"{base}_{i}{ext}"):
        i += 1
    return f"{base}_{i}{ext}"


def get_extension_counts(files):
    counts = {}
    for file_path in files:
        ext = Path(file_path).suffix.lower() or "[no extension]"
        counts[ext] = counts.get(ext, 0) + 1
    return dict(sorted(counts.items(), key=lambda i: (i[0] != "[no extension]", i[0])))


def scan_folder(folder_path, target_exts, exclude_folders, exclude_files,
                exclude_exts, size_limit, status_callback=None):
    report = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "folders": [], "files": [], "extensions": target_exts,
        "size_limit": size_limit, "exclude_folders": exclude_folders,
        "exclude_files": exclude_files, "exclude_exts": exclude_exts,
        "files_content": {}, "file_sizes": {}, "folder_stats": {},
        "total_size": 0, "base_path": folder_path, "extension_counts": {},
    }

    for root_dir, dirs, files in os.walk(folder_path):
        if status_callback:
            status_callback(f"Scanning: {os.path.relpath(root_dir, folder_path)}")

        dirs[:] = [d for d in dirs if not matches_any(d, exclude_folders)]
        for dir_name in dirs:
            full = os.path.join(root_dir, dir_name)
            report["folders"].append(os.path.relpath(full, folder_path))

        rel_dir = os.path.relpath(root_dir, folder_path)
        folder_file_count = folder_size = 0

        for file_name in files:
            name_l = file_name.lower()
            if matches_any(file_name, exclude_files):
                continue
            if any(name_l.endswith(ext) for ext in exclude_exts):
                continue

            full = os.path.join(root_dir, file_name)
            rel = os.path.relpath(full, folder_path)
            try:
                size = os.path.getsize(full)
            except Exception:
                size = 0

            report["files"].append(rel)
            report["file_sizes"][rel] = size
            report["total_size"] += size
            folder_file_count += 1
            folder_size += size

            if any(name_l.endswith(ext) for ext in target_exts):
                if size_limit and size > size_limit:
                    report["files_content"][rel] = (
                        f"[Skipped: file size {format_size(size)} exceeds "
                        f"read limit {format_size(size_limit)}]")
                else:
                    try:
                        with open(full, "r", encoding="utf-8") as f:
                            report["files_content"][rel] = f.read()
                    except Exception as e:
                        report["files_content"][rel] = f"Error reading file: {e}"

        report["folder_stats"][rel_dir] = {
            "subfolders": len(dirs), "files": folder_file_count, "size": folder_size,
        }

    report["extension_counts"] = get_extension_counts(report["files"])
    return report


def _write_report(report, out):
    exts = report.get("extensions", [])
    out(f"SCAN REPORT for: {report.get('base_path', '')}")
    out("=" * 60)
    out(f"Generated   : {report.get('generated', '')}")
    out("")
    out("=" * 60)
    out("SELECTED OPTIONS")
    out("=" * 60)
    out(f"Read extensions      : {', '.join(exts) or '(none)'}")
    sl = report.get("size_limit", 0)
    out(f"Read size limit      : {format_size(sl) if sl else '(none)'}")
    out(f"Excluded folders     : {', '.join(report.get('exclude_folders', [])) or '(none)'}")
    out(f"Excluded files       : {', '.join(report.get('exclude_files', [])) or '(none)'}")
    out(f"Excluded file types  : {', '.join(report.get('exclude_exts', [])) or '(none)'}")
    out("")
    out("=" * 60)
    out("SUMMARY")
    out("=" * 60)
    out(f"Total folders : {len(report['folders'])}")
    out(f"Total files   : {len(report['files'])}")
    out(f"Total size    : {format_size(report['total_size'])}")
    out("")
    out("Extensions:")
    counts = report.get("extension_counts", {})
    if counts:
        for ext, count in counts.items():
            out(f"{ext} : {count}")
    else:
        out("(none)")

    out("")
    out(f"FOLDERS ({len(report['folders'])} found):")
    out("-" * 40)
    for folder in sorted(report["folder_stats"].keys()):
        st = report["folder_stats"][folder]
        label = "(root)" if folder == "." else folder
        out(f"📁 {label}  [{st['subfolders']} subfolders, "
            f"{st['files']} files, {format_size(st['size'])}]")

    out(f"\nFILES ({len(report['files'])} found):")
    out("-" * 40)
    for file in sorted(report["files"]):
        marker = "⭐" if any(file.lower().endswith(e) for e in exts) else "📄"
        out(f"{marker} {file}  ({format_size(report['file_sizes'].get(file, 0))})")

    out(f"\nFILE CONTENTS ({len(report['files_content'])} files): "
        f"{', '.join(exts) or '(none)'}")
    out("-" * 50)
    for file_path, content in report["files_content"].items():
        out(f"\n{'=' * 60}")
        out(f"FILE: {file_path}")
        out(f"{'=' * 60}")
        out(content)
        out(f"\n--- END OF: {file_path} ---")
        out(f"{'=' * 60}")


def report_to_string(report):
    lines = []
    _write_report(report, lines.append)
    return "\n".join(lines)


def save_report_to_file(report, output_file="folder_scan_report.txt"):
    output_file = get_unique_filename(output_file)
    with open(output_file, "w", encoding="utf-8") as f:
        _write_report(report, lambda line: f.write(line + "\n"))
    return output_file


# ------------------------------- Modern GUI -------------------------------- #
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

FONT_FAMILY = "Segoe UI"
MONO_FAMILY = "Consolas"


class FolderScannerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Folder Scanner")
        self.geometry("1150x800")
        self.minsize(900, 600)

        self.history = load_history()
        self.report = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self._build_header()
        self._build_inputs()
        self._build_report_area()
        self._build_statusbar()

    # ---------- layout sections ----------
    def _build_header(self):
        header = ctk.CTkFrame(self, corner_radius=0, height=64,
                              fg_color=("gray92", "gray13"))
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(header, text="  🔍  Folder Scanner",
                     font=ctk.CTkFont(FONT_FAMILY, 22, "bold")).grid(
            row=0, column=0, sticky="w", padx=20, pady=14)

        self.theme_menu = ctk.CTkOptionMenu(
            header, values=["Dark", "Light", "System"],
            width=110, command=self._change_theme)
        self.theme_menu.set("Dark")
        self.theme_menu.grid(row=0, column=1, padx=20, pady=14, sticky="e")

    def _build_inputs(self):
        card = ctk.CTkFrame(self, corner_radius=14)
        card.grid(row=1, column=0, sticky="ew", padx=20, pady=(16, 8))
        card.grid_columnconfigure(1, weight=1)

        self.folder_var = ctk.StringVar()
        self.extensions_var = ctk.StringVar(
            value=", ".join(self.history.get("extensions", [])))
        sl = self.history.get("size_limit", 0)
        self.size_limit_var = ctk.StringVar(value=format_size(sl) if sl else "")
        self.exclude_folders_var = ctk.StringVar(
            value=", ".join(self.history.get("exclude_folders", [])))
        self.exclude_files_var = ctk.StringVar(
            value=", ".join(self.history.get("exclude_files", [])))
        self.exclude_exts_var = ctk.StringVar(
            value=", ".join(self.history.get("exclude_exts", [])))

        # folder row with browse button
        self._row_label(card, 0, "Folder")
        folder_entry = ctk.CTkEntry(card, textvariable=self.folder_var,
                                    placeholder_text="Choose a folder to scan…")
        folder_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=8)
        ctk.CTkButton(card, text="Browse", width=100,
                      command=self.browse_folder).grid(
            row=0, column=2, padx=(0, 16), pady=8)

        self._entry_row(card, 1, "Read extensions", self.extensions_var,
                        "e.g.  py, sql, .js")

        self._row_label(card, 2, "Read size limit")
        size_entry = ctk.CTkEntry(card, textvariable=self.size_limit_var,
                                  placeholder_text="500KB, 1.5MB, none")
        size_entry.grid(row=2, column=1, sticky="ew", padx=(0, 8), pady=8)
        ctk.CTkLabel(card, text="bare number = MB",
                     text_color=("gray45", "gray60"),
                     font=ctk.CTkFont(FONT_FAMILY, 12)).grid(
            row=2, column=2, sticky="w", padx=(0, 16))

        self._entry_row(card, 3, "Exclude folders", self.exclude_folders_var,
                        "e.g.  .git, node_modules, %cache%")
        self._entry_row(card, 4, "Exclude files", self.exclude_files_var,
                        "e.g.  *.lock, %secret%")
        self._entry_row(card, 5, "Exclude file types", self.exclude_exts_var,
                        "e.g.  png, exe, .zip")

        # action bar
        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.grid(row=6, column=0, columnspan=3, sticky="ew",
                     padx=16, pady=(8, 14))
        actions.grid_columnconfigure(3, weight=1)

        self.scan_button = ctk.CTkButton(actions, text="Scan Folder", width=140,
                                         height=38, command=self.start_scan,
                                         font=ctk.CTkFont(FONT_FAMILY, 14, "bold"))
        self.scan_button.grid(row=0, column=0, padx=(0, 10))

        self.save_button = ctk.CTkButton(actions, text="Save Report", width=130,
                                         height=38, state="disabled",
                                         command=self.save_report)
        self.save_button.grid(row=0, column=1, padx=(0, 10))

        ctk.CTkButton(actions, text="Clear", width=90, height=38,
                      fg_color="transparent", border_width=1,
                      text_color=("gray20", "gray85"),
                      command=self.clear_report).grid(row=0, column=2)

        self.progress = ctk.CTkProgressBar(actions, mode="indeterminate",
                                           height=8)
        self.progress.grid(row=0, column=3, sticky="ew", padx=(16, 0))
        self.progress.set(0)

    def _build_report_area(self):
        frame = ctk.CTkFrame(self, corner_radius=14)
        frame.grid(row=2, column=0, sticky="nsew", padx=20, pady=8)
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        self.report_text = ctk.CTkTextbox(
            frame, wrap="none", corner_radius=10,
            font=ctk.CTkFont(MONO_FAMILY, 13))
        self.report_text.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

    def _build_statusbar(self):
        bar = ctk.CTkFrame(self, corner_radius=0, height=30,
                           fg_color=("gray88", "gray16"))
        bar.grid(row=3, column=0, sticky="ew")
        self.status_var = ctk.StringVar(value="Ready")
        ctk.CTkLabel(bar, textvariable=self.status_var,
                     font=ctk.CTkFont(FONT_FAMILY, 12),
                     text_color=("gray30", "gray70")).pack(
            side="left", padx=20, pady=4)

    # ---------- small builders ----------
    def _row_label(self, parent, row, text):
        ctk.CTkLabel(parent, text=text, anchor="w", width=130,
                     font=ctk.CTkFont(FONT_FAMILY, 13)).grid(
            row=row, column=0, sticky="w", padx=(16, 10), pady=8)

    def _entry_row(self, parent, row, label, var, placeholder):
        self._row_label(parent, row, label)
        entry = ctk.CTkEntry(parent, textvariable=var,
                             placeholder_text=placeholder)
        entry.grid(row=row, column=1, columnspan=2, sticky="ew",
                   padx=(0, 16), pady=8)
        return entry

    # ---------- behavior ----------
    def _change_theme(self, choice):
        ctk.set_appearance_mode(choice.lower())

    def browse_folder(self):
        folder = filedialog.askdirectory(title="Select a folder to scan")
        if folder:
            self.folder_var.set(folder)

    def clear_report(self):
        self.report_text.delete("1.0", "end")
        self.report = None
        self.save_button.configure(state="disabled")
        self.status_var.set("Ready")

    def set_status(self, message):
        self.status_var.set(message)

    def get_settings(self):
        folder = self.folder_var.get().strip()
        if not folder:
            raise ValueError("Please select a folder.")
        if not os.path.isdir(folder):
            raise ValueError("Selected folder does not exist.")
        return (
            folder,
            normalize_extensions(self.extensions_var.get().strip()),
            normalize_names(self.exclude_folders_var.get().strip()),
            normalize_names(self.exclude_files_var.get().strip()),
            normalize_extensions(self.exclude_exts_var.get().strip()),
            parse_size_limit(self.size_limit_var.get().strip()),
        )

    def start_scan(self):
        try:
            settings = self.get_settings()
        except ValueError as e:
            messagebox.showerror("Invalid Settings", str(e))
            return

        self.scan_button.configure(state="disabled")
        self.save_button.configure(state="disabled")
        self.report_text.delete("1.0", "end")
        self.progress.start()
        self.set_status("Starting scan…")

        Thread(target=self.run_scan, args=(settings,), daemon=True).start()

    def run_scan(self, settings):
        folder, exts, ex_folders, ex_files, ex_exts, size_limit = settings
        save_history({
            "extensions": exts, "size_limit": size_limit,
            "exclude_folders": ex_folders, "exclude_files": ex_files,
            "exclude_exts": ex_exts,
        })
        try:
            report = scan_folder(
                folder, exts, ex_folders, ex_files, ex_exts, size_limit,
                status_callback=lambda m: self.after(0, self.set_status, m))
            text = report_to_string(report)
            self.after(0, self.finish_scan, report, text)
        except Exception as e:
            self.after(0, self.scan_failed, str(e))

    def finish_scan(self, report, text):
        self.report = report
        self.report_text.delete("1.0", "end")
        self.report_text.insert("end", text)
        self.report_text.see("1.0")
        self.progress.stop()
        self.progress.set(0)
        self.scan_button.configure(state="normal")
        self.save_button.configure(state="normal")
        self.set_status(f"Scan complete · {len(report['files'])} files found")

    def scan_failed(self, message):
        self.progress.stop()
        self.progress.set(0)
        self.scan_button.configure(state="normal")
        self.set_status("Scan failed.")
        messagebox.showerror("Scan Error", message)

    def save_report(self):
        if not self.report:
            messagebox.showinfo("No Report", "Nothing to save yet.")
            return
        out_file = filedialog.asksaveasfilename(
            title="Save Report", defaultextension=".txt",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")],
            initialfile="folder_scan_report.txt")
        if not out_file:
            return
        try:
            with open(out_file, "w", encoding="utf-8") as f:
                _write_report(self.report, lambda line: f.write(line + "\n"))
            self.set_status(f"Report saved to: {out_file}")
            messagebox.showinfo("Saved", f"Report saved to:\n{out_file}")
        except Exception as e:
            messagebox.showerror("Save Error", str(e))


def main():
    app = FolderScannerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
