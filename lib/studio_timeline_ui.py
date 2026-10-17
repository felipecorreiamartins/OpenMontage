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

from lib.studio_hyperframes import (
    DEFAULT_DURATION_SECONDS as HF_DEFAULT_DURATION, HYPERFRAMES_CREATOR,
    HYPERFRAMES_LICENSE, HYPERFRAMES_SOURCE, render_test_scene, validate_duration,
)
from lib.studio_stickman import (
    CHARACTER_LABELS as STICKMAN_CHARACTER_LABELS, CHARACTERS as STICKMAN_CHARACTERS,
    DEFAULT_DURATION_SECONDS as STICKMAN_DEFAULT_DURATION, PRESET_KEYS as STICKMAN_PRESETS,
    PRESET_LABELS as STICKMAN_PRESET_LABELS, STICKMAN_CREATOR, STICKMAN_LICENSE,
    STICKMAN_SOURCE, build_spec as build_stickman_spec,
    preset_default_duration as stickman_preset_duration,
    render_stickman_scene, validate_spec as validate_stickman_spec,
)
from lib.studio_scene_generator import generate_plan_file
from lib.studio_scenes import ScenePlan, load_scenes, save_plan, save_scenes, scenes_to_items
from lib.studio_stock_search import (
    available_stock_source_names, build_search_input, normalize_kind,
    run_stock_search, scene_with_clip, stock_clip_path, stock_install_instructions, write_credits,
)
from lib.studio_timeline import (
    APPROVED_WAV, FPS, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS,
    TimelineItem, fit_to_audio, move_item, seconds_to_frames, timeline_frames,
)
from tools.video.studio_export import StudioExport, wav_duration

TRANSITION_LABELS = {"Corte": "cut", "Crossfade": "crossfade", "Fade por preto": "fade"}


def _setup_modal_dialog(dialog: tk.Toplevel) -> None:
    """Make a Toplevel modal but resilient to minimize / alt-tab on Windows.

    A bare grab_set() can get stuck when the dialog is iconified: Tk keeps
    redirecting input to the hidden window and the user cannot return.
    Release the grab on <Unmap> and re-establish it (plus lift) on <Map>.
    """
    def _on_unmap(_event):
        try:
            if dialog.winfo_exists():
                dialog.grab_release()
        except tk.TclError:
            pass

    def _on_map(_event):
        try:
            if dialog.winfo_exists():
                dialog.grab_set()
                dialog.lift()
        except tk.TclError:
            pass

    dialog.bind("<Unmap>", _on_unmap, add="+")
    dialog.bind("<Map>", _on_map, add="+")


class TimelineEditor(tk.Toplevel):
    def __init__(self, master, output_dir: Path, plans_dir: Path | None = None):
        super().__init__(master)
        self.title("OpenMontage Studio — Montagem local")
        self.geometry("1080x700")
        self.minsize(850, 630)
        self.output_dir = output_dir
        self.plans_dir = Path(plans_dir) if plans_dir is not None else output_dir / "plans"
        self.items: list[TimelineItem] = []
        self.events: queue.Queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.busy = False
        self.closing = False
        self.after_close = None
        self.last_output: Path | None = None
        self.last_plan: Path | None = None
        self.current_plan: ScenePlan | None = None
        self.current_plan_path: Path | None = None
        # Timeline positions differ from plan positions when planning scenes are skipped.
        self._timeline_scene_ids: list[str | None] = []
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
        self._button(plan_row, "Buscar mídia stock…", self.open_stock_search)
        self._button(plan_row, "Cena HyperFrames…", self.open_hyperframes_dialog)
        self._button(plan_row, "Cena Stickman…", self.open_stickman_dialog)

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
                  "Planos scenes.json importam/exportam a montagem inteira sem tocar no áudio. "
                  "Cenas HyperFrames geram um MP4 silencioso local (1920×1080 · 30 fps) que pode ir para o plano ou para a timeline. "
                  "Cenas Stickman animam personagens articulados (entrar, caminhar, sentar, digitar, gestos) pelo mesmo caminho local.",
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
        dialog.minsize(420, 360)
        dialog.transient(self)
        dialog.grab_set()
        _setup_modal_dialog(dialog)
        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_rowconfigure(1, weight=1)
        ttk.Label(dialog, text="Texto da narração (segmentos viram cenas de planejamento)",
                  style="Section.TLabel").grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 6))
        body = ttk.Frame(dialog)
        body.grid(row=1, column=0, sticky="nsew", padx=14)
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(0, weight=1)
        text = tk.Text(body, wrap="word", bg="#0f1720", fg="#e8eef5", insertbackground="white",
                       relief="flat", padx=8, pady=6, font=("Segoe UI", 10))
        scroll = ttk.Scrollbar(body, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.grid(row=0, column=1, sticky="ns")
        text.grid(row=0, column=0, sticky="nsew")
        ttk.Label(dialog, text="As durações são proporcionais ao WAV ativo. Nenhuma mídia é inventada; "
                               "preencha 'media' em cada cena e use Importar plano para montar o vídeo.",
                  wraplength=620, justify="left").grid(row=2, column=0, sticky="ew", padx=14, pady=(8, 4))
        footer = ttk.Frame(dialog)
        footer.grid(row=3, column=0, sticky="ew", padx=14, pady=(4, 14))

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
            destination = self.plans_dir / "scenes.json"
            if destination.exists():
                destination = self.plans_dir / f"scenes-{datetime.now():%Y%m%d-%H%M%S-%f}.json"
            path = generate_plan_file(narration_text, duration, destination, wav=wav)
            plan = load_scenes(path)
            return "plan_generated", (path, len(plan.scenes), duration, plan)

        self._start(worker)

    def import_plan(self):
        if self.busy:
            return
        initialdir = self.plans_dir
        if self.current_plan_path is not None:
            initialdir = self.current_plan_path.parent
        chosen = filedialog.askopenfilename(
            parent=self, title="Importar scenes.json", initialdir=str(initialdir),
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
            self.current_plan = plan
            self.current_plan_path = Path(chosen)
            self._timeline_scene_ids = []
            messagebox.showerror(
                "Plano de planejamento",
                f"O plano tem {planning} cena(s) de planejamento sem 'media'. "
                "Use Buscar mídia stock… para associar mídias às cenas e importe novamente para montar o vídeo.",
                parent=self)
            self.status.set(f"Plano carregado: {planning} cena(s) de planejamento, sem mídia para montar.")
            return
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
        self.current_plan = plan
        self.current_plan_path = Path(chosen)
        self._timeline_scene_ids = [entry.id for entry in plan.scenes if entry.media is not None]
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

    def open_stock_search(self):
        if self.busy:
            return
        if self.current_plan is None:
            messagebox.showinfo(
                "Plano necessário",
                "Gere ou importe um plano de cenas antes de buscar mídia stock.",
                parent=self)
            return
        plan = self.current_plan
        available = available_stock_source_names()
        if not available:
            missing = ["pexels", "pixabay_video", "wikimedia"]
            messagebox.showerror(
                "Nenhuma fonte stock disponível",
                "Configure pelo menos uma das fontes abaixo:\n"
                + stock_install_instructions(missing),
                parent=self)
            return
        scene_ids = [entry.id for entry in plan.scenes]
        default_scene = scene_ids[0]
        selected = self._index()
        selected_scene = (self._timeline_scene_ids[selected]
                          if selected is not None and selected < len(self._timeline_scene_ids) else None)
        if selected_scene in scene_ids:
            default_scene = selected_scene
        elif plan.planning_count:
            for entry in plan.scenes:
                if entry.media is None:
                    default_scene = entry.id
                    break
        default_query = ""
        for entry in plan.scenes:
            if entry.id == default_scene:
                default_query = (entry.narration or entry.note or "").strip()
                break
        dialog = tk.Toplevel(self)
        dialog.title("Buscar mídia stock")
        dialog.geometry("560x340")
        dialog.minsize(480, 300)
        dialog.transient(self)
        dialog.grab_set()
        _setup_modal_dialog(dialog)
        ttk.Label(dialog, text="Buscar imagem ou clipe gratuito (Pexels, Pixabay, Wikimedia)",
                  style="Section.TLabel").pack(anchor="w", padx=14, pady=(14, 6))
        form = ttk.Frame(dialog)
        form.pack(fill="x", padx=14)
        ttk.Label(form, text="Cena de destino").pack(anchor="w")
        scene_var = tk.StringVar(value=default_scene)
        scene_box = ttk.Combobox(form, textvariable=scene_var, values=scene_ids, state="readonly")
        scene_box.pack(fill="x", pady=(2, 8))
        ttk.Label(form, text="Termo de busca").pack(anchor="w")
        query_var = tk.StringVar(value=default_query)
        query_entry = ttk.Entry(form, textvariable=query_var)
        query_entry.pack(fill="x", pady=(2, 8))

        def scene_changed(_event):
            entry = next(entry for entry in plan.scenes if entry.id == scene_var.get())
            query_var.set((entry.narration or entry.note or "").strip())

        scene_box.bind("<<ComboboxSelected>>", scene_changed)
        row = ttk.Frame(form)
        row.pack(fill="x", pady=(0, 8))
        ttk.Label(row, text="Tipo").pack(side="left", padx=(0, 4))
        kind_var = tk.StringVar(value="video")
        ttk.Combobox(row, textvariable=kind_var, values=("video", "image", "any"),
                     state="readonly", width=10).pack(side="left", padx=(0, 12))
        ttk.Label(row, text="Resultados").pack(side="left", padx=(0, 4))
        count_var = tk.StringVar(value="3")
        ttk.Spinbox(row, from_=1, to=10, textvariable=count_var, width=5).pack(side="left", padx=(0, 12))
        ttk.Label(row, text="Fontes: " + ", ".join(available)).pack(side="left")
        ttk.Label(dialog, text="A busca baixa arquivos em uma subpasta 'stock' do projeto e grava "
                               "licença/autor na cena selecionada. O WAV aprovado não é alterado.",
                  wraplength=500, justify="left").pack(anchor="w", padx=14, pady=(0, 6))
        footer = ttk.Frame(dialog)
        footer.pack(fill="x", padx=14, pady=(4, 14))

        def cancel():
            dialog.destroy()

        def start_search():
            query = query_var.get().strip()
            if not query:
                messagebox.showerror("Termo necessário", "Digite um termo de busca.", parent=dialog)
                return
            try:
                kind = normalize_kind(kind_var.get())
                count = max(1, min(int(count_var.get()), 20))
            except (ValueError, TypeError):
                messagebox.showerror("Valor inválido", "Tipo ou quantidade inválidos.", parent=dialog)
                return
            scene_id = scene_var.get()
            dialog.destroy()
            self.search_stock(scene_id, query, kind, count, available)

        ttk.Button(footer, text="Cancelar", command=cancel).pack(side="right", padx=(6, 0))
        ttk.Button(footer, text="Buscar", style="Accent.TButton", command=start_search).pack(side="right")
        query_entry.focus_set()

    def search_stock(self, scene_id: str, query: str, kind: str, count: int, sources: list[str]):
        if self.busy:
            return
        stock_dir = self.output_dir / "stock"
        self.status.set(f"Buscando mídia stock para {scene_id!r}: “{query}”…")
        inputs = build_search_input(
            query=query,
            output_dir=stock_dir,
            kind=kind,
            sources=sources,
            clips_per_query=count,
            timeout_seconds=120.0,
            slot_id=scene_id,
        )

        def worker():
            summary = run_stock_search(inputs)
            if self.cancel_event.is_set():
                return "cancelled", "Busca stock cancelada."
            return "stock_results", (scene_id, summary)

        self._start(worker)

    def open_hyperframes_dialog(self):
        if self.busy:
            return
        dialog = tk.Toplevel(self)
        dialog.title("Gerar cena HyperFrames")
        dialog.geometry("560x360")
        dialog.minsize(500, 320)
        dialog.transient(self)
        dialog.grab_set()
        _setup_modal_dialog(dialog)
        ttk.Label(dialog, text="Cena animada de teste (HyperFrames local)",
                  style="Section.TLabel").pack(anchor="w", padx=14, pady=(14, 6))
        form = ttk.Frame(dialog)
        form.pack(fill="x", padx=14)
        ttk.Label(form, text="Texto da cena").pack(anchor="w")
        text_var = tk.StringVar(value="Cena HyperFrames")
        text_entry = ttk.Entry(form, textvariable=text_var)
        text_entry.pack(fill="x", pady=(2, 8))
        ttk.Label(form, text="Subtítulo (opcional)").pack(anchor="w")
        subtitle_var = tk.StringVar(value="OpenMontage Studio")
        ttk.Entry(form, textvariable=subtitle_var).pack(fill="x", pady=(2, 8))
        row = ttk.Frame(form)
        row.pack(fill="x", pady=(0, 8))
        ttk.Label(row, text="Duração (s)").pack(side="left", padx=(0, 4))
        duration_var = tk.StringVar(value=str(HF_DEFAULT_DURATION))
        ttk.Entry(row, textvariable=duration_var, width=8).pack(side="left", padx=(0, 14))
        add_to_timeline = tk.BooleanVar(value=True)
        ttk.Checkbutton(row, text="Adicionar à timeline", variable=add_to_timeline).pack(side="left")
        scene_var = tk.StringVar(value="(não associar)")
        if self.current_plan is not None:
            scene_ids = [entry.id for entry in self.current_plan.scenes]
            default_scene = "(não associar)"
            for entry in self.current_plan.scenes:
                if entry.media is None:
                    default_scene = entry.id
                    break
            scene_var.set(default_scene)
            ttk.Label(form, text="Cena de destino no plano").pack(anchor="w")
            ttk.Combobox(form, textvariable=scene_var,
                         values=tuple(["(não associar)", *scene_ids]),
                         state="readonly").pack(fill="x", pady=(2, 8))
        ttk.Label(
            dialog,
            text="Renderiza localmente com HyperFrames (Node 22+, FFmpeg e npx): MP4 silencioso "
                 "1920×1080 · 30 fps, sem chamadas pagas. O WAV aprovado e as mídias existentes "
                 "não são alterados; saídas recebem nomes novos. Dependências ausentes aparecem "
                 "como erro, sem interromper o Studio.",
            wraplength=500, justify="left").pack(anchor="w", padx=14, pady=(0, 6))
        footer = ttk.Frame(dialog)
        footer.pack(fill="x", padx=14, pady=(4, 14))

        def cancel():
            dialog.destroy()

        def start():
            scene_id = None if scene_var.get() == "(não associar)" else scene_var.get()
            try:
                duration = validate_duration(duration_var.get())
            except ValueError as exc:
                messagebox.showerror("Duração inválida", str(exc), parent=dialog)
                return
            content = text_var.get().strip()
            if not content:
                messagebox.showerror("Texto necessário", "Digite o texto da cena.", parent=dialog)
                return
            dialog.destroy()
            self.generate_hyperframes_scene(
                content, subtitle_var.get(), duration,
                add_to_timeline.get(), scene_id)

        ttk.Button(footer, text="Cancelar", command=cancel).pack(side="right", padx=(6, 0))
        ttk.Button(footer, text="Gerar cena", style="Accent.TButton", command=start).pack(side="right")
        text_entry.focus_set()

    def generate_hyperframes_scene(self, text, subtitle, duration_seconds,
                                   add_to_timeline, scene_id):
        if self.busy:
            return
        try:
            duration = validate_duration(duration_seconds)
        except ValueError as exc:
            messagebox.showerror("Duração inválida", str(exc), parent=self)
            return
        if not str(text).strip():
            messagebox.showerror("Texto necessário", "Digite o texto da cena.", parent=self)
            return
        if scene_id and self.current_plan is None:
            scene_id = None
        self.progress["value"] = 0
        self.status.set("Preparando a geração da cena HyperFrames…")
        output_dir = self.output_dir

        def worker():
            summary = render_test_scene(
                output_dir=output_dir,
                text=text,
                subtitle=subtitle,
                duration_seconds=duration,
                progress=lambda fraction, message: self.events.put(
                    ("progress", (fraction, message))),
                cancel_event=self.cancel_event,
            )
            if self.cancel_event.is_set():
                detail = summary.get("error") or "Geração de cena HyperFrames cancelada."
                return "cancelled", detail
            return "hyperframes_scene", (
                summary,
                {"add_to_timeline": bool(add_to_timeline), "scene_id": scene_id},
            )

        self._start(worker)

    def _finish_hyperframes_scene(self, summary: dict, options: dict):
        path = Path(summary["output"])
        scene_id = options.get("scene_id")
        associated = False
        notes: list[str] = []
        if scene_id:
            clip = {
                "path": str(path),
                "source": HYPERFRAMES_SOURCE,
                "source_id": Path(summary.get("workspace") or path).name,
                "source_url": "",
                "creator": HYPERFRAMES_CREATOR,
                "license": HYPERFRAMES_LICENSE,
                "kind": "video",
            }
            if self._apply_clip_to_scene(scene_id, clip):
                associated = True
                notes.append(f"cena {scene_id} associada no plano")
            else:
                notes.append(f"não foi possível associar a cena {scene_id}")
        if options.get("add_to_timeline"):
            padding = len(self.items) - len(self._timeline_scene_ids)
            if padding > 0:
                self._timeline_scene_ids.extend([None] * padding)
            self._timeline_scene_ids.append(scene_id if associated else None)
            duration = float(summary.get("duration_seconds") or 5.0)
            self.items.append(TimelineItem(path, duration))
            self._refresh(len(self.items) - 1)
            notes.append("adicionado à timeline")
        self.progress["value"] = 100
        detail = (
            f"Cena HyperFrames pronta: {path.name} · {summary['width']}×{summary['height']} · "
            f"{summary['fps']} fps · {float(summary.get('duration_seconds') or 0):.3f} s"
        )
        if notes:
            detail += " · " + "; ".join(notes)
        self.status.set(detail + ".")

    def open_stickman_dialog(self):
        if self.busy:
            return
        dialog = tk.Toplevel(self)
        dialog.title("Gerar cena Stickman")
        dialog.geometry("580x430")
        dialog.minsize(520, 380)
        dialog.transient(self)
        dialog.grab_set()
        _setup_modal_dialog(dialog)
        ttk.Label(dialog, text="Cena animada Stickman (motor local SVG + GSAP)",
                  style="Section.TLabel").pack(anchor="w", padx=14, pady=(14, 6))
        form = ttk.Frame(dialog)
        form.pack(fill="x", padx=14)
        ttk.Label(form, text="Roteiro (preset)").pack(anchor="w")
        preset_var = tk.StringVar(value=STICKMAN_PRESETS[0])
        preset_box = ttk.Combobox(
            form, textvariable=preset_var, state="readonly",
            values=tuple(f"{key} — {STICKMAN_PRESET_LABELS[key]}" for key in STICKMAN_PRESETS))
        preset_box.pack(fill="x", pady=(2, 8))
        ttk.Label(form, text="Personagem").pack(anchor="w")
        character_var = tk.StringVar(value=STICKMAN_CHARACTERS[0])
        ttk.Combobox(
            form, textvariable=character_var, state="readonly",
            values=tuple(f"{key} — {STICKMAN_CHARACTER_LABELS[key]}"
                         for key in STICKMAN_CHARACTERS)).pack(fill="x", pady=(2, 8))
        row = ttk.Frame(form)
        row.pack(fill="x", pady=(0, 8))
        ttk.Label(row, text="Duração (s)").pack(side="left", padx=(0, 4))
        duration_var = tk.StringVar(value=str(STICKMAN_DEFAULT_DURATION))
        ttk.Entry(row, textvariable=duration_var, width=8).pack(side="left", padx=(0, 14))
        add_to_timeline = tk.BooleanVar(value=True)
        ttk.Checkbutton(row, text="Adicionar à timeline", variable=add_to_timeline).pack(side="left")
        scene_var = tk.StringVar(value="(não associar)")
        if self.current_plan is not None:
            scene_ids = [entry.id for entry in self.current_plan.scenes]
            default_scene = "(não associar)"
            for entry in self.current_plan.scenes:
                if entry.media is None:
                    default_scene = entry.id
                    break
            scene_var.set(default_scene)
            ttk.Label(form, text="Cena de destino no plano").pack(anchor="w")
            ttk.Combobox(form, textvariable=scene_var,
                         values=tuple(["(não associar)", *scene_ids]),
                         state="readonly").pack(fill="x", pady=(2, 8))
        ttk.Label(
            dialog,
            text="Renderiza localmente com HyperFrames (Node 22+, FFmpeg e npx): personagem "
                 "articulado com ações reais (entrar, caminhar, sentar, digitar, gestos, emoções) "
                 "em cenários reutilizáveis. MP4 silencioso 1920×1080 · 30 fps, sem chamadas "
                 "pagas. O WAV aprovado e as mídias existentes não são alterados; saídas recebem "
                 "nomes novos. Dependências ausentes aparecem como erro, sem interromper o Studio.",
            wraplength=520, justify="left").pack(anchor="w", padx=14, pady=(0, 6))
        footer = ttk.Frame(dialog)
        footer.pack(fill="x", padx=14, pady=(4, 14))

        def preset_key() -> str:
            return preset_var.get().split(" — ", 1)[0].strip()

        def character_key() -> str:
            return character_var.get().split(" — ", 1)[0].strip()

        def sync_duration(_event=None):
            try:
                spec = build_stickman_spec(preset_key(),
                                           stickman_preset_duration(preset_key()),
                                           character_key())
            except ValueError:
                return
            duration_var.set(str(spec["duration_seconds"]))

        preset_box.bind("<<ComboboxSelected>>", sync_duration)
        sync_duration()

        def cancel():
            dialog.destroy()

        def start():
            scene_id = None if scene_var.get() == "(não associar)" else scene_var.get()
            try:
                spec = build_stickman_spec(preset_key(), duration_var.get(), character_key())
            except ValueError as exc:
                messagebox.showerror("Cena Stickman inválida", str(exc), parent=dialog)
                return
            dialog.destroy()
            self.generate_stickman_scene(
                spec, add_to_timeline.get(), scene_id)

        ttk.Button(footer, text="Cancelar", command=cancel).pack(side="right", padx=(6, 0))
        ttk.Button(footer, text="Gerar cena", style="Accent.TButton", command=start).pack(side="right")

    def generate_stickman_scene(self, spec, add_to_timeline, scene_id):
        if self.busy:
            return
        try:
            validate_stickman_spec(spec)
        except ValueError as exc:
            messagebox.showerror("Cena Stickman inválida", str(exc), parent=self)
            return
        if scene_id and self.current_plan is None:
            scene_id = None
        self.progress["value"] = 0
        self.status.set("Preparando a geração da cena Stickman…")
        output_dir = self.output_dir

        def worker():
            summary = render_stickman_scene(
                output_dir=output_dir,
                spec=spec,
                progress=lambda fraction, message: self.events.put(
                    ("progress", (fraction, message))),
                cancel_event=self.cancel_event,
            )
            if self.cancel_event.is_set():
                detail = summary.get("error") or "Geração de cena Stickman cancelada."
                return "cancelled", detail
            return "stickman_scene", (
                summary,
                {"add_to_timeline": bool(add_to_timeline), "scene_id": scene_id},
            )

        self._start(worker)

    def _finish_stickman_scene(self, summary: dict, options: dict):
        path = Path(summary["output"])
        scene_id = options.get("scene_id")
        associated = False
        notes: list[str] = []
        if scene_id:
            clip = {
                "path": str(path),
                "source": STICKMAN_SOURCE,
                "source_id": Path(summary.get("workspace") or path).name,
                "source_url": "",
                "creator": STICKMAN_CREATOR,
                "license": STICKMAN_LICENSE,
                "kind": "video",
            }
            if self._apply_clip_to_scene(scene_id, clip):
                associated = True
                notes.append(f"cena {scene_id} associada no plano")
            else:
                notes.append(f"não foi possível associar a cena {scene_id}")
        if options.get("add_to_timeline"):
            padding = len(self.items) - len(self._timeline_scene_ids)
            if padding > 0:
                self._timeline_scene_ids.extend([None] * padding)
            self._timeline_scene_ids.append(scene_id if associated else None)
            duration = float(summary.get("duration_seconds") or 5.0)
            self.items.append(TimelineItem(path, duration))
            self._refresh(len(self.items) - 1)
            notes.append("adicionado à timeline")
        self.progress["value"] = 100
        detail = (
            f"Cena Stickman pronta: {path.name} · {summary['width']}×{summary['height']} · "
            f"{summary['fps']} fps · {float(summary.get('duration_seconds') or 0):.3f} s · "
            f"preset {summary.get('preset') or '?'}"
        )
        if notes:
            detail += " · " + "; ".join(notes)
        self.status.set(detail + ".")

    def _show_stock_results(self, scene_id: str, summary: dict):
        clips = summary.get("clips", [])
        errors = summary.get("errors", [])
        search_error = summary.get("error", "")
        if not clips:
            if search_error or errors or summary.get("timed_out"):
                detail = search_error or str(errors) or "O tempo limite da busca foi atingido."
                self.status.set(f"Falha na busca para {scene_id!r}: {detail}")
                messagebox.showerror("Falha na busca stock", detail, parent=self)
            else:
                self.status.set(f"Nenhum resultado para {scene_id!r}. Tente outras palavras.")
                messagebox.showinfo(
                    "Sem resultados",
                    f"Nenhum resultado para “{scene_id}”. Tente outras palavras ou outro tipo.",
                    parent=self)
            return
        if summary.get("timed_out"):
            self.status.set(f"Busca para {scene_id!r} expirou; mostrando resultados parciais.")
        elif errors:
            self.status.set(f"Busca para {scene_id!r}: {len(clips)} resultado(s), {len(errors)} erro(s).")
        else:
            self.status.set(f"Busca para {scene_id!r}: {len(clips)} resultado(s).")
        dialog = tk.Toplevel(self)
        dialog.title(f"Resultados stock — {scene_id}")
        dialog.geometry("720x420")
        dialog.minsize(520, 340)
        dialog.transient(self)
        dialog.grab_set()
        _setup_modal_dialog(dialog)
        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_rowconfigure(1, weight=1)
        ttk.Label(dialog, text=f"Resultados para {scene_id}", style="Section.TLabel").grid(
            row=0, column=0, sticky="ew", padx=12, pady=(12, 4))
        table = ttk.Frame(dialog)
        table.grid(row=1, column=0, sticky="nsew", padx=12)
        table.grid_columnconfigure(0, weight=1)
        table.grid_rowconfigure(0, weight=1)
        tree = ttk.Treeview(table, columns=("name", "source", "creator", "license", "kind"),
                            show="headings", selectmode="browse", height=8)
        for key, title, width in (("name", "Arquivo", 220), ("source", "Fonte", 90),
                                  ("creator", "Autor", 130), ("license", "Licença", 160),
                                  ("kind", "Tipo", 60)):
            tree.heading(key, text=title)
            tree.column(key, width=width, minwidth=50, stretch=key == "name")
        scrollbar = ttk.Scrollbar(table, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=0, column=1, sticky="ns")
        tree.grid(row=0, column=0, sticky="nsew")
        clips_by_id = {}
        for clip in clips:
            name = Path(str(clip.get("path", ""))).name
            item_id = tree.insert("", "end", values=(
                name,
                clip.get("source", ""),
                clip.get("creator", ""),
                clip.get("license", ""),
                clip.get("kind", ""),
            ))
            clips_by_id[item_id] = clip
        first_id = tree.get_children()[0]
        tree.selection_set(first_id)
        tree.focus(first_id)
        row = 2
        if errors or search_error:
            detail = search_error or "; ".join(str(e.get("error", e)) if isinstance(e, dict) else str(e)
                                               for e in errors[:3])
            ttk.Label(dialog, text=f"Erros: {detail}", wraplength=680).grid(
                row=row, column=0, sticky="ew", padx=12, pady=(4, 0))
            row += 1
        footer = ttk.Frame(dialog)
        footer.grid(row=row, column=0, sticky="ew", padx=12, pady=(8, 12))

        def use_in_scene():
            selection = tree.selection()
            if not selection:
                return
            clip = clips_by_id[selection[0]]
            if self._apply_clip_to_scene(scene_id, clip):
                dialog.destroy()

        def add_to_timeline():
            selection = tree.selection()
            if not selection:
                return
            clip = clips_by_id[selection[0]]
            try:
                path = stock_clip_path(clip)
            except (OSError, ValueError) as exc:
                messagebox.showerror("Clipe inválido", str(exc), parent=dialog)
                return
            self.add_paths([path])
            dialog.destroy()

        ttk.Button(footer, text="Fechar", command=dialog.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(footer, text="Adicionar à timeline", command=add_to_timeline).pack(side="right", padx=(6, 0))
        ttk.Button(footer, text="Usar nesta cena", style="Accent.TButton", command=use_in_scene).pack(side="right")

    def _apply_clip_to_scene(self, scene_id: str, clip: dict) -> bool:
        if self.busy:
            return False
        plan = self.current_plan
        if plan is None:
            messagebox.showerror("Plano perdido", "Gere ou importe um plano antes de associar mídia.", parent=self)
            return False
        updated_scenes = []
        target = None
        for entry in plan.scenes:
            if entry.id == scene_id:
                try:
                    updated = scene_with_clip(entry, clip)
                except (OSError, ValueError) as exc:
                    messagebox.showerror("Clipe inválido", str(exc), parent=self)
                    return False
                updated_scenes.append(updated)
                target = updated
            else:
                updated_scenes.append(entry)
        if target is None:
            messagebox.showerror("Cena não encontrada", f"Cena {scene_id!r} não existe no plano.", parent=self)
            return False
        new_plan = ScenePlan(
            scenes=tuple(updated_scenes),
            version=plan.version,
            title=plan.title,
            wav=plan.wav,
            metadata=plan.metadata,
        )
        destination = self.current_plan_path or (self.plans_dir / "scenes.json")
        try:
            save_plan(destination, new_plan)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Não foi possível salvar o plano", str(exc), parent=self)
            return False
        self.current_plan = new_plan
        self.current_plan_path = destination
        self.last_plan = destination
        credits_path = destination.parent / "CREDITS.md"
        try:
            write_credits(new_plan.scenes, credits_path)
        except OSError as exc:
            self.status.set(f"Mídia associada à cena {scene_id!r}. Plano salvo; falha ao gravar créditos: {exc}")
            messagebox.showwarning("Créditos não salvos", f"O plano foi salvo, mas {credits_path} não pôde ser gravado:\n{exc}", parent=self)
            return True
        self.status.set(
            f"Mídia associada à cena {scene_id!r} ({target.source}). "
            f"Plano salvo em {destination.name}. Créditos em {credits_path.name}. "
            "Use Importar plano para atualizar a timeline.")
        return True

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
            self._timeline_scene_ids.extend([None] * (len(self.items) - len(self._timeline_scene_ids) + len(added)))
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
            if index < len(self._timeline_scene_ids):
                self._timeline_scene_ids.pop(index)
            self._refresh(min(index, len(self.items) - 1))

    def move_selected(self, offset):
        index = self._index()
        if not self.busy and index is not None and 0 <= index + offset < len(self.items):
            if len(self._timeline_scene_ids) == len(self.items):
                self._timeline_scene_ids.insert(index + offset, self._timeline_scene_ids.pop(index))
            else:
                self._timeline_scene_ids = []
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
                    path, scene_count, duration, plan = payload
                    self.last_plan = path
                    self.current_plan = plan
                    self.current_plan_path = path
                    self._timeline_scene_ids = []
                    self.status.set(
                        f"Plano gerado: {scene_count} cena(s) para WAV de {duration:.3f} s → {path}. "
                        "Preencha 'media' (ex.: Buscar mídia stock…) e use Importar plano.")
                    messagebox.showinfo(
                        "Plano gerado",
                        f"{scene_count} cena(s) de planejamento salvas em:\n{path}\n\n"
                        "A timeline continua vazia até cada cena receber 'media'. "
                        "Use Buscar mídia stock… para preencher as cenas e depois "
                        "Importar plano para montar a timeline.",
                        parent=self)
                elif kind == "stock_results":
                    scene_id, summary = payload
                    self._show_stock_results(scene_id, summary)
                elif kind == "hyperframes_scene":
                    summary, options = payload
                    if not summary.get("ok"):
                        detail = summary.get("error") or "Falha desconhecida ao gerar a cena HyperFrames."
                        self.status.set(f"Falha na cena HyperFrames: {detail}")
                        messagebox.showerror("Falha na cena HyperFrames", detail, parent=self)
                    else:
                        self._finish_hyperframes_scene(summary, options)
                elif kind == "stickman_scene":
                    summary, options = payload
                    if not summary.get("ok"):
                        detail = summary.get("error") or "Falha desconhecida ao gerar a cena Stickman."
                        self.status.set(f"Falha na cena Stickman: {detail}")
                        messagebox.showerror("Falha na cena Stickman", detail, parent=self)
                    else:
                        self._finish_stickman_scene(summary, options)
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
