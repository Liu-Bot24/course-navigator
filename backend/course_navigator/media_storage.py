"""Prepare owned video files without exposing or overwriting another instance."""

from contextlib import contextmanager
from pathlib import Path
import shutil
from uuid import uuid4

from . import artifacts
from .models import CourseItem


@contextmanager
def prepared_video(workspace: Path, item: CourseItem, source, extension: str):
    directory = workspace / "downloads" / item.instance_id / uuid4().hex
    path = directory / f"{item.id}{extension}"
    with artifacts.lease(directory):
        try:
            directory.mkdir(parents=True, exist_ok=False)
            if isinstance(source, Path):
                shutil.copy2(source, path)
            else:
                with path.open("wb") as output:
                    shutil.copyfileobj(source, output)
            # The caller commits its record before exiting this scope. Any
            # failed/stale commit cleans only this operation's directory.
            yield path
        except BaseException:
            artifacts.remove_tree(directory)
            raise
