"""Tk timeline editor; background work communicates only through a queue."""

from __future__ import annotations

import os
import queue
import threading
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from lib.studio_scene_generator import generate_plan_file
from lib.studio_scenes import load_scenes, save_scenes, scenes_to_items
from lib.studio_timeline import (
    APPROVED_WAV, FPS, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS,
    TimelineItem, fit_to_audio, move_item, seconds_to_frames, timeline_frames,
)
from tools.video.studio_export import StudioExport, wav_duration

TRANSITION_LABELS = {"Corte": "cut", "Crossfade": "crossfade", "Fade por preto": "fade"}


class TimelineEditor(tk.Toplevel):
    def __init__(self, master, output_dir: Path):
        super().__init__(master)
        self.title("OpenMontage Studio — Montagem local")
        self.geometry("1080x700")
        self.minsize(850, 630)
        self.output_dir = output_dir
        self.items: list[TimelineItem] = []
        self.events: queue.Queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.busy = False
        self.closing = False
        self.after_close = None
        self.last_output: Path | None = None
        self.last_plan: Path | None = None
        self._controls = []
        self._poll_id = None
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.request_close)
        self._poll_id = self.after(100, self._poll)

    def _button(self, parent, text, command):
        button = ttk.Button(parent, text=text, command=command)
        button.pack(side="left", padx=(0, 6))
        self._controls.append((button, "normal"))
        return button

    def _build(self):
        body = ttk.Frame(self, padding=18)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Montagem de imagens e clipes locais", style="Section.TLabel").pack(anchor="w")
        ttk.Label(body, text="MP4 · 1920×1080 · H.264 · 30 fps. O WAV completo define a duração final.",
                  wraplength=950).pack(anchor="w", pady=(8, 12))
        audio_row = ttk.Frame(body)
        audio_row.pack(fill="x")
        ttk.Label(audio_row, text="WAV:").pack(side="left", padx=(0, 8))
        self.wav_path = tk.StringVar(value=str(APPROVED_WAV))
        entry = ttk.Entry(audio_row, textvariable=self.wav_path)
        entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self._controls.append((entry, "normal"))
        self._button(audio_row, "Escolher WAV", self._browse_wav)
        self.wav_path.trace_add("write", self._wav_changed)
        self.wav_info = tk.StringVar(value="WAV aprovado selecionado por padrão. Use Ajustar ao WAV para medir e sincronizar.")
        ttk.Label(body, textvariable=self.wav_info, wraplength=950).pack(anchor="w", pady=7)

        actions = ttk.Frame(body)
        actions.pack(fill="x", pady=(5, 8))
        self._button(actions, "Adicionar mídias", self._browse_media)
        self._button(actions, "Remover", self.remove_selected)
        self._button(actions, "Subir", lambda: self.move_selected(-1))
        self._button(actions, "Descer", lambda: self.move_selected(1))
        self._button(actions, "Ajustar ao WAV", self.adjust_to_wav)
        plan_row = ttk.Frame(body)
        plan_row.pack(fill="x", pady=(0, 8))
        self._button(plan_row, "Gerar Plano…", self.open_plan_generator)
        self._button(plan_row, "Importar plano (scenes.json)…", self.import_plan)
        self._button(plan_row, "Exportar plano (scenes.json)…", self.export_plan)

        table = ttk.Frame(body)
        table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table, columns=("order", "name", "duration", "transition", "overlap"),
                                 show="headings", selectmode="browse", height=8)
        for key, title, width in (("order", "Ordem", 50), ("name", "Arquivo", 340),
                                  ("duration", "Duração (s)", 105), ("transition", "Para o próximo", 145),
                                  ("overlap", "Transição (s)", 110)):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=50, stretch=key == "name")
        scrollbar = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._selected)

        edit = ttk.Frame(body)
        edit.pack(fill="x", pady=10)
        self.item_duration = tk.StringVar(value="5")
        self.transition = tk.StringVar(value="Corte")
        self.transition_duration = tk.StringVar(value="0.5")
        for title, variable in (("Duração do item (s)", self.item_duration), ("Duração da transição (s)", self.transition_duration)):
            cell = ttk.Frame(edit)
            cell.pack(side="left", padx=(0, 12))
            ttk.Label(cell, text=title).pack(anchor="w")
            widget = ttk.Entry(cell, textvariable=variable, width=19)
            widget.pack(anchor="w", pady=3)
            self._controls.append((widget, "normal"))
        cell = ttk.Frame(edit)
        cell.pack(side="left", padx=(0, 12))
        ttk.Label(cell, text="Transição para o próximo").pack(anchor="w")
        widget = ttk.Combobox(cell, textvariable=self.transition, values=tuple(TRANSITION_LABELS), state="readonly", width=20)
        widget.pack(anchor="w", pady=3)
        self._controls.append((widget, "readonly"))
        self._button(edit, "Aplicar ao item", self.apply_selected)

        self.summary = tk.StringVar(value="Timeline vazia.")
        ttk.Label(body, textvariable=self.summary, wraplength=950).pack(anchor="w")
        ttk.Label(body, text="As transições sobrepõem os itens e reduzem a duração total; a última não é aplicada. "
                  "Clipes começam no início: são cortados ou mantêm o último quadro. Áudios dos clipes são ignorados. "
                  "Imagens mantêm proporção, com barras pretas quando necessário. O WAV não recebe novos ganhos ou efeitos. "
                  "Planos scenes.json importam/exportam a montagem inteira sem tocar no áudio.",
                  wraplength=980, justify="left").pack(anchor="w", pady=(8, 10))

        footer = ttk.Frame(body)
        footer.pack(fill="x")
        self.export_button = self._button(footer, "Exportar MP4…", self.export)
        self.cancel_button = ttk.Button(footer, text="Cancelar exportação", command=self.cancel_event.set, state="disabled")
        self.cancel_button.pack(side="left", padx=(0, 6))
        self.open_button = ttk.Button(footer, text="Abrir MP4", command=self.open_output, state="disabled")
        self.open_button.pack(side="left")
        self.progress = ttk.Progressbar(body, maximum=100)
        self.progress.pack(fill="x", pady=8)
        self.status = tk.StringVar(value="Adicione mídias, configure os itens, ajuste ao WAV e exporte.")
        ttk.Label(body, textvariable=self.status, wraplength=980).pack(anchor="w")

    def _wav_changed(self, *_):
        if hasattr(self, "wav_info"):
            self.wav_info.set("WAV alterado. Use Ajustar ao WAV antes de exportar.")

    def _browse_wav(self):
        chosen = filedialog.askopenfilename(parent=self, title="Escolher WAV (somente leitura)", filetypes=(("Áudio WAV", "*.wav"),))
        if chosen:
            self.wav_path.set(chosen)

    def _browse_media(self):
        chosen = filedialog.askopenfilenames(parent=self, title="Adicionar imagens e clipes locais", filetypes=(
            ("Imagens e vídeos", " ".join("*" + ext for ext in sorted(IMAGE_EXTENSIONS | VIDEO_EXTENSIONS))),))
        if chosen:
            self.add_paths(chosen)

    def open_plan_generator(self):
        if self.busy:
            return
        dialog = tk.Toplevel(self)
        dialog.title("Gerar plano de cenas")
        dialog.geometry("680x440")
        dialog.minsize(520, 320)
        dialog.transient(self)
        dialog.grab_set()
        ttk.Label(dialog, text="Texto da narração (segmentos viram cenas de planejamento)",
                  style="Section.TLabel").pack(anchor="w", padx=14, pady=(14, 6))
        body = ttk.Frame(dialog)
        body.pack(fill="both", expand=True, padx=14)
        text = tk.Text(body, wrap="word", bg="#0f1720", fg="#e8eef5", insertbackground="white",
                       relief="flat", padx=8, pady=6, font=("Segoe UI", 10))
        scroll = ttk.Scrollbar(body, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        ttk.Label(dialog, text="As durações são proporcionais ao WAV ativo. Nenhuma mídia é inventada; "
                               "preencha 'media' em cada cena e use Importar plano para montar o vídeo.",
                  wraplength=620, justify="left").pack(anchor="w", padx=14, pady=(8, 4))
        footer = ttk.Frame(dialog)
        footer.pack(fill="x", padx=14, pady=(4, 14))

        def cancel():
            dialog.destroy()

        def generate():
            content = text.get("1.0", "end").strip()
            if not content:
                messagebox.showerror("Texto necessário", "Cole ou escreva o texto da narração.", parent=dialog)
                return
            dialog.destroy()
            self.generate_plan(content)

        ttk.Button(footer, text="Cancelar", command=cancel).pack(side="right", padx=(6, 0))
        ttk.Button(footer, text="Gerar plano", style="Accent.TButton", command=generate).pack(side="right")
        text.focus_set()

    def generate_plan(self, narration_text: str):
        if self.busy:
            return
        wav = Path(self.wav_path.get()).expanduser()
        self.status.set("Gerando plano de cenas a partir da narração…")

        def worker():
            duration = wav_duration(wav)
            if self.cancel_event.is_set():
                return "cancelled", "Geração de plano cancelada."
            destination = self.output_dir / f"plano-gerado-{datetime.now():%Y%m%d-%H%M%S-%f}.json"
            path = generate_plan_file(narration_text, duration, destination, wav=wav)
            plan = load_scenes(path)
            return "plan_generated", (path, len(plan.scenes), duration)

        self._start(worker)

    def import_plan(self):
        if self.busy:
            return
        chosen = filedialog.askopenfilename(
            parent=self, title="Importar scenes.json",
            filetypes=(("Plano de cenas", "*.json"), ("Todos", "*.*")))
        if not chosen:
            return
        try:
            plan = load_scenes(chosen)
        except ValueError as exc:
            messagebox.showerror("Plano inválido", str(exc), parent=self)
            return
        planning = plan.planning_count
        media_items = scenes_to_items(plan)
        if not media_items:
            messagebox.showerror(
                "Plano de planejamento",
                f"O plano tem {planning} cena(s) de planejamento sem 'media'. "
                "Preencha os caminhos de mídia no JSON e importe novamente para montar o vídeo.",
                parent=self)
            self.status.set(f"Plano carregado: {planning} cena(s) de planejamento, sem mídia para montar.")
            return
        current_wav = Path(self.wav_path.get()).expanduser().resolve()
        if plan.wav is not None and plan.wav != current_wav:
            swap = messagebox.askyesno(
                "Trocar WAV do plano?",
                f"O plano referencia outro WAV:\n{plan.wav}\n\n"
                f"WAV ativo:\n{current_wav}\n\n"
                "Trocar o WAV ativo pelo do plano? A mixagem aprovada permanece em disco; "
                "esta escolha só altera qual WAV a montagem usa.",
                parent=self)
            if swap:
                self.wav_path.set(str(plan.wav))
        if self.items:
            replace_all = messagebox.askyesno(
                "Substituir timeline?",
                f"O plano contém {len(media_items)} cena(s) com mídia"
                + (f" ({planning} de planejamento serão ignoradas)" if planning else "")
                + f" e substituirá os {len(self.items)} item(ns) atuais. Continuar?",
                parent=self)
            if not replace_all:
                self.status.set("Importação cancelada. A timeline foi preservada.")
                return
        self.items = media_items
        self._refresh(0)
        skipped = f" ({planning} cena(s) de planejamento sem mídia ignoradas)" if planning else ""
        self.status.set(f"Plano importado: {len(self.items)} cena(s){skipped}. Ajustando ao WAV…")
        self.wav_info.set("Plano importado. Ajustando a timeline ao WAV ativo…")
        self.adjust_to_wav()

    def export_plan(self):
        if self.busy:
            return
        if not self.items:
            messagebox.showerror("Timeline vazia", "Adicione mídias antes de exportar o plano.", parent=self)
            return
        chosen = filedialog.asksaveasfilename(
            parent=self, title="Exportar plano de cenas", defaultextension=".json",
            initialdir=str(self.output_dir), initialfile=f"cenas-{datetime.now():%Y%m%d-%H%M%S-%f}.json",
            filetypes=(("Plano de cenas", "*.json"),), confirmoverwrite=True)
        if not chosen:
            return
        try:
            path = save_scenes(chosen, self.items, wav=self.wav_path.get(),
                               metadata={"generated_by": "OpenMontage Studio"})
        except (OSError, ValueError) as exc:
            messagebox.showerror("Não foi possível exportar o plano", str(exc), parent=self)
            return
        self.status.set(f"Plano exportado: {path}")

    def add_paths(self, paths):
        if self.busy:
            return
        try:
            added = []
            for raw in paths:
                path = Path(raw).expanduser().resolve(strict=True)
                if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS:
                    raise ValueError(f"Imagem ou clipe não suportado: {path.name}")
                added.append(TimelineItem(path))
            self.items.extend(added)
            self._refresh(len(self.items) - 1)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Mídia inválida", str(exc), parent=self)

    def _index(self):
        selected = self.tree.selection()
        return int(selected[0]) if selected else None

    def _selected(self, _event=None):
        index = self._index()
        if index is None or index >= len(self.items) or self.busy:
            return
        item = self.items[index]
        self.item_duration.set(f"{item.frames / FPS:.6f}")
        self.transition.set(next(key for key, value in TRANSITION_LABELS.items() if value == item.transition))
        self.transition_duration.set(str(item.transition_duration))

    def _refresh(self, select=None):
        self.tree.delete(*self.tree.get_children())
        labels = {value: key for key, value in TRANSITION_LABELS.items()}
        for i, item in enumerate(self.items):
            active = i < len(self.items) - 1
            self.tree.insert("", "end", iid=str(i), values=(i + 1, item.path.name, f"{item.frames / FPS:.3f}",
                labels[item.transition] if active else "Fim", f"{item.transition_duration:.3f}" if active and item.transition != "cut" else "—"))
        if select is not None and 0 <= select < len(self.items):
            self.tree.selection_set(str(select))
            self.tree.see(str(select))
            self._selected()
        try:
            frames = timeline_frames(self.items)
            self.summary.set(f"{len(self.items)} itens · {frames} quadros · duração efetiva: {frames / FPS:.3f} s.")
        except ValueError as exc:
            self.summary.set(str(exc))

    def apply_selected(self):
        index = self._index()
        if self.busy or index is None:
            return
        try:
            transition = TRANSITION_LABELS[self.transition.get()]
            duration = seconds_to_frames(self.item_duration.get()) / FPS
            overlap = seconds_to_frames(self.transition_duration.get(), "Transição") / FPS if transition != "cut" else 0.5
            self.items[index] = replace(self.items[index], duration=duration, transition=transition, transition_duration=overlap)
            self._refresh(index)
        except (ValueError, KeyError) as exc:
            messagebox.showerror("Configuração inválida", str(exc), parent=self)

    def remove_selected(self):
        index = self._index()
        if not self.busy and index is not None:
            self.items.pop(index)
            self._refresh(min(index, len(self.items) - 1))

    def move_selected(self, offset):
        index = self._index()
        if not self.busy and index is not None and 0 <= index + offset < len(self.items):
            self._refresh(move_item(self.items, index, offset))

    def _set_busy(self, value):
        self.busy = value
        for widget, ready in self._controls:
            widget.configure(state="disabled" if value else ready)
        self.cancel_button.configure(state="normal" if value else "disabled")
        if not value:
            self._selected()

    def _start(self, function):
        self.cancel_event.clear()
        self._set_busy(True)
        def worker():
            try:
                self.events.put(function())
            except Exception as exc:
                self.events.put(("error", str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def adjust_to_wav(self):
        if self.busy:
            return
        if not self.items:
            messagebox.showerror("Timeline vazia", "Adicione mídias antes de ajustar ao WAV.", parent=self)
            return
        snapshot = list(self.items)
        wav = Path(self.wav_path.get())
        self.status.set("Medindo o WAV e ajustando a timeline…")
        def adjust():
            duration = wav_duration(wav)
            if self.cancel_event.is_set():
                return "cancelled", "Ajuste cancelado. A timeline foi preservada."
            return "fit", (duration, fit_to_audio(snapshot, duration))
        self._start(adjust)

    def export(self):
        if self.busy:
            return
        try:
            timeline_frames(self.items)
        except ValueError as exc:
            messagebox.showerror("Timeline inválida", str(exc), parent=self)
            return
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("Pasta de saída indisponível", str(exc), parent=self)
            return
        chosen = filedialog.asksaveasfilename(parent=self, title="Exportar em um novo MP4", defaultextension=".mp4",
            initialdir=str(self.output_dir), initialfile=f"montagem-{datetime.now():%Y%m%d-%H%M%S-%f}.mp4",
            filetypes=(("Vídeo MP4", "*.mp4"),), confirmoverwrite=False)
        if not chosen:
            return
        output = Path(chosen)
        if output.exists() or output.is_symlink():
            messagebox.showerror("Destino existente", "Escolha um novo nome. Arquivos existentes não são sobrescritos.", parent=self)
            return
        inputs = {"items": [{**asdict(item), "path": str(item.path)} for item in self.items],
                  "wav_path": self.wav_path.get(), "output_path": str(output)}
        self.progress["value"] = 0
        self.status.set("Validando mídias, WAV e timeline…")
        def render():
            result = StudioExport().execute(inputs, cancel=self.cancel_event,
                progress=lambda fraction, message: self.events.put(("progress", (fraction, message))))
            return ("exported", result.data) if result.success else ("cancelled" if result.data.get("cancelled") else "error", result.error)
        self._start(render)

    def _poll(self):
        self._poll_id = None
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "progress":
                    self.progress["value"] = payload[0] * 100
                    self.status.set(payload[1])
                    continue
                self._set_busy(False)
                if kind == "exported":
                    self.last_output = Path(payload["output"])
                    self.open_button.configure(state="normal")
                    self.progress["value"] = 100
                    self.status.set(f"Exportação verificada: {self.last_output}")
                if self.closing:
                    shutting_down = self.after_close is not None
                    self._finish_close()
                    if shutting_down:
                        return
                    continue
                if kind == "fit":
                    duration, self.items = payload
                    self._refresh(0)
                    self.wav_info.set(f"WAV: {duration:.3f} s. Vídeo ajustado ao quadro seguinte, com diferença menor que 1/30 s.")
                    self.status.set("Timeline ajustada. Confira a ordem e exporte o MP4.")
                elif kind == "plan_generated":
                    path, scene_count, duration = payload
                    self.last_plan = path
                    self.status.set(
                        f"Plano gerado: {scene_count} cena(s) para WAV de {duration:.3f} s → {path.name}. "
                        "Preencha 'media' e use Importar plano.")
                elif kind == "exported":
                    pass
                elif kind == "cancelled":
                    self.status.set(str(payload))
                else:
                    self.status.set(f"Erro: {payload}")
                    messagebox.showerror("Falha na montagem", str(payload), parent=self)
        except queue.Empty:
            pass
        self._poll_id = self.after(100, self._poll)

    def open_output(self):
        if self.last_output and self.last_output.is_file():
            try:
                os.startfile(str(self.last_output))
            except (OSError, AttributeError) as exc:
                messagebox.showerror("Não foi possível abrir o MP4", str(exc), parent=self)

    def request_close(self, after=None):
        if after is not None:
            self.after_close = after
        if self.busy:
            self.closing = True
            self.cancel_event.set()
            self.status.set("Cancelando a operação antes de fechar…")
        else:
            self._finish_close()

    def _finish_close(self):
        callback = self.after_close
        self.closing = False
        if callback:
            self.destroy()
            callback()
        else:
            # Closing the editor is navigation: retain the user's timeline
            # until the Studio itself closes.
            self.withdraw()

    def destroy(self):
        if self._poll_id is not None:
            self.after_cancel(self._poll_id)
            self._poll_id = None
        super().destroy()
