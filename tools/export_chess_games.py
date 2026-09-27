"""Export the two complete final-checkpoint matches from the preserved evidence archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import chess
import chess.pgn
from pydantic import BaseModel, ConfigDict, TypeAdapter


class Outcome(str, Enum):
    WIN = 'win'
    DRAW = 'draw'
    LOSS = 'loss'


class Player(str, Enum):
    FIRST = 'first'
    SECOND = 'second'


class Termination(str, Enum):
    NATURAL = 'natural'
    MAXIMUM_PLIES = 'maximum_plies'


class RecordedGame(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')
    game_index: int
    pair_index: int
    opening_id: str
    candidate_player: Player
    pair_seed: int
    initial_action_ids: tuple[int, ...]
    played_action_ids: tuple[int, ...]
    outcome: Outcome
    termination_reason: Termination
    plies: int
    duration_seconds: float


class Colour(str, Enum):
    WHITE = 'white'
    BLACK = 'black'


class GameEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')
    game_id: int
    opponent_nodes: int
    colour: Colour
    outcome: Outcome
    total_plies: int
    termination: Termination
    opening_id: str
    file: str


class MatchSource(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')
    opponent_nodes: int
    archive_member: str
    sha256: str
    source_revision: str


class Manifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')
    checkpoint: int
    searches: int
    parallel_searches: int
    sources: tuple[MatchSource, ...]
    games: tuple[GameEntry, ...]


@dataclass(frozen=True)
class ExportedGame:
    entry: GameEntry
    pgn: str


def action_mapping() -> tuple[chess.Move, ...]:
    # Mirrors reducedEncoding::calculateMoveMappings in the evaluated chess engine.
    directions = ((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1))
    knights = ((2, 1), (1, 2), (-1, 2), (-2, 1), (-2, -1), (-1, -2), (1, -2), (2, -1))
    moves: list[chess.Move] = []
    for square in range(64):
        row, column = divmod(square, 8)
        for row_step, column_step in directions:
            for distance in range(1, 8):
                target_row, target_column = row + row_step * distance, column + column_step * distance
                if 0 <= target_row < 8 and 0 <= target_column < 8:
                    moves.append(chess.Move(square, target_row * 8 + target_column))
        for row_step, column_step in knights:
            target_row, target_column = row + row_step, column + column_step
            if 0 <= target_row < 8 and 0 <= target_column < 8:
                moves.append(chess.Move(square, target_row * 8 + target_column))
        if row == 6:
            for offset in (-1, 0, 1):
                if 0 <= column + offset < 8:
                    for promotion in (chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT):
                        moves.append(chess.Move(square, 56 + column + offset, promotion=promotion))
    assert len(moves) == 1880
    return tuple(moves)


def reconstruct(record: RecordedGame, mapping: tuple[chess.Move, ...]) -> chess.pgn.Game:
    game = chess.pgn.Game()
    board = game.board()
    node: chess.pgn.GameNode = game
    for action in (*record.initial_action_ids, *record.played_action_ids):
        move = mapping[action]
        if board.turn == chess.BLACK:
            move = chess.Move(move.from_square ^ 56, move.to_square ^ 56, promotion=move.promotion)
        if board.is_kingside_castling(move):
            move = chess.Move(move.from_square, chess.G1 if board.turn else chess.G8)
        elif board.is_queenside_castling(move):
            move = chess.Move(move.from_square, chess.C1 if board.turn else chess.C8)
        if move not in board.legal_moves:
            raise ValueError(f'Illegal move in game {record.game_index} at ply {board.ply()}: {move}')
        board.push(move)
        node = node.add_variation(move)
    assert record.plies == len(record.played_action_ids)
    assert len(record.initial_action_ids) == 16
    match record.outcome:
        case Outcome.DRAW:
            expected = '1/2-1/2'
        case Outcome.WIN:
            expected = '1-0' if record.candidate_player == Player.FIRST else '0-1'
        case Outcome.LOSS:
            expected = '0-1' if record.candidate_player == Player.FIRST else '1-0'
    match record.termination_reason:
        case Termination.NATURAL:
            if board.result(claim_draw=True) != expected:
                raise ValueError(f'Result mismatch in game {record.game_index}: {board.fen()}')
        case Termination.MAXIMUM_PLIES:
            if board.ply() != 300 or record.outcome != Outcome.DRAW:
                raise ValueError(f'Unexpected capped result in game {record.game_index}')
    game.headers['Result'] = expected
    return game


def export_game(record: RecordedGame, nodes: int, date: str, mapping: tuple[chess.Move, ...]) -> ExportedGame:
    game = reconstruct(record, mapping)
    colour = Colour.WHITE if record.candidate_player == Player.FIRST else Colour.BLACK
    game.headers['Event'] = f'AlphaZero final evaluation: 100000 searches vs Stockfish 13 {nodes} nodes'
    game.headers['Site'] = 'Local evaluation'
    game.headers['Date'] = date
    game.headers['Round'] = str(record.game_index + 1)
    game.headers['White'] = 'AlphaZero checkpoint 1026' if colour == Colour.WHITE else 'Stockfish 13'
    game.headers['Black'] = 'Stockfish 13' if colour == Colour.WHITE else 'AlphaZero checkpoint 1026'
    game.headers['GameId'] = str(record.game_index)
    game.headers['OpeningId'] = record.opening_id
    game.headers['ModelSearches'] = '100000'
    game.headers['ModelParallelSearches'] = '16'
    game.headers['StockfishNodes'] = str(nodes)
    total_plies = len(record.initial_action_ids) + record.plies
    game.headers['PlyCount'] = str(total_plies)
    game.headers['Termination'] = 'normal' if record.termination_reason == Termination.NATURAL else 'adjudication'
    game.comment = 'The first eight full moves are the fixed evaluation opening. GameId is zero-based.'
    if record.termination_reason == Termination.MAXIMUM_PLIES:
        game.end().comment = 'Draw adjudicated at the evaluation limit of 300 half-moves.'
    entry = GameEntry(
        game_id=record.game_index,
        opponent_nodes=nodes,
        colour=colour,
        outcome=record.outcome,
        total_plies=total_plies,
        termination=record.termination_reason,
        opening_id=record.opening_id,
        file=f'sf{nodes}-game-{record.game_index:02d}.pgn',
    )
    return ExportedGame(
        entry, game.accept(chess.pgn.StringExporter(headers=True, variations=False, comments=True)) + '\n'
    )


def export_archive(archive_path: Path, output: Path) -> None:
    mapping = action_mapping()
    exported: list[ExportedGame] = []
    sources: list[MatchSource] = []
    with tarfile.open(archive_path) as archive:
        for nodes, member in (
            (100000, 'final-evaluation/s100k-vs-100k-batched/result.json'),
            (200000, 'final-evaluation/s100k-vs-200k/result.json'),
        ):
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError(f'Missing match record: {member}')
            payload = stream.read()
            source = json.loads(payload)
            assert source['evaluated_checkpoint']['generation'] == 1026
            assert source['model_search_budget']['searches_per_move'] == 100000
            assert source['model_search_budget']['parallel_searches'] == 16
            assert source['stockfish_match_nodes'] == nodes
            assert source['stockfish_identity'] == 'Stockfish 13'
            records = TypeAdapter(tuple[RecordedGame, ...]).validate_python(source['games'])
            assert sorted(record.game_index for record in records) == list(range(100))
            for outcome in Outcome:
                assert (
                    sum(record.outcome == outcome for record in records)
                    == source['aggregate'][outcome.value + ('es' if outcome == Outcome.LOSS else 's')]
                )
            date = source['started_at_utc'][:10].replace('-', '.')
            exported.extend(
                export_game(record, nodes, date, mapping)
                for record in sorted(records, key=lambda record: record.game_index)
            )
            sources.append(
                MatchSource(
                    opponent_nodes=nodes,
                    archive_member=member,
                    sha256=hashlib.sha256(payload).hexdigest(),
                    source_revision=source['source_revision'],
                )
            )
    output.mkdir(parents=True, exist_ok=True)
    for game in exported:
        (output / game.entry.file).write_text(game.pgn, encoding='utf-8', newline='\n')
    (output / 'all-200-games.pgn').write_text('\n'.join(game.pgn for game in exported), encoding='utf-8', newline='\n')
    manifest = Manifest(
        checkpoint=1026,
        searches=100000,
        parallel_searches=16,
        sources=tuple(sources),
        games=tuple(game.entry for game in exported),
    )
    (output / 'games.json').write_text(manifest.model_dump_json(indent=2) + '\n', encoding='utf-8', newline='\n')
    print(f'Exported and legally replayed {len(exported)} games; outcomes match both source aggregates.')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'assets' / 'chess-games')
    arguments = parser.parse_args()
    export_archive(arguments.archive, arguments.output)


if __name__ == '__main__':
    main()
