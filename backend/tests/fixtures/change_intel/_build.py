"""Build git fixture repositories for Change Intelligence (Phase 2) tests.

Run once (re-run rebuilds): creates 10 small git repositories under
fixtures/change_intel, each with two commits tagged `base` and `target`.
Each case targets one DoD requirement.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent
GIT_AUTHOR = ["-c", "user.name=MedhaFixture", "-c", "user.email=fixture@medha.local"]


def run(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *GIT_AUTHOR, *args], cwd=str(cwd), check=True, capture_output=True, text=True
    )


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def commit(cwd: Path, message: str, tag: str | None = None) -> None:
    run(cwd, "add", "-A")
    run(cwd, "commit", "-q", "-m", message)
    if tag:
        run(cwd, "tag", tag)


def make_repo(name: str) -> Path:
    root = FIXTURES / name
    for attempt in range(3):
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)
        try:
            root.mkdir(parents=True)
            break
        except FileExistsError:
            time.sleep(0.3)
    run(root, "init", "-q", "-b", "main")
    return root


def fixture_1_simple_import() -> None:
    repo = make_repo("simple_import")
    write(repo / "app.py", "def main():\n    print('hello')\n\nmain()\n")
    commit(repo, "base", "base")
    write(repo / "mod.py", "def greet(name):\n    return f'hi {name}'\n")
    write(repo / "app.py", "from mod import greet\n\n\ndef main():\n    print(greet('world'))\n\nmain()\n")
    commit(repo, "target uses mod", "target")


def fixture_2_multi_level() -> None:
    repo = make_repo("multi_level")
    write(repo / "a.py", "import b\n\ndef run_a():\n    return b.run_b()\n")
    write(repo / "b.py", "import c\n\ndef run_b():\n    return c.run_c()\n")
    write(repo / "c.py", "def run_c():\n    return 1\n")
    commit(repo, "base", "base")
    write(repo / "c.py", "def run_c():\n    return 2\n\ndef extra():\n    return 3\n")
    commit(repo, "target changes c", "target")


def fixture_3_unrelated_file() -> None:
    repo = make_repo("unrelated_file")
    write(repo / "app.py", "def main():\n    print('ok')\n")
    write(repo / "README.md", "# Demo app\n")
    commit(repo, "base", "base")
    write(repo / "README.md", "# Demo app\n\nUpdated docs.\n")
    write(repo / "note.py", "NOTE = 'isolated'\n")
    commit(repo, "target docs + isolated file", "target")


def fixture_4_deleted_symbol() -> None:
    repo = make_repo("deleted_symbol")
    write(repo / "mod.py", "def helper(value):\n    return value * 2\n\ndef keep():\n    return 'keep'\n")
    write(repo / "use.py", "from mod import helper\n\nprint(helper(3))\n")
    commit(repo, "base", "base")
    write(repo / "mod.py", "def keep():\n    return 'keep'\n")
    write(repo / "use.py", "# NOTE: still imports helper (removed)\nfrom mod import helper\n\nprint(helper(3))\n")
    commit(repo, "target removes helper", "target")


def fixture_5_added_file() -> None:
    repo = make_repo("added_file")
    write(repo / "app.py", "def main():\n    print('ok')\n")
    commit(repo, "base", "base")
    write(repo / "new_module.py", "def compute(x):\n    return x + 1\n")
    commit(repo, "target adds new_module", "target")


def fixture_6_rename() -> None:
    repo = make_repo("rename")
    write(repo / "auth.py", "class Auth:\n    def login(self):\n        return True\n")
    write(repo / "app.py", "from auth import Auth\n\ndef main():\n    return Auth().login()\n")
    commit(repo, "base", "base")
    write(repo / "authentication.py", "class Auth:\n    def login(self):\n        return True\n")
    write(repo / "app.py", "from authentication import Auth\n\ndef main():\n    return Auth().login()\n")
    (repo / "auth.py").unlink()
    commit(repo, "target renames auth to authentication", "target")


def fixture_7_cycle() -> None:
    repo = make_repo("cycle")
    write(repo / "a.py", "import b\n\ndef fn_a():\n    return b.fn_b()\n")
    write(repo / "b.py", "import a\n\ndef fn_b():\n    return a.fn_a()\n")
    commit(repo, "base", "base")
    write(repo / "a.py", "import b\n\ndef fn_a():\n    return b.fn_b() + 1\n\ndef newer():\n    return 'x'\n")
    commit(repo, "target modifies a", "target")


def fixture_8_dynamic_import() -> None:
    repo = make_repo("dynamic_import")
    write(repo / "loader.py", "import importlib\n\n\ndef load_plugin():\n    mod = importlib.import_module('plugin_catalog')\n    return mod.run()\n")
    write(repo / "app.py", "def main():\n    print('ok')\n")
    commit(repo, "base", "base")
    write(repo / "loader.py", "import importlib\n\n\ndef load_plugin():\n    mod = importlib.import_module('plugin_catalog')\n    return mod.run()\n\n\nCACHE = {}\n")
    commit(repo, "target adds cache", "target")


def fixture_9_api_consumer() -> None:
    repo = make_repo("api_consumer")
    write(repo / "api/routes.py", "def handler():\n    return 'v1'\n")
    write(repo / "clients/web_client.py", "from api.routes import handler\n\ndef fetch():\n    return handler()\n")
    commit(repo, "base", "base")
    write(repo / "api/routes.py", "def handler():\n    return 'v1'\n\ndef new_handler():\n    return 'v2'\n")
    commit(repo, "target adds endpoint", "target")


def fixture_10_verification_req() -> None:
    repo = make_repo("verification_req")
    write(repo / "services/svc.py", "def run():\n    return 'ok'\n")
    write(repo / "config.yaml", "service: svc\nport: 8080\n")
    commit(repo, "base", "base")
    write(repo / "services/svc.py", "import os\n\ndef run():\n    return os.getenv('CONFIG', 'ok')\n")
    write(repo / "config.yaml", "service: svc\nport: 9090\nmode: strict\n")
    commit(repo, "target changes svc and config", "target")


def fixture_11_delete_import_chain() -> None:
    repo = make_repo("delete_import_chain")
    write(repo / "helpers/residual.py", "def compute():\n    return 42\n")
    write(repo / "main.py", "from helpers.residual import compute\n\n\ndef run():\n    return compute()\n")
    commit(repo, "base", "base")
    (repo / "helpers/residual.py").unlink()
    commit(repo, "target deletes residual module", "target")


def main() -> None:
    functions = [
        fixture_1_simple_import,
        fixture_2_multi_level,
        fixture_3_unrelated_file,
        fixture_4_deleted_symbol,
        fixture_5_added_file,
        fixture_6_rename,
        fixture_7_cycle,
        fixture_8_dynamic_import,
        fixture_9_api_consumer,
        fixture_10_verification_req,
        fixture_11_delete_import_chain,
    ]
    for fn in functions:
        fn()
        print(f"built {fn.__name__.split('_', 2)[1]}")


if __name__ == "__main__":
    main()