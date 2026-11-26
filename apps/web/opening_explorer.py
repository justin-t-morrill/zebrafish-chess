"""Local opening names, move orders, and the engine's actual weighted book."""
from __future__ import annotations

import csv
import re
import threading
from functools import lru_cache
from pathlib import Path

from zebrafish.review.chess_support import chess


@lru_cache(maxsize=24000)
def position_key(fen):
    # Ignore clocks and irrelevant en-passant targets. Transpositions share a key.
    return " ".join(chess.Board(fen).fen(en_passant="legal").split()[:4])


class OpeningCatalog:
    def __init__(self, names, book, sources=None):
        self.names = {}
        self.entries = []
        self.book = {}
        self.sources = sources
        self.lines = None
        self.line_lock = threading.Lock()
        if Path(names).is_file():
            with Path(names).open(encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle, delimiter="\t"):
                    try:
                        board = chess.Board(row['fen'])
                        if not board.is_valid():
                            continue
                        key = position_key(row['fen'])
                        self.names[key] = {'eco': row['eco'], 'name': row['name'], 'fen': board.fen()}
                    except (ValueError, KeyError):
                        continue
            self.entries = sorted(self.names.values(), key=lambda item: (item['name'].casefold(), item['eco']))
            for index, entry in enumerate(self.entries):
                entry['id'] = str(index)
        if Path(book).is_file():
            with Path(book).open(encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle, delimiter="\t"):
                    try:
                        key = position_key(row['fen'])
                        item = {'uci': row['move'], 'weight': max(0, int(row['weight'])),
                                'games': max(0, int(row.get('games') or 0))}
                        choices = self.book.setdefault(key, {})
                        # Canonical EP keys can merge equivalent source rows.
                        if item['uci'] not in choices or item['weight'] > choices[item['uci']]['weight']:
                            choices[item['uci']] = item
                    except (ValueError, KeyError):
                        continue

    def is_book_move(self, board, move):
        return move in board.legal_moves and move.uci() in self.book.get(position_key(board.fen()), {})

    def exact(self, board):
        return self.names.get(position_key(board.fen()))

    def describe(self, board, history=()):
        key = position_key(board.fen())
        found = self.names.get(key)
        exact = found is not None
        if not found:
            previous = board.copy()
            while previous.move_stack:
                previous.pop()
                found = self.exact(previous)
                if found:
                    break
        if not found:
            for fen in reversed(history):
                found = self.names.get(position_key(fen))
                if found:
                    break
        in_book = key in self.book
        label = f"{found['eco']} · {found['name']}" if found else (
            'Starting position' if key == position_key(chess.STARTING_FEN) else
            'Unnamed book position' if in_book else 'No recognized opening')
        return {'label': label, 'name': found['name'] if found else '',
                'eco': found['eco'] if found else '', 'exact': exact,
                'in_book': in_book, 'book_moves': len(self.book.get(key, {})),
                'recognized_fen': found['fen'] if found else None}

    def continuations(self, board):
        moves = []
        for entry in self.book.get(position_key(board.fen()), {}).values():
            try:
                move = chess.Move.from_uci(entry['uci'])
            except ValueError:
                continue
            if move not in board.legal_moves:
                continue
            child = board.copy(stack=False)
            child.push(move)
            named = self.exact(child)
            moves.append({**entry, 'san': board.san(move), 'fen': child.fen(),
                          'name': named['name'] if named else '', 'eco': named['eco'] if named else ''})
        total = sum(entry['weight'] for entry in moves)
        for entry in moves:
            entry['share'] = round(100 * entry['weight'] / total, 2) if total else 0
        return sorted(moves, key=lambda entry: (-entry['weight'], entry['san']))

    def search(self, query='', offset=0, limit=20):
        self._ensure_lines()
        words = query.casefold().split()
        matches = [entry for entry in self.entries
                   if all(word in (entry['eco'] + ' ' + entry['name']).casefold() for word in words)]
        if not words:
            common = ['Sicilian Defense', 'French Defense', 'Italian Game', 'Ruy Lopez',
                      'Caro-Kann Defense', "Queen's Gambit Declined", 'English Opening',
                      "King's Indian Defense"]
            matches.sort(key=lambda entry: (common.index(entry['name']) if entry['name'] in common else len(common),
                                            entry['name'].casefold(), entry['eco']))
        else:
            text = query.casefold().strip()
            matches.sort(key=lambda entry: (0 if entry['name'].casefold() == text or entry['eco'].casefold() == text else
                                            1 if entry['name'].casefold().startswith(text) else 2,
                                            len(entry['name']), entry['name'].casefold(), entry['eco']))
        return {'results': [{**entry, 'in_book': position_key(entry['fen']) in self.book,
                             'moves': self.lines.get(position_key(entry['fen']), [])}
                            for entry in matches[offset:offset + limit]],
                'total': len(matches), 'offset': offset, 'has_more': offset + limit < len(matches)}

    def named_position(self, index):
        if not str(index).isdigit() or not 0 <= int(index) < len(self.entries):
            raise ValueError('Choose a named opening from the results.')
        entry = self.entries[int(index)]
        self._ensure_lines()
        return {**entry, 'moves': self.lines.get(position_key(entry['fen']), [])}

    def _ensure_lines(self):
        # Move orders are optional, loaded only when using the named explorer.
        with self.line_lock:
            if self.lines is None:
                self.lines = {}
                if self.sources:
                    for source in sorted(Path(self.sources).glob('[abcde].tsv')):
                        with source.open(encoding='utf-8-sig', newline='') as handle:
                            for row in csv.DictReader(handle, delimiter='\t'):
                                board = chess.Board()
                                moves = re.sub(r'\d+\.(?:\.\.)?', '', row.get('pgn', '')).split()
                                try:
                                    for san in moves:
                                        board.push_san(san)
                                    key = position_key(board.fen())
                                    if moves and (key not in self.lines or len(moves) < len(self.lines[key])):
                                        self.lines[key] = moves
                                except ValueError:
                                    continue


@lru_cache(maxsize=1)
def project_catalog(root):
    return OpeningCatalog(root / 'openings/book/OpeningNames.tsv', root / 'openings/book/OpeningBook.tsv',
                          root / 'openings/data/lichess/lichess-chess-openings')
