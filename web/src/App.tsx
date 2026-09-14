import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ConfigProvider } from 'antd';
import { useAppStore } from './store/app';
import AppLayout from './layouts/AppLayout';
import Login from './pages/Login';
import KBList from './pages/KBList';
import KBDetail from './pages/KBDetail';
import Chat from './pages/Chat';

const theme = {
  token: {
    colorPrimary: '#4f6bed',
    borderRadius: 8,
    fontFamily:
      "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
  },
};

function App() {
  const apiKey = useAppStore((state) => state.apiKey);

  return (
    <ConfigProvider theme={theme}>
      <BrowserRouter>
        <Routes>
          {!apiKey ? (
            <>
              <Route path="/login" element={<Login />} />
              <Route path="*" element={<Navigate to="/login" />} />
            </>
          ) : (
            <Route element={<AppLayout />}>
              <Route path="/" element={<KBList />} />
              <Route path="/kb/:kbId" element={<KBDetail />} />
              <Route path="/chat" element={<Chat />} />
              <Route path="/chat/:threadId" element={<Chat />} />
              <Route path="*" element={<Navigate to="/" />} />
            </Route>
          )}
        </Routes>
      </BrowserRouter>
    </ConfigProvider>
  );
}

export default App;
