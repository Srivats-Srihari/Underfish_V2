from flask import Flask
import threading
import bot  # this will run your lichess bot

app = Flask(__name__)

@app.route('/')
def index():
    return "Underfish is alive and trolling on Lichess!"

def run_bot():
    bot.start_bot()  # call the function in bot.py

if __name__ == "__main__":
    # Start lichess bot in background thread
    t = threading.Thread(target=run_bot, daemon=True)
    t.start()

    # Run Flask so Render sees port 5000
    app.run(host="0.0.0.0", port=5000)
