"""Coding agent: write → test → inspect → fix → retest, inside a sandboxed workspace folder."""
from __future__ import annotations

import subprocess
import sys
from collections import Counter
from pathlib import Path

from app.agents.base import Agent
from app.core.files import project_root, safe_resolve

MAX_ITERATIONS = 3


def analyze_project(path: str | Path) -> dict:
    """Deterministic project structure analysis (languages, LOC, tests, config files)."""
    root = safe_resolve(path)
    langs: Counter[str] = Counter()
    loc = 0
    tests = 0
    files = 0
    for p in root.rglob("*"):
        if p.is_file() and ".git" not in p.parts and "node_modules" not in p.parts:
            files += 1
            langs[p.suffix or p.name] += 1
            if p.suffix in (".py", ".ts", ".tsx", ".js", ".go", ".rs", ".java"):
                try:
                    loc += sum(1 for _ in p.open(encoding="utf-8", errors="ignore"))
                except OSError:
                    pass
                if "test" in p.name.lower():
                    tests += 1
    return {"files": files, "loc": loc, "test_files": tests, "extensions": langs.most_common(12),
            "has_readme": any(root.glob("README*")), "configs": [p.name for p in root.iterdir() if p.name in
                                                                   ("pyproject.toml", "package.json", "requirements.txt", "Dockerfile", "go.mod")]}


def run_pytest(workdir: Path, timeout: int = 120) -> tuple[bool, str]:
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider"], cwd=workdir,
                          capture_output=True, text=True, timeout=timeout)
    return proc.returncode == 0, (proc.stdout + proc.stderr)[-6000:]


class CodingAgent(Agent):
    agent_type = "coding"

    def build(self, spec: str, project_slug: str | None) -> dict:
        if not self.has_llm:
            raise RuntimeError("코드 생성에는 LLM이 필요합니다 (ANTHROPIC_API_KEY 설정). 프로젝트 분석(analyze_project)은 오프라인에서도 동작합니다.")
        workdir = project_root(project_slug) / "data" / f"code_task_{self.task_id or 'adhoc'}"
        workdir.mkdir(parents=True, exist_ok=True)
        history: list[dict] = []
        feedback = ""
        for it in range(1, MAX_ITERATIONS + 1):
            self.work(f"코드 작성/수정 {it}회차")
            prev = f"PREVIOUS TEST OUTPUT (fix the failures):\n{feedback}" if feedback else ""
            data = self.llm_json("code", f"""Write a small Python module with pytest tests for this spec.
SPEC: {spec}
{prev}
Return JSON {{"files": {{"relative/path.py": "content"}}, "notes": "..."}}. Include test files named test_*.py. No network access.""")
            if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
                history.append({"iteration": it, "error": "invalid LLM output"})
                continue
            for rel, content in data["files"].items():
                target = (workdir / rel).resolve()
                if workdir.resolve() not in target.parents:
                    continue  # refuse path traversal
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(str(content), encoding="utf-8")
            ok, out = run_pytest(workdir)
            history.append({"iteration": it, "passed": ok, "output": out[-1500:]})
            self.say(f"🧪 테스트 {it}회차: {'통과' if ok else '실패 → 수정'}")
            if ok:
                return {"workdir": str(workdir), "passed": True, "iterations": history}
            feedback = out
        return {"workdir": str(workdir), "passed": False, "iterations": history}
