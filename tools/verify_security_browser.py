"""Check real login and mobile navigation on a disposable database and web port."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
from customer_clone import customer_clone
from iris2 import services
from iris2.app import create_app
from iris2.server import proxy_options
from waitress.server import create_server


def main():
    output = Path('reports/security-review-20261126/browser').resolve()
    output.mkdir(parents=True, exist_ok=True)
    with customer_clone():
        password = secrets.token_urlsafe(24)
        username = 'security-browser@example.test'
        services.save_user(dict(username=username, display_name='Security browser',
            password=password, password_confirm=password, is_admin='on', is_active='on'))
        app = create_app(dict(TESTING=True, AUTH_DISABLED=False, CSRF_ENABLED=True))
        server = create_server(app, host='127.0.0.1', port=0, threads=4,
            asyncore_loop_timeout=0.05, expose_tracebacks=False, **proxy_options(None))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        node = Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs/Microsoft VS Code/Code.exe'
        try:
            settings = dict(base='http://127.0.0.1:' + str(server.effective_port),
                username=username, password=password, out=str(output))
            # Test credentials travel only via stdin; never save settings to a report.
            result = subprocess.run([str(node) if node.is_file() else 'node', 'tools/verify_security_browser.mjs'],
                input=json.dumps(settings), text=True, encoding='utf-8', capture_output=True,
                env=dict(os.environ, ELECTRON_RUN_AS_NODE='1'), timeout=240)
            (output / 'stdout.txt').write_text(result.stdout, encoding='utf-8')
            (output / 'stderr.txt').write_text(result.stderr, encoding='utf-8')
            if result.returncode:
                raise RuntimeError('Security browser check failed; inspect private reports.')
            print(result.stdout.strip(), flush=True)
        finally:
            server.close()
            server.task_dispatcher.shutdown()
            thread.join(5)
            if thread.is_alive():
                raise RuntimeError('Temporary security server did not stop.')
    print('Temporary server, database and database account removed; production not started.', flush=True)


if __name__ == '__main__':
    main()
