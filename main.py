from flask import Flask
import threading
import bot  # runs your bot when imported

app = Flask(__name__)

@app.route("/")
def home():
    return "Underfish bot is alive!"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
