"""Render a chess game as a compact animated WebP for the homepage.

Usage:
    python tools/render_game_gif.py GAME.pgn [--out assets/chess-game.webp]
                                   [--white "AlphaZero"] [--white-sub "self-play model, White"]
                                   [--black "Stockfish"] [--black-sub "2200 Elo, 1 s/move, Black"]

Requires: pip install chess cairosvg pillow

Pacing is heuristic: the opening is skimmed, the last 14 plies are slowed down,
and captures, checks and promotions each add a beat. Forced replies (three legal
moves or fewer) snap through.
"""
import argparse, sys
import io, json, re
import chess, chess.pgn, chess.svg
import cairosvg
from PIL import Image, ImageDraw, ImageFont

ap = argparse.ArgumentParser()
ap.add_argument("pgn", help="path to a PGN file (first game is used)")
ap.add_argument("--out", default="assets/chess-game.webp")
ap.add_argument("--white", default="AlphaZero")
ap.add_argument("--white-sub", default="self-play model, White")
ap.add_argument("--black", default="Stockfish")
ap.add_argument("--black-sub", default="2200 Elo, 1 s/move, Black")
ap.add_argument("--winner", default="AlphaZero", help="name used in the checkmate caption")
ap.add_argument("--orientation", default="white", choices=("white", "black"),
                help="which side is at the bottom of the board")
ap.add_argument("--scale", type=float, default=2.0,
                help="render scale; 2.0 keeps it crisp on HiDPI screens")
ap.add_argument("--speed", type=float, default=1.0,
                help="playback speed multiplier; below 1.0 is slower")
ap.add_argument("--move-ms", type=int, default=700,
                help="milliseconds per move (uniform pacing, the default)")
ap.add_argument("--start-ms", type=int, default=1500, help="hold on the starting position")
ap.add_argument("--end-ms", type=int, default=3500, help="hold on the final position")
ap.add_argument("--adaptive", action="store_true",
                help="vary the pace per move instead of holding every move equally: "
                     "skim the opening, linger on captures, checks and the finish")
ap.add_argument("--quality", type=int, default=82, help="WebP quality, 0-100")
args = ap.parse_args()
OUT = args.out

# ---- site palette -------------------------------------------------------
BG        = (251, 250, 247)
PANEL     = (255, 255, 255)
INK       = (22, 24, 29)
MUTED     = (106, 113, 128)
RULE      = (228, 224, 215)
TEAL      = (22, 97, 90)

BOARD_COLORS = {
    "square light":          "#ece9e1",
    "square dark":           "#9fb3ad",
    "square light lastmove": "#cfe0d6",
    "square dark lastmove":  "#7fa298",
    "margin":                "#ffffff",
    "coord":                 "#6a7180",
    "inner border":          "#dcd8cf",
    "outer border":          "#ffffff",
    "arrow green":           "#16615a80",
}

S = args.scale


def px(v):
    return int(round(v * S))


BOARD_PX = px(452)
PAD_X    = px(26)
HEADER   = px(52)
FOOTER   = px(46)
W = BOARD_PX + 2 * PAD_X
H = HEADER + BOARD_PX + FOOTER

F = "/usr/share/fonts/truetype/dejavu/"
f_name   = ImageFont.truetype(F + "DejaVuSans-Bold.ttf", px(15))
f_sub    = ImageFont.truetype(F + "DejaVuSans.ttf", px(11))
f_move   = ImageFont.truetype(F + "DejaVuSansMono-Bold.ttf", px(15))
f_small  = ImageFont.truetype(F + "DejaVuSans.ttf", px(11))


ORIENTATION = chess.WHITE if args.orientation == "white" else chess.BLACK


def board_png(board, lastmove):
    check_sq = board.king(board.turn) if board.is_check() else None
    svg = chess.svg.board(
        board, lastmove=lastmove, check=check_sq, orientation=ORIENTATION,
        size=BOARD_PX, colors=BOARD_COLORS, coordinates=True, borders=False,
    )
    png = cairosvg.svg2png(bytestring=svg.encode(), output_width=BOARD_PX, output_height=BOARD_PX)
    return Image.open(io.BytesIO(png)).convert("RGB")


def frame(board, lastmove, san, movetext, status):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)

    # header
    d.text((PAD_X, px(13)), args.white, font=f_name, fill=TEAL)
    d.text((PAD_X, px(31)), args.white_sub, font=f_sub, fill=MUTED)
    right = args.black
    rw = d.textlength(right, font=f_name)
    d.text((W - PAD_X - rw, px(13)), right, font=f_name, fill=INK)
    sub = args.black_sub
    sw = d.textlength(sub, font=f_sub)
    d.text((W - PAD_X - sw, px(31)), sub, font=f_sub, fill=MUTED)
    d.line([(PAD_X, HEADER - px(8)), (W - PAD_X, HEADER - px(8))], fill=RULE, width=max(1, px(1)))

    im.paste(board_png(board, lastmove), (PAD_X, HEADER))

    # footer: move number + SAN on the left, status on the right
    fy = HEADER + BOARD_PX + px(13)
    if movetext:
        d.text((PAD_X, fy), movetext, font=f_move, fill=INK)
    if status:
        sw = d.textlength(status, font=f_small)
        d.text((W - PAD_X - sw, fy + px(3)), status, font=f_small,
               fill=TEAL if "mate" in status.lower() else MUTED)
    return im


def duration_ms(board_before, move, ply, total, is_last):
    """Milliseconds to hold the position after `move`.

    Uniform by default: every move gets the same beat, which is easier to follow
    than a pace that keeps changing under you. `--adaptive` restores the older
    behaviour, which skimmed the opening and slowed down for sharp moves.
    """
    if not args.adaptive:
        return int(args.move_ms / args.speed)

    legal = board_before.legal_moves.count()
    board_after = board_before.copy()
    capture = board_before.is_capture(move)
    board_after.push(move)
    check = board_after.is_check()

    if ply < 20:                 # opening, largely book
        d = 240
    elif ply < total - 14:       # middlegame
        d = 300
    else:                        # the finishing combination
        d = 480

    if capture:
        d += 110
    if check:
        d += 200
    if move.promotion:
        d += 280
    if legal <= 3:               # forced reply — snap through it
        d -= 80
    return int(max(180, min(950, d)) / args.speed)


def main():
    with open(args.pgn, encoding="utf-8", errors="ignore") as fh:
        game = chess.pgn.read_game(fh)
    if game is None:
        sys.exit(f"no game found in {args.pgn}")

    board = game.board()
    frames, durs = [], []

    frames.append(frame(board, None, None, "", "starting position"))
    durs.append(int(args.start_ms / args.speed))

    moves = list(game.mainline_moves())
    for i, mv in enumerate(moves):
        san = board.san(mv)
        num = board.fullmove_number
        prefix = f"{num}." if board.turn == chess.WHITE else f"{num}..."
        before = board.copy()
        board.push(mv)

        if board.is_checkmate():
            status = f"checkmate — {args.winner} wins"
        elif board.is_check():
            status = "check"
        elif before.is_capture(mv):
            status = "capture"
        else:
            status = ""

        frames.append(frame(board, mv, san, f"{prefix} {san}", status))
        durs.append(duration_ms(before, mv, i, len(moves), i == len(moves) - 1))

    # hold the final position
    frames.append(frames[-1].copy())
    durs.append(int(args.end_ms / args.speed))

    frames[0].save(
        OUT, format="WEBP", save_all=True, append_images=frames[1:],
        duration=durs, loop=0, quality=args.quality, method=6,
    )
    import os
    print(f"{len(frames)} frames, {sum(durs)/1000:.1f}s, {os.path.getsize(OUT)//1024} KB, {W}x{H}")


main()
