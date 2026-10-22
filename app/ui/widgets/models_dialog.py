"""Popup “Product Models” — trích xuất Product Models từ link/file bằng ChatGPT."""
from __future__ import annotations

import re
from html import escape as _esc, unescape
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QHBoxLayout,
                               QLabel, QPlainTextEdit, QPushButton, QVBoxLayout)

from ...ai.manager import build_models_prompt
from ..toast import show_toast
from ..workers import ModelsWorker

FILE_FILTER = ("Tài liệu (*.pdf *.docx *.doc *.txt *.png *.jpg *.jpeg *.webp);;"
               "Tất cả tệp (*)")

# Trạng thái popup dùng CHUNG cho mọi job (config.json -> ui.models_state)
STATE_KEY = "models_state"


def _plain(text: str) -> str:
    """Bỏ thẻ HTML + giải mã thực thể + viết thường + gộp khoảng trắng."""
    t = re.sub(r"<[^>]+>", " ", str(text or ""))
    t = unescape(t)
    t = re.sub(r"\s+", " ", t).strip().lower()
    return t


def insert_models_block(html_text: str, models: list[str]) -> tuple[str, str, int]:
    """Chèn <ul><li>model</li>…</ul> vào nội dung.

    - Ưu tiên: NGAY TRƯỚC <h2> thứ 4.
    - Không có h2 thứ 4 -> trước <h2> thứ 3.
    - Không có h2 thứ 3 -> CUỐI BÀI.
    - Chèn TOÀN BỘ mã trong ô kết quả (không giới hạn).
    Trả về (html mới, mô tả vị trí, số mã đã chèn).
    """
    html_text = str(html_text or "")
    items = [str(m).strip() for m in (models or []) if str(m).strip()]
    if not items:
        return html_text, "", 0
    block = "<ul>" + "".join(f"<li>{_esc(m)}</li>" for m in items) + "</ul>"
    heads = list(re.finditer(r"<h2\b[^>]*>.*?</h2>", html_text, re.I | re.S))
    if len(heads) >= 4:
        i, pos = heads[3].start(), "TRƯỚC <h2> thứ 4"
    elif len(heads) == 3:
        i, pos = heads[2].start(), "TRƯỚC <h2> thứ 3"
    else:
        tail = html_text.rstrip()
        return (tail + ("\n" if tail else "") + block), "CUỐI BÀI", len(items)
    return html_text[:i] + block + "\n" + html_text[i:], pos, len(items)


class ModelsDialog(QDialog):
    """Ô link + ô chọn file -> nút Xuất -> hiện danh sách Product Models."""

    def __init__(self, store, task_id: str = "", get_content=None,
                 apply_content=None, parent=None,
                 links_prefill=None, brand: str = "") -> None:
        super().__init__(parent)
        self.store = store
        self.brand = str(brand or "").strip()
        # TRẠNG THÁI DÙNG CHUNG (mọi job dùng chung link + kết quả đã Xuất)
        state = self._state()
        saved_links = [str(u).strip() for u in (state.get("links") or []) if str(u).strip()]
        saved_out = str(state.get("result") or "")
        # KHÔNG tự điền link của job nữa — chỉ giữ link người dùng đã gõ lần trước
        self._prefill = saved_links
        self.file_path = ""
        self._worker = None
        self.task_id = str(task_id or "")
        self._get_content = get_content
        self._apply_content = apply_content

        self.setWindowTitle("Product Models")
        self._state_timer = None
        self.setMinimumWidth(660)
        self.resize(700, 640)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(8)

        title = QLabel("Trích xuất Product Models từ link hoặc file")
        title.setStyleSheet("font-weight:700;font-size:15px;")
        root.addWidget(title)

        root.addWidget(QLabel("Link nguồn (mỗi dòng 1 link):"))
        self.links = QPlainTextEdit()
        self.links.setPlaceholderText("https://…")
        self.links.setFixedHeight(76)
        self.links.textChanged.connect(self._queue_state_save)
        if self._prefill:
            self.links.setPlainText("\n".join(self._prefill))
        root.addWidget(self.links)

        row = QHBoxLayout()
        self.pick_btn = QPushButton("Chọn file…")
        self.pick_btn.setProperty("class", "ghost")
        self.pick_btn.clicked.connect(self._pick_file)
        row.addWidget(self.pick_btn)
        self.file_lab = QLabel("(chưa chọn file)")
        self.file_lab.setObjectName("taskMeta")
        self.file_lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row.addWidget(self.file_lab, 1)
        self.clear_btn = QPushButton("✕")
        self.clear_btn.setProperty("class", "ghost")
        self.clear_btn.setFixedWidth(34)
        self.clear_btn.setToolTip("Bỏ file đã chọn")
        self.clear_btn.clicked.connect(self._clear_file)
        self.clear_btn.hide()
        row.addWidget(self.clear_btn)
        root.addLayout(row)

        self.export_btn = QPushButton("Xuất")
        self.export_btn.setProperty("class", "green")
        self.export_btn.clicked.connect(self._on_export)
        root.addWidget(self.export_btn, alignment=Qt.AlignLeft)

        self.status = QLabel("")
        self.status.setObjectName("taskMeta")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        root.addWidget(QLabel("Kết quả (mỗi Product Model 1 dòng):"))
        self.out = QPlainTextEdit()
        self.out.setPlaceholderText("Kết quả sẽ hiện ở đây…")
        if saved_out:
            self.out.setPlainText(saved_out)
        # DÁN/GÕ vào ô kết quả -> tự lưu (dùng chung mọi job)
        self.out.textChanged.connect(self._queue_state_save)
        root.addWidget(self.out, 1)

        foot = QHBoxLayout()
        foot.addStretch(1)
        self.copy_btn = QPushButton("Sao chép")
        self.copy_btn.setProperty("class", "ghost")
        self.copy_btn.clicked.connect(self._copy)
        foot.addWidget(self.copy_btn)
        self.insert_btn = QPushButton("Chèn vào nội dung")
        self.insert_btn.setProperty("class", "ghost")
        self.insert_btn.setToolTip(
            "Chèn danh sách mã ở trên vào NỘI DUNG của công việc đang mở:\n"
            "ngay TRƯỚC <h2> thứ 4 (không có thì trước <h2> thứ 3, không có nữa thì cuối bài)."
        )
        self.insert_btn.clicked.connect(self._insert_to_content)
        foot.addWidget(self.insert_btn)
        self.close_btn = QPushButton("Đóng")
        self.close_btn.clicked.connect(self.reject)
        foot.addWidget(self.close_btn)
        root.addLayout(foot)

    # ------------------------------------------------------------------ #
    def _state(self) -> dict:
        """Dict trạng thái dùng chung (lưu trong config.json)."""
        try:
            ui = self.store.data.setdefault("ui", {})
            st = ui.get(STATE_KEY)
            if not isinstance(st, dict):
                st = {}
                ui[STATE_KEY] = st
            return st
        except Exception:      # noqa: BLE001
            return {}

    def _save_state(self) -> None:
        """Lưu LINK + KẾT QUẢ (dùng chung mọi job)."""
        try:
            st = self._state()
            st["links"] = self._links()
            st["result"] = self.out.toPlainText()
            self.store.save()
        except Exception:      # noqa: BLE001
            pass

    def _queue_state_save(self, *_a) -> None:
        """Hẹn lưu sau 0,8 giây (tránh ghi config mỗi lần gõ)."""
        try:
            from PySide6.QtCore import QTimer

            if self._state_timer is None:
                self._state_timer = QTimer(self)
                self._state_timer.setSingleShot(True)
                self._state_timer.setInterval(800)
                self._state_timer.timeout.connect(self._save_state)
            self._state_timer.start()
        except Exception:      # noqa: BLE001
            pass

    def _pick_file(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "Chọn file nguồn", "", FILE_FILTER)
        if not p:
            return
        self.file_path = p
        self.file_lab.setText(Path(p).name)
        self.clear_btn.show()

    def _clear_file(self) -> None:
        self.file_path = ""
        self.file_lab.setText("(chưa chọn file)")
        self.clear_btn.hide()

    def _links(self) -> list[str]:
        out: list[str] = []
        for line in self.links.toPlainText().splitlines():
            for piece in line.replace(",", " ").split():
                t = piece.strip()
                if t and t not in out:
                    out.append(t)
        return out

    def _on_export(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        links = self._links()
        files = [self.file_path] if self.file_path else []
        if not links and not files:
            show_toast(self, "Nhập link hoặc chọn file trước", 2600, ok=False)
            return
        prompt = build_models_prompt(links, bool(files))

        self.export_btn.setEnabled(False)
        self.export_btn.setText("Đang xuất…")
        self.out.setPlainText("")
        self.status.setText("Đang mở ChatGPT (Project)…")

        worker = ModelsWorker(self.store, prompt, files)
        worker.log.connect(self._on_log)
        worker.ok.connect(self._on_ok)
        worker.failed.connect(self._on_fail)
        worker.finished.connect(self._on_done)
        self._worker = worker
        worker.start()

    def _on_log(self, text: str) -> None:
        self.status.setText(str(text or ""))

    def _on_ok(self, text: str) -> None:
        rows = [ln.strip() for ln in str(text or "").splitlines() if ln.strip()]
        if self.brand:                     # thêm THƯƠNG HIỆU trước mỗi mã
            rows = [f"{self.brand} {r}" for r in rows]
        self.out.setPlainText("\n".join(rows))
        self._save_state()                 # nhớ kết quả DÙNG CHUNG cho mọi job
        self.status.setText(f"Xong — {len(rows)} Product Models")
        show_toast(self, f"Đã trích xuất {len(rows)} Product Models", 2600)

    def _on_fail(self, err: str) -> None:
        self.status.setText("")
        show_toast(self, str(err)[:160] or "Không trích xuất được", 4200, ok=False)

    def _on_done(self) -> None:
        self._worker = None
        self.export_btn.setEnabled(True)
        self.export_btn.setText("Xuất")

    def _insert_to_content(self) -> None:
        models = [ln.strip() for ln in self.out.toPlainText().splitlines() if ln.strip()]
        if not models:
            show_toast(self, "Chưa có Product Models để chèn", 2400, ok=False)
            return
        if not self.task_id or self._get_content is None or self._apply_content is None:
            show_toast(self, "Chưa mở công việc nào để chèn", 2600, ok=False)
            return
        try:
            cur = self._get_content() or ""
        except Exception:      # noqa: BLE001
            cur = ""
        if not str(cur).strip():
            show_toast(self, "Công việc chưa có nội dung", 2600, ok=False)
            return
        new_html, pos, n = insert_models_block(cur, models)
        self._apply_content(self.task_id, new_html)
        show_toast(self, f"Đã chèn {n} mã ({pos})", 3000)

    def _copy(self) -> None:
        text = self.out.toPlainText().strip()
        if not text:
            show_toast(self, "Chưa có kết quả để sao chép", 2200, ok=False)
            return
        QApplication.clipboard().setText(text)
        show_toast(self, "Đã sao chép", 1800)

    # ------------------------------------------------------------------ #
    def closeEvent(self, event) -> None:      # noqa: N802
        self._save_state()
        if self._worker is not None and self._worker.isRunning():
            show_toast(self, "Đang xuất — vui lòng chờ xong", 2600, ok=False)
            event.ignore()
            return
        super().closeEvent(event)
