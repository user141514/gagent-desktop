import sys, os, json, re, time, subprocess
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'memory'))
_r = subprocess.run
def _d(b):
    if not b: return ''
    if isinstance(b, str): return b
    try: return b.decode('utf-8')
    except: return b.decode('utf-8', errors='replace')
def _run(*a, **k):
    t = k.pop('text', 0) | k.pop('universal_newlines', 0)
    enc = k.pop('encoding', None)
    k.pop('errors', None)
    if enc: t = 1
    if t and isinstance(k.get('input'), str):
        k['input'] = k['input'].encode()
    r = _r(*a, **k)
    if t:
        if r.stdout is not None: r.stdout = _d(r.stdout)
        if r.stderr is not None: r.stderr = _d(r.stderr)
    return r
subprocess.run = _run
sys.excepthook = lambda t, v, tb: (sys.__excepthook__(t, v, tb), print(f"\n[Agent Hint]: NO GUESSING! You MUST probe first. If missing common package, pip.")) if issubclass(t, (ImportError, AttributeError)) else sys.__excepthook__(t, v, tb)

# ── Process safety: pre-import psutil if available ──
try:
    import psutil as _psutil
    _HAS_PSUTIL = True
except ImportError:
    _psutil = None
    _HAS_PSUTIL = False

def _safe_process_info(pid):
    """Return (name, status, is_zombie) for a PID without sending signals."""
    if _HAS_PSUTIL:
        try:
            p = _psutil.Process(pid)
            return p.name(), p.status(), p.status() == 'zombie'
        except Exception:
            return None, None, False
    return None, None, False

def _list_my_child_processes():
    """List child processes of the current process."""
    if _HAS_PSUTIL:
        try:
            current = _psutil.Process()
            return [(c.pid, c.name(), c.status()) for c in current.children(recursive=True)]
        except Exception:
            return []
    return []
