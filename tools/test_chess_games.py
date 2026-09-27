"""Validate the published PGNs without requiring the original evidence archive."""

import io
import unittest
from collections import Counter
from pathlib import Path

import chess.pgn

from tools.export_chess_games import Colour, Manifest, Outcome, Termination, action_mapping

ROOT = Path(__file__).resolve().parents[1]
GAMES = ROOT / 'assets' / 'chess-games'


class ChessGamesTest(unittest.TestCase):
    def test_encoding(self) -> None:
        mapping = action_mapping()
        self.assertEqual(len(mapping), 1880)
        self.assertEqual(len(set(mapping)), 1880)

    def test_published_games(self) -> None:
        manifest = Manifest.model_validate_json((GAMES / 'games.json').read_text(encoding='utf-8'))
        self.assertEqual(len(manifest.games), 200)
        combined = io.StringIO((GAMES / 'all-200-games.pgn').read_text(encoding='utf-8'))
        for entry in manifest.games:
            with self.subTest(file=entry.file):
                game = chess.pgn.read_game(io.StringIO((GAMES / entry.file).read_text(encoding='utf-8')))
                self.assertIsNotNone(game)
                assert game is not None
                self.assertEqual(game.errors, [])
                self.assertEqual(str(chess.pgn.read_game(combined)), str(game))
                self.assertEqual(game.headers['GameId'], str(entry.game_id))
                self.assertEqual(game.headers['StockfishNodes'], str(entry.opponent_nodes))
                self.assertEqual(game.end().ply(), entry.total_plies)
                expected = '1/2-1/2'
                if entry.outcome != Outcome.DRAW:
                    white_wins = (entry.outcome == Outcome.WIN) == (entry.colour == Colour.WHITE)
                    expected = '1-0' if white_wins else '0-1'
                self.assertEqual(game.headers['Result'], expected)
                if entry.termination == Termination.NATURAL:
                    self.assertEqual(game.end().board().result(claim_draw=True), expected)
                else:
                    self.assertEqual(entry.total_plies, 300)
                    self.assertEqual(entry.outcome, Outcome.DRAW)
        self.assertIsNone(chess.pgn.read_game(combined))
        for nodes, counts in ((100000, (51, 38, 11)), (200000, (25, 56, 19))):
            selected = [entry for entry in manifest.games if entry.opponent_nodes == nodes]
            self.assertEqual(sorted(entry.game_id for entry in selected), list(range(100)))
            totals = Counter(entry.outcome for entry in selected)
            self.assertEqual(tuple(totals[outcome] for outcome in Outcome), counts)
            self.assertEqual(Counter(entry.colour for entry in selected), {Colour.WHITE: 50, Colour.BLACK: 50})

    def test_featured_game_unchanged(self) -> None:
        old = chess.pgn.read_game(io.StringIO((ROOT / 'assets' / 'alphazero-game-74.pgn').read_text()))
        new = chess.pgn.read_game(io.StringIO((GAMES / 'sf200000-game-74.pgn').read_text()))
        assert old is not None and new is not None
        self.assertEqual(list(old.mainline_moves()), list(new.mainline_moves()))


if __name__ == '__main__':
    unittest.main()
