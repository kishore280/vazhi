import { useEffect, useState } from 'react';
import { Button, InputNumber, Table, Tag, Empty, Spin } from 'antd';
import { PlayCircleOutlined } from '@ant-design/icons';
import { apiClient } from '../lib/api';
import type { EvalRunItem } from '../lib/api';
import './EvalPanel.css';

interface EvalRun {
  run_id: string;
  status: string;
  overall_score: number | null;
  metrics: Record<string, number>;
  total_items: number;
  completed_items: number;
  started_at: string;
  completed_at: string | null;
}

const STATUS_COLOR: Record<string, string> = {
  running: 'processing',
  completed: 'success',
  failed: 'error',
  pending: 'warning',
};

export default function EvalPanel({ kbId }: { kbId: string }) {
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [numQuestions, setNumQuestions] = useState(5);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [runDetail, setRunDetail] = useState<{ items: EvalRunItem[] } | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const loadRuns = async () => {
    setLoading(true);
    try {
      const data = await apiClient.listEvals(kbId);
      setRuns(data);
    } finally {
      setLoading(false);
    }
  };

  const handleCreateRun = async () => {
    setCreating(true);
    try {
      await apiClient.runEval(kbId, { num_questions: numQuestions });
      await loadRuns();
    } finally {
      setCreating(false);
    }
  };

  const handleSelectRun = async (runId: string) => {
    setSelectedRunId(runId);
    setDetailLoading(true);
    try {
      const detail = await apiClient.getEvalRun(kbId, runId);
      setRunDetail(detail);
    } finally {
      setDetailLoading(false);
    }
  };

  useEffect(() => {
    loadRuns();
  }, [kbId]);

  const runColumns = [
    {
      title: 'Status',
      dataIndex: 'status',
      key: 'status',
      width: 110,
      render: (status: string) => <Tag color={STATUS_COLOR[status] || 'default'}>{status}</Tag>,
    },
    {
      title: 'Overall score',
      dataIndex: 'overall_score',
      key: 'overall_score',
      width: 130,
      render: (v: number | null) => (v == null ? '-' : `${(v * 100).toFixed(1)}%`),
    },
    {
      title: 'Completed',
      key: 'progress',
      width: 110,
      render: (_: unknown, r: EvalRun) => `${r.completed_items} / ${r.total_items}`,
    },
    {
      title: 'Started',
      dataIndex: 'started_at',
      key: 'started_at',
      render: (v: string) => new Date(v).toLocaleString(),
    },
  ];

  const itemColumns = [
    { title: 'Question', dataIndex: 'query_text', key: 'query_text', width: 280 },
    {
      title: 'Generated answer',
      dataIndex: 'generated_answer',
      key: 'generated_answer',
      width: 320,
      render: (v: string | null) => v || '-',
    },
    {
      title: 'Retrieval',
      key: 'retrieval',
      width: 220,
      render: (_: unknown, item: EvalRunItem) => (
        <div className="metric-chips">
          {Object.entries(item.metrics)
            .filter(([k]) => k.startsWith('recall') || k.startsWith('f1'))
            .map(([k, v]) => (
              <span key={k} className="metric-chip">
                <small>{k}</small>
                <strong>{Number(v).toFixed(2)}</strong>
              </span>
            ))}
        </div>
      ),
    },
    {
      title: 'Judge',
      key: 'judge',
      width: 220,
      render: (_: unknown, item: EvalRunItem) => {
        const score = item.metrics.judge_score;
        if (score === undefined) return '-';
        const pass = Number(score) > 0.5;
        return (
          <div>
            <Tag color={pass ? 'success' : 'error'}>{pass ? 'correct' : 'incorrect'}</Tag>
            <div className="judge-reasoning" title={String(item.metrics.judge_reasoning || '')}>
              {String(item.metrics.judge_reasoning || '')}
            </div>
          </div>
        );
      },
    },
  ];

  return (
    <div className="eval-panel">
      <div className="eval-toolbar">
        <InputNumber min={1} max={50} value={numQuestions} onChange={(v) => setNumQuestions(v || 5)} />
        <Button type="primary" icon={<PlayCircleOutlined />} onClick={handleCreateRun} loading={creating}>
          Run Evaluation
        </Button>
      </div>

      <Table
        rowKey="run_id"
        columns={runColumns}
        dataSource={runs}
        loading={loading}
        pagination={false}
        onRow={(r) => ({ onClick: () => handleSelectRun(r.run_id), style: { cursor: 'pointer' } })}
        rowClassName={(r) => (r.run_id === selectedRunId ? 'eval-row-selected' : '')}
        locale={{ emptyText: <Empty description="No evaluation runs yet." /> }}
        style={{ marginBottom: 24 }}
      />

      {selectedRunId ? (
        <div className="eval-results">
          <h3>Results</h3>
          {detailLoading ? (
            <div className="eval-results-loading">
              <Spin />
            </div>
          ) : (
            <Table
              rowKey="item_index"
              columns={itemColumns}
              dataSource={runDetail?.items || []}
              pagination={false}
              scroll={{ x: 1040 }}
            />
          )}
        </div>
      ) : null}
    </div>
  );
}
