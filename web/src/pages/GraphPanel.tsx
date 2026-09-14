import { useEffect, useRef, useState } from 'react';
import { Graph } from '@antv/g6';
import { Input, Button, Empty, Spin } from 'antd';
import { SearchOutlined, ReloadOutlined } from '@ant-design/icons';
import { apiClient } from '../lib/api';
import type { GraphNode, GraphEdge } from '../lib/api';
import './GraphPanel.css';

const NODE_PALETTE = [
  '#3996ae',
  '#5ad8a6',
  '#f6bd16',
  '#f27c7c',
  '#9581cc',
  '#6dc8ec',
  '#ff9d4d',
  '#92d050',
  '#e885ba',
];

const EDGE_PALETTE = [
  '#99add1',
  '#3996ae',
  '#13c2c2',
  '#faad14',
  '#f27c7c',
  '#9581cc',
  '#52c41a',
  '#ff9d4d',
];

function hashToColor(key: string, palette: string[]): string {
  let hash = 0;
  for (let i = 0; i < key.length; i++) {
    hash = (hash << 5) - hash + key.charCodeAt(i);
    hash |= 0;
  }
  return palette[Math.abs(hash) % palette.length];
}

interface TypeCount {
  type: string;
  count: number;
  color: string;
}

export default function GraphPanel({ kbId }: { kbId: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<Graph | null>(null);
  const [loading, setLoading] = useState(true);
  const [empty, setEmpty] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [nodeTypeCounts, setNodeTypeCounts] = useState<TypeCount[]>([]);
  const [edgeTypeCounts, setEdgeTypeCounts] = useState<TypeCount[]>([]);
  const [selected, setSelected] = useState<{ kind: 'node' | 'edge'; data: GraphNode | GraphEdge } | null>(
    null
  );

  const loadGraph = async () => {
    setLoading(true);
    setError(null);
    try {
      const { nodes, edges } = await apiClient.getSubgraph(kbId, 200);
      const filteredNodes = search.trim()
        ? nodes.filter((n) => n.name?.toLowerCase().includes(search.trim().toLowerCase()))
        : nodes;
      const nodeIds = new Set(filteredNodes.map((n) => n.id));
      const filteredEdges = search.trim()
        ? edges.filter((e) => nodeIds.has(e.source_id) && nodeIds.has(e.target_id))
        : edges;

      setEmpty(filteredNodes.length === 0);
      renderGraph(filteredNodes, filteredEdges);
      computeCounts(filteredNodes, filteredEdges);
    } catch (err) {
      setError((err as Error).message);
      setEmpty(true);
    } finally {
      setLoading(false);
    }
  };

  const computeCounts = (nodes: GraphNode[], edges: GraphEdge[]) => {
    const nodeCounts = new Map<string, number>();
    for (const n of nodes) {
      const type = n.type || 'Entity';
      nodeCounts.set(type, (nodeCounts.get(type) || 0) + 1);
    }
    const edgeCounts = new Map<string, number>();
    for (const e of edges) {
      const type = e.type || 'RELATED_TO';
      edgeCounts.set(type, (edgeCounts.get(type) || 0) + 1);
    }
    setNodeTypeCounts(
      [...nodeCounts.entries()]
        .map(([type, count]) => ({ type, count, color: hashToColor(type, NODE_PALETTE) }))
        .sort((a, b) => b.count - a.count)
    );
    setEdgeTypeCounts(
      [...edgeCounts.entries()]
        .map(([type, count]) => ({ type, count, color: hashToColor(type, EDGE_PALETTE) }))
        .sort((a, b) => b.count - a.count)
    );
  };

  const renderGraph = (nodes: GraphNode[], edges: GraphEdge[]) => {
    if (!containerRef.current) return;

    const degree = new Map<string, number>();
    for (const e of edges) {
      degree.set(e.source_id, (degree.get(e.source_id) || 0) + 1);
      degree.set(e.target_id, (degree.get(e.target_id) || 0) + 1);
    }

    const g6Data = {
      nodes: nodes.map((n) => ({
        id: String(n.id),
        data: { original: n },
        style: {
          size: Math.min(15 + (degree.get(n.id) || 0) * 5, 50),
          fill: hashToColor(n.type || 'Entity', NODE_PALETTE),
          labelText: n.name,
          labelFill: '#525252',
        },
      })),
      edges: edges.map((e) => ({
        id: String(e.id),
        source: String(e.source_id),
        target: String(e.target_id),
        data: { original: e },
        style: {
          stroke: hashToColor(e.type || 'RELATED_TO', EDGE_PALETTE),
          labelText: e.type || '',
          endArrow: true,
        },
      })),
    };

    if (graphRef.current) {
      graphRef.current.destroy();
    }

    const graph = new Graph({
      container: containerRef.current,
      autoFit: 'view',
      autoResize: true,
      data: g6Data,
      node: {
        type: 'circle',
        style: { lineWidth: 1.5, stroke: '#fff', opacity: 0.9 },
      },
      edge: {
        type: 'quadratic',
        style: { lineWidth: 1.2, opacity: 0.8 },
      },
      layout: {
        type: 'd3-force',
        preventOverlap: true,
        alphaDecay: 0.1,
        alphaMin: 0.01,
        velocityDecay: 0.6,
        iterations: 150,
        force: {
          center: { x: 0.5, y: 0.5, strength: 0.1 },
          charge: { strength: -400, distanceMax: 600 },
          link: { distance: 100, strength: 0.8 },
        },
        collide: { radius: 40, strength: 0.8, iterations: 3 },
      } as any,
      behaviors: ['drag-element', 'zoom-canvas', 'drag-canvas', 'hover-activate'],
    });

    graph.on('node:click', (evt: any) => {
      const nodeData = graph.getNodeData(evt.target.id);
      const original = nodeData?.data?.original as GraphNode | undefined;
      if (original) setSelected({ kind: 'node', data: original });
    });
    graph.on('edge:click', (evt: any) => {
      const edgeData = graph.getEdgeData(evt.target.id);
      const original = edgeData?.data?.original as GraphEdge | undefined;
      if (original) setSelected({ kind: 'edge', data: original });
    });
    graph.on('canvas:click', () => setSelected(null));

    graph.render();
    graphRef.current = graph;
  };

  useEffect(() => {
    loadGraph();
    return () => {
      graphRef.current?.destroy();
      graphRef.current = null;
    };
  }, [kbId]);

  return (
    <div className="graph-panel">
      <div className="graph-toolbar">
        <Input
          placeholder="Search entities"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onPressEnter={loadGraph}
          prefix={<SearchOutlined />}
          style={{ width: 240 }}
        />
        <Button icon={<ReloadOutlined />} onClick={loadGraph} />
      </div>

      <div className="graph-canvas-wrapper">
        <div ref={containerRef} className="graph-canvas" />

        {loading ? (
          <div className="graph-overlay">
            <Spin />
          </div>
        ) : null}

        {!loading && empty ? (
          <div className="graph-overlay">
            <Empty description={error || 'No entities found. Ingest documents to build the graph.'} />
          </div>
        ) : null}

        {!loading && !empty ? (
          <div className="graph-stats-panel">
            <div className="stats-group">
              {nodeTypeCounts.map((tc) => (
                <div key={tc.type} className="stats-row">
                  <span className="stats-dot" style={{ background: tc.color }} />
                  <span className="stats-label">{tc.type}</span>
                  <span className="stats-count">{tc.count}</span>
                </div>
              ))}
            </div>
            <div className="stats-group">
              {edgeTypeCounts.map((tc) => (
                <div key={tc.type} className="stats-row">
                  <span className="stats-dot" style={{ background: tc.color }} />
                  <span className="stats-label">{tc.type}</span>
                  <span className="stats-count">{tc.count}</span>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {selected ? (
          <div className="graph-detail-panel">
            <div className="detail-header">
              <span>{selected.kind === 'node' ? 'Entity' : 'Relation'}</span>
              <button className="detail-close" onClick={() => setSelected(null)}>
                ×
              </button>
            </div>
            <div className="detail-body">
              {selected.kind === 'node' ? (
                <>
                  <DetailRow label="Name" value={(selected.data as GraphNode).name} />
                  <DetailRow label="ID" value={(selected.data as GraphNode).id} />
                  <DetailRow label="Type" value={(selected.data as GraphNode).type || '-'} />
                </>
              ) : (
                <>
                  <DetailRow label="Type" value={(selected.data as GraphEdge).type || '-'} />
                  <DetailRow label="Source" value={(selected.data as GraphEdge).source_id} />
                  <DetailRow label="Target" value={(selected.data as GraphEdge).target_id} />
                </>
              )}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="detail-row">
      <span className="detail-row-label">{label}</span>
      <span className="detail-row-value">{value}</span>
    </div>
  );
}
