"""Start a disposable test Postgres: uv run -m e2e.local."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory

from pgserver.postgres_server import get_server

from backend import manage


def main() -> None:
    """Print the temporary test connection and remove its data on exit."""
    with TemporaryDirectory(prefix="undercover-tests-") as directory:
        server = get_server(Path(directory) / "postgres", cleanup_mode="stop")
        try:
            os.environ["TEST_DATABASE_URL"] = server.get_uri()
            manage.initialize_test()
            print("Set this line in .env, then run npm run check in another terminal:")
            print(f"TEST_DATABASE_URL={server.get_uri()}")
            input("Press Enter to stop and remove this test database. ")
        finally:
            server.cleanup()


if __name__ == "__main__":
    main()
