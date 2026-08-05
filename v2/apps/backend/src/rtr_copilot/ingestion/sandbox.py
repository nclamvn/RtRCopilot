import ctypes
import errno
import os
import resource
import signal
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

from rtr_copilot.ingestion.errors import IngestionFailure


@dataclass(frozen=True)
class SandboxResult:
    stdout: bytes
    stderr_fingerprint: str | None


class ProcessSandbox:
    """Structured-argv, non-shell runner with bounded local resources."""

    def __init__(
        self,
        *,
        timeout_seconds: int,
        temp_bytes: int,
        allowed_tools: frozenset[str] = frozenset({
            "ffmpeg",
            "ffprobe",
            "python",
            "soffice",
            "tesseract",
        }),
        read_only_roots: tuple[Path, ...] = (Path("/opt/rtr/models"),),
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.temp_bytes = temp_bytes
        self.allowed_tools = allowed_tools
        self.read_only_roots = tuple(path.resolve() for path in read_only_roots)

    @staticmethod
    def _network_seccomp() -> None:
        class ScmpArgCmp(ctypes.Structure):
            _fields_ = [
                ("arg", ctypes.c_uint),
                ("op", ctypes.c_uint),
                ("datum_a", ctypes.c_uint64),
                ("datum_b", ctypes.c_uint64),
            ]

        try:
            library = ctypes.CDLL("libseccomp.so.2", use_errno=True)
        except OSError as exc:
            raise RuntimeError("seccomp_unavailable") from exc
        library.seccomp_init.argtypes = [ctypes.c_uint32]
        library.seccomp_init.restype = ctypes.c_void_p
        library.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
        library.seccomp_syscall_resolve_name.restype = ctypes.c_int
        library.seccomp_rule_add_array.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_int,
            ctypes.c_uint,
            ctypes.POINTER(ScmpArgCmp),
        ]
        library.seccomp_rule_add_array.restype = ctypes.c_int
        library.seccomp_load.argtypes = [ctypes.c_void_p]
        library.seccomp_load.restype = ctypes.c_int
        library.seccomp_release.argtypes = [ctypes.c_void_p]
        allow = 0x7FFF0000
        deny = 0x00050000 | errno.EPERM
        context = library.seccomp_init(allow)
        if not context:
            raise RuntimeError("seccomp_init_failed")
        try:
            # LibreOffice requires AF_UNIX sockets for local headless-process
            # IPC. Deny creation of every non-local socket domain instead of
            # disabling IPC operations such as bind/connect globally.
            comparison = (ScmpArgCmp * 1)(ScmpArgCmp(
                arg=0,
                op=1,  # SCMP_CMP_NE
                datum_a=socket.AF_UNIX,
                datum_b=0,
            ))
            for name in (b"socket", b"socketpair"):
                syscall = library.seccomp_syscall_resolve_name(name)
                if syscall >= 0 and library.seccomp_rule_add_array(
                    context,
                    deny,
                    syscall,
                    1,
                    comparison,
                ) != 0:
                    raise RuntimeError("seccomp_rule_failed")
            if library.seccomp_load(context) != 0:
                raise RuntimeError("seccomp_load_failed")
        finally:
            library.seccomp_release(context)

    @classmethod
    def _limits(cls, temp_bytes: int) -> None:
        os.setsid()
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_FSIZE, (temp_bytes, temp_bytes))
        resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
        # The same non-root UID is intentionally shared by API/worker containers.
        # Leave a bounded per-UID budget that still permits native OCR/ASR threads.
        resource.setrlimit(resource.RLIMIT_NPROC, (256, 256))
        resource.setrlimit(resource.RLIMIT_CPU, (120, 121))
        ctypes.CDLL(None).prctl(38, 1, 0, 0, 0)  # PR_SET_NO_NEW_PRIVS
        cls._network_seccomp()

    def run(self, argv: list[str], *, temp_root: Path) -> SandboxResult:
        if not argv or Path(argv[0]).name not in self.allowed_tools:
            raise IngestionFailure("tool_not_allowed", stage="sandbox")
        if any("://" in argument or "\x00" in argument for argument in argv):
            raise IngestionFailure("network_argument_forbidden", stage="sandbox")
        try:
            ctypes.CDLL("libseccomp.so.2")
        except OSError as exc:
            raise IngestionFailure("sandbox_unavailable", stage="sandbox") from exc
        root = temp_root.resolve(strict=True)
        for argument in argv[1:]:
            if argument.startswith("/"):
                resolved = Path(argument).resolve()
                if (
                    not resolved.is_relative_to(root)
                    and not any(
                        resolved.is_relative_to(read_root)
                        for read_root in self.read_only_roots
                    )
                ):
                    raise IngestionFailure("path_escape_forbidden", stage="sandbox")
        environment = {
            "HOME": str(root),
            "TMPDIR": str(root),
            "XDG_CACHE_HOME": str(root / ".cache"),
            "XDG_CONFIG_HOME": str(root / ".config"),
            "PATH": "/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "SAL_USE_VCLPLUGIN": "svp",
            "http_proxy": "",
            "https_proxy": "",
            "HTTP_PROXY": "",
            "HTTPS_PROXY": "",
            "NO_PROXY": "*",
        }
        process = subprocess.Popen(
            argv,
            cwd=root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            start_new_session=False,
            preexec_fn=lambda: self._limits(self.temp_bytes),
        )
        try:
            stdout, stderr = process.communicate(timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            raise IngestionFailure(
                "tool_timeout",
                retryable=True,
                stage="sandbox",
            ) from exc
        if process.returncode:
            raise IngestionFailure(
                f"tool_exit_{process.returncode}",
                stage="sandbox",
            )
        stderr_fingerprint = (
            __import__("hashlib").sha256(stderr[:4096]).hexdigest()
            if stderr
            else None
        )
        return SandboxResult(stdout=stdout, stderr_fingerprint=stderr_fingerprint)
