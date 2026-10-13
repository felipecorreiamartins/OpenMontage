"""OpenMontage Studio: local audio tools and non-destructive FFmpeg timeline."""

from __future__ import annotations

import json
import queue
import re
import subprocess
import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from tools.audio.audio_mixer import AudioMixer
from tools.audio.kokoro_tts import KokoroTTS
from lib.studio_timeline_ui import TimelineEditor


ROOT = Path(__file__).resolve().parent
DEFAULT_CATALOG = Path(r"D:\YouTube-Automacao\Musicas\catalogo_musical.json")
DEFAULT_OUTPUT = ROOT / "projects" / "openmontage-studio" / "audio"
VOICES = ("af_heart", "am_echo", "am_michael")  # voices used in existing local Kokoro tests
MODE_IDS = ("create", "edit", "custom")
MODE_LABELS = {
    "create": "Criar vídeo",
    "edit": "Editar vídeo bruto",
    "custom": "Produção personalizada",
}
MOOD_LABELS = {
    "suspense": "Suspense", "epica": "Épica", "emocional": "Emocional",
    "misterio": "Mistério", "cinematografica": "Cinematográfica",
    "leve": "Leve", "descontraida": "Descontraída", "tranquila": "Tranquila",
    "ambiente": "Ambiente", "terror": "Terror", "tecnologia": "Tecnologia",
}


def duration_seconds(hours: str | int, minutes: str | int, seconds: str | int) -> int:
    """Parse custom hours/minutes/seconds; empty fields count as zero."""
    values = []
    for label, raw in (("horas", hours), ("minutos", minutes), ("segundos", seconds)):
        value_text = str(raw).strip()
        if not value_text:
            value_text = "0"
        try:
            value = int(value_text)
        except (ValueError, TypeError):
            raise ValueError(f"Informe um número inteiro válido para {label}.") from None
        if value < 0:
            raise ValueError(f"{label.capitalize()} não podem ser negativos.")
        values.append(value)
    hour_value, minute_value, second_value = values
    if minute_value > 59:
        raise ValueError("Minutos devem estar entre 0 e 59.")
    if second_value > 59:
        raise ValueError("Segundos devem estar entre 0 e 59.")
    total = hour_value * 3600 + minute_value * 60 + second_value
    if total == 0:
        raise ValueError("A duração planejada precisa ser maior que zero.")
    return total


def mode_for_tab(index: int) -> str:
    """Map notebook tabs to stable mode IDs used by navigation and tests."""
    if not isinstance(index, int) or index < 0:
        raise ValueError(f"Aba de modo inválida: {index!r}")
    try:
        return MODE_IDS[index]
    except (IndexError, TypeError):
        raise ValueError(f"Aba de modo inválida: {index!r}") from None


def local_video_selection(path: str | Path) -> Path:
    """Resolve an existing local video path without reading or modifying it."""
    source = Path(path).expanduser()
    if not source.is_file():
        raise FileNotFoundError(f"Arquivo de vídeo não encontrado: {source}")
    return source.resolve()


def load_music_catalog(path: str | Path) -> list[dict]:
    """Load only catalog entries whose audio file is present on disk."""
    catalog_path = Path(path).expanduser()
    if not catalog_path.is_file():
        return []
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("O catálogo deve conter uma lista JSON de faixas.")
    return [
        track for track in data
        if isinstance(track, dict)
        and track.get("arquivo")
        and Path(track["arquivo"]).is_file()
        and isinstance(track.get("humor", []), list)
    ]


def pick_music(tracks: list[dict], mood: str) -> dict | None:
    """Return a deterministic available catalog match for the chosen mood."""
    key = mood.strip().casefold()
    matches = [track for track in tracks if key in [str(tag).casefold() for tag in track.get("humor", [])]]
    return sorted(matches, key=lambda item: str(item.get("nome", "")).casefold())[0] if matches else None


def audio_duration(path: str | Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, timeout=30, check=True,
    )
    duration = float(result.stdout.strip())
    if duration <= 0:
        raise ValueError("A faixa de narração está vazia.")
    return duration


class OpenMontageStudio(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("OpenMontage Studio")
        self.geometry("1240x920")
        self.minsize(1020, 760)
        self.configure(bg="#10151c")
        self.style = ttk.Style(self)
        self.style.theme_use("clam")
        self._configure_styles()
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.busy = False
        self.narration_path: Path | None = None
        self.music_track: dict | None = None
        self.music_catalog: list[dict] = []
        self.current_mode = MODE_IDS[0]
        self.timeline_editor: TimelineEditor | None = None
        self._build_ui()
        self._refresh_catalog()
        self.protocol("WM_DELETE_WINDOW", self._close_studio)
        self.after(150, self._poll_events)

    def _configure_styles(self) -> None:
        self.style.configure("TFrame", background="#10151c")
        self.style.configure("Card.TFrame", background="#18212b")
        self.style.configure("TLabel", background="#10151c", foreground="#e8eef5", font=("Segoe UI", 10))
        self.style.configure("Card.TLabel", background="#18212b", foreground="#e8eef5", font=("Segoe UI", 10))
        self.style.configure("Title.TLabel", font=("Segoe UI Semibold", 23), foreground="#f4f7fb")
        self.style.configure("Sub.TLabel", foreground="#9cabbc")
        self.style.configure("Section.TLabel", background="#18212b", foreground="#a8d7ff", font=("Segoe UI Semibold", 12))
        self.style.configure("TButton", padding=(12, 8), font=("Segoe UI Semibold", 10))
        self.style.configure("Accent.TButton", background="#2476d2", foreground="white")
        self.style.map("Accent.TButton", background=[("disabled", "#33404e"), ("active", "#318be9")])
        self.style.configure("TEntry", fieldbackground="#0f1720", foreground="#e8eef5", insertcolor="white")
        self.style.configure("TCombobox", fieldbackground="#0f1720", foreground="#e8eef5", arrowcolor="#e8eef5")
        self.style.map("TCombobox", fieldbackground=[("readonly", "#0f1720")],
                       foreground=[("readonly", "#e8eef5")])
        self.style.configure("TNotebook", background="#18212b", borderwidth=0)
        self.style.configure("TNotebook.Tab", padding=(12, 9), background="#202c38", foreground="#d9e3ec")
        self.style.map("TNotebook.Tab", background=[("selected", "#2476d2")], foreground=[("selected", "white")])

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=(24, 20))
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="OpenMontage Studio", style="Title.TLabel").pack(anchor="w")
        ttk.Label(outer, text="Planeje o projeto e use os recursos locais já integrados", style="Sub.TLabel").pack(anchor="w", pady=(2, 12))

        project = ttk.Frame(outer, style="Card.TFrame", padding=14)
        project.pack(fill="x", pady=(0, 10))
        ttk.Label(project, text="Projeto e duração planejada", style="Section.TLabel").pack(anchor="w", pady=(0, 8))
        self.topic = tk.StringVar()
        self.project_description = tk.Text(project, height=3, wrap="word", bg="#0f1720", fg="#e8eef5", insertbackground="white", relief="flat", padx=8, pady=6, font=("Segoe UI", 9))
        identity = ttk.Frame(project, style="Card.TFrame")
        identity.pack(fill="x")
        identity.columnconfigure(0, weight=1)
        identity.columnconfigure(1, weight=2)
        ttk.Label(identity, text="Tema", style="Card.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Label(identity, text="Descrição (referência do projeto)", style="Card.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Entry(identity, textvariable=self.topic).grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=(4, 0))
        self.project_description.grid(in_=identity, row=1, column=1, sticky="ew", pady=(4, 0))

        duration_row = ttk.Frame(project, style="Card.TFrame")
        duration_row.pack(fill="x", pady=(9, 0))
        self.hours = tk.StringVar(value="00")
        self.minutes = tk.StringVar(value="08")
        self.seconds = tk.StringVar(value="00")
        self.duration_mode = tk.StringVar(value="Duração aproximada")
        for label, var, width in (("Horas", self.hours, 5), ("Minutos", self.minutes, 5), ("Segundos", self.seconds, 5)):
            cell = ttk.Frame(duration_row, style="Card.TFrame")
            cell.pack(side="left", padx=(0, 8))
            ttk.Label(cell, text=label, style="Card.TLabel").pack(anchor="w")
            ttk.Entry(cell, textvariable=var, width=width).pack(anchor="w", pady=(3, 0))
        self.duration_mode_combo = ttk.Combobox(duration_row, textvariable=self.duration_mode, values=("Duração aproximada", "Alvo rígido (não integrado)"), state="readonly")
        self._field(duration_row, "Tipo de duração", self.duration_mode_combo)
        self.duration_mode_combo.bind("<<ComboboxSelected>>", lambda _event: self._update_duration_status())
        self.duration_status = tk.StringVar(value="Planejamento: 00:08:00. A duração não controla a mixagem nem garante a duração do vídeo.")
        ttk.Label(project, textvariable=self.duration_status, style="Card.TLabel", wraplength=1000).pack(anchor="w", pady=(8, 0))
        for field in (self.hours, self.minutes, self.seconds):
            field.trace_add("write", lambda *_: self._update_duration_status())

        prep = ttk.Frame(outer, style="Card.TFrame", padding=(14, 10))
        prep.pack(fill="x", pady=(0, 10))
        ttk.Label(prep, text="Preferências preparatórias — não alteram as operações atuais", style="Section.TLabel").pack(anchor="w", pady=(0, 6))
        options = ttk.Frame(prep, style="Card.TFrame")
        options.pack(fill="x")
        self.language = tk.StringVar(value="English (Kokoro disponível)")
        self.subtitles = tk.StringVar(value="Desativadas")
        self.visual_style = tk.StringVar(value="clean-professional")
        for label, variable, values in (
            ("Idioma", self.language, ("English (Kokoro disponível)", "Português (preparatório)", "Deutsch (preparatório)", "Español (preparatório)")),
            ("Legendas", self.subtitles, ("Desativadas", "Preparar SRT (não integrado)", "Legendas queimadas (não integrado)")),
            ("Estilo visual", self.visual_style, ("clean-professional", "premium-minimalist", "anime-ghibli", "flat-motion-graphics", "minimalist-diagram")),
        ):
            item = ttk.Frame(options, style="Card.TFrame")
            item.pack(side="left", fill="x", expand=True, padx=(0, 10))
            ttk.Label(item, text=label, style="Card.TLabel").pack(anchor="w")
            ttk.Combobox(item, textvariable=variable, values=values, state="readonly").pack(fill="x", pady=(3, 0))
        ttk.Label(prep, text="Kokoro desta instalação gera inglês. Outros idiomas, legendas e estilos são apenas escolhas de planejamento.", style="Card.TLabel", wraplength=1000).pack(anchor="w", pady=(5, 0))

        body = ttk.Frame(outer)
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body, style="Card.TFrame", padding=12)
        left.pack(side="left", fill="both", expand=True, padx=(0, 10))
        right = ttk.Frame(body, style="Card.TFrame", padding=14, width=370)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)

        self.notebook = ttk.Notebook(left, style="TNotebook")
        self.notebook.pack(fill="both", expand=True)
        self.mode_pages: dict[str, ttk.Frame] = {}
        for mode_id in MODE_IDS:
            page = ttk.Frame(self.notebook, style="Card.TFrame", padding=16)
            self.notebook.add(page, text=MODE_LABELS[mode_id])
            self.mode_pages[mode_id] = page
        self.notebook.bind("<<NotebookTabChanged>>", self._on_mode_changed)
        self._build_create_mode(self.mode_pages["create"])
        self._build_edit_mode(self.mode_pages["edit"])
        self._build_custom_mode(self.mode_pages["custom"])

        # Keep the existing audio controls reachable at the minimum window
        # size, where the fixed-height side panel used to clip its buttons.
        audio_canvas = tk.Canvas(right, bg="#18212b", highlightthickness=0)
        audio_scroll = ttk.Scrollbar(right, orient="vertical", command=audio_canvas.yview)
        audio_canvas.configure(yscrollcommand=audio_scroll.set)
        audio_scroll.pack(side="right", fill="y")
        audio_canvas.pack(side="left", fill="both", expand=True)
        audio_panel = ttk.Frame(audio_canvas, style="Card.TFrame")
        audio_window = audio_canvas.create_window((0, 0), window=audio_panel, anchor="nw")
        audio_panel.bind("<Configure>", lambda _event: audio_canvas.configure(scrollregion=audio_canvas.bbox("all")))
        audio_canvas.bind("<Configure>", lambda event: audio_canvas.itemconfigure(audio_window, width=event.width))
        self._build_audio_panel(audio_panel)

        bottom = ttk.Frame(outer, style="Card.TFrame", padding=10)
        bottom.pack(fill="x", pady=(10, 0))
        self.status = tk.StringVar(value="Pronto. Áudio local e montagem manual com exportação MP4 disponíveis.")
        ttk.Label(bottom, textvariable=self.status, style="Card.TLabel").pack(anchor="w")
        self.progress = ttk.Progressbar(bottom, mode="indeterminate")
        self.progress.pack(fill="x", pady=5)
        self.log = tk.Text(bottom, height=4, wrap="word", bg="#0f1720", fg="#bdc9d5", insertbackground="white", relief="flat", state="disabled", font=("Consolas", 9))
        self.log.pack(fill="x")

    def _build_create_mode(self, page: ttk.Frame) -> None:
        ttk.Label(page, text="Criar vídeo do zero", style="Section.TLabel").pack(anchor="w")
        ttk.Label(page, text="Prepare o tema e o texto da narração. O painel ao lado gera e mixa áudio local. Monte imagens e clipes locais com um WAV na montagem manual; roteiro automático e pesquisa de mídia ainda não estão integrados. A montagem também aceita e salva planos scenes.json.", style="Card.TLabel", wraplength=610, justify="left").pack(anchor="w", pady=(10, 12))
        ttk.Label(page, text="Cole ou escreva o texto que será narrado no campo Texto da narração, no painel Áudio.", style="Card.TLabel", wraplength=610).pack(anchor="w")
        ttk.Button(page, text="Abrir montagem local e exportar MP4", command=self._open_timeline).pack(anchor="w", pady=14)

    def _build_edit_mode(self, page: ttk.Frame) -> None:
        ttk.Label(page, text="Selecionar vídeo bruto", style="Section.TLabel").pack(anchor="w")
        ttk.Label(page, text="Escolha um arquivo para registrar a origem do projeto. Esta etapa não analisa, copia, altera nem exclui o vídeo selecionado. O arquivo selecionado pode ser levado à montagem manual e a um plano scenes.json.", style="Card.TLabel", wraplength=610, justify="left").pack(anchor="w", pady=(10, 12))
        self.source_video = tk.StringVar(value="")
        self._field(page, "Arquivo original (somente leitura)", self._path_entry(page, self.source_video, self._browse_source_video))
        self.source_info = ttk.Label(page, text="Nenhum arquivo selecionado.", style="Card.TLabel", wraplength=610)
        self.source_info.pack(anchor="w", pady=(8, 12))
        ttk.Label(page, text="A análise de conteúdo e a edição automática de vídeos brutos não fazem parte desta etapa.", style="Card.TLabel", wraplength=610).pack(anchor="w")
        ttk.Button(page, text="Adicionar selecionado à montagem manual", command=self._add_source_to_timeline).pack(anchor="w", pady=14)

    def _build_custom_mode(self, page: ttk.Frame) -> None:
        ttk.Label(page, text="Produção personalizada", style="Section.TLabel").pack(anchor="w")
        ttk.Label(page, text="Configure separadamente os parâmetros preparatórios acima. A duração em horas, minutos e segundos é uma meta de planejamento; o fluxo atual de áudio usa a duração efetiva da narração.", style="Card.TLabel", wraplength=610, justify="left").pack(anchor="w", pady=(10, 12))
        ttk.Label(page, text="Integrado: voz Kokoro em inglês, música local, mixagem e montagem manual de imagens/clipes com WAV e exportação MP4. Idiomas adicionais, legendas e estilos aplicados permanecem preparatórios. A montagem tem suas próprias durações e usa o WAV como referência; planos scenes.json importam e exportam a montagem completa.", style="Card.TLabel", wraplength=610, justify="left").pack(anchor="w")
        ttk.Button(page, text="Configurar timeline e exportar MP4", command=self._open_timeline).pack(anchor="w", pady=14)

    def _open_timeline(self) -> TimelineEditor:
        if self.timeline_editor is None or not self.timeline_editor.winfo_exists():
            self.timeline_editor = TimelineEditor(self, ROOT / "projects" / "openmontage-studio" / "renders")
        self.timeline_editor.deiconify()
        self.timeline_editor.lift()
        return self.timeline_editor

    def _add_source_to_timeline(self) -> None:
        try:
            source = local_video_selection(self.source_video.get())
        except (OSError, ValueError) as exc:
            messagebox.showerror("Selecione um vídeo", str(exc))
            return
        self._open_timeline().add_paths([source])

    def _close_studio(self) -> None:
        if self.timeline_editor is not None and self.timeline_editor.winfo_exists():
            self.timeline_editor.request_close(after=self.destroy)
        else:
            self.destroy()

    def _build_audio_panel(self, right: ttk.Frame) -> None:
        ttk.Label(right, text="Áudio local", style="Section.TLabel").pack(anchor="w", pady=(0, 8))
        self.voice = tk.StringVar(value="am_echo")
        self._field(right, "Voz Kokoro", ttk.Combobox(right, textvariable=self.voice, values=VOICES, state="readonly"))
        ttk.Label(right, text="Texto da narração (não há geração de roteiro integrada)", style="Card.TLabel", wraplength=325).pack(anchor="w", pady=(8, 4))
        self.script = tk.Text(right, height=8, wrap="word", bg="#0f1720", fg="#e8eef5", insertbackground="white", relief="flat", padx=8, pady=6, font=("Segoe UI", 9))
        self.script.pack(fill="x")
        self.mood = tk.StringVar(value="suspense")
        self.mood_combo = ttk.Combobox(right, textvariable=self.mood, values=tuple(MOOD_LABELS), state="readonly")
        self._field(right, "Emoção da música local", self.mood_combo)
        self.catalog_path = tk.StringVar(value=str(DEFAULT_CATALOG))
        self._field(right, "Catálogo musical", self._path_entry(right, self.catalog_path, self._browse_catalog))
        self.output_path = tk.StringVar(value=str(DEFAULT_OUTPUT))
        self._field(right, "Pasta de saída", self._path_entry(right, self.output_path, self._browse_output))
        self.track_label = ttk.Label(right, text="Nenhuma faixa selecionada", style="Card.TLabel", wraplength=325)
        self.track_label.pack(anchor="w", pady=(2, 6))
        ttk.Button(right, text="Selecionar música pela emoção", command=self._select_music).pack(fill="x", pady=(3, 12))
        ttk.Label(right, text="Mix aprovado: voz +3 dB · duck −35 dB · master +3 dB · teto −1 dBFS", style="Card.TLabel", wraplength=325).pack(anchor="w", pady=(0, 7))
        ttk.Label(right, text="A licença das faixas precisa ser verificada antes de monetizar.", style="Card.TLabel", wraplength=325).pack(anchor="w", pady=(0, 8))
        self.tts_button = ttk.Button(right, text="Gerar narração Kokoro", style="Accent.TButton", command=self._generate_narration)
        self.tts_button.pack(fill="x", pady=4)
        self.mix_button = ttk.Button(right, text="Mixar narração + música", command=self._mix_audio)
        self.mix_button.pack(fill="x", pady=4)
        ttk.Label(right, text="Montagem manual e MP4 disponíveis nos modos ao lado. Roteiro e pesquisa automática ainda não integrados.", style="Card.TLabel", wraplength=325).pack(anchor="w", pady=(8, 0))

    def _update_duration_status(self) -> None:
        try:
            total = duration_seconds(self.hours.get(), self.minutes.get(), self.seconds.get())
        except ValueError as exc:
            self.duration_status.set(f"Duração planejada inválida: {exc}")
            return
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        mode = self.duration_mode.get()
        limitation = "alvo rígido não está implementado" if mode.startswith("Alvo rígido") else "não controla a mixagem nem garante a duração do vídeo"
        self.duration_status.set(f"Planejamento: {hours:02d}:{minutes:02d}:{seconds:02d}. Duração aproximada; {limitation}.")

    def _on_mode_changed(self, _event=None) -> None:
        try:
            self.current_mode = mode_for_tab(self.notebook.index("current"))
        except ValueError as exc:
            self._log(str(exc))
            return
        self.status.set(f"Modo atual: {MODE_LABELS[self.current_mode]}.")
        self._log(f"Navegação: {MODE_LABELS[self.current_mode]}.")

    def _browse_source_video(self) -> None:
        chosen = filedialog.askopenfilename(
            title="Selecionar vídeo bruto (somente leitura)",
            filetypes=(("Vídeos", "*.mp4 *.mov *.mkv *.avi *.webm"), ("Todos", "*.*")),
        )
        if not chosen:
            return
        try:
            selected = local_video_selection(chosen)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Arquivo inválido", str(exc))
            return
        self.source_video.set(str(selected))
        size_mb = selected.stat().st_size / (1024 * 1024)
        self.source_info.configure(text=f"Selecionado (não alterado): {selected.name} · {size_mb:.1f} MB\n{selected}")
        self._log(f"Vídeo bruto selecionado em modo somente leitura: {selected}")

    @staticmethod
    def _field(parent: ttk.Frame, label: str, widget: tk.Widget) -> None:
        ttk.Label(parent, text=label, style="Card.TLabel").pack(anchor="w", pady=(7, 4))
        widget.pack(fill="x")

    def _path_entry(self, parent: ttk.Frame, variable: tk.StringVar, callback) -> ttk.Frame:
        row = ttk.Frame(parent, style="Card.TFrame")
        ttk.Entry(row, textvariable=variable).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="…", width=3, command=callback).pack(side="left", padx=(5, 0))
        return row

    def _browse_catalog(self) -> None:
        chosen = filedialog.askopenfilename(title="Escolher catálogo JSON", filetypes=(("Catálogo JSON", "*.json"), ("Todos", "*.*")))
        if chosen:
            self.catalog_path.set(chosen)
            self._refresh_catalog()

    def _browse_output(self) -> None:
        chosen = filedialog.askdirectory(title="Pasta de saída", initialdir=self.output_path.get())
        if chosen:
            self.output_path.set(chosen)

    def _refresh_catalog(self) -> None:
        try:
            self.music_catalog = load_music_catalog(self.catalog_path.get())
            moods = sorted({str(mood).casefold() for track in self.music_catalog for mood in track.get("humor", [])})
            if moods:
                self.mood_combo.configure(values=moods)
                if self.mood.get() not in moods:
                    self.mood.set(moods[0])
            self._log(f"Catálogo: {len(self.music_catalog)} faixas encontradas.")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self.music_catalog = []
            self._log(f"Erro ao ler catálogo: {exc}")

    def _select_music(self) -> None:
        self._refresh_catalog()
        self.music_track = pick_music(self.music_catalog, self.mood.get())
        if not self.music_track:
            self.track_label.configure(text=f"Nenhuma faixa disponível para ‘{self.mood.get()}’.")
            self._log(f"Nenhuma música encontrada para a emoção {self.mood.get()}.")
            return
        self.track_label.configure(text=f"Selecionada: {self.music_track.get('nome')}\nLicença: não confirmada no catálogo.")
        self._log(f"Música selecionada: {self.music_track.get('nome')} ({self.music_track.get('arquivo')}).")

    def _unique_output(self, prefix: str) -> Path:
        safe = re.sub(r"[^a-z0-9]+", "-", self.topic.get().strip().lower()).strip("-") or "documentario"
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        folder = Path(self.output_path.get()).expanduser()
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{safe}-{prefix}-{stamp}.wav"

    def _generate_narration(self) -> None:
        if not self.language.get().startswith("English"):
            messagebox.showerror(
                "Idioma não integrado",
                "O runner Kokoro configurado nesta instalação gera narração em inglês. "
                "A preferência selecionada fica apenas como planejamento.",
            )
            return
        text = self.script.get("1.0", "end").strip()
        if not self.topic.get().strip() or not text:
            messagebox.showerror("Dados necessários", "Preencha o tema e o texto da narração antes de gerar o áudio.")
            return
        output = self._unique_output("narracao")
        self._start_task("Gerando narração local com Kokoro…", self._run_tts, text, self.voice.get(), output)

    @staticmethod
    def _run_tts(text: str, voice: str, output: Path) -> Path:
        result = KokoroTTS().execute({"text": text, "voice": voice, "output_path": str(output)})
        if not result.success:
            raise RuntimeError(result.error or "Kokoro não concluiu a narração.")
        return output

    def _mix_audio(self) -> None:
        if not self.narration_path or not self.narration_path.is_file():
            messagebox.showerror("Narração necessária", "Gere a narração com Kokoro antes de mixar.")
            return
        if self.music_track is None:
            self._select_music()
        if self.music_track is None:
            messagebox.showerror("Música não encontrada", "Não há faixa disponível para a emoção escolhida.")
            return
        output = self._unique_output("mix")
        speech = self.narration_path
        music = Path(self.music_track["arquivo"])
        target_duration = audio_duration(speech)
        self._start_task("Mixando áudio com o perfil aprovado e limitador de pico…", self._run_mix, speech, music, output, target_duration)

    @staticmethod
    def _run_mix(speech: Path, music: Path, output: Path, duration: float) -> Path:
        result = AudioMixer().execute({
            "operation": "full_mix",
            "tracks": [{"path": str(speech), "role": "speech"}, {"path": str(music), "role": "music", "fade_in_seconds": 2, "fade_out_seconds": 3}],
            "narration_gain_db": 3, "duck_level": -35, "master_gain_db": 3,
            "normalize": False, "peak_limit_db": -1, "target_duration": duration,
            "output_path": str(output),
        })
        if not result.success:
            raise RuntimeError(result.error or "O mixer não concluiu a mixagem.")
        return output

    def _start_task(self, description: str, function, *args) -> None:
        if self.busy:
            return
        self.busy = True
        self.status.set(description)
        self.progress.start(12)
        self.tts_button.configure(state="disabled")
        self.mix_button.configure(state="disabled")
        def worker() -> None:
            try:
                self.events.put(("success", function(*args)))
            except Exception as exc:  # surfaced in the UI and log
                self.events.put(("error", str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def _poll_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                self.busy = False
                self.progress.stop()
                self.tts_button.configure(state="normal")
                self.mix_button.configure(state="normal")
                if kind == "success":
                    path = Path(payload)
                    if "narracao" in path.name:
                        self.narration_path = path
                        self.status.set(f"Narração gerada: {path.name}")
                    else:
                        self.status.set(f"Mix finalizado: {path.name}")
                    self._log(f"Concluído: {path}")
                else:
                    self.status.set("Ocorreu um erro. Consulte o log.")
                    self._log(f"ERRO: {payload}")
                    messagebox.showerror("Falha na operação", str(payload))
        except queue.Empty:
            pass
        self.after(150, self._poll_events)

    def _log(self, message: str) -> None:
        if not hasattr(self, "log"):
            return
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")


if __name__ == "__main__":
    OpenMontageStudio().mainloop()
