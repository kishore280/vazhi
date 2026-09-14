import { useState } from 'react';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import { Tooltip, Badge } from 'antd';
import {
  MessageOutlined,
  DatabaseOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  PlusOutlined,
} from '@ant-design/icons';
import { useAppStore } from '../store/app';
import './AppLayout.css';

interface NavItem {
  key: string;
  label: string;
  icon: React.ReactNode;
  path: string;
}

const NAV_ITEMS: NavItem[] = [
  { key: 'chat', label: 'Agent', icon: <MessageOutlined />, path: '/chat' },
  { key: 'kb', label: 'Knowledge Bases', icon: <DatabaseOutlined />, path: '/' },
];

export default function AppLayout() {
  const [collapsed, setCollapsed] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const logout = useAppStore((state) => state.logout);

  const isActive = (path: string) =>
    path === '/' ? location.pathname === '/' : location.pathname.startsWith(path);

  return (
    <div className="app-layout">
      <aside className={collapsed ? 'sidebar sidebar-collapsed' : 'sidebar'}>
        <div className="sidebar-brand">
          {!collapsed && (
            <>
              <div className="brand-avatar">V</div>
              <span className="brand-name">Vazhi</span>
            </>
          )}
          <button
            className="icon-btn sidebar-collapse-btn"
            onClick={() => setCollapsed(!collapsed)}
          >
            {collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
          </button>
        </div>

        <div className="nav">
          <Tooltip title="New chat" placement="right" open={collapsed ? undefined : false}>
            <button className="nav-item nav-item-primary" onClick={() => navigate('/chat')}>
              <PlusOutlined />
              {!collapsed && <span className="nav-text">New chat</span>}
            </button>
          </Tooltip>

          {NAV_ITEMS.map((item) => (
            <Tooltip
              key={item.key}
              title={item.label}
              placement="right"
              open={collapsed ? undefined : false}
            >
              <button
                className={isActive(item.path) ? 'nav-item nav-item-active' : 'nav-item'}
                onClick={() => navigate(item.path)}
              >
                {item.icon}
                {!collapsed && <span className="nav-text">{item.label}</span>}
              </button>
            </Tooltip>
          ))}
        </div>

        <div className="fill" />

        <div className="sidebar-footer">
          <Tooltip title="Log out" placement="right" open={collapsed ? undefined : false}>
            <button className="nav-item" onClick={logout}>
              <Badge dot={false}>
                <span className="user-avatar">U</span>
              </Badge>
              {!collapsed && <span className="nav-text">Log out</span>}
            </button>
          </Tooltip>
        </div>
      </aside>

      <main id="app-router-view">
        <Outlet />
      </main>
    </div>
  );
}
