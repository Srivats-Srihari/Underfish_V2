import berserk
import chess
import time
import random
import os
import chess.engine
import chess
import chess.engine

import random
import re
import chess


# === CONFIGURATION ===
STOCKFISH_PATH = "./stockfish"  # our downloaded binary

token = os.environ["Lichess_token"]  # Lichess token stored as secret

# === SETUP ===
session = berserk.TokenSession(token)
client = berserk.Client(session=session)
engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)


# === ENGINE HELPERS ===

def _get_cp_and_mate_from_info(info, perspective_color):
"""
Robustly extract (cp, mate) from an engine info dict for the given perspective_color.
Returns (cp, mate) where cp is an int or None, mate is int (positive => perspective mates,
negative => perspective gets mated) or None.
"""
score = info.get("score")
if score is None:
    return None, None

# Try to get a POV score for the requested color
pov_candidates = []

# 1) preferred: Score.pov(color) if available
try:
    pov_candidates.append(score.pov(perspective_color))
except Exception:
    pass

# 2) Score.white() / Score.black()
try:
    pov_candidates.append(score.white() if perspective_color == chess.WHITE else score.black())
except Exception:
    pass

# 3) Score.relative (best-effort fallback)
try:
    pov_candidates.append(score.relative)
except Exception:
    pass

# Try each candidate for mate() or score()
for pov in pov_candidates:
    if pov is None:
        continue
    # mate check
    try:
        if getattr(pov, "is_mate", lambda: False)():
            # some wrappers support .mate()
            try:
                return None, pov.mate()
            except Exception:
                # ignore and try other access patterns
                pass
    except Exception:
        pass

    # cp check
    try:
        if getattr(pov, "score", None) is not None:
            cp = pov.score(mate_score=100000)
            return cp, None
    except Exception:
        pass

# Final fallback: parse string form (very last resort)
try:
    s = str(score)
    # look for "#3" style mate or numeric cp
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
                           eval_depth: int = 10,
                           max_mate_depth: int = 25,
                           cp_cap_one_move: int = 550,
                           cp_cap_total: int = -925):
"""
Return the worst legal move (from the bot's perspective) subject to survivability constraints:
  - never play a move that allows a forced mate against us,
  - do not accept a one-move drop larger than cp_cap_one_move,
  - do not let total eval drop below cp_cap_total (both values are from the bot's perspective).
Emergency rules:
  - If in check -> play engine best move (survive).
  - If we can mate opponent -> play that mate.
  - If >25% of moves allow forced mate against us -> play engine best move.
  - If position eval already < -1500 -> play engine best move.
Returns a chess.Move.
"""
bot_color = board.turn
legal_moves = list(board.legal_moves)
if not legal_moves:
    return None

# Emergency: if in check, play best move to survive
if board.is_check():
    print("🛡️ In check — playing best move.")
    try:
        best_info = engine.analyse(board, chess.engine.Limit(depth=eval_depth), multipv=1)
        return best_info[0]["pv"][0]
    except Exception as e:
        print("⚠️ Engine failed to return best move in check:", e)
        return random.choice(legal_moves)

# Get current evaluation from bot's perspective
try:
    cur_info = engine.analyse(board, chess.engine.Limit(depth=eval_depth))
    cur_cp, cur_mate = _get_cp_and_mate_from_info(cur_info, bot_color)
    if cur_cp is None:
        # fallback default
        cur_cp = 0
except Exception as e:
    print("⚠️ Engine error obtaining current eval:", e)
    cur_cp = 0

move_candidates = []
mate_losses = 0
winning_mate_move = None
total = len(legal_moves)

for move in legal_moves:
    temp = board.copy()
    temp.push(move)

    try:
        # Use a mate-aware depth first (so mate lines are discovered reliably)
        info = engine.analyse(temp, chess.engine.Limit(depth=max_mate_depth))
    except Exception as e:
        print(f"⚠️ Engine mate-depth failed for {move.uci()}: {e}")
        # As a safe fallback, skip move if we can't analyze it reliably
        continue

    # Extract cp and mate from engine info from the bot's perspective
    cp_after, mate_after = _get_cp_and_mate_from_info(info, bot_color)

    # If engine says mate (positive => perspective_color mates, negative => perspective gets mated)
    if mate_after is not None:
        if mate_after > 0:
            # this move lets *us* mate the opponent — instant winner, take it
            print(f"🏆 Mate found for us with {move.uci()} in {mate_after}")
            winning_mate_move = move
            # no need to continue checking this move further
            continue
        else:
            # move leads to forced mate against us; mark and skip
            mate_losses += 1
            print(f"⛔ Skipping {move.uci()} — leads to mate in {abs(mate_after)}")
            continue

    # If we couldn't get a cp (weird), skip this move (conservative)
    if cp_after is None:
        print(f"⚠️ Could not obtain CP for {move.uci()} — skipping")
        continue

    # Now cp_after is evaluation from BOT's perspective (positive = good)
    # Compute one-move drop: how much worse we become after playing this move
    drop = cur_cp - cp_after

    # Cap checks
    if drop > cp_cap_one_move:
        print(f"🚫 Skipping {move.uci()} — one-move drop {drop} cp > {cp_cap_one_move}")
        continue
    

    # Candidate accepted
    move_candidates.append((cp_after, move))
    print(f"🪓 Candidate {move.uci()} → cp_after={cp_after}, drop={drop}")

# If we have a direct mate for us, play it
if winning_mate_move is not None:
    return winning_mate_move

# If >25% of legal moves lead to mate against us → play best move to survive
if mate_losses / total > 0.25:
    print(f"⚠️ {mate_losses}/{total} moves lead to mate (>25%) — play best move.")
    try:
        best_info = engine.analyse(board, chess.engine.Limit(depth=eval_depth), multipv=1)
        return best_info[0]["pv"][0]
    except Exception as e:
        print("⚠️ Engine failed to give best move, falling back to candidate/worst:", e)

# If current position already very bad, prefer best move to survive
try:
    pos_info = engine.analyse(board, chess.engine.Limit(depth=eval_depth))
    pos_cp, pos_mate = _get_cp_and_mate_from_info(pos_info, bot_color)
    if pos_cp is not None and pos_cp < -1250:
        print(f"🚨 Current pos eval {pos_cp} < -1500 — survival mode: play best move.")
        best_info = engine.analyse(board, chess.engine.Limit(depth=eval_depth), multipv=1)
        return best_info[0]["pv"][0]
except Exception:
    pass

# If we have valid candidates, pick the worst (lowest cp_after) — i.e. biggest loss for us
if move_candidates:
    worst = min(move_candidates, key=lambda x: x[0])[1]
    print(f"🤡 Picking worst survivable move: {worst.uci()}")
    return worst

# Nothing survivable found — fall back to best move (safer) or any legal move
print("‼️ No survivable candidates — falling back to best/legal move.")
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
    print(f"[{game_id}] Event in game stream: {event}")

    if event['type'] in ['gameFull', 'gameState']:
        state = event.get('state', event)
        moves = state.get('moves', '')
        print(f"[{game_id}] Moves so far: {moves}")
        board = chess.Board()
        for move in moves.split():
            board.push_uci(move)

        if board.turn == my_color and not board.is_game_over():
            print(f"[{game_id}] Thinking...")
            move = pick_worst_survivable_move(board.copy(), engine)
            if move:
                print(f"[{game_id}] Playing move: {move.uci()}")
                try:
                    client.bots.make_move(game_id, move.uci())
                except Exception as e:
                    print(f"[{game_id}] Failed to make move: {e}")
            else:
                print(f"[{game_id}] No safe move found!")
        else:
            print(f"[{game_id}] Not my turn or game is over.")

# === MAIN LOOP ===
def main():
print("WorstBot is online.")
for event in client.bots.stream_incoming_events():
    print(f"Event received: {event}")

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
        print(f"Game started! Game ID: {game_id}, I am playing as {my_color_str.upper()}")
        threading.Thread(target=handle_game, args=(game_id, my_color), daemon=True).start()


