"""Legacy state migration participates in the same lock as state updates."""
import builtins
import json
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextlib import contextmanager

import pytest
from kroger_api.utils.locking import file_lock

from kroger_mcp.tools import shared


@pytest.mark.parametrize("filename, data", [
    ("kroger_preferences.json", {"preferred_location_id": "01400513"}),
    ("kroger_cart.json", {"current_cart": []}),
    ("kroger_order_history.json", []),
])
def test_legacy_state_is_migrated_once(isolated, filename, data):
    with open(filename, "w") as legacy:
        json.dump(data, legacy)
    assert shared.load_state_file(filename, type(data)()) == data

    # A stale file in the working directory must not replace current state.
    current = type(data)()
    shared.save_state_file(filename, current)
    assert shared.load_state_file(filename, type(data)()) == current
    assert json.loads((isolated / filename).read_text()) == current


def test_legacy_migration_waits_for_the_state_file_lock(isolated, monkeypatch):
    filename = shared.PREFERENCES_FILE
    with open(filename, "w") as legacy:
        json.dump({"preferred_location_id": "01400513"}, legacy)
    resolved = threading.Event()
    get_path = shared.get_token_file_path

    def resolve(name):
        path = get_path(name)
        resolved.set()
        return path

    monkeypatch.setattr(shared, "get_token_file_path", resolve)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with file_lock(str(isolated / filename)):
            migration = pool.submit(shared.resolve_data_file, filename)
            assert resolved.wait(timeout=5)
            with pytest.raises(TimeoutError):
                migration.result(timeout=0.2)
            assert not (isolated / filename).exists()
            # The lock holder saves newer state before migration can run.
            current = {"preferred_location_id": "01400514"}
            (isolated / filename).write_text(json.dumps(current))
        assert migration.result(timeout=5) == str(isolated / filename)
        assert json.loads((isolated / filename).read_text()) == current


def test_reader_waits_for_an_in_progress_legacy_migration(isolated, monkeypatch):
    filename = shared.PREFERENCES_FILE
    data = {"preferred_location_id": "01400513"}
    with open(filename, "w") as legacy:
        json.dump(data, legacy)
    copying = threading.Event()
    finish_copy = threading.Event()

    class PausedSource:
        def __init__(self, source):
            self.source = source

        def read(self):
            # The destination is open but has not received the legacy JSON yet.
            copying.set()
            assert finish_copy.wait(timeout=5)
            return self.source.read()

    @contextmanager
    def paused_open(name, mode="r", *args, **kwargs):
        with builtins.open(name, mode, *args, **kwargs) as stream:
            yield PausedSource(stream) if name == filename and mode == "r" else stream

    monkeypatch.setattr(shared, "open", paused_open, raising=False)
    with ThreadPoolExecutor(max_workers=2) as pool:
        migration = pool.submit(shared.resolve_data_file, filename)
        try:
            assert copying.wait(timeout=5)
            reader = pool.submit(shared.load_state_file, filename, {})
            with pytest.raises(TimeoutError):
                reader.result(timeout=0.2)
        finally:
            finish_copy.set()
        migration.result(timeout=5)
        assert reader.result(timeout=5) == data
