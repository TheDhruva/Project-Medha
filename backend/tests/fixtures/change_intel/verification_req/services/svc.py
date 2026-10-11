import os

def run():
    return os.getenv('CONFIG', 'ok')
