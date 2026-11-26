"""Launch the real GUI against a disposable copy for manual/automated QA."""
import argparse
import sys
import tkinter as tk
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from review_gui import ReviewGui
from reviewer.storage import load_review, save_review

p = argparse.ArgumentParser()
p.add_argument("review", type=Path)
a = p.parse_args()
root = tk.Tk()
app = ReviewGui(root)
app.review = load_review(a.review)
output = HERE / "output/rating_gui.review.json"
save_review(app.review, output)
app.review_path = output
app._display_review()
root.title("Rating GUI verification")
root.mainloop()
