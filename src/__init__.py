from flask import Flask
from Restful import startup

def main():
    app = Flask(__name__)
    startup(app)
