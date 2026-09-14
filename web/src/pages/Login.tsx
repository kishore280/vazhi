import { useState } from 'react';
import { Input, Button } from 'antd';
import { useAppStore } from '../store/app';
import './Login.css';

export default function Login() {
  const [keyInput, setKeyInput] = useState('');
  const setApiKey = useAppStore((state) => state.setApiKey);
  const loadKBs = useAppStore((state) => state.loadKBs);

  const handleLogin = () => {
    if (!keyInput.trim()) return;
    setApiKey(keyInput.trim());
    loadKBs();
  };

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-brand">V</div>
        <h1>Vazhi</h1>
        <p>Enter your API key to continue</p>
        <Input.Password
          placeholder="API key"
          value={keyInput}
          onChange={(e) => setKeyInput(e.target.value)}
          onPressEnter={handleLogin}
          size="large"
          autoFocus
        />
        <Button type="primary" size="large" block onClick={handleLogin} style={{ marginTop: 16 }}>
          Continue
        </Button>
      </div>
    </div>
  );
}
