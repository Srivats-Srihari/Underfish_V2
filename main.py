from flask import Flask
import bot  # importing bot.py runs it automatically

app = Flask(__name__)

@app.route("/")
def index():
    return "Underfish bot is running on Render!"
