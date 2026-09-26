"use client";

import { useState } from "react";
import { api, setToken } from "@/lib/api";

export default function Login() {
  const [username, setU] = useState("ceo");
  const [password, setP] = useState("");
  const [err, setErr] = useState("");
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    try {
      const r = await api<{ token: string }>("/api/auth/login", { method: "POST", json: { username, password } });
      setToken(r.token);
      location.href = "/";
    } catch (e: any) { setErr(e.message || "로그인 실패"); }
  };
  return (
    <div className="min-h-screen flex items-center justify-center bg-[#151722]">
      <form onSubmit={submit} className="px-panel p-6 w-80 flex flex-col gap-3">
        <div className="px-title text-xl text-center">PERSONAL AI OFFICE</div>
        <p className="text-center text-cream/70 text-[12px]">CEO 출근 체크</p>
        <input className="px-input" value={username} onChange={(e) => setU(e.target.value)} placeholder="아이디" autoComplete="username" />
        <input className="px-input" type="password" value={password} onChange={(e) => setP(e.target.value)} placeholder="비밀번호" autoComplete="current-password" />
        {err && <div className="text-rose text-[12px]">{err}</div>}
        <button className="px-btn justify-center" type="submit">출근하기 ▶</button>
      </form>
    </div>
  );
}
