#!/usr/bin/env python3
"""Native desktop explorer for C Engine game-review files and positions."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"src"))
from zebrafish.paths import resource

from zebrafish.review.chess_support import chess
from zebrafish.review.classical import format_components
from zebrafish.review.models import (AnalysisSettings, ClassicalBreakdown, GameReview,
                             MoveReview, PlayerSummary)
from zebrafish.review.pgn_source import read_pgn_games
from zebrafish.review.position_review import review_position
from zebrafish.review.storage import load_review, save_review
from zebrafish.opponents.finish_engine import FinishEngine


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENGINE = resource("engine")
STRENGTH_ADAPTER = resource("strength_adapter")
OPENING_BOOK = resource("book") / "OpeningBook.tsv"
ASSETS = resource("artwork")
APP_BG = "#262522"
PANEL = "#312e2b"
SURFACE = "#3c3936"
TEXT = "#f0efed"
MUTED = "#b7b5b2"
ACCENT = "#81b64c"
LIGHT = "#eeeed2"
DARK = "#769656"
LAST_LIGHT = "#f5f682"
LAST_DARK = "#baca44"
PIECES = {
    "K": "♔", "Q": "♕", "R": "♖", "B": "♗", "N": "♘", "P": "♙",
    "k": "♚", "q": "♛", "r": "♜", "b": "♝", "n": "♞", "p": "♟",
}


def score(value) -> str:
    return "unavailable" if value is None else f"{value / 100:+.2f}"


class ReviewGui:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("C Engine Game Review")
        self.root.geometry("1500x950")
        self.root.minsize(1180, 760)
        self.root.configure(bg=APP_BG)
        self.review: GameReview | None = None
        self.review_path: Path | None = None
        self.elo_estimation_running = False
        self.elo_explanations: dict[str, dict] = {}
        self.record: MoveReview | None = None
        self.position_analysis_classical: ClassicalBreakdown | None = None
        self.line_root_fen = chess.STARTING_FEN
        self.line_moves: list[str] = []
        self.line_index = 0
        self.current_board = chess.Board()
        self.selected_square: int | None = None
        self.display_last_move = None
        self.manual_mode = False
        self.finish_active = False
        self.finish_thinking = False
        self.finish_human_color = chess.WHITE
        self.finish_engine: FinishEngine | None = None
        self.finish_generation = 0
        self.engine_var = tk.StringVar(value=str(DEFAULT_ENGINE))
        self.threads_value = tk.IntVar(value=1)
        self.flipped = False
        self.current_eval_cp: int | None = 0
        self.graph_points: list[tuple[float, float, int]] = []
        self.board_press_square: int | None = None
        self.annotation_start: int | None = None
        self.annotation_squares: set[int] = set()
        self.annotation_arrows: list[tuple[int, int]] = []
        self.work_queue: queue.Queue = queue.Queue()
        self.piece_images: dict[str, tk.PhotoImage] = {}
        self._configure_style()
        self._load_piece_images()
        self._build()
        self.root.bind("<Left>", lambda _event: self.move_selection(-1))
        self.root.bind("<Right>", lambda _event: self.move_selection(1))
        self.root.bind("<Home>", lambda _event: self.select_game_endpoint(False))
        self.root.bind("<End>", lambda _event: self.select_game_endpoint(True))
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(100, self._poll_worker)

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", background=APP_BG, foreground=TEXT,
                        font=("Segoe UI", 10))
        style.configure("TFrame", background=APP_BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TLabel", background=APP_BG, foreground=TEXT)
        style.configure("Panel.TLabel", background=PANEL, foreground=TEXT)
        style.configure("Muted.TLabel", background=PANEL, foreground=MUTED)
        style.configure("TLabelFrame", background=PANEL, foreground=TEXT,
                        bordercolor="#4a4744", relief="solid")
        style.configure("TLabelFrame.Label", background=PANEL,
                        foreground=TEXT, font=("Segoe UI Semibold", 10))
        style.configure("TButton", background="#4b4845", foreground=TEXT,
                        borderwidth=0, padding=(12, 7))
        style.map("TButton", background=[("active", "#5a5753"),
                                          ("pressed", "#696560")])
        style.configure("Accent.TButton", background=ACCENT,
                        foreground="#17200f", font=("Segoe UI Semibold", 10))
        style.map("Accent.TButton", background=[("active", "#95c65f"),
                                                 ("pressed", "#6fa13e")])
        style.configure("Tool.TButton", background=PANEL, foreground=MUTED,
                        padding=(8, 5), borderwidth=0)
        style.map("Tool.TButton",
                  background=[("active", SURFACE), ("pressed", "#4b4845")],
                  foreground=[("active", TEXT)])
        style.configure("Tool.TMenubutton", background=PANEL, foreground=MUTED,
                        padding=(8, 5), borderwidth=0, arrowcolor=MUTED)
        style.map("Tool.TMenubutton",
                  background=[("active", SURFACE), ("pressed", "#4b4845")],
                  foreground=[("active", TEXT)], arrowcolor=[("active", TEXT)])
        style.configure("Status.TLabel", background=SURFACE, foreground=MUTED,
                        padding=(9, 5))
        style.configure("TEntry", fieldbackground=SURFACE, foreground=TEXT,
                        insertcolor=TEXT, bordercolor="#55514d",
                        selectbackground=ACCENT, selectforeground="#17200f",
                        lightcolor="#55514d", darkcolor="#55514d", padding=5)
        style.map("TEntry",
                  fieldbackground=[("disabled", "#2c2a28"), ("readonly", SURFACE)],
                  foreground=[("disabled", MUTED), ("readonly", TEXT)])
        style.configure("TCombobox", fieldbackground=SURFACE, foreground=TEXT,
                        background=SURFACE, arrowcolor=TEXT,
                        selectbackground=ACCENT, selectforeground="#17200f",
                        bordercolor="#55514d", lightcolor="#55514d",
                        darkcolor="#55514d", padding=4)
        style.map("TCombobox",
                  fieldbackground=[("disabled", "#2c2a28"), ("readonly", SURFACE)],
                  background=[("active", "#4b4845"), ("readonly", SURFACE)],
                  foreground=[("disabled", MUTED), ("readonly", TEXT)],
                  arrowcolor=[("disabled", MUTED), ("readonly", TEXT)])
        # TSpinbox does not inherit TEntry field colors consistently on Windows.
        # Give thread-count selectors their own complete state map so the Clam
        # theme cannot fall back to a white field with the global light text.
        style.configure("TSpinbox", fieldbackground=SURFACE, foreground=TEXT,
                        background=SURFACE, arrowcolor=TEXT, insertcolor=TEXT,
                        selectbackground=ACCENT, selectforeground="#17200f",
                        bordercolor="#55514d", lightcolor="#55514d",
                        darkcolor="#55514d", padding=4)
        style.map("TSpinbox",
                  fieldbackground=[("disabled", "#2c2a28"), ("readonly", SURFACE)],
                  background=[("active", "#4b4845"), ("readonly", SURFACE)],
                  foreground=[("disabled", MUTED), ("readonly", TEXT)],
                  arrowcolor=[("disabled", MUTED), ("readonly", TEXT)])
        # The Combobox popup is a classic Tk Listbox rather than a ttk widget.
        self.root.option_add("*TCombobox*Listbox.background", SURFACE)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#17200f")
        style.configure("TPanedwindow", background=APP_BG)
        style.configure("Sash", sashthickness=5, background=APP_BG)
        style.configure("Treeview", background=SURFACE, fieldbackground=SURFACE,
                        foreground=TEXT, bordercolor="#55514d", rowheight=25)
        style.map("Treeview", background=[("selected", ACCENT)],
                  foreground=[("selected", "#17200f")])
        style.configure("Treeview.Heading", background="#4b4845",
                        foreground=TEXT, bordercolor="#55514d",
                        font=("Segoe UI Semibold", 9), padding=(6, 5))
        style.map("Treeview.Heading",
                  background=[("active", "#5a5753")],
                  foreground=[("active", TEXT)])

    def _load_piece_images(self) -> None:
        names = {
            "K": "white_king", "Q": "white_queen", "R": "white_rook",
            "B": "white_bishop", "N": "white_knight", "P": "white_pawn",
            "k": "black_king", "q": "black_queen", "r": "black_rook",
            "b": "black_bishop", "n": "black_knight", "p": "black_pawn",
        }
        for symbol, name in names.items():
            path = ASSETS / f"{name}_modern_64x64.png"
            if path.is_file():
                self.piece_images[symbol] = tk.PhotoImage(file=str(path))

    def _build(self) -> None:
        header = ttk.Frame(self.root, padding=(14, 10), style="Panel.TFrame")
        header.pack(fill="x")
        brand = ttk.Frame(header, style="Panel.TFrame")
        brand.pack(side="left")
        ttk.Label(brand, text="GAME REVIEW", style="Panel.TLabel",
                  font=("Segoe UI Semibold", 15)).pack(anchor="w")
        ttk.Label(brand, text="Explore · explain · replay", style="Muted.TLabel",
                  font=("Segoe UI", 9)).pack(anchor="w")
        toolbar = ttk.Frame(header, style="Panel.TFrame")
        toolbar.pack(side="right", fill="x", expand=True, padx=(24, 0))
        ttk.Button(toolbar, text="Open", command=self.open_review,
                   style="Accent.TButton").pack(side="left")
        ttk.Button(toolbar, text="Paste PGN", command=self.open_paste_dialog,
                   style="Tool.TButton").pack(side="left", padx=(5, 14))
        ttk.Button(toolbar, text="⏮", width=3,
                   command=lambda: self.select_game_endpoint(False),
                   style="Tool.TButton").pack(side="left")
        ttk.Button(toolbar, text="‹ Move", command=lambda: self.move_selection(-1),
                   style="Tool.TButton").pack(side="left", padx=2)
        ttk.Button(toolbar, text="Move ›", command=lambda: self.move_selection(1),
                   style="Tool.TButton").pack(side="left")
        ttk.Button(toolbar, text="⏭", width=3,
                   command=lambda: self.select_game_endpoint(True),
                   style="Tool.TButton").pack(side="left", padx=(2, 0))
        ttk.Button(toolbar, text="Engine settings", command=self.open_engine_settings,
                   style="Tool.TButton").pack(side="right")

        self.summary_label = ttk.Label(
            self.root, text="Open or paste a reviewed game to begin",
            anchor="center", padding=(8, 7), style="Panel.TLabel",
            font=("Segoe UI Semibold", 10))
        self.summary_label.pack(fill="x", padx=6, pady=(0, 5))

        elo_panel = ttk.Frame(self.root, padding=(10, 7), style="Panel.TFrame")
        elo_panel.pack(fill="x", padx=6, pady=(0, 5))
        ttk.Label(elo_panel, text="ESTIMATED RATING", style="Panel.TLabel",
                  font=("Segoe UI Semibold", 10)).pack(side="left", padx=(0, 12))
        self.elo_summary_label = ttk.Label(
            elo_panel,
            text="Analyze a game to estimate each player’s Chess.com Blitz-equivalent performance.",
            style="Muted.TLabel", anchor="w")
        self.elo_summary_label.pack(side="left", fill="x", expand=True)
        self.white_elo_details = ttk.Button(
            elo_panel, text="White details", state="disabled",
            command=lambda: self.show_elo_details("white"))
        self.white_elo_details.pack(side="right", padx=(5, 0))
        self.black_elo_details = ttk.Button(
            elo_panel, text="Black details", state="disabled",
            command=lambda: self.show_elo_details("black"))
        self.black_elo_details.pack(side="right", padx=(5, 0))
        self.elo_button = ttk.Button(
            elo_panel, text="Estimate rating",
            command=self.estimate_performance_elo)
        self.elo_button.pack(side="right", padx=(8, 0))

        body = ttk.Panedwindow(self.root, orient="horizontal")
        body.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        left = ttk.Frame(body)
        right = ttk.Frame(body)
        body.add(left, weight=3)
        body.add(right, weight=4)

        board_area = ttk.Frame(left)
        board_area.pack(pady=4)
        self.eval_bar = tk.Canvas(board_area, width=42, height=592,
                                  highlightthickness=0, bg=APP_BG)
        self.eval_bar.pack(side="left", padx=(0, 4))
        self.canvas = tk.Canvas(board_area, width=592, height=592, highlightthickness=0,
                                bg=APP_BG)
        self.canvas.pack(side="left")
        self.canvas.bind("<ButtonPress-1>", self.on_board_click)
        self.canvas.bind("<ButtonRelease-1>", self.on_board_release)
        self.canvas.bind("<ButtonPress-3>", self.on_annotation_press)
        self.canvas.bind("<ButtonRelease-3>", self.on_annotation_release)
        line_controls = ttk.Frame(left, style="Panel.TFrame", padding=(5, 4))
        line_controls.pack(fill="x", padx=4)
        ttk.Button(line_controls, text="‹", width=3, command=lambda: self.step_line(-1),
                   style="Tool.TButton").pack(side="left")
        self.position_label = ttk.Label(line_controls, text="Starting position", anchor="center",
                                        style="Panel.TLabel")
        self.position_label.pack(side="left", fill="x", expand=True)
        ttk.Button(line_controls, text="›", width=3, command=lambda: self.step_line(1),
                   style="Tool.TButton").pack(side="right")

        utility_controls = ttk.Frame(left, style="Panel.TFrame", padding=(5, 4))
        utility_controls.pack(fill="x", padx=4, pady=(4, 0))
        tools_button = ttk.Menubutton(utility_controls, text="Board tools",
                                      style="Tool.TMenubutton")
        tools_menu = tk.Menu(tools_button, tearoff=False, bg=SURFACE, fg=TEXT,
                             activebackground=ACCENT, activeforeground="#17200f",
                             bd=0, relief="flat")
        tools_menu.add_command(label="Undo played move", command=self.undo_manual_move)
        tools_menu.add_command(label="Flip board", command=self.flip_board)
        tools_menu.add_separator()
        tools_menu.add_command(label="Copy FEN", command=self.copy_fen)
        tools_menu.add_command(label="Copy variation", command=self.copy_variation)
        tools_menu.add_command(label="Clear markings", command=self.clear_annotations)
        tools_button["menu"] = tools_menu
        tools_button.pack(side="left")
        self.finish_button = ttk.Button(
            utility_controls, text="Finish vs Engine",
            command=self.open_finish_dialog, style="Accent.TButton")
        self.finish_button.pack(side="right")

        eval_box = ttk.LabelFrame(left, text="Evaluate displayed position", padding=6)
        eval_box.pack(fill="x", padx=4, pady=8)
        self.limit_kind = tk.StringVar(value="time")
        ttk.Combobox(eval_box, textvariable=self.limit_kind,
                     values=("time", "depth", "nodes"), width=8,
                     state="readonly").pack(side="left")
        self.limit_value = tk.StringVar(value="2.0")
        ttk.Entry(eval_box, textvariable=self.limit_value, width=10).pack(side="left", padx=5)
        ttk.Label(eval_box, text="Threads").pack(side="left", padx=(4, 2))
        ttk.Spinbox(eval_box, from_=1, to=16, textvariable=self.threads_value,
                    width=3).pack(side="left", padx=(0, 5))
        self.evaluate_button = ttk.Button(eval_box, text="Evaluate Position",
                                          command=self.evaluate_position,
                                          style="Accent.TButton")
        self.evaluate_button.pack(side="left")
        self.eval_status = ttk.Label(eval_box, text="Time is seconds", style="Status.TLabel")
        self.eval_status.pack(side="left", padx=8)

        graph_frame = ttk.LabelFrame(right, text="Evaluation history", padding=5)
        graph_frame.pack(fill="x", pady=(0, 6))
        self.graph = tk.Canvas(graph_frame, height=145, bg=SURFACE,
                               highlightthickness=0)
        self.graph.pack(fill="x")
        self.graph.bind("<Button-1>", self.on_graph_click)
        self.graph.bind("<Motion>", self.on_graph_hover)
        self.graph.bind("<Leave>", lambda _event: self.graph_hint.config(text=""))
        self.graph.bind("<Configure>", lambda _event: self.draw_eval_graph())
        self.graph_hint = ttk.Label(graph_frame, text="", style="Muted.TLabel")
        self.graph_hint.pack(anchor="w")

        top_right = ttk.Panedwindow(right, orient="horizontal")
        top_right.pack(fill="both", expand=True)
        moves_frame = ttk.LabelFrame(top_right, text="Game moves", padding=4)
        details_frame = ttk.Frame(top_right)
        top_right.add(moves_frame, weight=1)
        top_right.add(details_frame, weight=3)
        list_options = dict(bg=SURFACE, fg=TEXT, selectbackground=ACCENT,
                            selectforeground="#17200f", relief="flat",
                            borderwidth=0, highlightthickness=0,
                            font=("Segoe UI", 10), activestyle="none")
        self.moves_list = tk.Listbox(moves_frame, width=20, exportselection=False,
                                     **list_options)
        self.moves_list.pack(fill="both", expand=True)
        self.moves_list.bind("<<ListboxSelect>>", self.on_game_move)

        critical_controls = ttk.Frame(moves_frame, style="Panel.TFrame")
        critical_controls.pack(fill="x", pady=(5, 0))
        self.critical_filter = tk.StringVar(value="inaccuracy+")
        ttk.Combobox(critical_controls, textvariable=self.critical_filter,
                     values=("inaccuracy+", "mistake+", "blunders", "all"),
                     width=11, state="readonly").pack(side="left", fill="x", expand=True)
        ttk.Button(critical_controls, text="◀", width=3,
                   command=lambda: self.navigate_critical(-1)).pack(side="left", padx=2)
        ttk.Button(critical_controls, text="▶", width=3,
                   command=lambda: self.navigate_critical(1)).pack(side="left")

        ttk.Label(details_frame, text="Line to explore:").pack(anchor="w")
        self.branch_var = tk.StringVar(value="Best: explainable")
        self.branch = ttk.Combobox(details_frame, textvariable=self.branch_var,
            values=("Position before move", "Position after move",
                    "Best: full", "Best: explainable",
                    "Played: full", "Played: explainable",
                    "Simpler alternative: full", "Simpler alternative: explainable"),
            state="readonly")
        self.branch.pack(fill="x")
        self.branch.bind("<<ComboboxSelected>>", lambda _event: self.select_branch())

        self.line_list = tk.Listbox(details_frame, height=6, exportselection=False,
                                    **list_options)
        self.line_list.pack(fill="x", pady=5)
        self.line_list.bind("<<ListboxSelect>>", self.on_line_move)

        comparison = ttk.LabelFrame(details_frame, text="Best move vs played move",
                                    padding=4)
        comparison.pack(fill="x", pady=(0, 5))
        self.best_compare = tk.Text(comparison, height=4, width=28, wrap="word",
                                    bg=SURFACE, fg=TEXT, relief="flat", padx=7, pady=5)
        self.best_compare.pack(side="left", fill="both", expand=True)
        self.played_compare = tk.Text(comparison, height=4, width=28, wrap="word",
                                      bg=SURFACE, fg=TEXT, relief="flat", padx=7, pady=5)
        self.played_compare.pack(side="left", fill="both", expand=True, padx=(5, 0))

        component_row = ttk.Frame(details_frame)
        component_row.pack(fill="x", pady=(0, 5))
        self.best_component_canvas = tk.Canvas(
            component_row, height=115, bg=SURFACE, highlightthickness=0)
        self.best_component_canvas.pack(side="left", fill="both", expand=True)
        self.played_component_canvas = tk.Canvas(
            component_row, height=115, bg=SURFACE, highlightthickness=0)
        self.played_component_canvas.pack(side="left", fill="both", expand=True,
                                          padx=(5, 0))
        self.best_component_canvas.bind(
            "<Configure>", lambda _event: self.draw_component_pair())
        self.played_component_canvas.bind(
            "<Configure>", lambda _event: self.draw_component_pair())

        self.details = tk.Text(details_frame, height=10, width=48, wrap="word",
                               font=("Segoe UI", 10),
                               bg=SURFACE, fg=TEXT, insertbackground=TEXT,
                               selectbackground=ACCENT, relief="flat",
                               padx=12, pady=10, spacing1=2, spacing3=2)
        self.details.pack(fill="both", expand=True)
        self.draw_board(self.current_board)

    def open_engine_settings(self) -> None:
        """Show infrequently changed engine settings outside the main toolbar."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Engine settings")
        dialog.geometry("680x210")
        dialog.resizable(False, False)
        dialog.configure(bg=APP_BG)
        dialog.transient(self.root)
        dialog.grab_set()
        panel = ttk.Frame(dialog, padding=16, style="Panel.TFrame")
        panel.pack(fill="both", expand=True, padx=10, pady=10)
        ttk.Label(panel, text="ENGINE SETTINGS", style="Panel.TLabel",
                  font=("Segoe UI Semibold", 13)).pack(anchor="w")
        ttk.Label(panel,
                  text="Used by position analysis and Finish vs Engine. Review creation has its own settings.",
                  style="Muted.TLabel").pack(anchor="w", pady=(2, 12))
        form = ttk.Frame(panel, style="Panel.TFrame")
        form.pack(fill="x")
        ttk.Label(form, text="Engine", style="Panel.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(form, textvariable=self.engine_var).grid(
            row=0, column=1, sticky="ew", pady=4)
        ttk.Button(form, text="Browse", command=self.choose_engine,
                   style="Tool.TButton").grid(row=0, column=2, padx=(6, 0), pady=4)
        ttk.Label(form, text="Threads", style="Panel.TLabel").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Spinbox(form, from_=1, to=16, textvariable=self.threads_value,
                    width=5).grid(row=1, column=1, sticky="w", pady=4)
        form.columnconfigure(1, weight=1)
        ttk.Button(panel, text="Done", command=dialog.destroy,
                   style="Accent.TButton").pack(anchor="e", pady=(12, 0))

    def choose_engine(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Chess engine", "*.exe"), ("All files", "*.*")])
        if path:
            self.engine_var.set(path)

    def open_review(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Review JSON", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            self.review = load_review(path)
        except Exception as error:
            messagebox.showerror("Could not open review", str(error))
            return
        self.review_path = Path(path)
        self.elo_explanations = {
            color: summary.elo_details for color, summary in self.review.players.items()
            if summary.elo_details and summary.elo_model_version == "performance_elo_v4_hybrid_asymmetric"
        }
        self.white_elo_details.config(
            state="normal" if "white" in self.elo_explanations else "disabled")
        self.black_elo_details.config(
            state="normal" if "black" in self.elo_explanations else "disabled")
        self._display_review()

    def _display_review(self) -> None:
        """Populate the explorer from the review currently held in memory."""
        if not self.review:
            return
        self._refresh_move_list()
        self.update_summary()
        self.update_elo_summary()
        self.draw_eval_graph()
        if self.review.moves:
            self.moves_list.selection_set(0)
            self.on_game_move()

    def _refresh_move_list(self) -> None:
        """Refresh move labels while retaining the currently selected ply."""
        if not self.review:
            return
        selected = self.moves_list.curselection()
        self.moves_list.delete(0, "end")
        for move in self.review.moves:
            prefix = f"{move.move_number}." if move.mover == "white" else f"{move.move_number}..."
            impact = ""
            self.moves_list.insert("end", f"{prefix} {move.san}  {move.classification}{impact}")
        if selected and selected[0] < len(self.review.moves):
            self.moves_list.selection_set(selected[0])

    def update_summary(self) -> None:
        if not self.review:
            return
        headers = self.review.headers
        white = headers.get("White", "White")
        black = headers.get("Black", "Black")
        result = headers.get("Result", "*")

        def side_summary(side: str) -> str:
            summary = self.review.players.get(side)
            accuracy = (f"{summary.accuracy:.1f}%" if summary and
                        summary.accuracy is not None else "—")
            moves = [move for move in self.review.moves if move.mover == side]
            counts = {name: sum(move.classification == name for move in moves)
                      for name in ("inaccuracy", "mistake", "blunder")}
            return (f"{accuracy} accuracy · {counts['inaccuracy']} inaccuracies · "
                    f"{counts['mistake']} mistakes · {counts['blunder']} blunders")

        informative = [move for move in self.review.moves
                       if move.expected_score_loss is not None]
        worst = max(informative, key=lambda move: move.expected_score_loss,
                    default=None)
        critical = [move for move in informative if move.critical]
        hardest = max(critical,
                      key=lambda move: getattr(move.stability,
                                               "discovery_depth", 0) or 0,
                      default=None)
        opening = headers.get("Opening") or headers.get("ECO") or "Opening unknown"
        notes = []
        if worst:
            notes.append(f"largest miss: {worst.move_number}{'.' if worst.mover == 'white' else '…'} {worst.san}")
        if hardest:
            notes.append(f"deepest critical discovery: depth {hardest.stability.discovery_depth or '—'}")
        self.summary_label.config(
            text=f"{white}: {side_summary('white')}     {result}     "
                 f"{black}: {side_summary('black')}\n{opening} · " + " · ".join(notes))

    @staticmethod
    def _performance_side_text(review: GameReview, side: str) -> str:
        summary = review.players.get(side)
        if not summary or summary.estimated_performance_elo is None:
            return f"{side.title()}: not estimated"
        if summary.elo_model_version != "performance_elo_v4_hybrid_asymmetric":
            return f"{side.title()}: old estimate — refresh to use the new model"
        estimate = round(summary.estimated_performance_elo)
        low = summary.elo_interval_low
        high = summary.elo_interval_high
        interval = (f"{round(low)}–{round(high)}" if low is not None and high is not None
                    else "unavailable")
        decisions = sum(
            move.mover == side and move.ply >= 13 and not move.forced and
            move.expected_score_loss is not None for move in review.moves)
        quality = summary.elo_evidence_quality or "unknown"
        scale = summary.elo_details.get("rating_scale", "Chess.com Blitz equivalent")
        return (f"{side.title()}: {estimate} {scale}  ·  68% compatibility range "
                 f"{interval}  ·  {quality}")

    def update_elo_summary(self) -> None:
        if not self.review:
            self.elo_summary_label.config(
                text="Analyze a game to estimate each player’s Chess.com Blitz-equivalent performance.")
            return
        text = (self._performance_side_text(self.review, "white") + "\n" +
                self._performance_side_text(self.review, "black"))
        if not self.review.complete:
            text += "     ·     Preliminary: review is incomplete"
        self.elo_summary_label.config(text=text)
        has_estimate = any(
            summary.estimated_performance_elo is not None
            for summary in self.review.players.values())
        self.elo_button.config(
            text="Refresh rating" if has_estimate else
                 "Estimate rating")

    def estimate_performance_elo(self, *, automatic: bool = False) -> None:
        """Run model inference away from Tk's UI thread and retain the result."""
        if not self.review or self.elo_estimation_running:
            return
        review = self.review
        review_path = self.review_path
        self.elo_estimation_running = True
        self.elo_button.config(state="disabled")
        self.elo_summary_label.config(text="Estimating rating…")

        def work() -> None:
            try:
                from zebrafish.ratings.performance_elo import estimate_review

                estimates = estimate_review(review)
                if not estimates:
                    raise ValueError(
                        "Not enough moves for a rating estimate.")
                self.work_queue.put(
                    ("elo_ok", (review, review_path, estimates, automatic)))
            except Exception as error:
                self.work_queue.put(("elo_error", (review, str(error), automatic)))

        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def _feature_label(name: str) -> str:
        return name.replace("_", " ").title().replace("P90", "90th percentile")

    @staticmethod
    def _feature_value(name: str, value: float) -> str:
        if name.endswith("_rate") or name.startswith("coverage_"):
            return f"{value * 100:.1f}%"
        if "loss" in name:
            return f"{value:.4f} expected score"
        if name == "mean_clock":
            return f"{value:.1f} seconds"
        if name == "is_white":
            return "yes" if value else "no"
        return f"{value:.2f}"

    def show_elo_details(self, side: str) -> None:
        explanation = self.elo_explanations.get(side)
        if not explanation or explanation.get("model_version") != "performance_elo_v4_hybrid_asymmetric":
            messagebox.showinfo("Rating details unavailable", "Refresh the rating estimate to use the new model.")
            return
        review = self.review
        dialog = tk.Toplevel(self.root)
        dialog.title(f"{side.title()} — estimated rating and game evidence")
        dialog.geometry("940x790")
        dialog.minsize(740, 620)
        dialog.configure(bg=APP_BG)
        panel = ttk.Frame(dialog, padding=16, style="Panel.TFrame")
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text=f"{side.upper()} · ESTIMATED RATING FROM THIS GAME",
                  style="Panel.TLabel", font=("Segoe UI Semibold", 14)).pack(anchor="w")
        ttk.Label(panel, text=f"{explanation['performance_elo']} {explanation.get('rating_scale', 'Chess.com Blitz equivalent')}",
                  style="Panel.TLabel", font=("Segoe UI Semibold", 22)).pack(anchor="w", pady=(8, 3))
        ttk.Label(panel, style="Muted.TLabel", wraplength=870,
                  text=(f"Typical 68% account-rating compatibility: "
                        f"{explanation['compatibility_68_low']}–{explanation['compatibility_68_high']}.\n"
                        f"Broad 90% compatibility: {explanation['range_low']}–{explanation['range_high']}. "
                        "These describe real players who produced similar games, not a confidence "
                        "bound on an unobservable true one-game performance.")).pack(anchor="w")
        ttk.Label(panel, style="Muted.TLabel", wraplength=870,
                  text=(f"Uses {explanation.get('informative_moves', 0)} informative decisions. "
                        "RatingNet uses complete clock records when available; missing clocks use separate calibration.")).pack(anchor="w", pady=(5, 9))
        ttk.Label(panel, text="How the estimate was combined", style="Panel.TLabel",
                  font=("Segoe UI Semibold", 13)).pack(anchor="w")
        ttk.Label(panel, style="Muted.TLabel", wraplength=870,
                  text=(f"RatingNet game-strength center: {explanation.get('ratingnet_shared_center_elo', '—')} · "
                        f"Engine/move estimate before centering: {explanation.get('precnn_performance_elo', '—')} · "
                        f"Preserved player gap: {100 * explanation.get('performance_gap_weight', 0):.0f}%\n"
                        f"Aggregate engine model: {explanation.get('aggregate_elo', '—')} · "
                        f"Move-distribution estimate: {explanation.get('move_distribution_elo', '—')} · "
                        f"Internal gate: {100 * explanation.get('effective_gate', 0):.1f}%"))\
            .pack(anchor="w", pady=(2, 9))
        ttk.Label(panel, text="What this game showed", style="Panel.TLabel",
                  font=("Segoe UI Semibold", 13)).pack(anchor="w")
        ttk.Label(panel,
                  text=(f"Category ratings are recentered by one shared adjustment "
                        f"({explanation.get('transparent_explanation', {}).get('subcategory_centering_adjustment', 0):+.0f}) "
                        f"so their evidence-weighted average matches the headline. "
                        f"Their relative strengths and weaknesses are unchanged."),
                  style="Muted.TLabel", wraplength=870).pack(anchor="w", pady=(2, 8))
        transparent = explanation.get("transparent_explanation", {})
        for skill in ("tactical", "positional", "defensive", "conversion", "consistency"):
            item = transparent.get("skills", {}).get(skill, {})
            frame = ttk.Frame(panel, style="Panel.TFrame")
            frame.pack(fill="x", pady=(0, 7))
            skill_text = (f"{round(item.get('performance_elo', 0))} estimated "
                          f"(raw {round(item.get('raw_performance_elo', item.get('performance_elo', 0)))}) · "
                          f"{item.get('decisions', 0)} decisions · "
                          f"weight {100 * item.get('averaging_weight', 0):.0f}%"
                          if item.get("available") else "Not enough evidence")
            ttk.Label(frame, text=f"{skill.title()}: {skill_text}",
                      style="Panel.TLabel", wraplength=860).pack(anchor="w")
            factors = ", ".join(
                f"{factor.get('name', 'factor')}: {factor.get('mapped_rating', '—')}"
                for factor in item.get("factors", [])[:3])
            ttk.Label(frame, text=factors, style="Muted.TLabel",
                      wraplength=860).pack(anchor="w")
        ttk.Label(panel, text="Supporting moves — double-click to inspect", style="Panel.TLabel").pack(anchor="w", pady=(3, 4))
        columns = ("category", "move", "evidence", "loss")
        table = ttk.Treeview(panel, columns=columns, show="headings", height=6)
        for key, label, width in (("category", "Context", 110), ("move", "Move", 110),
                                  ("evidence", "Observed evidence", 420), ("loss", "Expected-score loss", 145)):
            table.heading(key, text=label)
            table.column(key, width=width, stretch=True)
        mapping = {}
        contexts = {row.get("ply"): row for row in transparent.get("move_context", [])}
        for row in explanation.get("move_impacts", []):
            context = contexts.get(row.get("ply"), {})
            skill = context.get("primary_skill", "move")
            evidence = (f"{row.get('classification', 'move')} · "
                        f"Elo influence {row.get('elo_impact', 0):+.1f}")
            item_id = table.insert("", "end", values=(
                skill.title(), f"Ply {row['ply']}: {row['san']}", evidence,
                f"{100 * row.get('expected_score_loss', 0):.1f}%"))
            mapping[item_id] = row["ply"]
        def inspect_move(_event=None):
            selected = table.selection()
            if selected and self.review is review:
                ply = mapping[selected[0]]
                index = next((i for i, move in enumerate(review.moves) if move.ply == ply), None)
                if index is not None:
                    self.select_game_move(index)
        table.bind("<Double-1>", inspect_move)
        table.pack(fill="both", expand=True)
        ttk.Label(panel, style="Muted.TLabel", wraplength=870,
                  text="The compatibility intervals were calibrated on the natural population of real rated Blitz games, "
                       "then combined with uncertainty in converting Lichess Blitz to a Chess.com Blitz equivalent.").pack(anchor="w", pady=(8, 0))

    def draw_eval_graph(self) -> None:
        if not hasattr(self, "graph"):
            return
        self.graph.delete("all")
        self.graph_points = []
        width = max(200, self.graph.winfo_width())
        height = max(120, self.graph.winfo_height())
        margin_x, margin_y = 28, 17
        middle = height / 2
        self.graph.create_rectangle(0, 0, width, middle, fill="#e7e5df", outline="")
        self.graph.create_rectangle(0, middle, width, height, fill="#292724", outline="")
        self.graph.create_line(0, middle, width, middle, fill="#807d78", width=1)
        self.graph.create_text(5, 5, text="+5", anchor="nw", fill="#55514d",
                               font=("Segoe UI", 8))
        self.graph.create_text(5, height - 5, text="−5", anchor="sw", fill="#cbc8c2",
                               font=("Segoe UI", 8))
        if not self.review or not self.review.moves:
            self.graph.create_text(width / 2, middle, text="No analyzed moves",
                                   fill=MUTED)
            return
        values = [move.evaluation_after_cp for move in self.review.moves]
        count = len(values)
        points = []
        for index, value in enumerate(values):
            cp = 0 if value is None else max(-500, min(500, value))
            x = margin_x + index * (width - 2 * margin_x) / max(1, count - 1)
            y = middle - (cp / 500) * (middle - margin_y)
            points.append((x, y))
            self.graph_points.append((x, y, index))
        if len(points) > 1:
            self.graph.create_line(*[coordinate for point in points for coordinate in point],
                                   fill="#5f8f3e", width=3, smooth=True)
        colors = {"inaccuracy": "#f0c15a", "mistake": "#e58b3f",
                  "blunder": "#d64b40"}
        for index, (x, y) in enumerate(points):
            classification = self.review.moves[index].classification
            radius = 5 if classification in colors else 2
            self.graph.create_oval(x - radius, y - radius, x + radius, y + radius,
                                   fill=colors.get(classification, "#6b963f"), outline="")
        selected = self.moves_list.curselection() if hasattr(self, "moves_list") else ()
        if selected and selected[0] < len(points):
            x, y = points[selected[0]]
            self.graph.create_oval(x - 8, y - 8, x + 8, y + 8,
                                   outline="#3b82d0", width=3)

    def _nearest_graph_index(self, x: float) -> int | None:
        if not self.graph_points:
            return None
        return min(self.graph_points, key=lambda point: abs(point[0] - x))[2]

    def on_graph_click(self, event) -> None:
        index = self._nearest_graph_index(event.x)
        if index is not None:
            self.select_game_move(index)

    def on_graph_hover(self, event) -> None:
        index = self._nearest_graph_index(event.x)
        if index is None or not self.review:
            return
        move = self.review.moves[index]
        prefix = f"{move.move_number}." if move.mover == "white" else f"{move.move_number}…"
        loss = (f" · loss {100 * move.expected_score_loss:.2f}%"
                if move.expected_score_loss is not None else "")
        self.graph_hint.config(
            text=f"{prefix} {move.san} · {score(move.evaluation_after_cp)} · "
                 f"{move.classification}{loss}")

    def select_game_move(self, index: int) -> None:
        if not self.review or not self.review.moves:
            return
        index = max(0, min(len(self.review.moves) - 1, index))
        self.moves_list.selection_clear(0, "end")
        self.moves_list.selection_set(index)
        self.moves_list.see(index)
        self.on_game_move()

    def select_game_endpoint(self, ending: bool) -> None:
        if self.review and self.review.moves:
            self.select_game_move(len(self.review.moves) - 1 if ending else 0)

    def navigate_critical(self, direction: int) -> None:
        if not self.review or not self.review.moves:
            return
        accepted = {
            "all": {"best", "excellent", "good", "inaccuracy", "mistake", "blunder"},
            "inaccuracy+": {"inaccuracy", "mistake", "blunder"},
            "mistake+": {"mistake", "blunder"},
            "blunders": {"blunder"},
        }[self.critical_filter.get()]
        candidates = [index for index, move in enumerate(self.review.moves)
                      if move.classification in accepted]
        if not candidates:
            return
        selected = self.moves_list.curselection()
        current = selected[0] if selected else (-1 if direction > 0 else len(self.review.moves))
        ordered = candidates if direction > 0 else list(reversed(candidates))
        target = next((index for index in ordered
                       if (index > current if direction > 0 else index < current)),
                      ordered[0])
        self.select_game_move(target)

    def open_paste_dialog(self) -> None:
        """Collect a PGN and review settings without requiring a source file."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Paste a PGN")
        dialog.geometry("760x620")
        dialog.minsize(620, 480)
        dialog.configure(bg=APP_BG)
        dialog.transient(self.root)

        panel = ttk.Frame(dialog, padding=14, style="Panel.TFrame")
        panel.pack(fill="both", expand=True, padx=10, pady=10)
        ttk.Label(panel, text="PASTE PGN", style="Panel.TLabel",
                  font=("Segoe UI Semibold", 15)).pack(anchor="w")
        ttk.Label(panel,
                  text="Paste one complete game. Headers are optional.",
                  style="Muted.TLabel").pack(anchor="w", pady=(2, 10))
        pgn_text = tk.Text(panel, wrap="word", undo=True, bg=SURFACE, fg=TEXT,
                           insertbackground=TEXT, selectbackground=ACCENT,
                           relief="flat", padx=10, pady=10,
                           font=("Consolas", 10))
        pgn_text.pack(fill="both", expand=True)

        settings = ttk.Frame(panel, style="Panel.TFrame")
        settings.pack(fill="x", pady=(10, 0))
        ttk.Label(settings, text="Review limit", style="Panel.TLabel").pack(
            side="left")
        kind = tk.StringVar(value="time")
        ttk.Combobox(settings, textvariable=kind,
                     values=("time", "depth", "nodes"), width=8,
                     state="readonly").pack(side="left", padx=(6, 4))
        value = tk.StringVar(value="300")
        ttk.Entry(settings, textvariable=value, width=10).pack(side="left")
        ttk.Label(settings, text="Threads", style="Panel.TLabel").pack(
            side="left", padx=(8, 2))
        threads = tk.IntVar(value=1)
        ttk.Spinbox(settings, from_=1, to=16, textvariable=threads,
                    width=3).pack(side="left")
        hint = ttk.Label(settings, text="seconds for the complete review",
                         style="Muted.TLabel")
        hint.pack(side="left", padx=8)

        def update_hint(*_args) -> None:
            descriptions = {
                "time": "seconds for the complete review",
                "depth": "maximum depth for every position",
                "nodes": "nodes for every position",
            }
            hint.config(text=descriptions[kind.get()])

        kind.trace_add("write", update_hint)
        status = ttk.Label(settings, text="", style="Muted.TLabel")
        status.pack(side="right", padx=8)
        start = ttk.Button(settings, text="Start review",
                           style="Accent.TButton")
        start.pack(side="right")

        def begin() -> None:
            text = pgn_text.get("1.0", "end").strip()
            try:
                limit = float(value.get())
                if limit <= 0 or (kind.get() in ("depth", "nodes") and
                                  not limit.is_integer()):
                    raise ValueError
            except ValueError:
                messagebox.showerror("Invalid review limit",
                                     "Enter a positive whole number for depth or "
                                     "nodes, or positive seconds for time.",
                                     parent=dialog)
                return
            try:
                thread_count = int(threads.get())
                if not 1 <= thread_count <= 16:
                    raise ValueError
            except (ValueError, tk.TclError):
                messagebox.showerror("Invalid thread count",
                                     "Threads must be from 1 through 16.",
                                     parent=dialog)
                return
            engine = Path(self.engine_var.get())
            if not engine.is_file():
                messagebox.showerror("Engine not found", str(engine), parent=dialog)
                return
            if not text:
                messagebox.showerror("No PGN", "Paste a PGN before starting.",
                                     parent=dialog)
                return
            start.config(state="disabled")
            pgn_text.config(state="disabled")
            status.config(text="Preparing…")
            limit_kind = kind.get()

            def work() -> None:
                try:
                    from zebrafish.review.analyzer import analyze_review

                    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                    output_dir = resource("reviews")
                    output_dir.mkdir(parents=True, exist_ok=True)
                    source = output_dir / f"pasted-{stamp}.source.pgn"
                    output = output_dir / f"pasted-{stamp}.review.json"
                    source.write_text(text + "\n", encoding="utf-8")
                    games = read_pgn_games(source)
                    if not games:
                        raise ValueError("The pasted text does not contain a readable PGN game.")
                    game = games[0]
                    review = GameReview(
                        source_pgn=str(source.resolve()),
                        source_game_index=1,
                        headers=game.headers,
                        settings=AnalysisSettings(
                            engine_version=str(engine),
                            nodes_per_position=int(limit) if limit_kind == "nodes" else 0,
                            multipv=1,
                            threads=thread_count,
                        ),
                    )
                    save_review(review, output)
                    kwargs = {
                        "depth": int(limit) if limit_kind == "depth" else None,
                        "movetime_ms": None,
                        "nodes_per_position": int(limit) if limit_kind == "nodes" else None,
                        "total_time_seconds": limit if limit_kind == "time" else None,
                        "cpu_count": thread_count,
                        "progress": lambda record: self.work_queue.put(
                            ("review_progress", f"Analyzed {record.move_number}"
                             f"{'.' if record.mover == 'white' else '…'} {record.san}")),
                    }
                    analyze_review(review, review_path=output,
                                   engine_path=engine, **kwargs)
                    self.work_queue.put(("review_ok", (load_review(output), dialog,
                                                        str(output))))
                except Exception as error:
                    self.work_queue.put(("review_error", (str(error), dialog, start,
                                                           pgn_text, status)))

            threading.Thread(target=work, daemon=True).start()

        start.config(command=begin)
        pgn_text.focus_set()

    def move_selection(self, amount: int) -> None:
        if not self.review or not self.review.moves:
            return
        selected = self.moves_list.curselection()
        index = selected[0] if selected else 0
        index = max(0, min(len(self.review.moves) - 1, index + amount))
        self.select_game_move(index)

    def on_game_move(self, _event=None) -> None:
        if not self.review or not self.moves_list.curselection():
            return
        self.record = self.review.moves[self.moves_list.curselection()[0]]
        self.position_analysis_classical = None
        self.current_eval_cp = self.record.evaluation_after_cp
        # A highlighted game move represents the position after that move, as
        # in standard chess viewers. The line selector can still switch to the
        # pre-move position or either analyzed continuation.
        self.branch_var.set("Position after move")
        self.select_branch(start_at_end=True)
        self.show_record()
        self.draw_eval_graph()
        self.draw_eval_bar()

    def _branch_data(self) -> tuple[str, list[str]]:
        if not self.record:
            return chess.STARTING_FEN, []
        name = self.branch_var.get()
        r = self.record
        if name == "Position after move":
            return r.fen_before, [r.san]
        if name == "Best: full":
            return r.fen_before, r.full_best_pv_san
        if name == "Best: explainable":
            return r.fen_before, r.stable_best_pv_san + r.qsearch_pv_san
        if name == "Played: full":
            return r.fen_before, r.full_response_pv_san
        if name == "Played: explainable":
            return r.fen_before, r.stable_response_pv_san + r.response_qsearch_pv_san
        alt = r.simpler_good_alternative
        if name == "Simpler alternative: full":
            return r.fen_before, list(alt.get("full_line_san", []))
        if name == "Simpler alternative: explainable":
            return r.fen_before, list(alt.get("explainable_line_san", []))
        return r.fen_before, []

    def select_branch(self, start_at_end: bool = False) -> None:
        self.manual_mode = False
        self.selected_square = None
        self.line_root_fen, self.line_moves = self._branch_data()
        if self.record:
            name = self.branch_var.get()
            self.current_eval_cp = (self.record.evaluation_after_cp
                                    if name.startswith("Played") or
                                    name == "Position after move"
                                    else self.record.evaluation_before_cp)
        self.line_list.delete(0, "end")
        self.line_list.insert("end", "0. Starting position")
        for index, move in enumerate(self.line_moves, 1):
            self.line_list.insert("end", f"{index}. {move}")
        self.line_index = len(self.line_moves) if start_at_end else 0
        self.line_list.selection_set(0)
        if self.line_index:
            self.line_list.selection_clear(0, "end")
            self.line_list.selection_set(self.line_index)
            self.line_list.see(self.line_index)
        self.set_line_position()

    def draw_eval_bar(self) -> None:
        if not hasattr(self, "eval_bar"):
            return
        canvas = self.eval_bar
        canvas.delete("all")
        width, height = 42, 592
        top, bottom = 8, 584
        cp = self.current_eval_cp or 0
        bounded = max(-1000, min(1000, cp))
        white_fraction = 0.5 + bounded / 2000
        split = bottom - white_fraction * (bottom - top)
        canvas.create_rectangle(4, top, width - 4, bottom,
                                fill="#22211f", outline="#111")
        canvas.create_rectangle(4, split, width - 4, bottom,
                                fill="#eee", outline="")
        label = "?" if self.current_eval_cp is None else score(self.current_eval_cp)
        canvas.create_text(width / 2, top + 13 if cp <= 0 else bottom - 13,
                           text=label, fill="#eee" if cp <= 0 else "#222",
                           font=("Segoe UI Semibold", 9))

    def draw_components(self, canvas: tk.Canvas,
                        breakdown: ClassicalBreakdown | None,
                        title: str) -> None:
        canvas.delete("all")
        width = max(260, canvas.winfo_width())
        canvas.create_text(8, 7, anchor="nw",
                           text=title,
                           fill=TEXT, font=("Segoe UI Semibold", 9))
        if not breakdown:
            canvas.create_text(width / 2, 75, text="No component data",
                               fill=MUTED)
            return
        terms = [
            ("Material", breakdown.material),
            ("Placement", breakdown.piece_square),
            ("Activity", breakdown.activity),
            ("King safety", breakdown.king_safety),
            ("Pawns", breakdown.pawn_structure),
            ("Threats", breakdown.threats),
            ("Endgame", breakdown.endgame),
        ]
        center = width * .55
        maximum = max(100, max(abs(value) for _, value in terms))
        scale = (width * .36) / maximum
        for row, (name, value) in enumerate(terms):
            y = 30 + row * 16
            canvas.create_text(8, y, text=name, anchor="w", fill=MUTED,
                               font=("Segoe UI", 8))
            canvas.create_line(center, y - 6, center, y + 6, fill="#77736e")
            end = center + value * scale
            canvas.create_rectangle(min(center, end), y - 4, max(center, end), y + 4,
                                    fill="#7fb34d" if value >= 0 else "#b06666",
                                    outline="")
            canvas.create_text(width - 8, y, text=score(value), anchor="e",
                               fill=TEXT, font=("Consolas", 8))

    def draw_component_pair(self) -> None:
        """Keep best and played endpoint explanations visibly separate."""
        if self.record is None and self.position_analysis_classical is not None:
            self.draw_components(self.best_component_canvas,
                                 self.position_analysis_classical,
                                 "Analyzed-position classical endpoint")
            self.draw_components(self.played_component_canvas, None,
                                 "Played-line comparison unavailable")
            return
        best = self.record.best_classical if self.record else None
        played = self.record.played_classical if self.record else None
        self.draw_components(self.best_component_canvas, best,
                             "Best-line classical endpoint")
        self.draw_components(self.played_component_canvas, played,
                             "Played-line classical endpoint")

    def on_line_move(self, _event=None) -> None:
        if self.line_list.curselection():
            self.line_index = self.line_list.curselection()[0]
            self.set_line_position()

    def step_line(self, amount: int) -> None:
        self.line_index = max(0, min(len(self.line_moves), self.line_index + amount))
        self.line_list.selection_clear(0, "end")
        self.line_list.selection_set(self.line_index)
        self.line_list.see(self.line_index)
        self.set_line_position()

    def flip_board(self) -> None:
        self.flipped = not self.flipped
        self.selected_square = None
        self.draw_board(self.current_board, self.display_last_move)

    def copy_fen(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self.current_board.fen())
        self.eval_status.config(text="FEN copied")

    def copy_variation(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(" ".join(self.line_moves[:self.line_index]))
        self.eval_status.config(text="Variation copied")

    def clear_annotations(self) -> None:
        self.annotation_squares.clear()
        self.annotation_arrows.clear()
        self.draw_board(self.current_board, self.display_last_move)

    def _canvas_square(self, x: int, y: int) -> int | None:
        size, offset = 72, 8
        display_file = (x - offset) // size
        display_row = (y - offset) // size
        if not (0 <= display_file < 8 and 0 <= display_row < 8):
            return None
        if self.flipped:
            file, rank = 7 - display_file, display_row
        else:
            file, rank = display_file, 7 - display_row
        return chess.square(file, rank)

    def on_board_release(self, event) -> None:
        square = self._canvas_square(event.x, event.y)
        if (square is not None and self.board_press_square is not None and
                square != self.board_press_square and self.selected_square is not None):
            self._play_to_square(square)
        self.board_press_square = None

    def on_annotation_press(self, event) -> None:
        self.annotation_start = self._canvas_square(event.x, event.y)

    def on_annotation_release(self, event) -> None:
        target = self._canvas_square(event.x, event.y)
        start = self.annotation_start
        self.annotation_start = None
        if start is None or target is None:
            return
        if start == target:
            if start in self.annotation_squares:
                self.annotation_squares.remove(start)
            else:
                self.annotation_squares.add(start)
        else:
            arrow = (start, target)
            if arrow in self.annotation_arrows:
                self.annotation_arrows.remove(arrow)
            else:
                self.annotation_arrows.append(arrow)
        self.draw_board(self.current_board, self.display_last_move)

    def set_line_position(self) -> None:
        board = chess.Board(self.line_root_fen)
        last = None
        for san in self.line_moves[:self.line_index]:
            try:
                move = board.parse_san(san)
            except ValueError:
                break
            board.push(move)
            last = move
        self.current_board = board
        self.selected_square = None
        self.display_last_move = last
        self.draw_board(board, last)
        prefix = "Played variation" if self.manual_mode else self.branch_var.get()
        self.position_label.config(
            text=f"{prefix} — ply {self.line_index}/{len(self.line_moves)}")

    def _refresh_line_list(self) -> None:
        self.line_list.delete(0, "end")
        self.line_list.insert("end", "0. Starting position")
        for index, move in enumerate(self.line_moves, 1):
            self.line_list.insert("end", f"{index}. {move}")
        self.line_list.selection_set(self.line_index)
        self.line_list.see(self.line_index)

    def on_board_click(self, event) -> None:
        """Select and play legal moves on the currently displayed board."""
        if (self.finish_active and
                (self.finish_thinking or self.current_board.turn != self.finish_human_color)):
            return
        square = self._canvas_square(event.x, event.y)
        self.board_press_square = square
        if square is None:
            self.selected_square = None
            self.draw_board(self.current_board, self.display_last_move)
            return
        piece = self.current_board.piece_at(square)

        if self.selected_square is None:
            if piece and piece.color == self.current_board.turn:
                self.selected_square = square
            self.draw_board(self.current_board, self.display_last_move)
            return

        if piece and piece.color == self.current_board.turn:
            self.selected_square = square
            self.draw_board(self.current_board, self.display_last_move)
            return

        self._play_to_square(square)

    def _play_to_square(self, square: int) -> None:
        candidates = [move for move in self.current_board.legal_moves
                      if move.from_square == self.selected_square and
                      move.to_square == square]
        if not candidates:
            self.selected_square = None
            self.draw_board(self.current_board, self.display_last_move)
            return

        move = candidates[0]
        if len(candidates) > 1:
            choice = simpledialog.askstring(
                "Promotion", "Promote to queen, rook, bishop, or knight (q/r/b/n):",
                initialvalue="q", parent=self.root)
            promotion = {"q": chess.QUEEN, "r": chess.ROOK,
                         "b": chess.BISHOP, "n": chess.KNIGHT}.get(
                             (choice or "q").strip().lower(), chess.QUEEN)
            move = next((candidate for candidate in candidates
                         if candidate.promotion == promotion), candidates[0])
        if not self.manual_mode:
            self.line_root_fen = self.current_board.fen()
            self.line_moves = []
            self.line_index = 0
            self.manual_mode = True
        san = self.current_board.san(move)
        self.line_moves = self.line_moves[:self.line_index]
        self.line_moves.append(san)
        self.line_index += 1
        self.current_eval_cp = None
        self.selected_square = None
        self._refresh_line_list()
        self.set_line_position()
        if self.finish_active:
            self._finish_position_changed()

    def open_finish_dialog(self) -> None:
        """Choose an opponent and start an exploratory game from the board."""
        if self.finish_active:
            self.stop_finish_game()
            return
        engine = Path(self.engine_var.get())
        if not engine.is_file():
            messagebox.showerror("Engine not found", str(engine))
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("Finish this position vs engine")
        dialog.configure(bg=APP_BG)
        dialog.transient(self.root)
        dialog.grab_set()
        panel = ttk.Frame(dialog, padding=16, style="Panel.TFrame")
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text="FINISH FROM THE DISPLAYED POSITION",
                  style="Panel.TLabel", font=("Segoe UI Semibold", 13)).pack(anchor="w")
        ttk.Label(panel, text="This creates an exploratory variation; the saved review is unchanged.",
                  style="Muted.TLabel").pack(anchor="w", pady=(2, 12))

        side_var = tk.StringVar(value="White" if self.current_board.turn else "Black")
        mode_var = tk.StringVar(value="Maximum strength")
        elo_var = tk.IntVar(value=1500)
        time_var = tk.DoubleVar(value=1.0)
        form = ttk.Frame(panel, style="Panel.TFrame")
        form.pack(fill="x")
        ttk.Label(form, text="You play", style="Panel.TLabel").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Combobox(form, textvariable=side_var, values=("White", "Black"),
                     state="readonly", width=22).grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Label(form, text="Opponent", style="Panel.TLabel").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Combobox(form, textvariable=mode_var,
                     values=("Maximum strength", "Match reviewed opponent", "Selected Elo"),
                     state="readonly", width=22).grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Label(form, text="Selected Chess.com Elo", style="Panel.TLabel").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Spinbox(form, from_=400, to=2800, increment=50, textvariable=elo_var,
                    width=10).grid(row=2, column=1, sticky="w", pady=4)
        ttk.Label(form, text="Engine time / move", style="Panel.TLabel").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Spinbox(form, from_=0.05, to=60, increment=0.25, textvariable=time_var,
                    width=10).grid(row=3, column=1, sticky="w", pady=4)
        ttk.Label(form, text="seconds", style="Muted.TLabel").grid(row=3, column=1, sticky="e", pady=4)
        form.columnconfigure(1, weight=1)

        def start() -> None:
            try:
                seconds = float(time_var.get())
                if seconds <= 0:
                    raise ValueError
                selected_elo = int(elo_var.get())
                if not 400 <= selected_elo <= 2800:
                    raise ValueError
            except (ValueError, tk.TclError):
                messagebox.showerror("Invalid setting", "Use Elo 400–2800 and a positive time.", parent=dialog)
                return
            self._start_finish_game(side_var.get(), mode_var.get(), selected_elo,
                                    round(seconds * 1000))
            dialog.destroy()

        buttons = ttk.Frame(panel, style="Panel.TFrame")
        buttons.pack(anchor="e", pady=(14, 0))
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="left", padx=4)
        ttk.Button(buttons, text="Start", command=start,
                   style="Accent.TButton").pack(side="left")

    def _matched_opponent_elo(self, human_color: bool) -> int:
        """Return the reviewed opponent's estimate on the playing calibration scale."""
        if not self.review:
            raise ValueError("Open or create a review before matching its opponent.")
        opponent = "black" if human_color == chess.WHITE else "white"
        summary = self.review.players.get(opponent)
        if not summary or summary.estimated_performance_elo is None:
            raise ValueError(f"No rating estimate is available for {opponent.title()}.")
        from export_strength_profile import chesscom_to_ccrl
        return chesscom_to_ccrl(float(summary.estimated_performance_elo))

    def _start_finish_game(self, side_name: str, mode: str,
                           selected_elo: int, movetime_ms: int) -> None:
        human_color = chess.WHITE if side_name == "White" else chess.BLACK
        try:
            from export_strength_profile import chesscom_to_ccrl
            strength = None if mode == "Maximum strength" else (
                self._matched_opponent_elo(human_color)
                if mode == "Match reviewed opponent" else
                chesscom_to_ccrl(selected_elo))
            if strength is not None and not STRENGTH_ADAPTER.is_file():
                raise FileNotFoundError(STRENGTH_ADAPTER)
            engine = FinishEngine(Path(self.engine_var.get()),
                                  threads=max(1, min(16, int(self.threads_value.get()))),
                                  strength_elo=strength, adapter=STRENGTH_ADAPTER,
                                  book=OPENING_BOOK)
        except Exception as error:
            messagebox.showerror("Could not start opponent", str(error))
            return
        self.stop_finish_game(silent=True)
        self.finish_engine = engine
        self.finish_active = True
        self.finish_human_color = human_color
        self.finish_movetime_ms = movetime_ms
        self.finish_generation += 1
        self.line_root_fen = self.current_board.fen()
        self.line_moves = []
        self.line_index = 0
        self.manual_mode = True
        self._refresh_line_list()
        self.set_line_position()
        label = ("maximum strength" if strength is None else
                 (f"matched to the reviewed opponent ({strength} internal target)"
                  if mode == "Match reviewed opponent" else
                  f"about {selected_elo} Chess.com Blitz ({strength} internal target)"))
        self.finish_button.config(text="Stop Finish Game")
        self.eval_status.config(text=f"Finish game active · opponent {label}")
        self._finish_position_changed()

    def _finish_position_changed(self) -> None:
        if not self.finish_active:
            return
        if self.current_board.is_game_over(claim_draw=True):
            outcome = self.current_board.outcome(claim_draw=True)
            self.eval_status.config(text=f"Game over · {outcome.result() if outcome else '*'}")
            return
        if self.current_board.turn == self.finish_human_color:
            self.eval_status.config(text="Your move")
            return
        self.finish_thinking = True
        generation = self.finish_generation
        fen = self.current_board.fen()
        engine = self.finish_engine
        self.eval_status.config(text="Opponent is thinking…")

        def work() -> None:
            try:
                move = engine.move(fen, self.finish_movetime_ms) if engine else ""
                self.work_queue.put(("finish_move", (generation, fen, move)))
            except Exception as error:
                self.work_queue.put(("finish_error", (generation, str(error))))
        threading.Thread(target=work, daemon=True).start()

    def _apply_finish_move(self, fen: str, uci: str) -> None:
        if not self.finish_active or self.current_board.fen() != fen:
            return
        move = chess.Move.from_uci(uci)
        if move not in self.current_board.legal_moves:
            raise ValueError(f"engine returned illegal move {uci}")
        san = self.current_board.san(move)
        self.line_moves = self.line_moves[:self.line_index]
        self.line_moves.append(san)
        self.line_index += 1
        self.selected_square = None
        self._refresh_line_list()
        self.set_line_position()
        self._finish_position_changed()

    def stop_finish_game(self, *, silent: bool = False) -> None:
        was_active = self.finish_active
        self.finish_active = False
        self.finish_thinking = False
        self.finish_generation += 1
        engine, self.finish_engine = self.finish_engine, None
        if engine:
            threading.Thread(target=engine.close, daemon=True).start()
        if hasattr(self, "finish_button"):
            self.finish_button.config(text="Finish vs Engine")
        if was_active and not silent:
            self.eval_status.config(text="Finish game stopped; variation remains on board")

    def close(self) -> None:
        self.stop_finish_game(silent=True)
        self.root.destroy()

    def undo_manual_move(self) -> None:
        if not self.manual_mode or self.line_index <= 0:
            return
        self.line_moves = self.line_moves[:self.line_index - 1]
        self.line_index -= 1
        self._refresh_line_list()
        self.set_line_position()

    def draw_board(self, board, last=None) -> None:
        self.canvas.delete("all")
        size = 72
        offset = 8
        legal_targets = ({move.to_square for move in board.legal_moves
                          if move.from_square == self.selected_square}
                         if self.selected_square is not None else set())
        self.canvas.create_rectangle(offset + 5, offset + 6,
                                     offset + size * 8 + 5,
                                     offset + size * 8 + 6,
                                     fill="#171614", outline="")
        for row in range(8):
            for file in range(8):
                board_file = 7 - file if self.flipped else file
                rank = row if self.flipped else 7 - row
                square = chess.square(board_file, rank)
                color = LIGHT if (row + file) % 2 == 0 else DARK
                if last is not None and square in (last.from_square, last.to_square):
                    color = LAST_LIGHT if color == LIGHT else LAST_DARK
                if square == self.selected_square:
                    color = "#f6f669" if color in (LIGHT, LAST_LIGHT) else "#bbca45"
                if square in self.annotation_squares:
                    color = "#d6a84b"
                x, y = offset + file * size, offset + row * size
                self.canvas.create_rectangle(x, y, x + size, y + size,
                                             fill=color, outline=color)
                piece = board.piece_at(square)
                if piece:
                    image = self.piece_images.get(piece.symbol())
                    if image:
                        self.canvas.create_image(x + size / 2, y + size / 2,
                                                 image=image)
                    else:
                        self.canvas.create_text(x + size / 2, y + size / 2,
                            text=PIECES[piece.symbol()], font=("Segoe UI Symbol", 48))
                if square in legal_targets:
                    if piece:
                        self.canvas.create_oval(x + 7, y + 7, x + size - 7,
                                                y + size - 7,
                                                outline="#456b32", width=5)
                    else:
                        radius = 9
                        self.canvas.create_oval(x + size / 2 - radius,
                                                y + size / 2 - radius,
                                                x + size / 2 + radius,
                                                y + size / 2 + radius,
                                                fill="#456b32", outline="")
                coordinate = DARK if color in (LIGHT, LAST_LIGHT) else LIGHT
                if row == 7:
                    self.canvas.create_text(x + 5, y + size - 4,
                        text=chess.FILE_NAMES[board_file], anchor="sw", fill=coordinate,
                        font=("Segoe UI Semibold", 8))
                if file == 0:
                    self.canvas.create_text(x + 4, y + 4, text=str(rank + 1),
                        anchor="nw", fill=coordinate,
                        font=("Segoe UI Semibold", 8))
        for start, target in self.annotation_arrows:
            start_file = chess.square_file(start)
            start_rank = chess.square_rank(start)
            target_file = chess.square_file(target)
            target_rank = chess.square_rank(target)
            if self.flipped:
                start_file, start_rank = 7 - start_file, start_rank
                target_file, target_rank = 7 - target_file, target_rank
            else:
                start_rank, target_rank = 7 - start_rank, 7 - target_rank
            x1, y1 = offset + (start_file + .5) * size, offset + (start_rank + .5) * size
            x2, y2 = offset + (target_file + .5) * size, offset + (target_rank + .5) * size
            self.canvas.create_line(x1, y1, x2, y2, fill="#d69e2e", width=7,
                                    arrow="last", arrowshape=(14, 18, 7))
        self.draw_eval_bar()

    def show_record(self) -> None:
        if not self.record:
            return
        r = self.record
        best_line = " ".join(r.stable_best_pv_san + r.qsearch_pv_san) or "—"
        played_line = " ".join(r.stable_response_pv_san + r.response_qsearch_pv_san) or "—"
        self.best_compare.delete("1.0", "end")
        self.best_compare.insert(
            "1.0", f"BEST  {r.best_move_san or r.best_move_uci}  "
                   f"{score(r.evaluation_before_cp)}\n{best_line}\n\n"
                   f"Classical: {format_components(r.best_classical) if r.best_classical else '—'}")
        self.played_compare.delete("1.0", "end")
        self.played_compare.insert(
            "1.0", f"PLAYED  {r.san}  {score(r.evaluation_after_cp)}\n"
                   f"{played_line}\n\n"
                   f"Classical: {format_components(r.played_classical) if r.played_classical else '—'}")
        self.draw_component_pair()
        text = [
            f"{r.move_number}{'.' if r.mover == 'white' else '...'} {r.san}: {r.classification}",
            f"Played-move NNUE: {score(r.evaluation_after_cp)}",
            f"Best move: {r.best_move_san or r.best_move_uci} ({score(r.evaluation_before_cp)})",
            f"Expected-score loss: {100 * r.expected_score_loss:.2f}%" if r.expected_score_loss is not None else "Expected-score loss: unavailable",
            "",
            "Full best line: " + " ".join(r.full_best_pv_san),
            "Explainable best line: " + " ".join(r.stable_best_pv_san + r.qsearch_pv_san),
            f"Best endpoint NNUE: {score(r.qsearch_score_cp)}",
            "Best classical: " + (format_components(r.best_classical) if r.best_classical else "unavailable"),
            "",
            "Full played line: " + " ".join(r.full_response_pv_san),
            "Explainable played line: " + " ".join(r.stable_response_pv_san + r.response_qsearch_pv_san),
            f"Played endpoint NNUE: {score(r.response_qsearch_score_cp)}",
            "Played classical: " + (format_components(r.played_classical) if r.played_classical else "unavailable"),
        ]
        if r.simpler_good_alternative:
            alt = r.simpler_good_alternative
            text += ["", f"Simpler good alternative: {alt['move_san']} ({score(alt['score_cp'])})",
                     "Alternative line: " + " ".join(alt["explainable_line_san"])]
        self.details.delete("1.0", "end")
        self.details.insert("1.0", "\n".join(text))

    def evaluate_position(self) -> None:
        try:
            value = float(self.limit_value.get())
            if value <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid limit", "Enter a positive number.")
            return
        engine = Path(self.engine_var.get())
        if not engine.is_file():
            messagebox.showerror("Engine not found", str(engine))
            return
        self.evaluate_button.config(state="disabled")
        self.eval_status.config(text="Analyzing…")
        fen = self.current_board.fen()
        kind = self.limit_kind.get()

        def work() -> None:
            try:
                thread_count = max(1, min(16, int(self.threads_value.get())))
                result = review_position(fen, engine_path=engine,
                                         limit_kind=kind, limit_value=value,
                                         cpu_count=thread_count,
                                         threads=thread_count)
                self.work_queue.put(("ok", result))
            except Exception as error:
                self.work_queue.put(("error", str(error)))
        threading.Thread(target=work, daemon=True).start()

    def _poll_worker(self) -> None:
        try:
            kind, payload = self.work_queue.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll_worker)
            return
        if kind == "finish_move":
            generation, fen, move = payload
            if generation == self.finish_generation:
                self.finish_thinking = False
                try:
                    self._apply_finish_move(fen, move)
                except Exception as error:
                    self.stop_finish_game(silent=True)
                    messagebox.showerror("Opponent move failed", str(error))
            self.root.after(100, self._poll_worker)
            return
        if kind == "finish_error":
            generation, error = payload
            if generation == self.finish_generation:
                self.stop_finish_game(silent=True)
                self.eval_status.config(text="Finish game failed")
                messagebox.showerror("Opponent failed", error)
            self.root.after(100, self._poll_worker)
            return
        if kind == "review_progress":
            # The paste dialog owns its detailed progress text; the title gives
            # useful feedback even if the dialog is behind the main window.
            self.root.title(f"C Engine Game Review — {payload}")
            self.root.after(100, self._poll_worker)
            return
        if kind == "review_ok":
            self.review, dialog, output = payload
            self.review_path = Path(output)
            self.elo_explanations = {}
            self.white_elo_details.config(state="disabled")
            self.black_elo_details.config(state="disabled")
            self.root.title("C Engine Game Review")
            if dialog.winfo_exists():
                dialog.destroy()
            self._display_review()
            self.estimate_performance_elo(automatic=True)
            messagebox.showinfo("Review complete",
                                f"The pasted game is ready.\n\nSaved to:\n{output}")
            self.root.after(100, self._poll_worker)
            return
        if kind == "review_error":
            error, dialog, start, pgn_text, status = payload
            self.root.title("C Engine Game Review")
            if dialog.winfo_exists():
                start.config(state="normal")
                pgn_text.config(state="normal")
                status.config(text="Review failed")
                messagebox.showerror("Review failed", error, parent=dialog)
            self.root.after(100, self._poll_worker)
            return
        if kind == "elo_ok":
            review, review_path, estimates, automatic = payload
            for color, estimate in estimates.items():
                summary = review.players.get(color)
                if summary is None:
                    summary = PlayerSummary(color=color)
                    review.players[color] = summary
                summary.estimated_performance_elo = estimate["performance_elo"]
                summary.elo_interval_low = estimate.get("display_range_low", estimate["range_low"])
                summary.elo_interval_high = estimate.get("display_range_high", estimate["range_high"])
                summary.elo_evidence_quality = estimate["evidence_quality"]
                summary.elo_model_version = estimate.get("model_version", "")
                summary.elo_details = estimate
            if review_path is not None:
                save_review(review, review_path)
            self.elo_estimation_running = False
            self.elo_button.config(state="normal")
            if review is self.review:
                self.elo_explanations = estimates
                self._refresh_move_list()
                self.elo_button.config(state="normal", text="Refresh rating")
                self.white_elo_details.config(
                    state="normal" if "white" in estimates else "disabled")
                self.black_elo_details.config(
                    state="normal" if "black" in estimates else "disabled")
                self.update_elo_summary()
            if not automatic:
                messagebox.showinfo(
                    "Rating estimate ready",
                    "The estimates were calculated and saved with this review."
                    if review_path is not None else
                    "The estimates were calculated. Save persistence is unavailable "
                    "because this review has no file path.")
            self.root.after(100, self._poll_worker)
            return
        if kind == "elo_error":
            failed_review, error, automatic = payload
            self.elo_estimation_running = False
            self.elo_button.config(state="normal")
            if failed_review is not self.review:
                self.root.after(100, self._poll_worker)
                return
            self.update_elo_summary()
            if automatic:
                self.elo_summary_label.config(text=f"Rating estimate unavailable: {error}")
            else:
                messagebox.showerror("Rating estimate unavailable", error)
            self.root.after(100, self._poll_worker)
            return

        self.evaluate_button.config(state="normal")
        if kind == "error":
            self.eval_status.config(text="Analysis failed")
            messagebox.showerror("Analysis failed", payload)
        else:
            self.eval_status.config(text="Analysis complete")
            result = payload
            classical: ClassicalBreakdown = result["classical"]
            self.current_eval_cp = result["root_nnue_cp"]
            self.draw_eval_bar()
            self.record = None
            self.position_analysis_classical = classical
            self.draw_component_pair()
            self.best_compare.delete("1.0", "end")
            self.best_compare.insert(
                "1.0", f"BEST  {result['best_move']}  {score(result['root_nnue_cp'])}\n"
                       + " ".join(result["explainable_line_san"]) + "\n\n"
                       f"Classical: {format_components(classical)}")
            self.played_compare.delete("1.0", "end")
            self.played_compare.insert(
                "1.0", "POSITION ANALYSIS\nNo played-move comparison for a standalone position.")
            method = ("robust consensus" if result["consensus"] else "strict")
            if not result["stable"]:
                method = "full-PV fallback; no stable line"
            lines = [
                "POSITION ANALYSIS",
                f"Best move: {result['best_move']}",
                f"Root NNUE: {score(result['root_nnue_cp'])}",
                "Full line: " + " ".join(result["full_line_san"]),
                "Explainable line with qsearch: " + " ".join(result["explainable_line_san"]),
                f"Line selection: {method}",
                f"Depths: discovered {result['discovery_depth']}, stable {result['stability_depth']}, verified {result['verification_depth']}",
                f"Endpoint NNUE: {score(result['endpoint_nnue_cp'])}; difference {score(result['endpoint_delta_cp'])}",
                f"Explainable classical total: {score(classical.total)}",
                "Components: " + format_components(classical),
                "",
                *result["explanation"],
            ]
            self.details.delete("1.0", "end")
            self.details.insert("1.0", "\n".join(lines))
            self.line_root_fen = result["fen"]
            self.line_moves = result["explainable_line_san"]
            self.manual_mode = False
            self.line_list.delete(0, "end")
            self.line_list.insert("end", "0. Starting position")
            for index, move in enumerate(self.line_moves, 1):
                self.line_list.insert("end", f"{index}. {move}")
            self.line_index = 0
            self.line_list.selection_set(0)
            self.set_line_position()
        self.root.after(100, self._poll_worker)


def main() -> None:
    root = tk.Tk()
    ReviewGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
