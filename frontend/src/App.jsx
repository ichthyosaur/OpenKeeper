import React, { useEffect, useMemo, useRef, useState } from "react";

const fallbackProfessions = [
  "retired_soldier",
  "police",
  "doctor",
  "professor",
  "private_detective",
  "journalist",
  "occult_researcher",
  "engineer",
  "archaeologist",
  "lawyer",
  "nurse",
  "photojournalist",
];

const defaultAttributes = {
  str: 50,
  dex: 50,
  int: 50,
  con: 50,
  app: 50,
  pow: 50,
  siz: 50,
  edu: 50,
};

const defaultStats = {
  hp: 10,
  san: 60,
  mp: 10,
  luck: 50,
};

function textFromI18n(content) {
  if (!content) return "";
  return content.zh || content.en || "";
}

export default function App() {
  const [serverUrl, setServerUrl] = useState("http://localhost:8000");
  const [wsUrl, setWsUrl] = useState("ws://localhost:8000/ws");
  const [role, setRole] = useState("player");
  const [playerId, setPlayerId] = useState(() => crypto.randomUUID());
  const [name, setName] = useState("");
  const [gender, setGender] = useState("");
  const [color, setColor] = useState("#2dd4bf");
  const [profession, setProfession] = useState(fallbackProfessions[0]);
  const [professionMap, setProfessionMap] = useState({});
  const [connected, setConnected] = useState(false);
  const [history, setHistory] = useState([]);
  const [stateView, setStateView] = useState({ players: {} });
  const [sessionInfo, setSessionInfo] = useState(null);
  const [inputText, setInputText] = useState("");
  const wsRef = useRef(null);

  const playerCard = useMemo(() => {
    return stateView.players?.[playerId] || {
      name,
      gender,
      color,
      profession,
      attributes: defaultAttributes,
      stats: defaultStats,
      skills: {},
      statuses: [],
    };
  }, [stateView, playerId, name, gender, color, profession]);

  useEffect(() => {
    fetch(`${serverUrl}/professions`)
      .then((res) => res.json())
      .then((data) => {
        if (data.professions) {
          setProfessionMap(data.professions);
          const keys = Object.keys(data.professions);
          if (keys.length > 0) setProfession(keys[0]);
        }
      })
      .catch(() => {});
  }, [serverUrl]);

  async function createCharacter() {
    const skills = professionMap[profession]?.skills || {};
    const payload = {
      player_id: playerId,
      name,
      gender,
      color,
      profession,
      background: "",
      attributes: defaultAttributes,
      stats: defaultStats,
      skills,
      statuses: [],
    };
    await fetch(`${serverUrl}/players`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  function connect() {
    if (wsRef.current) {
      wsRef.current.close();
    }
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;
    ws.onopen = () => {
      setConnected(true);
      ws.send(
        JSON.stringify({
          type: "client.join",
          payload: { player_id: playerId, role },
        })
      );
    };
    ws.onmessage = (evt) => {
      const message = JSON.parse(evt.data);
      if (message.type === "server.session_state") {
        setSessionInfo(message.payload);
        setHistory(message.payload.latest_history || []);
        setStateView(message.payload.visible_state || {});
        return;
      }
      if (message.type === "server.history_append") {
        const entry = message.payload.entry;
        if (Array.isArray(entry)) {
          setHistory(entry);
        } else {
          setHistory((prev) => [...prev, entry]);
        }
        return;
      }
      if (message.type === "server.state_update") {
        setStateView(message.payload.state_diff || {});
        return;
      }
    };
    ws.onclose = () => {
      setConnected(false);
    };
  }

  function sendAction() {
    if (!wsRef.current || wsRef.current.readyState !== 1) return;
    if (!inputText.trim()) return;
    wsRef.current.send(
      JSON.stringify({
        type: "client.player_action",
        payload: {
          player_id: playerId,
          action_text: { zh: inputText, en: "" },
        },
      })
    );
    setInputText("");
  }

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <div className="title">OpenKeeper</div>
          <div className="subtitle">TRPG Agent Session Console</div>
        </div>
        <div className={`status ${connected ? "on" : "off"}`}>
          {connected ? "CONNECTED" : "DISCONNECTED"}
        </div>
      </header>

      <section className="setup">
        <div className="card">
          <div className="card-title">角色创建</div>
          <div className="grid">
            <label>
              名称
              <input value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <label>
              性别
              <input value={gender} onChange={(e) => setGender(e.target.value)} />
            </label>
            <label>
              颜色
              <input type="color" value={color} onChange={(e) => setColor(e.target.value)} />
            </label>
            <label>
              职业
              <select value={profession} onChange={(e) => setProfession(e.target.value)}>
                {(Object.keys(professionMap).length ? Object.keys(professionMap) : fallbackProfessions).map(
                  (p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="actions">
            <button onClick={createCharacter}>创建角色</button>
          </div>
        </div>

        <div className="card">
          <div className="card-title">连接</div>
          <div className="grid">
            <label>
              Server URL
              <input value={serverUrl} onChange={(e) => setServerUrl(e.target.value)} />
            </label>
            <label>
              WS URL
              <input value={wsUrl} onChange={(e) => setWsUrl(e.target.value)} />
            </label>
            <label>
              Role
              <select value={role} onChange={(e) => setRole(e.target.value)}>
                <option value="player">player</option>
                <option value="host">host</option>
              </select>
            </label>
            <label>
              Player ID
              <input value={playerId} onChange={(e) => setPlayerId(e.target.value)} />
            </label>
          </div>
          <div className="actions">
            <button onClick={connect}>连接</button>
          </div>
        </div>
      </section>

      <section className="room">
        <div className="history panel">
          <div className="panel-title">历史记录</div>
          <div className="history-list">
            {history.map((entry, idx) => (
              <div className="history-item" key={`${entry.timestamp}-${idx}`}>
                <div className="history-meta">
                  <span>{entry.actor_type}</span>
                  <span>{entry.action_type}</span>
                </div>
                <div className="history-content">{textFromI18n(entry.content)}</div>
              </div>
            ))}
          </div>
          <div className="input-row">
            <input
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              placeholder="行动输入..."
              onKeyDown={(e) => {
                if (e.key === "Enter") sendAction();
              }}
            />
            <button onClick={sendAction}>发送</button>
          </div>
        </div>

        <div className="side">
          <div className="panel">
            <div className="panel-title">角色卡</div>
            <div className="card-info">
              <div>
                <strong>{playerCard.name || "Unknown"}</strong>
                <div className="muted">{playerCard.profession}</div>
              </div>
              <div className="chip" style={{ background: playerCard.color }}>
                {playerCard.gender || ""}
              </div>
            </div>
            <div className="stats">
              <div>HP: {playerCard.stats?.hp ?? 0}</div>
              <div>SAN: {playerCard.stats?.san ?? 0}</div>
              <div>MP: {playerCard.stats?.mp ?? 0}</div>
              <div>Luck: {playerCard.stats?.luck ?? 0}</div>
            </div>
            <div className="attributes">
              {Object.entries(playerCard.attributes || {}).map(([key, value]) => (
                <div key={key}>
                  {key.toUpperCase()}: {value}
                </div>
              ))}
            </div>
          </div>

          <div className="panel">
            <div className="panel-title">房间玩家</div>
            <div className="players">
              {Object.values(stateView.players || {}).map((p) => (
                <div className="player" key={p.player_id || p.name}>
                  <span className="dot" style={{ background: p.color || "#475569" }}></span>
                  <span>{p.name}</span>
                  <span className="muted">
                    HP {p.stats?.hp ?? "--"} / SAN {p.stats?.san ?? "--"}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
