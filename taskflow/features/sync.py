from __future__ import annotations

import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from taskflow.config import Config

logger = logging.getLogger(__name__)

SYNC_DIR = Path.home() / ".taskflow" / "sync"


class GitSync:
    def __init__(self, db_path: Path, repo_path: Path) -> None:
        self.db_path = db_path
        self.repo_path = repo_path

    def _run_git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=str(self.repo_path),
            capture_output=True,
            text=True,
            check=check,
        )

    def init_repo(self, repo_url: str) -> None:
        if not repo_url:
            return
        self.repo_path.mkdir(parents=True, exist_ok=True)
        if (self.repo_path / ".git").exists():
            self._run_git("remote", "set-url", "origin", repo_url, check=False)
            return
        parent = self.repo_path.parent
        parent.mkdir(parents=True, exist_ok=True)
        clone_target = self.repo_path.name
        subprocess.run(
            ["git", "clone", repo_url, clone_target],
            cwd=str(parent),
            capture_output=True,
            text=True,
            check=False,
        )
        if not (self.repo_path / ".git").exists():
            self._run_git("init")
            self._run_git("remote", "add", "origin", repo_url, check=False)

    def sync_push(self) -> bool:
        try:
            dest = self.repo_path / self.db_path.name
            dest.write_bytes(self.db_path.read_bytes())
            self._run_git("add", self.db_path.name)
            result = self._run_git("diff", "--cached", "--quiet", check=False)
            if result.returncode == 0:
                return True
            self._run_git("commit", "-m", f"taskflow sync {datetime.now().isoformat()}")
            result = self._run_git("push", "origin", "HEAD", check=False)
            return result.returncode == 0
        except subprocess.CalledProcessError:
            logger.exception("git push failed")
            return False

    def sync_pull(self) -> bool:
        try:
            result = self._run_git("pull", "origin", "HEAD", check=False)
            if result.returncode != 0:
                return False
            remote_db = self.repo_path / self.db_path.name
            if not remote_db.exists():
                return True
            if not self.db_path.exists():
                self.db_path.write_bytes(remote_db.read_bytes())
                return True
            remote_mtime = remote_db.stat().st_mtime
            local_mtime = self.db_path.stat().st_mtime
            if remote_mtime > local_mtime:
                self.db_path.write_bytes(remote_db.read_bytes())
            else:
                remote_db.write_bytes(self.db_path.read_bytes())
            return True
        except subprocess.CalledProcessError:
            logger.exception("git pull failed")
            return False


class WebDAVSync:
    def __init__(self, db_path: Path, url: str, auth: tuple[str, str] | None = None) -> None:
        self.db_path = db_path
        self.url = url.rstrip("/")
        self.auth = auth

    def sync_push(self) -> bool:
        try:
            with open(self.db_path, "rb") as f:
                resp = requests.put(f"{self.url}/{self.db_path.name}", data=f, auth=self.auth, timeout=30)
            return resp.status_code in (200, 201, 204)
        except requests.RequestException:
            logger.exception("webdav push failed")
            return False

    def sync_pull(self) -> bool:
        try:
            resp = requests.get(f"{self.url}/{self.db_path.name}", auth=self.auth, timeout=30)
            if resp.status_code != 200:
                return False
            remote_mtime = resp.headers.get("Last-Modified")
            if remote_mtime and self.db_path.exists():
                remote_dt = datetime.strptime(remote_mtime, "%a, %d %b %Y %H:%M:%S %Z").timestamp()
                local_mtime = self.db_path.stat().st_mtime
                if remote_dt <= local_mtime:
                    return True
            self.db_path.write_bytes(resp.content)
            return True
        except requests.RequestException:
            logger.exception("webdav pull failed")
            return False


class SyncManager:
    def __init__(self, db_path: Path, config: Config) -> None:
        self.db_path = db_path
        self.config = config
        self._last_sync_time: datetime | None = None
        self._sync_backend: GitSync | WebDAVSync | None = None
        self._init_backend()

    @property
    def is_configured(self) -> bool:
        return self.config.sync_method != "none" and self.config.sync_url != ""

    @property
    def validation_error(self) -> str | None:
        if self.config.sync_method == "none":
            return None
        if self.config.sync_method in ("git", "webdav") and not self.config.sync_url:
            return "同步地址未配置，请使用 config-set sync_url <地址>"
        return None

    def _init_backend(self) -> None:
        method = self.config.sync_method
        url = self.config.sync_url
        if method == "git":
            if not url:
                logger.warning("sync method is git but sync_url is empty, backend disabled")
                self._sync_backend = None
                return
            repo_path = SYNC_DIR / "git"
            self._sync_backend = GitSync(self.db_path, repo_path)
            self._sync_backend.init_repo(url)
        elif method == "webdav":
            if not url:
                logger.warning("sync method is webdav but sync_url is empty, backend disabled")
                self._sync_backend = None
                return
            self._sync_backend = WebDAVSync(self.db_path, url)

    @property
    def last_sync_time(self) -> datetime | None:
        return self._last_sync_time

    def sync_pull(self) -> bool:
        if self._sync_backend is None:
            logger.warning("no sync backend configured")
            return False
        ok = self._sync_backend.sync_pull()
        if ok:
            self._last_sync_time = datetime.now()
        return ok

    def sync_push(self) -> bool:
        if self._sync_backend is None:
            logger.warning("no sync backend configured")
            return False
        ok = self._sync_backend.sync_push()
        if ok:
            self._last_sync_time = datetime.now()
        return ok

    def sync(self) -> bool:
        if self._sync_backend is None:
            logger.warning("no sync backend configured")
            return False
        pull_ok = self._sync_backend.sync_pull()
        push_ok = self._sync_backend.sync_push()
        if pull_ok or push_ok:
            self._last_sync_time = datetime.now()
        return pull_ok and push_ok
