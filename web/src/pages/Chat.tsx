import { memo, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Button, Tooltip } from 'antd';
import { ArrowUpOutlined, PauseOutlined, PlusOutlined } from '@ant-design/icons';
import { useChatStore } from '../store/chat';
import type { ChatMessage } from '../store/chat';
import './Chat.css';

function newThreadId(): string {
  return crypto.randomUUID();
}

export default function Chat() {
  const { threadId: routeThreadId } = useParams<{ threadId: string }>();
  const navigate = useNavigate();
  const { messages, sending, error, startThread, loadHistory, sendMessage, stopGeneration, clearError } =
    useChatStore();

  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (routeThreadId) {
      loadHistory(routeThreadId);
    } else {
      const id = newThreadId();
      startThread(id);
      navigate(`/chat/${id}`, { replace: true });
    }
  }, [routeThreadId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = async (content: string) => {
    if (!routeThreadId || sending) return;
    await sendMessage(routeThreadId, content);
  };

  return (
    <div className="chat">
      <div className="chat-header">
        <div className="header__left">
          <span className="conversation-title">
            {messages.length > 0 ? 'Conversation' : 'New chat'}
          </span>
        </div>
        <div className="header__right">
          <Tooltip title="New chat">
            <button className="agent-nav-btn" onClick={() => navigate(`/chat/${newThreadId()}`)}>
              <PlusOutlined />
            </button>
          </Tooltip>
        </div>
      </div>

      {error ? (
        <div className="chat-error-banner">
          {error}
          <button onClick={clearError} className="chat-error-close">
            ×
          </button>
        </div>
      ) : null}

      <MessageList messages={messages} bottomRef={bottomRef} />

      <Composer sending={sending} onSend={handleSend} onStop={stopGeneration} />
    </div>
  );
}

const MessageList = memo(function MessageList({
  messages,
  bottomRef,
}: {
  messages: ChatMessage[];
  bottomRef: React.RefObject<HTMLDivElement | null>;
}) {
  return (
    <div className="chat-content-container">
      <div className="chat-main">
        <div className="chat-box">
          {messages.length === 0 ? (
            <div className="chat-greeting-input">
              <h1>What can I help with?</h1>
            </div>
          ) : (
            messages.map((m) => (
              <div key={m.id} className={`message-box ${m.type}`}>
                {m.type === 'human' ? (
                  <p className="message-text">{m.content}</p>
                ) : (
                  <div className="assistant-message">
                    {m.content ? (
                      <p className="message-text">{m.content}</p>
                    ) : m.streaming ? (
                      <div className="generating-status">
                        <div className="loading-dots">
                          <div />
                          <div />
                          <div />
                        </div>
                      </div>
                    ) : null}
                  </div>
                )}
              </div>
            ))
          )}
          <div ref={bottomRef} />
        </div>
      </div>
    </div>
  );
});

function Composer({
  sending,
  onSend,
  onStop,
}: {
  sending: boolean;
  onSend: (content: string) => void;
  onStop: () => void;
}) {
  const [input, setInput] = useState('');

  const handleSend = () => {
    if (!input.trim() || sending) return;
    const content = input.trim();
    setInput('');
    onSend(content);
  };

  const handleSendOrStop = () => {
    if (sending) {
      onStop();
    } else {
      handleSend();
    }
  };

  return (
    <div className="bottom">
      <div className="message-input-wrapper">
        <div className="input-box">
          <textarea
            className="user-input"
            placeholder="Ask something..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            rows={1}
          />
          <Tooltip title={sending ? 'Stop' : 'Send'}>
            <Button
              className="send-button"
              type="primary"
              shape="circle"
              icon={sending ? <PauseOutlined /> : <ArrowUpOutlined />}
              onClick={handleSendOrStop}
              disabled={!sending && !input.trim()}
            />
          </Tooltip>
        </div>
        <p className="note">Vazhi can make mistakes. Verify important information.</p>
      </div>
    </div>
  );
}
