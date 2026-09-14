import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Tabs, Table, Input, Button, Alert, Empty, Upload } from 'antd';
import type { TabsProps, UploadProps } from 'antd';
import {
  FileTextOutlined,
  SearchOutlined,
  LeftOutlined,
  ShareAltOutlined,
  BarChartOutlined,
  InboxOutlined,
} from '@ant-design/icons';
import { useAppStore } from '../store/app';
import type { QueryResult } from '../store/app';
import GraphPanel from './GraphPanel';
import EvalPanel from './EvalPanel';
import './KBDetail.css';

const { TextArea } = Input;

export default function KBDetail() {
  const { kbId } = useParams<{ kbId: string }>();
  const navigate = useNavigate();
  const { documents, loading, error, loadDocuments, ingestDocument, uploadDocument, queryKB, clearError } =
    useAppStore();

  const [activeTab, setActiveTab] = useState('query');
  const [queryText, setQueryText] = useState('');
  const [queryResults, setQueryResults] = useState<QueryResult[]>([]);
  const [ingestContent, setIngestContent] = useState('');
  const [ingestFilename, setIngestFilename] = useState('document.md');

  useEffect(() => {
    if (kbId) loadDocuments(kbId);
  }, [kbId]);

  const handleQuery = async () => {
    if (!kbId || !queryText.trim()) return;
    const results = await queryKB(kbId, queryText.trim());
    setQueryResults(results);
  };

  const handleIngest = async () => {
    if (!kbId || !ingestContent.trim()) return;
    await ingestDocument(kbId, ingestContent, ingestFilename);
    setIngestContent('');
    setActiveTab('documents');
  };

  const uploadProps: UploadProps = {
    accept: '.pdf,.txt,.md',
    showUploadList: false,
    beforeUpload: async (file) => {
      if (kbId) {
        await uploadDocument(kbId, file);
        setActiveTab('documents');
      }
      return false;
    },
  };

  const documentColumns = [
    { title: 'Filename', dataIndex: 'filename', key: 'filename' },
    {
      title: 'Created',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (v: string) => new Date(v).toLocaleString(),
    },
  ];

  const items: TabsProps['items'] = [
    {
      key: 'query',
      label: (
        <span className="tab-label">
          <SearchOutlined /> Retrieval Testing
        </span>
      ),
      children: (
        <div className="tab-panel">
          <div className="query-box">
            <Input
              placeholder="Ask a question..."
              value={queryText}
              onChange={(e) => setQueryText(e.target.value)}
              onPressEnter={handleQuery}
              size="large"
            />
            <Button type="primary" size="large" onClick={handleQuery} loading={loading}>
              Search
            </Button>
          </div>

          <div className="results">
            {queryResults.map((r) => (
              <div key={r.chunk_id} className="result-card">
                <div className="result-score">Score: {r.score.toFixed(3)}</div>
                <div className="result-content">{r.content}</div>
              </div>
            ))}
            {queryResults.length === 0 && !loading ? (
              <Empty description="No results yet. Try a query." />
            ) : null}
          </div>
        </div>
      ),
    },
    {
      key: 'documents',
      label: (
        <span className="tab-label">
          <FileTextOutlined /> File Management
        </span>
      ),
      children: (
        <div className="tab-panel">
          <Table
            columns={documentColumns}
            dataSource={documents}
            rowKey="doc_id"
            loading={loading}
            pagination={false}
            locale={{ emptyText: <Empty description="No documents ingested yet." /> }}
          />
        </div>
      ),
    },
    {
      key: 'ingest',
      label: <span className="tab-label">Ingest</span>,
      children: (
        <div className="tab-panel">
          <Upload.Dragger {...uploadProps} style={{ marginBottom: 24 }}>
            <p className="ant-upload-drag-icon">
              <InboxOutlined />
            </p>
            <p className="ant-upload-text">Click or drag a file to upload</p>
            <p className="ant-upload-hint">Supports .pdf, .txt, .md</p>
          </Upload.Dragger>

          <div className="ingest-divider">or paste text</div>

          <Input
            placeholder="Filename"
            value={ingestFilename}
            onChange={(e) => setIngestFilename(e.target.value)}
            style={{ marginBottom: 12 }}
          />
          <TextArea
            placeholder="Paste document content..."
            value={ingestContent}
            onChange={(e) => setIngestContent(e.target.value)}
            rows={12}
            style={{ marginBottom: 12 }}
          />
          <Button type="primary" onClick={handleIngest} loading={loading}>
            Ingest Document
          </Button>
        </div>
      ),
    },
    {
      key: 'graph',
      label: (
        <span className="tab-label">
          <ShareAltOutlined /> Knowledge Graph
        </span>
      ),
      children: kbId ? <GraphPanel kbId={kbId} /> : null,
    },
    {
      key: 'evaluation',
      label: (
        <span className="tab-label">
          <BarChartOutlined /> Evaluation
        </span>
      ),
      children: kbId ? <div style={{ paddingTop: 16 }}><EvalPanel kbId={kbId} /></div> : null,
    },
  ];

  return (
    <div className="kb-detail">
      <div className="kb-detail-header">
        <button className="back-btn" onClick={() => navigate('/')}>
          <LeftOutlined /> Knowledge Bases
        </button>
      </div>

      {error ? (
        <Alert
          message={error}
          type="error"
          closable
          onClose={clearError}
          style={{ margin: '0 24px 16px' }}
        />
      ) : null}

      <Tabs
        className="pill-tabs"
        items={items}
        activeKey={activeTab}
        onChange={setActiveTab}
        tabBarStyle={{ padding: '0 24px' }}
      />
    </div>
  );
}
