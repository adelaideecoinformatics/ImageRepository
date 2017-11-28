from flask import Flask
from Restful import createapp

def main():
    app = createapp()
    app.run()
