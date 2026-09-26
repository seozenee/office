"""Plugin architecture. Each integration is an independent plugin exposing risk-labelled actions,
which are registered into the tool registry (so the approval gate always applies).
Credentials come only from environment variables."""
from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.models import RiskLevel


@dataclass
class PluginAction:
    name: str
    description: str
    risk: RiskLevel
    fn: Callable[..., Any]


@dataclass
class Plugin:
    key: str
    name: str
    description: str
    env: list[str]
    actions: list[PluginAction] = field(default_factory=list)

    @property
    def configured(self) -> bool:
        return all(os.environ.get(e) for e in self.env)

    def info(self) -> dict[str, Any]:
        return {"key": self.key, "name": self.name, "description": self.description, "configured": self.configured,
                "env": self.env, "actions": [{"name": a.name, "description": a.description, "risk": a.risk.value} for a in self.actions]}


class PluginNotConfigured(RuntimeError):
    pass


def _env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise PluginNotConfigured(f"환경변수 {name} 가 설정되지 않았습니다")
    return v


def _http() -> httpx.Client:
    return httpx.Client(timeout=20)


# --- Slack ---------------------------------------------------------------------------------
def slack_post(text: str, channel: str | None = None) -> dict:
    with _http() as c:
        r = c.post("https://slack.com/api/chat.postMessage", headers={"Authorization": f"Bearer {_env('SLACK_BOT_TOKEN')}"},
                   json={"channel": channel or _env("SLACK_DEFAULT_CHANNEL"), "text": text})
        r.raise_for_status()
        return r.json()


# --- Discord -------------------------------------------------------------------------------
def discord_post(text: str) -> dict:
    with _http() as c:
        r = c.post(_env("DISCORD_WEBHOOK_URL"), json={"content": text[:1900]})
        r.raise_for_status()
        return {"status": r.status_code}


# --- GitHub --------------------------------------------------------------------------------
def _gh_headers() -> dict:
    return {"Authorization": f"Bearer {_env('GITHUB_TOKEN')}", "Accept": "application/vnd.github+json"}


def github_list_issues(repo: str, state: str = "open") -> list[dict]:
    with _http() as c:
        r = c.get(f"https://api.github.com/repos/{repo}/issues", params={"state": state, "per_page": 30}, headers=_gh_headers())
        r.raise_for_status()
        return [{"number": i["number"], "title": i["title"], "url": i["html_url"]} for i in r.json()]


def github_create_issue(repo: str, title: str, body: str = "") -> dict:
    with _http() as c:
        r = c.post(f"https://api.github.com/repos/{repo}/issues", json={"title": title, "body": body}, headers=_gh_headers())
        r.raise_for_status()
        return {"number": r.json()["number"], "url": r.json()["html_url"]}


# --- Notion --------------------------------------------------------------------------------
def notion_search(query: str) -> list[dict]:
    with _http() as c:
        r = c.post("https://api.notion.com/v1/search", json={"query": query, "page_size": 10},
                   headers={"Authorization": f"Bearer {_env('NOTION_TOKEN')}", "Notion-Version": "2022-06-28"})
        r.raise_for_status()
        return [{"id": x["id"], "url": x.get("url"), "object": x["object"]} for x in r.json().get("results", [])]


# --- Google (Gmail / Calendar / Drive / Sheets) using an OAuth access token -----------------
def _g() -> dict:
    return {"Authorization": f"Bearer {_env('GOOGLE_ACCESS_TOKEN')}"}


def gmail_list(query: str = "is:unread newer_than:2d", limit: int = 10) -> list[dict]:
    with _http() as c:
        r = c.get("https://gmail.googleapis.com/gmail/v1/users/me/messages", params={"q": query, "maxResults": limit}, headers=_g())
        r.raise_for_status()
        out = []
        for m in r.json().get("messages", []):
            d = c.get(f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{m['id']}", params={"format": "metadata",
                      "metadataHeaders": ["Subject", "From", "Date"]}, headers=_g()).json()
            hdr = {h["name"]: h["value"] for h in d.get("payload", {}).get("headers", [])}
            out.append({"id": m["id"], "subject": hdr.get("Subject"), "from": hdr.get("From"), "date": hdr.get("Date"), "snippet": d.get("snippet")})
        return out


def gmail_send(to: str, subject: str, body: str) -> dict:
    import base64
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["To"], msg["Subject"] = to, subject
    msg.set_content(body)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    with _http() as c:
        r = c.post("https://gmail.googleapis.com/gmail/v1/users/me/messages/send", json={"raw": raw}, headers=_g())
        r.raise_for_status()
        return {"id": r.json().get("id")}


def calendar_list(days: int = 7) -> list[dict]:
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    with _http() as c:
        r = c.get("https://www.googleapis.com/calendar/v3/calendars/primary/events", headers=_g(),
                  params={"timeMin": now.isoformat(), "timeMax": (now + timedelta(days=days)).isoformat(), "singleEvents": True, "orderBy": "startTime"})
        r.raise_for_status()
        return [{"summary": e.get("summary"), "start": e.get("start"), "end": e.get("end")} for e in r.json().get("items", [])]


def calendar_create(summary: str, start_iso: str, end_iso: str) -> dict:
    with _http() as c:
        r = c.post("https://www.googleapis.com/calendar/v3/calendars/primary/events", headers=_g(),
                   json={"summary": summary, "start": {"dateTime": start_iso}, "end": {"dateTime": end_iso}})
        r.raise_for_status()
        return {"id": r.json().get("id"), "link": r.json().get("htmlLink")}


def drive_list(query: str = "") -> list[dict]:
    with _http() as c:
        r = c.get("https://www.googleapis.com/drive/v3/files", headers=_g(),
                  params={"q": f"name contains '{query}'" if query else None, "pageSize": 20, "fields": "files(id,name,mimeType,modifiedTime)"})
        r.raise_for_status()
        return r.json().get("files", [])


def sheets_read(spreadsheet_id: str, range_: str) -> list[list[str]]:
    with _http() as c:
        r = c.get(f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{range_}", headers=_g())
        r.raise_for_status()
        return r.json().get("values", [])


def dropbox_list(path: str = "") -> list[dict]:
    with _http() as c:
        r = c.post("https://api.dropboxapi.com/2/files/list_folder", json={"path": path},
                   headers={"Authorization": f"Bearer {_env('DROPBOX_TOKEN')}"})
        r.raise_for_status()
        return [{"name": e["name"], "type": e[".tag"]} for e in r.json().get("entries", [])]


PLUGINS: list[Plugin] = [
    Plugin("slack", "Slack", "채널 메시지 게시", ["SLACK_BOT_TOKEN", "SLACK_DEFAULT_CHANNEL"],
           [PluginAction("slack.post_message", "Slack 메시지 게시", RiskLevel.HIGH, slack_post)]),
    Plugin("discord", "Discord", "웹훅으로 메시지 게시", ["DISCORD_WEBHOOK_URL"],
           [PluginAction("discord.post_message", "Discord 메시지 게시", RiskLevel.HIGH, discord_post)]),
    Plugin("github", "GitHub", "이슈 조회/생성", ["GITHUB_TOKEN"],
           [PluginAction("github.list_issues", "GitHub 이슈 조회", RiskLevel.LOW, github_list_issues),
            PluginAction("github.create_issue", "GitHub 이슈 생성", RiskLevel.HIGH, github_create_issue)]),
    Plugin("notion", "Notion", "페이지 검색", ["NOTION_TOKEN"],
           [PluginAction("notion.search", "Notion 검색", RiskLevel.LOW, notion_search)]),
    Plugin("gmail", "Gmail", "메일 조회/발송", ["GOOGLE_ACCESS_TOKEN"],
           [PluginAction("gmail.list", "중요 메일 조회", RiskLevel.LOW, gmail_list),
            PluginAction("gmail.send", "외부 이메일 발송", RiskLevel.HIGH, gmail_send)]),
    Plugin("calendar", "Google Calendar", "일정 조회/생성", ["GOOGLE_ACCESS_TOKEN"],
           [PluginAction("calendar.list", "일정 조회", RiskLevel.LOW, calendar_list),
            PluginAction("calendar.create", "일정 생성", RiskLevel.MEDIUM, calendar_create)]),
    Plugin("drive", "Google Drive", "파일 목록", ["GOOGLE_ACCESS_TOKEN"],
           [PluginAction("drive.list", "Drive 파일 조회", RiskLevel.LOW, drive_list)]),
    Plugin("sheets", "Google Sheets", "시트 읽기", ["GOOGLE_ACCESS_TOKEN"],
           [PluginAction("sheets.read", "Sheets 읽기", RiskLevel.LOW, sheets_read)]),
    Plugin("dropbox", "Dropbox", "폴더 조회", ["DROPBOX_TOKEN"],
           [PluginAction("dropbox.list", "Dropbox 폴더 조회", RiskLevel.LOW, dropbox_list)]),
]


def get_plugin(key: str) -> Plugin:
    for p in PLUGINS:
        if p.key == key:
            return p
    raise KeyError(key)
