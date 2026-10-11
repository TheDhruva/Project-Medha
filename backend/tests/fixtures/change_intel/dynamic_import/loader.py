import importlib


def load_plugin():
    mod = importlib.import_module('plugin_catalog')
    return mod.run()


CACHE = {}
