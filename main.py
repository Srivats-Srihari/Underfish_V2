import berserk
import chess
import time
import random
import os
import chess.engine
import re
import threading
from flask import Flask

# === CONFIGURATION ===
STOCKFISH_PATH = "./stockfish"  # our downloaded binary
token = os.environ["Lichess_token"]  # Lichess token stored as secret

# === SETUP ===
session = berserk.TokenSession(token)
client = berserk.Client(session=session)
engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)

# === ENGINE HELPERS ===
def _get_cp_and_mate_from_info(info, perspective_color):
    score = info.get("score")
    if score is None:
        return None, None

    pov_candidates = []
    try:
        pov_candidates.append(score.pov(perspective_color))
    except Exception:
        pass
    try:
        pov_candidates.append(score.white() if perspective_color == chess.WHITE else score.black())
    except Exception:
        pass
    try:
        pov_candidates.append(score.relative)
    except Exception:
        pass

    for pov in pov_candidates:
        if pov is None:
            continue
        try:
            if getattr(pov, "is_mate", lambda: False)():
                try:
                    return None, pov.mate()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            if getattr(pov, "score", None) is not None:
                cp = pov.score(mate_score=100000)
                return cp, None
        except Exception:
            pass

    try:
        s = str(score)
        mate_match = re.search(r"#\s*([+-]?\d+)", s)
        if mate_match:
            m = int(mate_match.group(1))
            return None, m
        num_match = re.search(r"([-+]?\d+)", s)
        if num_match:
            return int(num_match.group(1)), None
    except Exception:
        pass

    return None, None


def pick_worst_survivable_move(board: chess.Board,
                               engine,
                               eval_depth: int = 16,
                               max_mate_depth: int = 25,
                               cp_cap_one_move: int = 550,
                               cp_cap_total: int = -925):
    bot_color = board.turn
    legal_moves = list(board.legal_moves)
    if not legal_moves:
        return None

    if board.is_check():
        print("🛡️ In check — playing best move.")
        try:
            best_info = engine.analyse(board, chess.engine.Limit(depth=eval_depth), multipv=1)
            return best_info[0]["pv"][0]
        except Exception as e:
            print("⚠️ Engine failed in check:", e)
            return random.choice(legal_moves)

    try:
        cur_info = engine.analyse(board, chess.engine.Limit(depth=eval_depth))
        cur_cp, cur_mate = _get_cp_and_mate_from_info(cur_info, bot_color)
        if cur_cp is None:
            cur_cp = 0
    except Exception as e:
        print("⚠️ Engine error obtaining eval:", e)
        cur_cp = 0

    move_candidates = []
    mate_losses = 0
    winning_mate_move = None
    total = len(legal_moves)

    for move in legal_moves:
        temp = board.copy()
        temp.push(move)
        try:
            info = engine.analyse(temp, chess.engine.Limit(depth=max_mate_depth))
        except Exception as e:
            print(f"⚠️ Engine mate-depth failed for {move.uci()}: {e}")
            continue

        cp_after, mate_after = _get_cp_and_mate_from_info(info, bot_color)

        if mate_after is not None:
            if mate_after > 0:
                print(f"🏆 Mate found for us with {move.uci()} in {mate_after}")
                winning_mate_move = move
                continue
            else:
                mate_losses += 1
                print(f"⛔ Skipping {move.uci()} — mate in {abs(mate_after)}")
                continue

        if cp_after is None:
            print(f"⚠️ Could not obtain CP for {move.uci()} — skipping")
            continue

        drop = cur_cp - cp_after
        if drop > cp_cap_one_move:
            print(f"🚫 Skipping {move.uci()} — drop {drop} > {cp_cap_one_move}")
            continue

        move_candidates.append((cp_after, move))
        print(f"🪓 Candidate {move.uci()} → cp_after={cp_after}, drop={drop}")

    if winning_mate_move is not None:
        return winning_mate_move

    if mate_losses / total > 0.25:
        print(f"⚠️ {mate_losses}/{total} moves mate us — survival mode.")
        try:
            best_info = engine.analyse(board, chess.engine.Limit(depth=eval_depth), multipv=1)
            return best_info[0]["pv"][0]
        except Exception:
            return random.choice(legal_moves)

    try:
        pos_info = engine.analyse(board, chess.engine.Limit(depth=eval_depth))
        pos_cp, pos_mate = _get_cp_and_mate_from_info(pos_info, bot_color)
        if pos_cp is not None and pos_cp < -1250:
            print(f"🚨 Eval {pos_cp} < -1500 — survival mode.")
            best_info = engine.analyse(board, chess.engine.Limit(depth=eval_depth), multipv=1)
            return best_info[0]["pv"][0]
    except Exception:
        pass

    if move_candidates:
        worst = min(move_candidates, key=lambda x: x[0])[1]
        print(f"🤡 Worst survivable move: {worst.uci()}")
        return worst

    print("‼️ No survivable candidates — best fallback.")
    try:
        best_info = engine.analyse(board, chess.engine.Limit(depth=eval_depth), multipv=1)
        return best_info[0]["pv"][0]
    except Exception:
        return random.choice(legal_moves)


# === GAME HANDLER ===
def handle_game(game_id, my_color):
    print(f"[{game_id}] Game handler started.")
    board = chess.Board()
    time.sleep(1)
    game_stream = client.bots.stream_game_state(game_id)

    for event in game_stream:
        print(f"[{game_id}] Event: {event}")

        if event['type'] in ['gameFull', 'gameState']:
            state = event.get('state', event)
            moves = state.get('moves', '')
            print(f"[{game_id}] Moves: {moves}")
            board = chess.Board()
            for move in moves.split():
                board.push_uci(move)

            if board.turn == my_color and not board.is_game_over():
                print(f"[{game_id}] Thinking...")
                move = pick_worst_survivable_move(board.copy(), engine)
                if move:
                    print(f"[{game_id}] Playing: {move.uci()}")
                    try:
                        client.bots.make_move(game_id, move.uci())
                    except Exception as e:
                        print(f"[{game_id}] Move failed: {e}")
                else:
                    print(f"[{game_id}] No safe move.")
            else:
                print(f"[{game_id}] Not my turn or game over.")


# === MAIN LOOP ===
def main():
    print("WorstBot is online.")
    for event in client.bots.stream_incoming_events():
        print(f"Event: {event}")

        if event['type'] == 'challenge':
            print("Challenge received.")
            if event['challenge']['variant']['key'] == 'standard':
                client.bots.accept_challenge(event['challenge']['id'])
                print(f"Accepted challenge: {event['challenge']['id']}")
            else:
                print("Declined non-standard challenge.")
                client.bots.decline_challenge(event['challenge']['id'])

        elif event['type'] == 'gameStart':
            game_id = event['game']['id']
            my_color_str = event['game']['color']
            my_color = chess.WHITE if my_color_str == 'white' else chess.BLACK
            print(f"Game started! ID: {game_id}, Color: {my_color_str.upper()}")
            threading.Thread(target=handle_game, args=(game_id, my_color), daemon=True).start()


# === FLASK KEEP-ALIVE SERVER ===
app = Flask(__name__)

@app.route("/")
def home():
    return "✅ WorstBot is running on Render!"

if __name__ == "__main__":
    threading.Thread(target=main, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
