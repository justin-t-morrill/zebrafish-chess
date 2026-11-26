"""Hidden Tk integration check with real CPU inference and disposable storage."""
import sys
import tempfile
import time
import tkinter as tk
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from review_gui import ReviewGui
from reviewer.storage import load_review, save_review
from reviewer.models import PlayerSummary
from test_rating_estimate import example_review


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


root = tk.Tk()
root.withdraw()
try:
    with tempfile.TemporaryDirectory() as folder:
        app = ReviewGui(root)
        root.withdraw()
        app.review = example_review()
        app.review.players['white'] = PlayerSummary(color='white', estimated_performance_elo=1200,
                                                    elo_model_version='old_model')
        app.review_path = Path(folder) / 'review.json'
        save_review(app.review, app.review_path)
        app._display_review()
        assert 'old estimate' in app.elo_summary_label.cget('text')
        app.estimate_performance_elo(automatic=True)
        deadline = time.monotonic() + 85
        while app.elo_estimation_running and time.monotonic() < deadline:
            root.update()
            time.sleep(.03)
        assert not app.elo_estimation_running, 'Inference timed out'
        assert set(app.elo_explanations) == {'white', 'black'}, app.elo_summary_label.cget('text')
        restored = load_review(app.review_path)
        assert restored.players['white'].elo_model_version == 'ratingnet_natural_v1'
        assert restored.players['white'].elo_details == app.elo_explanations['white']
        assert all(move.performance_elo_impact is None for move in restored.moves)
        assert 'Lichess blitz' in app.elo_summary_label.cget('text')
        real_toplevel = tk.Toplevel
        def hidden_dialog(*args, **kwargs):
            dialog = real_toplevel(*args, **kwargs)
            dialog.withdraw()
            return dialog
        with patch('review_gui.tk.Toplevel', side_effect=hidden_dialog):
            app.show_elo_details('white')
        dialogs = [w for w in root.winfo_children() if isinstance(w, real_toplevel)]
        assert len(dialogs) == 1
        labels = [w.cget('text') for w in descendants(dialogs[0]) if w.winfo_class() == 'TLabel']
        for name in ('Tactical:', 'Positional:', 'Defensive:', 'Conversion:', 'Consistency:'):
            assert any(name in text for text in labels), name
        table = next(w for w in descendants(dialogs[0]) if w.winfo_class() == 'Treeview')
        rows = table.get_children()
        assert rows
        table.selection_set(rows[0])
        # Invoke the registered Tk callback without sending system input.
        callback = table.bind('<Double-1>').split('[', 1)[1].split()[0]
        with patch.object(app, 'select_game_move') as select:
            root.tk.call(callback, *(['0'] * 19))
            assert select.called
        print('PASS: real background inference, legacy refresh, persistence, details, and supporting-move navigation')
finally:
    root.destroy()
