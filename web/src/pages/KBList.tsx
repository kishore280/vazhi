import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Modal, Input, Alert, Empty, Spin } from 'antd';
import { PlusOutlined, DatabaseOutlined } from '@ant-design/icons';
import { useAppStore } from '../store/app';
import './KBList.css';

export default function KBList() {
  const navigate = useNavigate();
  const { kbs, loading, error, loadKBs, createKB, clearError } = useAppStore();
  const [newKBName, setNewKBName] = useState('');
  const [modalOpen, setModalOpen] = useState(false);

  useEffect(() => {
    loadKBs();
  }, []);

  const handleCreate = async () => {
    if (!newKBName.trim()) return;
    await createKB(newKBName.trim());
    setNewKBName('');
    setModalOpen(false);
  };

  return (
    <div className="kb-list-page">
      <header className="kb-list-header">
        <h1>Knowledge Bases</h1>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>
          New Knowledge Base
        </Button>
      </header>

      {error ? (
        <Alert
          message={error}
          type="error"
          closable
          onClose={clearError}
          style={{ marginBottom: 16 }}
        />
      ) : null}

      {loading && kbs.length === 0 ? (
        <div className="kb-list-loading">
          <Spin />
        </div>
      ) : kbs.length === 0 ? (
        <Empty description="No knowledge bases yet. Create one to get started." />
      ) : (
        <div className="kb-grid">
          {kbs.map((kb) => (
            <div key={kb.kb_id} className="kb-card" onClick={() => navigate(`/kb/${kb.kb_id}`)}>
              <DatabaseOutlined className="kb-card-icon" />
              <div className="kb-card-body">
                <h3>{kb.name}</h3>
                <p>Created {new Date(kb.created_at).toLocaleDateString()}</p>
              </div>
            </div>
          ))}
        </div>
      )}

      <Modal
        title="New Knowledge Base"
        open={modalOpen}
        onOk={handleCreate}
        onCancel={() => setModalOpen(false)}
        okText="Create"
        confirmLoading={loading}
      >
        <Input
          placeholder="KB name"
          value={newKBName}
          onChange={(e) => setNewKBName(e.target.value)}
          onPressEnter={handleCreate}
          autoFocus
        />
      </Modal>
    </div>
  );
}
