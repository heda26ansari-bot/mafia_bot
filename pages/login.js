import { useState } from "react";
import { useRouter } from "next/router";
import { apiFetch } from "../lib/api";

export default function Login(){
  const [user, setUser] = useState("");
  const [pass, setPass] = useState("");
  const router = useRouter();

  async function submit(e){
    e.preventDefault();
    const data = await fetch(process.env.NEXT_PUBLIC_API_URL + "/auth/login", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({username: user, password: pass})
    });
    if (!data.ok) {
      alert("Login failed");
      return;
    }
    const res = await data.json();
    // save token in localStorage (or httpOnly cookie via backend)
    localStorage.setItem("access_token", res.access_token);
    router.push("/dashboard");
  }

  return (
    <div className="p-6">
      <h1>Login</h1>
      <form onSubmit={submit}>
        <input value={user} onChange={(e)=>setUser(e.target.value)} placeholder="username" />
        <input type="password" value={pass} onChange={(e)=>setPass(e.target.value)} placeholder="password" />
        <button>Login</button>
      </form>
    </div>
  );
}
